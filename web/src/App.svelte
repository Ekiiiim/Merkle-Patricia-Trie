<script lang="ts">
  import { onMount } from 'svelte'
  import type { Graphviz } from '@hpcc-js/wasm-graphviz'

  type TrieOp = { op: 'insert' | 'delete'; key: string; value?: string }
  type Step = { label: string; state_root_hex: string; dot: string }
  type VerifyStep = {
    title: string
    detail: string
    ok?: boolean
    hash_hex?: string
    expected_state_root_hex?: string
    proof_index?: number
  }

  /** Synthetic DB row: in-RAM trie only (no SQLite file). Must not match real `db/*.db` names. */
  const MEMORY_DB = '__MPT_MEMORY__'

  let gv: Graphviz | null = $state(null)
  let loadError = $state<string | null>(null)
  let steps = $state<Step[]>([])
  let stepIndex = $state(0)
  let trieSvg = $state('')
  let operations = $state<TrieOp[]>([])
  let apiError = $state<string | null>(null)
  let busy = $state(false)

  let dbs = $state<string[]>([])
  let selectedDb = $state<string>('')
  let activeDb = $state<string | null>(null)

  let keyInput = $state('alice')
  let valueInput = $state('100')
  let keyFieldError = $state<string | null>(null)
  let valueFieldError = $state<string | null>(null)
  let proveKey = $state('alice')

  let verifyResult = $state<null | {
    state_root_hex: string
    prove_key: string
    value_hex: string
    proof_nodes_hex: string[]
    verify_steps: VerifyStep[]
    verified: boolean
    root_rlp_hex: string
    root_keccak_hex: string
  }>(null)
  let lookupResult = $state<null | {
    found: boolean
    key: string
    value_utf8: string | null
    value_hex: string | null
    state_root_hex: string
  }>(null)
  let verifyStepIndex = $state(0)
  let triePlaying = $state(false)
  let verifyPlaying = $state(false)

  let triePlayTimer: ReturnType<typeof setInterval> | null = null
  let verifyPlayTimer: ReturnType<typeof setInterval> | null = null

  async function fetchJson<T>(url: string, init?: RequestInit, timeoutMs = 10_000): Promise<{ res: Response; data: T }> {
    const ctrl = new AbortController()
    const t = setTimeout(() => ctrl.abort(), timeoutMs)
    try {
      const res = await fetch(url, { ...init, signal: ctrl.signal })
      const data = (await res.json().catch(() => ({}))) as T
      return { res, data }
    } finally {
      clearTimeout(t)
    }
  }

  onMount(() => {
    void (async () => {
      try {
        const { Graphviz: G } = await import('@hpcc-js/wasm-graphviz')
        gv = await G.load()
      } catch (e) {
        loadError = e instanceof Error ? e.message : String(e)
      }
    })()

    void (async () => {
      await refreshDbList()
      // Memory is default: show empty trie without requiring an insert first.
      if (!activeDb) {
        await replayToServer([])
      }
    })()

    return () => {
      if (triePlayTimer) clearInterval(triePlayTimer)
      if (verifyPlayTimer) clearInterval(verifyPlayTimer)
    }
  })

  $effect(() => {
    const engine = gv
    const raw = steps[stepIndex]?.dot
    const dot = typeof raw === 'string' ? raw.trim() : ''
    if (!engine || !dot) {
      trieSvg = ''
      return
    }
    try {
      // Use dot() (not layout()); some WASM builds misbehave on repeated layout() calls.
      trieSvg = engine.dot(dot, 'svg')
    } catch (e1) {
      try {
        trieSvg = engine.dot(dot, 'svg_inline')
      } catch (e2) {
        const m1 = e1 instanceof Error ? e1.message : String(e1)
        const m2 = e2 instanceof Error ? e2.message : String(e2)
        trieSvg = `<pre class="embed-err">Graphviz: ${m1}\n(retry svg_inline: ${m2})</pre>`
      }
    }
  })

  function stopTriePlay() {
    triePlaying = false
    if (triePlayTimer) {
      clearInterval(triePlayTimer)
      triePlayTimer = null
    }
  }

  function stopVerifyPlay() {
    verifyPlaying = false
    if (verifyPlayTimer) {
      clearInterval(verifyPlayTimer)
      verifyPlayTimer = null
    }
  }

  async function refreshDbList() {
    try {
      const { res, data } = await fetchJson<{
        dbs?: string[]
        active_db?: string | null
        operations?: TrieOp[]
        steps?: Step[]
      }>('/api/db/list', undefined, 5000)
      if (res.ok) {
        dbs = data.dbs ?? []
        activeDb = typeof data.active_db === 'string' ? data.active_db : null
        if (activeDb) {
          selectedDb = activeDb
        } else if (!selectedDb) {
          selectedDb = MEMORY_DB
        }
        // Rehydrate trie graph + op history after full page reload while server still has a DB session.
        if (activeDb && Array.isArray(data.steps) && data.steps.length > 0) {
          operations = data.operations ?? []
          steps = data.steps
          stepIndex = Math.max(0, steps.length - 1)
        }
      }
    } catch {
      // ignore; db selector is optional for demo
    }
  }

  async function activateMemoryMode() {
    apiError = null
    verifyResult = null
    stopVerifyPlay()
    stopTriePlay()
    if (activeDb) {
      return await unloadDb()
    }
    selectedDb = MEMORY_DB
    return await replayToServer([])
  }

  async function applyDbSelection(name: string) {
    if (!name) return
    if (name === MEMORY_DB) {
      await activateMemoryMode()
    } else {
      await loadDb(name)
    }
  }

  function onDbSelectChange() {
    void applyDbSelection(selectedDb)
  }

  async function loadDb(name: string) {
    if (name === MEMORY_DB) {
      return await activateMemoryMode()
    }
    apiError = null
    keyFieldError = null
    valueFieldError = null
    verifyResult = null
    lookupResult = null
    stopVerifyPlay()
    stopTriePlay()
    busy = true
    try {
      const { res, data } = await fetchJson<{ detail?: string; active_db?: string | null; steps?: Step[] }>(
        '/api/db/load',
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ db_name: name }),
        },
        20_000,
      )
      if (!res.ok) {
        apiError = typeof data.detail === 'string' ? data.detail : res.statusText
        selectedDb = activeDb ?? MEMORY_DB
        return false
      }
      activeDb = typeof data.active_db === 'string' ? data.active_db : null
      operations = []
      steps = data.steps ?? []
      stepIndex = Math.max(0, steps.length - 1)
      await refreshDbList()
      return true
    } finally {
      busy = false
    }
  }

  /**
   * Drop file DB session if any, then show an empty Memory trie.
   * In Memory mode (no file), the same button clears the in-RAM trie (replay from empty).
   */
  async function unloadDb() {
    apiError = null
    keyFieldError = null
    valueFieldError = null
    verifyResult = null
    lookupResult = null
    stopVerifyPlay()
    stopTriePlay()
    busy = true
    try {
      const { res, data } = await fetchJson<{ detail?: string; active_db?: string | null }>(
        '/api/db/unload',
        { method: 'POST' },
        10_000,
      )
      if (!res.ok) {
        apiError = typeof data.detail === 'string' ? data.detail : res.statusText
        return false
      }
      activeDb = null
      await refreshDbList()
      selectedDb = MEMORY_DB
      return await replayToServer([])
    } finally {
      busy = false
    }
  }

  async function replayToServer(ops: TrieOp[]) {
    apiError = null
    lookupResult = null
    busy = true
    try {
      const { res, data } = await fetchJson<{
        detail?: string
        steps?: Step[]
        active_db?: string | null
      }>(
        '/api/replay',
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ operations: ops }),
        },
        20_000,
      )
      if (!res.ok) {
        apiError = typeof data.detail === 'string' ? data.detail : res.statusText
        return false
      }
      keyFieldError = null
      valueFieldError = null
      activeDb = typeof data.active_db === 'string' ? data.active_db : null
      operations = ops
      steps = data.steps ?? []
      stepIndex = Math.max(0, steps.length - 1)
      stopTriePlay()
      return true
    } finally {
      busy = false
    }
  }

  async function insertOp() {
    keyFieldError = null
    valueFieldError = null
    const k = keyInput.trim()
    if (!k) {
      keyFieldError = 'Key is required to insert.'
      return
    }
    const v = String(valueInput ?? '').trim()
    if (!v) {
      valueFieldError = 'Value is required to insert.'
      return
    }
    await replayToServer([...operations, { op: 'insert', key: k, value: v }])
  }

  async function deleteOp() {
    keyFieldError = null
    valueFieldError = null
    const k = keyInput.trim()
    if (!k) return
    await replayToServer([...operations, { op: 'delete', key: k }])
  }

  async function loadSample() {
    proveKey = 'alice'
    keyInput = 'alice'
    valueInput = '100'
    if (activeDb) {
      const unloaded = await unloadDb()
      if (!unloaded) return
    }
    await replayToServer([
      { op: 'insert', key: 'alice', value: '100' },
      { op: 'insert', key: 'bob', value: '200' },
      { op: 'insert', key: 'alma', value: '300' },
      { op: 'insert', key: 'alick', value: '100' },
    ])
  }

  async function resetAll() {
    verifyResult = null
    lookupResult = null
    keyFieldError = null
    valueFieldError = null
    stopVerifyPlay()
    if (activeDb) {
      await loadDb(activeDb)
    } else {
      await replayToServer([])
    }
  }

  function goToTrieStep(idx: number) {
    stopTriePlay()
    stepIndex = Math.max(0, Math.min(idx, steps.length - 1))
  }

  function toggleTriePlay() {
    if (steps.length < 2) return
    stopVerifyPlay()
    if (triePlaying) {
      stopTriePlay()
      return
    }
    triePlaying = true
    let local = stepIndex
    const n = steps.length
    triePlayTimer = setInterval(() => {
      local = (local + 1) % n
      stepIndex = local
    }, 1500)
  }

  async function runLookup() {
    const k = keyInput.trim()
    if (!k) return
    apiError = null
    lookupResult = null
    busy = true
    try {
      const { res, data } = await fetchJson<{
        detail?: string
        found?: boolean
        key?: string
        value_utf8?: string | null
        value_hex?: string | null
        state_root_hex?: string
      }>(
        '/api/lookup',
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ operations, key: k }),
        },
        20_000,
      )
      if (!res.ok) {
        apiError = typeof data.detail === 'string' ? data.detail : res.statusText
        return
      }
      lookupResult = {
        found: !!data.found,
        key: typeof data.key === 'string' ? data.key : k,
        value_utf8: data.value_utf8 ?? null,
        value_hex: data.value_hex ?? null,
        state_root_hex: typeof data.state_root_hex === 'string' ? data.state_root_hex : '',
      }
    } finally {
      busy = false
    }
  }

  async function runVerifyDemo() {
    apiError = null
    verifyResult = null
    stopVerifyPlay()
    busy = true
    try {
      const { res, data } = await fetchJson<any>(
        '/api/verify-demo',
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            operations,
            prove_key: proveKey.trim() || 'alice',
          }),
        },
        20_000,
      )
      if (!res.ok) {
        apiError = typeof (data as { detail?: string }).detail === 'string'
          ? (data as { detail: string }).detail
          : res.statusText
        return
      }
      verifyResult = data as NonNullable<typeof verifyResult>
      verifyStepIndex = 0
    } finally {
      busy = false
    }
  }

  function toggleVerifyPlay() {
    if (!verifyResult?.verify_steps.length) return
    stopTriePlay()
    if (verifyPlaying) {
      stopVerifyPlay()
      return
    }
    verifyPlaying = true
    let local = verifyStepIndex
    const n = verifyResult.verify_steps.length
    verifyPlayTimer = setInterval(() => {
      local = (local + 1) % n
      verifyStepIndex = local
    }, 1200)
  }

</script>

<div class="mx-auto max-w-6xl px-6 py-5 pb-12">
  <header>
    <h1 class="text-2xl font-semibold tracking-tight">Merkle Patricia Trie</h1>
  </header>

  {#if loadError}
    <p class="mt-4 rounded-lg border border-(--bad) bg-(--surface) px-4 py-2 text-sm text-(--bad)">
      Could not load Graphviz WASM: {loadError}
    </p>
  {/if}

  {#if apiError}
    <p class="mt-4 rounded-lg border border-(--bad) bg-(--surface) px-4 py-2 text-sm text-(--bad)">
      {apiError}
    </p>
  {/if}

  <section class="mt-5 rounded-xl border border-(--border) bg-(--surface) p-4">
    <h2 class="text-base font-semibold">Operations</h2>
    <p class="mt-1 text-xs text-(--muted) leading-snug">
      UTF-8 keys and values (<code>demo.py</code> style). With a database loaded, replays commit to disk; otherwise the trie
      stays in memory.
    </p>

    <div
      class="mt-3 grid grid-cols-1 gap-4 md:grid-cols-2 md:items-start md:gap-x-6 md:gap-y-4"
    >
      <!-- Database: dropdown + buttons on one row; active status on the next row under the dropdown -->
      <div class="flex min-w-0 flex-col gap-2 md:border-r md:border-(--border) md:pr-6">
        <h3 class="text-sm font-semibold">Database (optional)</h3>
        <p class="text-xs text-(--muted) leading-snug">
          Pick a database from the list to switch immediately: file DBs persist each operation; <strong>Memory</strong> is
          an empty in-RAM trie (no file). <strong>Unload</strong> closes a loaded file DB and returns to Memory, or clears
          the Memory trie when you are already in Memory mode.
        </p>
        <label class="text-xs font-medium text-(--muted)" for="dbsel">Database file</label>
        <div class="flex flex-wrap items-end gap-2">
          <select
            id="dbsel"
            class="min-w-40 max-w-full flex-1 rounded-lg border border-(--border) bg-(--bg) px-3 py-2 text-sm text-(--text) outline-none focus:border-(--accent) sm:max-w-xs"
            bind:value={selectedDb}
            onchange={onDbSelectChange}
            disabled={busy || !!loadError}
          >
            <option value={MEMORY_DB}>Memory (in-RAM, empty on load)</option>
            {#each dbs as name}
              <option value={name}>{name}</option>
            {/each}
          </select>
          <button
            type="button"
            class="shrink-0 rounded-lg border border-(--border) bg-(--surface) px-3 py-2 text-sm hover:border-(--accent) hover:bg-(--accent-dim) disabled:cursor-not-allowed disabled:opacity-50"
            onclick={() => selectedDb && loadDb(selectedDb)}
            disabled={busy || !!loadError || !selectedDb}
          >
            Load
          </button>
          <button
            type="button"
            class="shrink-0 rounded-lg border border-(--border) bg-(--surface) px-3 py-2 text-sm hover:border-(--accent) hover:bg-(--accent-dim) disabled:cursor-not-allowed disabled:opacity-50"
            onclick={unloadDb}
            disabled={busy || !!loadError}
          >
            Unload
          </button>
        </div>
        {#if activeDb}
          <p class="truncate text-xs leading-snug text-(--muted)" title={activeDb}>
            Active: <code class="text-(--text)">{activeDb}</code>
          </p>
        {:else}
          <p class="text-xs leading-snug text-(--muted)">
            Active: <code class="text-(--text)">Memory</code> (not persisted)
          </p>
        {/if}
      </div>

      <!-- Key / value on one row; actions below -->
      <div class="flex min-w-0 flex-col gap-2">
        <div class="grid grid-cols-2 gap-2 sm:gap-3">
          <div class="flex min-w-0 flex-col gap-1">
            <label class="text-xs font-medium text-(--muted)" for="key">Key</label>
            <input
              class="w-full min-w-0 rounded-lg border bg-(--bg) px-3 py-2 text-sm text-(--text) outline-none focus:border-(--accent) {keyFieldError
                ? 'border-(--bad)'
                : 'border-(--border)'}"
              id="key"
              type="text"
              bind:value={keyInput}
              disabled={busy}
              aria-invalid={keyFieldError ? 'true' : 'false'}
              aria-describedby={keyFieldError ? 'key-field-error' : undefined}
              oninput={() => {
                keyFieldError = null
              }}
            />
            {#if keyFieldError}
              <p id="key-field-error" class="mt-0.5 text-xs leading-snug text-(--bad)" role="alert">
                {keyFieldError}
              </p>
            {/if}
          </div>
          <div class="flex min-w-0 flex-col gap-1">
            <label class="text-xs font-medium text-(--muted)" for="val">Value</label>
            <input
              class="w-full min-w-0 rounded-lg border bg-(--bg) px-3 py-2 text-sm text-(--text) outline-none focus:border-(--accent) {valueFieldError
                ? 'border-(--bad)'
                : 'border-(--border)'}"
              id="val"
              type="text"
              bind:value={valueInput}
              disabled={busy}
              title="Used for Insert"
              aria-invalid={valueFieldError ? 'true' : 'false'}
              aria-describedby={valueFieldError ? 'value-field-error' : undefined}
              oninput={() => {
                valueFieldError = null
              }}
            />
            {#if valueFieldError}
              <p id="value-field-error" class="mt-0.5 text-xs leading-snug text-(--bad)" role="alert">
                {valueFieldError}
              </p>
            {/if}
          </div>
        </div>
        <div class="flex min-w-0 flex-wrap gap-2">
          <button
            type="button"
            class="rounded-lg border border-transparent bg-(--accent) px-3 py-2 text-sm font-semibold text-[#0f1219] hover:brightness-110 disabled:cursor-not-allowed disabled:opacity-50"
            onclick={insertOp}
            disabled={busy || !!loadError}
          >
            Insert
          </button>
          <button
            type="button"
            class="rounded-lg border border-(--border) bg-(--surface) px-3 py-2 text-sm hover:border-(--accent) hover:bg-(--accent-dim) disabled:cursor-not-allowed disabled:opacity-50"
            onclick={deleteOp}
            disabled={busy || !!loadError}
          >
            Delete
          </button>
          <button
            type="button"
            class="rounded-lg border border-(--border) bg-(--surface) px-3 py-2 text-sm hover:border-(--accent) hover:bg-(--accent-dim) disabled:cursor-not-allowed disabled:opacity-50"
            onclick={runLookup}
            disabled={busy || !!loadError || !keyInput.trim()}
          >
            Lookup
          </button>
          <button
            type="button"
            class="rounded-lg border border-(--border) bg-(--surface) px-3 py-2 text-sm hover:border-(--accent) hover:bg-(--accent-dim) disabled:cursor-not-allowed disabled:opacity-50"
            onclick={loadSample}
            disabled={busy || !!loadError}
          >
            Sample
          </button>
          <button
            type="button"
            class="rounded-lg border border-(--border) bg-(--surface) px-3 py-2 text-sm hover:border-(--accent) hover:bg-(--accent-dim) disabled:cursor-not-allowed disabled:opacity-50"
            onclick={resetAll}
            disabled={busy || !!loadError}
          >
            Reset
          </button>
        </div>
      </div>
    </div>

    {#if lookupResult}
      <p
        class="mt-3 rounded-xl border border-(--border) bg-(--bg) px-4 py-3 text-sm leading-relaxed md:px-5 md:py-4 md:text-base"
      >
        {#if lookupResult.found}
          <span class="text-base font-medium text-(--text) md:text-lg">
            <code class="rounded bg-(--surface) px-1.5 py-0.5 text-[0.95em]">{lookupResult.key}</code> →
          </span>
          <span class="ml-2 font-mono text-base text-(--text) md:text-lg">{lookupResult.value_utf8 ?? '—'}</span>
          <span class="mt-2 block font-mono text-xs text-(--muted) break-all md:text-sm">
            hex {lookupResult.value_hex} · root {lookupResult.state_root_hex}
          </span>
        {:else}
          <span class="text-base text-(--muted) md:text-lg">
            No entry for <code class="rounded bg-(--surface) px-1.5 py-0.5 text-(--text)">{lookupResult.key}</code>.
          </span>
          <span class="mt-2 block font-mono text-xs text-(--muted) break-all md:text-sm">{lookupResult.state_root_hex}</span>
        {/if}
      </p>
    {/if}
  </section>

  <div
    class="mt-5 grid grid-cols-1 gap-5 md:grid-cols-[minmax(260px,1fr)_minmax(0,2fr)] md:items-stretch md:gap-5 md:min-h-[70vh]"
  >
    <section
      class="flex min-h-[280px] min-w-0 flex-col rounded-xl border border-(--border) bg-(--surface) p-4 md:h-full md:min-h-0"
    >
      <div class="flex shrink-0 flex-wrap items-start justify-between gap-2">
        <h2 class="text-base font-semibold">History</h2>
        {#if steps.length >= 2}
          <button
            type="button"
            class="shrink-0 rounded-lg border border-(--border) bg-(--surface) px-3 py-2 text-sm hover:border-(--accent) hover:bg-(--accent-dim) disabled:cursor-not-allowed disabled:opacity-50"
            onclick={toggleTriePlay}
            disabled={busy || !!loadError}
          >
            {triePlaying ? 'Pause' : 'Play steps'}
          </button>
        {/if}
      </div>
      <p class="mt-1 shrink-0 text-xs text-(--muted)">Click a step to show that trie state in the graph.</p>
      {#if steps.length === 0}
        <p class="mt-2 flex-1 text-sm text-(--muted) md:min-h-0">
          No steps yet - run an operation or pick a database above.
        </p>
      {:else}
        <ul
          class="mt-2 flex min-h-0 max-h-[70vh] flex-1 flex-col gap-1 overflow-y-auto pr-1 md:max-h-none"
        >
          {#each steps as step, idx}
            <li class="list-none">
              <button
                type="button"
                class="w-full max-w-full rounded-lg border px-3 py-2 text-left text-sm transition-colors disabled:opacity-50 {stepIndex === idx
                  ? 'border-(--accent) bg-(--accent-dim) text-(--text)'
                  : 'border-(--border) bg-(--surface) text-(--muted) hover:border-(--accent) hover:bg-(--accent-dim)'}"
                onclick={() => goToTrieStep(idx)}
                disabled={busy || !!loadError}
                aria-pressed={stepIndex === idx}
              >
                <span class="block font-medium text-(--text)">{step.label}</span>
                <span class="mt-0.5 block font-mono text-[10px] break-all text-(--muted)">
                  state_root: {step.state_root_hex}
                </span>
              </button>
            </li>
          {/each}
        </ul>
      {/if}
    </section>

    <section
      class="flex min-h-[280px] min-w-0 flex-col rounded-xl border border-(--border) bg-(--surface) p-4 md:h-full md:min-h-0"
    >
      <h2 class="shrink-0 text-base font-semibold">Structure (Graphviz)</h2>
      {#if trieSvg}
        <div
          class="graph-wrap mt-3 max-h-[70vh] min-h-0 flex-1 overflow-auto rounded-lg bg-white p-2 md:max-h-none"
        >
          {@html trieSvg}
        </div>
      {:else if steps.length > 0 && !steps[stepIndex]?.dot}
        <div
          class="mt-3 min-h-[200px] rounded-lg border border-(--border) bg-white"
          aria-label="Empty trie (no graph nodes)"
        ></div>
      {:else if !loadError}
        <p class="mt-3 flex-1 text-sm text-(--muted) md:min-h-0">Graph appears after the first successful replay.</p>
      {/if}
    </section>
  </div>

  <section class="mt-5 rounded-xl border border-(--border) bg-(--surface) p-4">
    <h2 class="text-base font-semibold">Root hash &amp; inclusion proof</h2>
    <p class="mt-1 text-sm text-(--muted)">
      The state root is <code>keccak256(RLP(root_node))</code>. The walkthrough replays your history, builds a
      proof for the key below, and steps through <code>verify_inclusion</code> (embedded vs hashed child refs).
    </p>

    <div class="mt-3 flex flex-wrap items-end gap-2">
      <label class="block w-full text-xs font-medium text-(--muted)" for="pk">Key to prove</label>
      <input
        class="w-full max-w-64 rounded-lg border border-(--border) bg-(--bg) px-3 py-2 text-sm text-(--text) outline-none focus:border-(--accent)"
        id="pk"
        type="text"
        bind:value={proveKey}
        disabled={busy}
      />
      <button
        type="button"
        class="rounded-lg border border-transparent bg-(--accent) px-3 py-2 text-sm font-semibold text-[#0f1219] hover:brightness-110 disabled:cursor-not-allowed disabled:opacity-50"
        onclick={runVerifyDemo}
        disabled={busy || !!loadError || (!activeDb && operations.length === 0)}
      >
        Run verification walkthrough
      </button>
    </div>

    {#if verifyResult}
      <div class="mt-3 rounded-lg border border-(--border) bg-(--bg) p-3">
        <p class="font-mono text-xs break-all text-(--muted)">
          state_root (keccak): <span class="break-all">{verifyResult.root_keccak_hex}</span>
        </p>
        <p class="mt-1 font-mono text-xs break-all text-(--muted)">
          root RLP (proof[0], hex): <span class="break-all">{verifyResult.root_rlp_hex}</span>
        </p>
        <p class="mt-1 font-mono text-xs break-all text-(--muted)">
          value for <code>{verifyResult.prove_key}</code>: <span class="break-all">{verifyResult.value_hex}</span>
        </p>
        <p class="mt-1 font-mono text-xs break-all text-(--muted)">
          proof nodes: {verifyResult.proof_nodes_hex.length}
        </p>
        <p class={`mt-2 font-bold ${verifyResult.verified ? 'text-(--good)' : 'text-(--bad)'}`}>
          Result: {verifyResult.verified ? 'VERIFIED' : 'FAILED'}
        </p>
      </div>

      <h3 class="mt-4 text-sm font-semibold">Verification steps</h3>
      <div class="mt-2 flex flex-col gap-2">
        <input
          class="w-full max-w-[420px]"
          type="range"
          min="0"
          max={verifyResult.verify_steps.length - 1}
          bind:value={verifyStepIndex}
          disabled={verifyResult.verify_steps.length < 2}
        />
        <button
          type="button"
          class="w-fit rounded-lg border border-(--border) bg-(--surface) px-3 py-2 text-sm hover:border-(--accent) hover:bg-(--accent-dim) disabled:cursor-not-allowed disabled:opacity-50"
          onclick={toggleVerifyPlay}
          disabled={verifyResult.verify_steps.length < 2}
        >
          {verifyPlaying ? 'Pause' : 'Play'}
        </button>
      </div>

      {#each verifyResult.verify_steps as s, i}
        <article
          class={`my-2 rounded-lg border border-(--border) p-3 opacity-60 ${
            i === verifyStepIndex ? 'opacity-100 border-(--accent) bg-(--accent-dim)' : ''
          } ${s.ok === true ? 'border-l-4 border-l-(--good)' : ''} ${
            s.ok === false ? 'border-l-4 border-l-(--bad)' : ''
          }`}
        >
          <h4 class="text-sm font-semibold">{s.title}</h4>
          <p class="mt-1 text-sm text-(--muted)">{s.detail}</p>
          {#if s.hash_hex}
            <p class="mt-2 font-mono text-[11px] break-all text-(--muted)">hash: {s.hash_hex}</p>
          {/if}
          {#if s.expected_state_root_hex}
            <p class="mt-2 font-mono text-[11px] break-all text-(--muted)">
              expected state_root: {s.expected_state_root_hex}
            </p>
          {/if}
          {#if s.proof_index !== undefined}
            <p class="mt-2 font-mono text-[11px] break-all text-(--muted)">proof index: {s.proof_index}</p>
          {/if}
        </article>
      {/each}
    {/if}
  </section>
</div>

<style>
  /* Graphviz output uses inline styles; keep a small global shim. */
  .graph-wrap :global(svg) {
    max-width: 100%;
    height: auto;
    display: block;
  }

  .graph-wrap :global(.embed-err) {
    color: #b91c1c;
    margin: 0;
    white-space: pre-wrap;
  }
</style>
