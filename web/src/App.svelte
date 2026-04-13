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

  let gv: Graphviz | null = $state(null)
  let loadError = $state<string | null>(null)
  let steps = $state<Step[]>([])
  let stepIndex = $state(0)
  let trieSvg = $state('')
  let operations = $state<TrieOp[]>([])
  let apiError = $state<string | null>(null)
  let busy = $state(false)

  let keyInput = $state('alice')
  let valueInput = $state('100')
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
  let verifyStepIndex = $state(0)
  let triePlaying = $state(false)
  let verifyPlaying = $state(false)

  let triePlayTimer: ReturnType<typeof setInterval> | null = null
  let verifyPlayTimer: ReturnType<typeof setInterval> | null = null

  onMount(() => {
    void (async () => {
      try {
        const { Graphviz: G } = await import('@hpcc-js/wasm-graphviz')
        gv = await G.load()
      } catch (e) {
        loadError = e instanceof Error ? e.message : String(e)
      }
    })()

    return () => {
      if (triePlayTimer) clearInterval(triePlayTimer)
      if (verifyPlayTimer) clearInterval(verifyPlayTimer)
    }
  })

  $effect(() => {
    const engine = gv
    const dot = steps[stepIndex]?.dot
    if (!engine || !dot) {
      trieSvg = ''
      return
    }
    try {
      trieSvg = engine.layout(dot, 'svg', 'dot')
    } catch (e) {
      trieSvg = `<pre class="embed-err">${e instanceof Error ? e.message : String(e)}</pre>`
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

  async function replayToServer(ops: TrieOp[]) {
    apiError = null
    busy = true
    try {
      const res = await fetch('/api/replay', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ operations: ops }),
      })
      const data = (await res.json().catch(() => ({}))) as { detail?: string; steps?: Step[] }
      if (!res.ok) {
        apiError = typeof data.detail === 'string' ? data.detail : res.statusText
        return false
      }
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
    const k = keyInput.trim()
    if (!k) return
    await replayToServer([...operations, { op: 'insert', key: k, value: valueInput }])
  }

  async function deleteOp() {
    const k = keyInput.trim()
    if (!k) return
    await replayToServer([...operations, { op: 'delete', key: k }])
  }

  async function loadSample() {
    proveKey = 'alice'
    keyInput = 'alice'
    valueInput = '100'
    await replayToServer([
      { op: 'insert', key: 'alice', value: '100' },
      { op: 'insert', key: 'bob', value: '200' },
      { op: 'insert', key: 'alma', value: '300' },
      { op: 'insert', key: 'alick', value: '100' },
    ])
  }

  async function resetAll() {
    verifyResult = null
    stopVerifyPlay()
    await replayToServer([])
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

  async function runVerifyDemo() {
    apiError = null
    verifyResult = null
    stopVerifyPlay()
    busy = true
    try {
      const res = await fetch('/api/verify-demo', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          operations,
          prove_key: proveKey.trim() || 'alice',
        }),
      })
      const data = await res.json().catch(() => ({}))
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

  function opLabel(o: TrieOp, i: number) {
    if (o.op === 'insert') return `${i + 1}. insert(${o.key} → ${o.value ?? ''})`
    return `${i + 1}. delete(${o.key})`
  }
</script>

<div class="mx-auto max-w-6xl px-6 py-5 pb-12">
  <header>
    <h1 class="text-2xl font-semibold tracking-tight">Merkle Patricia Trie</h1>
    <p class="mt-1 max-w-3xl text-sm text-[var(--muted)]">
      Ethereum-style RLP + Keccak-256. Edit the trie below; scrub through each applied operation, then run a
      proof verification walkthrough.
    </p>
  </header>

  {#if loadError}
    <p class="mt-4 rounded-lg border border-[var(--bad)] bg-[var(--surface)] px-4 py-2 text-sm text-[var(--bad)]">
      Could not load Graphviz WASM: {loadError}
    </p>
  {/if}

  {#if apiError}
    <p class="mt-4 rounded-lg border border-[var(--bad)] bg-[var(--surface)] px-4 py-2 text-sm text-[var(--bad)]">
      {apiError}
    </p>
  {/if}

  <div class="mt-5 flex flex-wrap items-start gap-5">
    <section class="flex-1 basis-[280px] rounded-xl border border-[var(--border)] bg-[var(--surface)] p-4">
      <h2 class="text-base font-semibold">Operations</h2>
      <p class="mt-1 text-sm text-[var(--muted)]">
        Keys and values are UTF-8 strings (same style as <code>demo.py</code>).
      </p>

      <div class="mt-3">
        <label class="block text-xs font-medium text-[var(--muted)]" for="key">Key</label>
        <input
          class="mt-1 w-full max-w-64 rounded-lg border border-[var(--border)] bg-[var(--bg)] px-3 py-2 text-sm text-[var(--text)] outline-none focus:border-[var(--accent)]"
          id="key"
          type="text"
          bind:value={keyInput}
          disabled={busy}
        />
      </div>
      <div class="mt-3">
        <label class="block text-xs font-medium text-[var(--muted)]" for="val">Value (insert only)</label>
        <input
          class="mt-1 w-full max-w-64 rounded-lg border border-[var(--border)] bg-[var(--bg)] px-3 py-2 text-sm text-[var(--text)] outline-none focus:border-[var(--accent)]"
          id="val"
          type="text"
          bind:value={valueInput}
          disabled={busy}
        />
      </div>

      <div class="mt-3 flex flex-wrap gap-2">
        <button
          type="button"
          class="rounded-lg border border-transparent bg-[var(--accent)] px-3 py-2 text-sm font-semibold text-[#0f1219] hover:brightness-110 disabled:cursor-not-allowed disabled:opacity-50"
          onclick={insertOp}
          disabled={busy || !!loadError}
        >
          Insert
        </button>
        <button
          type="button"
          class="rounded-lg border border-[var(--border)] bg-[var(--surface)] px-3 py-2 text-sm hover:border-[var(--accent)] hover:bg-[var(--accent-dim)] disabled:cursor-not-allowed disabled:opacity-50"
          onclick={deleteOp}
          disabled={busy || !!loadError}
        >
          Delete
        </button>
        <button
          type="button"
          class="rounded-lg border border-[var(--border)] bg-[var(--surface)] px-3 py-2 text-sm hover:border-[var(--accent)] hover:bg-[var(--accent-dim)] disabled:cursor-not-allowed disabled:opacity-50"
          onclick={loadSample}
          disabled={busy || !!loadError}
        >
          Load sample
        </button>
        <button
          type="button"
          class="rounded-lg border border-[var(--border)] bg-[var(--surface)] px-3 py-2 text-sm hover:border-[var(--accent)] hover:bg-[var(--accent-dim)] disabled:cursor-not-allowed disabled:opacity-50"
          onclick={resetAll}
          disabled={busy || !!loadError}
        >
          Reset
        </button>
      </div>

      <h3 class="mt-4 text-sm font-semibold">History</h3>
      {#if operations.length === 0}
        <p class="mt-1 text-sm text-[var(--muted)]">No operations yet — trie is empty.</p>
      {:else}
        <ol class="mt-2 list-decimal pl-5 text-sm text-[var(--muted)]">
          {#each operations as o, i}
            <li>{opLabel(o, i)}</li>
          {/each}
        </ol>
      {/if}

      <h3 class="mt-4 text-sm font-semibold">Trie step</h3>
      {#if steps.length}
        <p class="mt-1 font-mono text-xs break-all text-[var(--muted)]">{steps[stepIndex]?.label}</p>
        <p class="mt-1 font-mono text-xs break-all text-[var(--accent)]">
          state_root: {steps[stepIndex]?.state_root_hex}
        </p>
        <div class="mt-2 flex flex-col gap-2">
          <input
            class="w-full max-w-[420px]"
            type="range"
            min="0"
            max={steps.length - 1}
            bind:value={stepIndex}
            disabled={steps.length < 2}
          />
          <div class="flex flex-wrap gap-2">
            <button
              type="button"
              class="rounded-lg border border-[var(--border)] bg-[var(--surface)] px-3 py-2 text-sm hover:border-[var(--accent)] hover:bg-[var(--accent-dim)] disabled:cursor-not-allowed disabled:opacity-50"
              onclick={toggleTriePlay}
              disabled={steps.length < 2 || !!loadError}
            >
              {triePlaying ? 'Pause' : 'Play steps'}
            </button>
          </div>
        </div>
      {:else}
        <p class="mt-1 text-sm text-[var(--muted)]">Run an operation to see the trie.</p>
      {/if}
    </section>

    <section class="flex-[2_1_420px] rounded-xl border border-[var(--border)] bg-[var(--surface)] p-4 min-h-[280px]">
      <h2 class="text-base font-semibold">Structure (Graphviz)</h2>
      {#if trieSvg}
        <div class="graph-wrap mt-3 overflow-auto max-h-[70vh] rounded-lg bg-white p-2">
          {@html trieSvg}
        </div>
      {:else if !loadError}
        <p class="mt-3 text-sm text-[var(--muted)]">Graph appears after the first successful replay.</p>
      {/if}
    </section>
  </div>

  <section class="mt-5 rounded-xl border border-[var(--border)] bg-[var(--surface)] p-4">
    <h2 class="text-base font-semibold">Root hash &amp; inclusion proof</h2>
    <p class="mt-1 text-sm text-[var(--muted)]">
      The state root is <code>keccak256(RLP(root_node))</code>. The walkthrough replays your history, builds a
      proof for the key below, and steps through <code>verify_inclusion</code> (embedded vs hashed child refs).
    </p>

    <div class="mt-3 flex flex-wrap items-end gap-2">
      <label class="block w-full text-xs font-medium text-[var(--muted)]" for="pk">Key to prove</label>
      <input
        class="w-full max-w-64 rounded-lg border border-[var(--border)] bg-[var(--bg)] px-3 py-2 text-sm text-[var(--text)] outline-none focus:border-[var(--accent)]"
        id="pk"
        type="text"
        bind:value={proveKey}
        disabled={busy}
      />
      <button
        type="button"
        class="rounded-lg border border-transparent bg-[var(--accent)] px-3 py-2 text-sm font-semibold text-[#0f1219] hover:brightness-110 disabled:cursor-not-allowed disabled:opacity-50"
        onclick={runVerifyDemo}
        disabled={busy || !!loadError || operations.length === 0}
      >
        Run verification walkthrough
      </button>
    </div>

    {#if verifyResult}
      <div class="mt-3 rounded-lg border border-[var(--border)] bg-[var(--bg)] p-3">
        <p class="font-mono text-xs break-all text-[var(--muted)]">
          state_root (keccak): <span class="break-all">{verifyResult.root_keccak_hex}</span>
        </p>
        <p class="mt-1 font-mono text-xs break-all text-[var(--muted)]">
          root RLP (proof[0], hex): <span class="break-all">{verifyResult.root_rlp_hex}</span>
        </p>
        <p class="mt-1 font-mono text-xs break-all text-[var(--muted)]">
          value for <code>{verifyResult.prove_key}</code>: <span class="break-all">{verifyResult.value_hex}</span>
        </p>
        <p class="mt-1 font-mono text-xs break-all text-[var(--muted)]">
          proof nodes: {verifyResult.proof_nodes_hex.length}
        </p>
        <p class={`mt-2 font-bold ${verifyResult.verified ? 'text-[var(--good)]' : 'text-[var(--bad)]'}`}>
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
          class="w-fit rounded-lg border border-[var(--border)] bg-[var(--surface)] px-3 py-2 text-sm hover:border-[var(--accent)] hover:bg-[var(--accent-dim)] disabled:cursor-not-allowed disabled:opacity-50"
          onclick={toggleVerifyPlay}
          disabled={verifyResult.verify_steps.length < 2}
        >
          {verifyPlaying ? 'Pause' : 'Play'}
        </button>
      </div>

      {#each verifyResult.verify_steps as s, i}
        <article
          class={`my-2 rounded-lg border border-[var(--border)] p-3 opacity-60 ${
            i === verifyStepIndex ? 'opacity-100 border-[var(--accent)] bg-[var(--accent-dim)]' : ''
          } ${s.ok === true ? 'border-l-4 border-l-[var(--good)]' : ''} ${
            s.ok === false ? 'border-l-4 border-l-[var(--bad)]' : ''
          }`}
        >
          <h4 class="text-sm font-semibold">{s.title}</h4>
          <p class="mt-1 text-sm text-[var(--muted)]">{s.detail}</p>
          {#if s.hash_hex}
            <p class="mt-2 font-mono text-[11px] break-all text-[var(--muted)]">hash: {s.hash_hex}</p>
          {/if}
          {#if s.expected_state_root_hex}
            <p class="mt-2 font-mono text-[11px] break-all text-[var(--muted)]">
              expected state_root: {s.expected_state_root_hex}
            </p>
          {/if}
          {#if s.proof_index !== undefined}
            <p class="mt-2 font-mono text-[11px] break-all text-[var(--muted)]">proof index: {s.proof_index}</p>
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
