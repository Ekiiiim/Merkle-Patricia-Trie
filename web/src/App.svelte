<script lang="ts">
  import { onMount } from 'svelte'
  import GraphView from './GraphView.svelte'
  import ExpandableHex from './lib/ExpandableHex.svelte'

  type TrieOp = { op: 'insert' | 'delete'; key: string; value?: string }
  type TrieGraph = { nodes: any[]; edges: any[] }
  type Step = { label: string; state_root_hex: string; dot: string; graph?: TrieGraph }
  type VerifyStep = {
    title: string
    detail: string
    ok?: boolean
    hash_hex?: string
    expected_state_root_hex?: string
    proof_index?: number
    depth?: number
    n_nibbles?: number
    key_path_nibbles_hex?: string
    detail_hexes?: { label: string; hex: string }[]
    node_kind?: 'leaf' | 'extension' | 'branch'
    node_hash_hex?: string
  }

  /** Synthetic DB row: in-RAM trie only (no SQLite file). Must not match real `db/*.db` names. */
  const MEMORY_DB = '__MPT_MEMORY__'

  let steps = $state<Step[]>([])
  let stepIndex = $state(0)
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
    value_utf8: string | null
    value_hex: string
    proof_nodes_hex: string[]
    verify_steps: VerifyStep[]
    verified: boolean
    root_rlp_hex: string
    root_keccak_hex: string
  }>(null)
  /** Verify-demo API failure; shown inside the verification section, not as global apiError. */
  let verifySectionError = $state<string | null>(null)
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
  let historyPanelTab = $state<'history' | 'verification'>('history')

  let triePlayTimer: ReturnType<typeof setInterval> | null = null
  let verifyPlayTimer: ReturnType<typeof setInterval> | null = null
  let verifyStepsScrollEl = $state<HTMLDivElement | null>(null)

  let selectedGraphNode = $state<any | null>(null)
  let selectedNodeId = $state<string | null>(null)
  let highlightPath = $state<string[]>([])
  let highlightCurrent = $state<string | null>(null)

  function nibbleCountFromHexPrefix(x: unknown): number | null {
    if (typeof x !== 'string') return null
    const s = x.startsWith('0x') ? x.slice(2) : x
    if (!/^[0-9a-fA-F]*$/.test(s)) return null
    return s.length
  }

  function formatHexBytesSpaced(hex: unknown): string {
    if (typeof hex !== 'string') return ''
    const s = hex.startsWith('0x') ? hex.slice(2) : hex
    if (!s) return ''
    const cleaned = s.toLowerCase().replace(/[^0-9a-f]/g, '')
    const pairs = cleaned.match(/.{1,2}/g) ?? []
    return `0x${pairs.join(' ')}`
  }

  function as0xHex(hex: unknown): string {
    if (typeof hex !== 'string') return ''
    const s = hex.trim()
    if (!s) return ''
    return s.startsWith('0x') ? s : `0x${s}`
  }

  // Click-to-expand truncation lives in `ExpandableHex`.

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
    // Whenever we scrub the verification slider, update the highlighted path on the trie graph.
    const all = verifyResult?.verify_steps ?? []
    const idx = Math.max(0, Math.min(verifyStepIndex, Math.max(0, all.length - 1)))
    const path: string[] = []
    const seen = new Set<string>()
    for (let i = 0; i <= idx; i++) {
      const h = all[i]?.node_hash_hex
      if (typeof h === 'string' && h && !seen.has(h)) {
        seen.add(h)
        path.push(h)
      }
    }
    highlightPath = path
    highlightCurrent = path.length ? path[path.length - 1] : null
  })

  $effect(() => {
    // In play mode, keep the currently-selected verification step visible.
    if (historyPanelTab !== 'verification') return
    if (!verifyPlaying) return
    if (!verifyStepsScrollEl) return
    if (!verifyResult?.verify_steps?.length) return
    const idx = Math.max(0, Math.min(verifyStepIndex, verifyResult.verify_steps.length - 1))
    const el = verifyStepsScrollEl.querySelector<HTMLElement>(`[data-verify-step="${idx}"]`)
    el?.scrollIntoView({ block: 'nearest' })
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
    verifySectionError = null
    selectedGraphNode = null
    selectedNodeId = null
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
    verifySectionError = null
    lookupResult = null
    selectedGraphNode = null
    selectedNodeId = null
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

  /** Drop the loaded file DB session on the server and return to an empty in-RAM trie. */
  async function unloadDb() {
    apiError = null
    keyFieldError = null
    valueFieldError = null
    verifyResult = null
    verifySectionError = null
    lookupResult = null
    selectedGraphNode = null
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
    selectedGraphNode = null
    selectedNodeId = null
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
      verifySectionError = null
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
    if (!k) {
      keyFieldError = 'Key is required to delete.'
      return
    }
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
    verifySectionError = null
    lookupResult = null
    keyFieldError = null
    valueFieldError = null
    selectedGraphNode = null
    selectedNodeId = null
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
    verifySectionError = null
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
        verifySectionError =
          typeof (data as { detail?: string }).detail === 'string'
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
      <div class="flex min-w-0 w-full flex-col gap-2 md:border-r md:border-(--border) md:pr-6">
        <div class="flex min-w-0 w-full flex-col gap-1">
          <label class="text-xs font-medium text-(--muted)" for="dbsel">Database</label>
          <div class="flex min-w-0 w-full flex-nowrap items-end gap-2">
            <select
              id="dbsel"
              class="min-w-0 w-full flex-1 rounded-lg border border-(--border) bg-(--bg) px-3 py-2 text-sm text-(--text) outline-none focus:border-(--accent)"
              bind:value={selectedDb}
              onchange={onDbSelectChange}
              disabled={busy}
            >
              <option value={MEMORY_DB}>None (empty in-RAM trie, non-persistent)</option>
              {#each dbs as name}
                <option value={name}>{name}</option>
              {/each}
            </select>
            <button
              type="button"
              class="shrink-0 rounded-lg border border-(--border) bg-(--surface) px-3 py-2 text-sm hover:border-(--accent) hover:bg-(--accent-dim) disabled:cursor-not-allowed disabled:opacity-50"
              onclick={unloadDb}
              disabled={busy || !activeDb}
            >
              Unload
            </button>
          </div>
        </div>
        {#if activeDb}
          <p class="truncate text-xs leading-snug text-(--muted)" title={activeDb}>
            Active: <code class="text-(--text)">{activeDb}</code>
          </p>
        {:else}
          <p class="text-xs leading-snug text-(--muted)">
            Active: <code class="text-(--text)">None</code> (empty in-RAM trie, non-persistent)
          </p>
        {/if}
      </div>

      <!-- Key / value on one row; actions below -->
      <div class="flex min-w-0 flex-col gap-2">
        <div class="grid grid-cols-2 gap-2 sm:gap-3">
          <div class="flex min-w-0 flex-col gap-1">
            <label class="text-xs font-medium text-(--muted)" for="key">Key</label>
            <div class="relative">
              <input
                class="w-full min-w-0 rounded-lg border bg-(--bg) px-3 py-2 pr-9 text-sm text-(--text) outline-none focus:border-(--accent) {keyFieldError
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
              {#if keyInput.trim().length > 0}
                <button
                  type="button"
                  class="absolute right-1 top-1/2 inline-flex h-7 w-7 -translate-y-1/2 items-center justify-center rounded-full bg-transparent text-sm leading-none text-(--muted) hover:text-(--text) disabled:cursor-not-allowed disabled:opacity-50"
                  onclick={() => {
                    keyInput = ''
                    keyFieldError = null
                  }}
                  disabled={busy}
                  aria-label="Clear key input"
                  title="Clear"
                >
                  ×
                </button>
              {/if}
            </div>
            {#if keyFieldError}
              <p id="key-field-error" class="mt-0.5 text-xs leading-snug text-(--bad)" role="alert">
                {keyFieldError}
              </p>
            {/if}
          </div>
          <div class="flex min-w-0 flex-col gap-1">
            <label class="text-xs font-medium text-(--muted)" for="val">Value</label>
            <div class="relative">
              <input
                class="w-full min-w-0 rounded-lg border bg-(--bg) px-3 py-2 pr-9 text-sm text-(--text) outline-none focus:border-(--accent) {valueFieldError
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
              {#if String(valueInput ?? '').trim().length > 0}
                <button
                  type="button"
                  class="absolute right-1 top-1/2 inline-flex h-7 w-7 -translate-y-1/2 items-center justify-center rounded-full bg-transparent text-sm leading-none text-(--muted) hover:text-(--text) disabled:cursor-not-allowed disabled:opacity-50"
                  onclick={() => {
                    valueInput = ''
                    valueFieldError = null
                  }}
                  disabled={busy}
                  aria-label="Clear value input"
                  title="Clear"
                >
                  ×
                </button>
              {/if}
            </div>
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
            disabled={busy}
          >
            Insert
          </button>
          <button
            type="button"
            class="rounded-lg border border-(--border) bg-(--surface) px-3 py-2 text-sm hover:border-(--accent) hover:bg-(--accent-dim) disabled:cursor-not-allowed disabled:opacity-50"
            onclick={deleteOp}
            disabled={busy}
          >
            Delete
          </button>
          <button
            type="button"
            class="rounded-lg border border-(--border) bg-(--surface) px-3 py-2 text-sm hover:border-(--accent) hover:bg-(--accent-dim) disabled:cursor-not-allowed disabled:opacity-50"
            onclick={runLookup}
            disabled={busy || !keyInput.trim()}
          >
            Lookup
          </button>
          <button
            type="button"
            class="rounded-lg border border-(--border) bg-(--surface) px-3 py-2 text-sm hover:border-(--accent) hover:bg-(--accent-dim) disabled:cursor-not-allowed disabled:opacity-50"
            onclick={loadSample}
            disabled={busy}
          >
            Sample
          </button>
          <button
            type="button"
            class="rounded-lg border border-(--border) bg-(--surface) px-3 py-2 text-sm hover:border-(--accent) hover:bg-(--accent-dim) disabled:cursor-not-allowed disabled:opacity-50"
            onclick={resetAll}
            disabled={busy}
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
      class="flex min-h-[280px] max-h-[70vh] min-w-0 flex-col overflow-hidden rounded-xl border border-(--border) bg-(--surface) p-4 md:h-full md:min-h-0"
    >
      <div class="flex shrink-0">
        <div class="flex w-full min-w-0 flex-1 items-center">
          <nav
            class="flex w-full min-w-0 rounded-lg border border-(--border) bg-(--bg) p-1"
            aria-label="History panel tabs"
          >
            <button
              type="button"
              class={`min-w-0 flex-1 rounded-md px-2 py-1.5 text-sm font-medium transition-colors ${
                historyPanelTab === 'history'
                  ? 'bg-(--surface) text-(--text) shadow-sm'
                  : 'text-(--muted) hover:bg-(--surface)'
              }`}
              onclick={() => {
                stopVerifyPlay()
                historyPanelTab = 'history'
              }}
              aria-current={historyPanelTab === 'history' ? 'page' : undefined}
            >
              History
            </button>
            <button
              type="button"
              class={`min-w-0 flex-1 rounded-md px-2 py-1.5 text-sm font-medium transition-colors ${
                historyPanelTab === 'verification'
                  ? 'bg-(--surface) text-(--text) shadow-sm'
                  : 'text-(--muted) hover:bg-(--surface)'
              }`}
              onclick={() => {
                stopTriePlay()
                historyPanelTab = 'verification'
              }}
              aria-current={historyPanelTab === 'verification' ? 'page' : undefined}
            >
              Verification
            </button>
          </nav>
        </div>
      </div>

      {#if historyPanelTab === 'history'}
        <div class="mt-2 flex shrink-0 flex-wrap items-center justify-between gap-2">
          <p class="text-xs text-(--muted)">Click a step to show that trie state in the graph.</p>
          {#if steps.length >= 2}
            <button
              type="button"
              class="shrink-0 rounded-lg border border-(--border) bg-(--surface) px-3 py-2 text-sm hover:border-(--accent) hover:bg-(--accent-dim) disabled:cursor-not-allowed disabled:opacity-50"
              onclick={toggleTriePlay}
              disabled={busy}
            >
              {triePlaying ? 'Pause' : 'Play steps'}
            </button>
          {/if}
        </div>
        {#if steps.length === 0}
          <p class="mt-2 flex-1 text-sm text-(--muted) md:min-h-0">
            No steps yet - run an operation or pick a database above.
          </p>
        {:else}
          <ul class="mt-2 flex min-h-0 flex-1 flex-col gap-1 overflow-y-auto pr-1">
            {#each steps as step, idx}
              <li class="list-none">
                <button
                  type="button"
                  class="w-full max-w-full rounded-lg border px-3 py-2 text-left text-sm transition-colors disabled:opacity-50 {stepIndex === idx
                    ? 'border-(--accent) bg-(--accent-dim) text-(--text)'
                    : 'border-(--border) bg-(--surface) text-(--muted) hover:border-(--accent) hover:bg-(--accent-dim)'}"
                  onclick={() => goToTrieStep(idx)}
                  disabled={busy}
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
      {:else}
        <p class="mt-2 shrink-0 text-xs text-(--muted) leading-snug">
          Root = <code>keccak256(RLP(root_node))</code>. Build a proof for the key below, then step through
          <code>verify_inclusion</code>.
        </p>

        <div class="mt-3 flex shrink-0 flex-col gap-2">
          <label class="text-xs font-medium text-(--muted)" for="pk">Key to prove</label>
          <div class="flex flex-wrap items-end gap-2">
            <input
              class="w-full min-w-0 flex-1 rounded-lg border border-(--border) bg-(--bg) px-3 py-2 text-sm text-(--text) outline-none focus:border-(--accent)"
              id="pk"
              type="text"
              bind:value={proveKey}
              disabled={busy}
            />
            <button
              type="button"
              class="rounded-lg border border-transparent bg-(--accent) px-3 py-2 text-sm font-semibold text-[#0f1219] hover:brightness-110 disabled:cursor-not-allowed disabled:opacity-50"
              onclick={runVerifyDemo}
              disabled={busy || (!activeDb && operations.length === 0)}
            >
              Verify
            </button>
          </div>
        </div>

        <div class="mt-3 min-h-0 flex-1 overflow-y-auto pr-1">
          {#if verifyResult}
            <div class="rounded-lg border border-(--border) bg-(--bg) p-3">
              <p class="font-mono text-[11px] break-all text-(--muted)">
                state_root (keccak): <span class="break-all">{verifyResult.root_keccak_hex}</span>
              </p>
              <p class="mt-1 font-mono text-[11px] break-all text-(--muted)">
                value for <code>{verifyResult.prove_key}</code>:
                <span class="break-all">{verifyResult.value_utf8 ?? verifyResult.value_hex}</span>
              </p>
              <p class="mt-1 font-mono text-[11px] break-all text-(--muted)">
                proof nodes: {verifyResult.proof_nodes_hex.length}
              </p>
              <p class={`mt-2 font-bold ${verifyResult.verified ? 'text-(--good)' : 'text-(--bad)'}`}>
                Result: {verifyResult.verified ? 'VERIFIED' : 'FAILED'}
              </p>
            </div>

            <div class="mt-3">
              <div class="flex items-center justify-between gap-2">
                <h3 class="text-sm font-semibold">Proof</h3>
                <p class="text-xs text-(--muted)">
                  {verifyResult.proof_nodes_hex.length} node{verifyResult.proof_nodes_hex.length === 1 ? '' : 's'}
                </p>
              </div>
              <div class="mt-2 max-h-48 overflow-y-auto rounded-lg border border-(--border) bg-(--bg) p-2 pr-1">
                {#each verifyResult.proof_nodes_hex as n, idx (idx)}
                  <div class="flex gap-2 py-1">
                    <span class="shrink-0 font-mono text-[11px] text-(--muted)">[{idx}]</span>
                    <span class="min-w-0 font-mono text-[11px] break-all text-(--muted)">
                      <ExpandableHex value={as0xHex(n)} className="text-(--muted)" first={16} last={12} />
                    </span>
                  </div>
                  {#if idx !== verifyResult.proof_nodes_hex.length - 1}
                    <div class="h-px bg-(--border) opacity-60"></div>
                  {/if}
                {/each}
              </div>
              <p class="mt-1 text-xs text-(--muted)">
                Each entry is an RLP-encoded node (hex). Click to expand/collapse.
              </p>
            </div>

            <div class="mt-3 flex min-h-0 flex-col">
              <div class="flex flex-wrap items-center justify-between gap-2">
                <h3 class="text-sm font-semibold">Steps</h3>
                <div class="flex items-center gap-2">
                  <button
                    type="button"
                    class="rounded-lg border border-(--border) bg-(--surface) px-3 py-2 text-sm hover:border-(--accent) hover:bg-(--accent-dim) disabled:cursor-not-allowed disabled:opacity-50"
                    onclick={toggleVerifyPlay}
                    disabled={verifyResult.verify_steps.length < 2}
                  >
                    {verifyPlaying ? 'Pause' : 'Play'}
                  </button>
                </div>
              </div>

              <div class="mt-2 max-h-76 min-h-0 overflow-y-auto pr-1" bind:this={verifyStepsScrollEl}>
                {#each verifyResult.verify_steps as s, i}
                  <button
                    type="button"
                    data-verify-step={i}
                    class={`w-full rounded-lg border border-(--border) p-3 text-left opacity-60 transition-colors hover:border-(--accent) hover:bg-(--accent-dim) disabled:cursor-not-allowed disabled:opacity-50 ${
                      i === verifyStepIndex ? 'opacity-100 border-(--accent) bg-(--accent-dim)' : ''
                    } ${s.ok === true ? 'border-l-4 border-l-(--good)' : ''} ${
                      s.ok === false ? 'border-l-4 border-l-(--bad)' : ''
                    }`}
                    aria-current={i === verifyStepIndex ? 'step' : undefined}
                    onclick={() => {
                      stopVerifyPlay()
                      verifyStepIndex = i
                    }}
                  >
                    <h4 class="text-sm font-semibold">{s.title}</h4>
                    <p class="mt-1 text-sm text-(--muted)">{s.detail}</p>
                    {#if Array.isArray(s.detail_hexes) && s.detail_hexes.length}
                      <div class="mt-1 flex flex-col gap-1">
                        {#each s.detail_hexes as hx, j (j)}
                          <p class="font-mono text-[11px] break-all text-(--muted)">
                            {hx.label}: <ExpandableHex value={as0xHex(hx.hex)} className="text-(--muted)" first={12} last={10} />
                          </p>
                        {/each}
                      </div>
                    {:else if s.key_path_nibbles_hex}
                      <p class="mt-1 font-mono text-[11px] break-all text-(--muted)">
                        path: <ExpandableHex value={as0xHex(s.key_path_nibbles_hex)} className="text-(--muted)" first={12} last={10} />
                      </p>
                    {/if}
                    {#if s.hash_hex}
                      <p class="mt-2 font-mono text-[11px] break-all text-(--muted)">
                        hash: <ExpandableHex value={as0xHex(s.hash_hex)} className="text-(--muted)" />
                      </p>
                    {/if}
                    {#if s.expected_state_root_hex}
                      <p class="mt-2 font-mono text-[11px] break-all text-(--muted)">
                        expected state_root:
                        <ExpandableHex value={as0xHex(s.expected_state_root_hex)} className="text-(--muted)" />
                      </p>
                    {/if}
                    {#if s.node_hash_hex}
                      <p class="mt-2 font-mono text-[11px] break-all text-(--muted)">
                        node hash: <ExpandableHex value={as0xHex(s.node_hash_hex)} className="text-(--muted)" />
                      </p>
                    {/if}
                    {#if s.proof_index !== undefined}
                      <p class="mt-2 font-mono text-[11px] break-all text-(--muted)">proof index: {s.proof_index}</p>
                    {/if}
                  </button>
                  {#if i !== verifyResult.verify_steps.length - 1}
                    <div class="h-2"></div>
                  {/if}
                {/each}
              </div>
            </div>
          {:else if verifySectionError}
            <div class="rounded-lg border border-(--border) bg-(--bg) p-3" role="alert">
              <p class="font-mono text-[11px] break-all text-(--muted)">state_root (keccak): —</p>
              <p class="mt-1 font-mono text-[11px] break-all text-(--muted)">
                value for <code>{proveKey}</code>: —
              </p>
              <p class="mt-1 font-mono text-[11px] break-all text-(--muted)">proof nodes: —</p>
              <p class="mt-2 font-bold text-(--bad)">Result: FAILED</p>
              <p class="mt-2 text-sm text-(--bad)">{verifySectionError}</p>
            </div>
          {:else}
            <p class="text-sm text-(--muted)">Run the walkthrough to see the computed root hash and proof steps.</p>
          {/if}
        </div>
      {/if}
    </section>

    <section
      class="flex min-h-[280px] min-w-0 flex-col rounded-xl border border-(--border) bg-(--surface) p-4 md:h-full md:min-h-0"
    >
      <h2 class="shrink-0 text-base font-semibold">Structure (interactive)</h2>
      {#if steps.length > 0 && steps[stepIndex]?.graph}
        <div class="mt-3 min-h-[260px] max-h-[70vh] flex-1 overflow-hidden rounded-lg border border-(--border) bg-white md:min-h-0">
          {#key steps[stepIndex]?.state_root_hex}
            <GraphView
              graph={steps[stepIndex]!.graph!}
              highlightPath={highlightPath}
              highlightCurrent={highlightCurrent}
              selectedId={selectedNodeId}
              on:nodeclick={(e: CustomEvent<any>) => {
                const id = String(e.detail?.id ?? '')
                selectedNodeId = id || null
                selectedGraphNode = e.detail
              }}
            />
          {/key}
        </div>
        {#if selectedGraphNode}
          {@const nodeUid = String(selectedGraphNode.id ?? selectedGraphNode.hash_hex ?? 'node')}
          <div class="mt-3 rounded-lg border border-(--border) bg-(--bg) p-3">
            <div class="flex items-start justify-between gap-3">
              <p class="text-sm font-semibold text-(--text)">Node details</p>
              <button
                type="button"
                class="rounded-md border border-(--border) bg-(--surface) px-2 py-1 text-xs hover:border-(--accent) hover:bg-(--accent-dim)"
                onclick={() => {
                  selectedGraphNode = null
                  selectedNodeId = null
                }}
              >
                Close
              </button>
            </div>
            <!-- 1. Summary -->
            <p class="mt-2 text-xs text-(--muted)">
              kind: <code class="text-(--text)">{selectedGraphNode.kind}</code>
            </p>
            {#if selectedGraphNode.value_utf8}
              <p class="mt-1 text-xs text-(--muted)">
                value (UTF-8): <code class="text-(--text)">{selectedGraphNode.value_utf8}</code>
              </p>
            {/if}
            {#if selectedGraphNode.kind === 'leaf' && selectedGraphNode.key_utf8}
              <p class="mt-1 text-xs text-(--muted)">
                key (UTF-8): <code class="text-(--text)">{selectedGraphNode.key_utf8}</code>
              </p>
            {/if}
            {#if selectedGraphNode.kind === 'leaf' && selectedGraphNode.key_keccak_hex}
              <p class="mt-1 text-xs text-(--muted)">
                keccak256(key) (bytes): <code class="text-(--text) break-all">{formatHexBytesSpaced(selectedGraphNode.key_keccak_hex)}</code>
              </p>
            {/if}
            {#if selectedGraphNode.path_nibbles_hex}
              <p class="mt-1 text-xs text-(--muted)">
                {selectedGraphNode.kind === 'leaf' ? 'full path (nibbles):' : 'path (nibbles):'}
                <code class="text-(--text) break-all">{selectedGraphNode.path_nibbles_hex}</code>
              </p>
            {/if}
            {#if selectedGraphNode.hash_hex}
              <p class="mt-1 text-xs text-(--muted)">
                hash: <code class="text-(--text) break-all">{selectedGraphNode.hash_hex}</code>
              </p>
            {/if}

            <!-- 2. Hash & RLP explanation (combined) -->
            {#if selectedGraphNode.rlp_hex && selectedGraphNode.hash_hex}
              <div class="mt-3">
                <p class="text-xs font-semibold text-(--text)">How hash is computed</p>
                <p class="mt-1 font-mono text-[11px] break-all text-(--muted)">
                  hash = keccak256(RLP(node)) = keccak256(
                  <ExpandableHex value={`0x${selectedGraphNode.rlp_hex}`} />
                  ) = <ExpandableHex value={`0x${selectedGraphNode.hash_hex}`} />
                </p>

                {#if selectedGraphNode.kind === 'leaf'}
                  <p class="mt-2 font-mono text-[11px] break-all text-(--muted)">
                    RLP(node) = RLP([ compact_encoding(path, leaf), value ]) = RLP([
                    <ExpandableHex value={`0x${selectedGraphNode.compact_path_hex ?? ''}`} />,
                    <ExpandableHex value={`0x${selectedGraphNode.value_hex ?? ''}`} />
                    ]) = <ExpandableHex value={`0x${selectedGraphNode.rlp_hex}`} />
                  </p>
                  {#if selectedGraphNode.node_path_nibbles_hex && selectedGraphNode.compact_path_hex}
                    {@const nibs = String(selectedGraphNode.node_path_nibbles_hex)}
                    {@const nNibs = nibbleCountFromHexPrefix(nibs) ?? 0}
                    {@const odd = nNibs % 2}
                    {@const flags = 2 + odd /* 2=leaf, +1 if odd */ }
                    <p class="mt-1 font-mono text-[11px] break-all text-(--muted)">
                      compact_encoding(path, leaf) = prepend(flags, remaining_path) = prepend({flags}, <ExpandableHex value={nibs} />) =
                      <ExpandableHex value={`0x${selectedGraphNode.compact_path_hex}`} />
                    </p>
                    <p class="mt-1 text-xs text-(--muted)">
                      flags = 2 (leaf) + {odd} (odd) = {flags} (high nibble of first byte)
                    </p>
                  {/if}
                {:else if selectedGraphNode.kind === 'extension'}
                  <p class="mt-2 text-xs text-(--muted)">
                    child_ref is embedded RLP if &lt; 32 bytes, otherwise a 32-byte keccak hash.
                  </p>
                  <p class="mt-1 font-mono text-[11px] break-all text-(--muted)">
                    RLP(node) = RLP([ compact_encoding(path, ext), child_ref ]) = RLP([
                    <ExpandableHex value={`0x${selectedGraphNode.compact_path_hex ?? ''}`} />,
                    <ExpandableHex value={`0x${selectedGraphNode.child_ref_hex ?? ''}`} />
                    ]) = <ExpandableHex value={`0x${selectedGraphNode.rlp_hex}`} />
                  </p>
                  {#if selectedGraphNode.node_path_nibbles_hex && selectedGraphNode.compact_path_hex}
                    {@const nibs = String(selectedGraphNode.node_path_nibbles_hex)}
                    {@const nNibs = nibbleCountFromHexPrefix(nibs) ?? 0}
                    {@const odd = nNibs % 2}
                    {@const flags = 0 + odd /* 0=ext, +1 if odd */ }
                    <p class="mt-1 font-mono text-[11px] break-all text-(--muted)">
                      compact_encoding(path, ext) = prepend(flags, remaining_path) = prepend({flags}, <ExpandableHex value={nibs} />) =
                      <ExpandableHex value={`0x${selectedGraphNode.compact_path_hex}`} />
                    </p>
                    <p class="mt-1 text-xs text-(--muted)">
                      flags = 0 (ext) + {odd} (odd) = {flags} (high nibble of first byte)
                    </p>
                  {/if}
                {:else if selectedGraphNode.kind === 'branch'}
                  <p class="mt-2 font-mono text-[11px] break-all text-(--muted)">
                    RLP(node) = RLP([ child0, …, child15, value ]) = <ExpandableHex value={`0x${selectedGraphNode.rlp_hex}`} />
                  </p>
                  <p class="mt-1 text-xs text-(--muted)">
                    Each child slot is empty bytes, embedded RLP (&lt; 32), or a 32-byte hash; index 16 is the branch value.
                  </p>
                  {#if Array.isArray(selectedGraphNode.child_refs_hex) && Array.isArray(selectedGraphNode.child_refs_kind)}
                    {@const refs: string[] = selectedGraphNode.child_refs_hex}
                    {@const kinds: string[] = selectedGraphNode.child_refs_kind}
                    <div class="mt-1 grid grid-cols-1 gap-1">
                      {#each refs as r, idx (idx)}
                        {#if r}
                          <p class="font-mono text-[11px] break-all text-(--muted)">
                            child[{idx.toString(16)}] ({kinds[idx]}):
                            <ExpandableHex value={`0x${r}`} />
                          </p>
                        {/if}
                      {/each}
                    </div>
                  {/if}
                  <p class="mt-1 font-mono text-[11px] break-all text-(--muted)">
                    value slot (index 16):
                    <ExpandableHex value={`0x${selectedGraphNode.value_slot_hex ?? ''}`} />
                  </p>
                {:else}
                  <p class="mt-2 text-xs text-(--muted)">No RLP breakdown for this synthetic node type.</p>
                {/if}
              </div>
            {/if}

          </div>
        {/if}
      {:else}
        <div class="mt-3 min-h-[200px] rounded-lg border border-(--border) bg-white" aria-label="Empty trie"></div>
      {/if}
    </section>
  </div>
</div>

<style>
</style>
