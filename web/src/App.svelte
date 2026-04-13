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

<div class="page">
  <header class="hero">
    <h1>Merkle Patricia Trie</h1>
    <p class="lede">
      Ethereum-style RLP + Keccak-256. Edit the trie below; scrub through each applied operation, then run a
      proof verification walkthrough.
    </p>
  </header>

  {#if loadError}
    <p class="banner bad">Could not load Graphviz WASM: {loadError}</p>
  {/if}

  {#if apiError}
    <p class="banner bad">{apiError}</p>
  {/if}

  <div class="grid">
    <section class="panel">
      <h2>Operations</h2>
      <p class="hint">Keys and values are UTF-8 strings (same style as <code>demo.py</code>).</p>

      <div class="field">
        <label for="key">Key</label>
        <input id="key" type="text" bind:value={keyInput} disabled={busy} />
      </div>
      <div class="field">
        <label for="val">Value (insert only)</label>
        <input id="val" type="text" bind:value={valueInput} disabled={busy} />
      </div>

      <div class="row-btns">
        <button type="button" class="primary" onclick={insertOp} disabled={busy || !!loadError}>Insert</button>
        <button type="button" onclick={deleteOp} disabled={busy || !!loadError}>Delete</button>
        <button type="button" onclick={loadSample} disabled={busy || !!loadError}>Load sample</button>
        <button type="button" onclick={resetAll} disabled={busy || !!loadError}>Reset</button>
      </div>

      <h3>History</h3>
      {#if operations.length === 0}
        <p class="muted">No operations yet — trie is empty.</p>
      {:else}
        <ol class="ops">
          {#each operations as o, i}
            <li>{opLabel(o, i)}</li>
          {/each}
        </ol>
      {/if}

      <h3>Trie step</h3>
      {#if steps.length}
        <p class="mono small">{steps[stepIndex]?.label}</p>
        <p class="mono small root">state_root: {steps[stepIndex]?.state_root_hex}</p>
        <div class="scrub">
          <input
            type="range"
            min="0"
            max={steps.length - 1}
            bind:value={stepIndex}
            disabled={steps.length < 2}
          />
          <div class="row-btns">
            <button type="button" onclick={toggleTriePlay} disabled={steps.length < 2 || !!loadError}>
              {triePlaying ? 'Pause' : 'Play steps'}
            </button>
          </div>
        </div>
      {:else}
        <p class="muted">Run an operation to see the trie.</p>
      {/if}
    </section>

    <section class="panel grow graph-panel">
      <h2>Structure (Graphviz)</h2>
      {#if trieSvg}
        <div class="graph-wrap">
          {@html trieSvg}
        </div>
      {:else if !loadError}
        <p class="muted">Graph appears after the first successful replay.</p>
      {/if}
    </section>
  </div>

  <section class="panel verify">
    <h2>Root hash &amp; inclusion proof</h2>
    <p class="hint">
      The state root is <code>keccak256(RLP(root_node))</code>. The walkthrough replays your history, builds a
      proof for the key below, and steps through <code>verify_inclusion</code> (embedded vs hashed child refs).
    </p>

    <div class="field inline">
      <label for="pk">Key to prove</label>
      <input id="pk" type="text" bind:value={proveKey} disabled={busy} />
      <button type="button" class="primary" onclick={runVerifyDemo} disabled={busy || !!loadError || operations.length === 0}>
        Run verification walkthrough
      </button>
    </div>

    {#if verifyResult}
      <div class="verify-summary">
        <p class="mono small">state_root (keccak): <span class="break">{verifyResult.root_keccak_hex}</span></p>
        <p class="mono small">root RLP (proof[0], hex): <span class="break">{verifyResult.root_rlp_hex}</span></p>
        <p class="mono small">
          value for <code>{verifyResult.prove_key}</code>: <span class="break">{verifyResult.value_hex}</span>
        </p>
        <p class="mono small">proof nodes: {verifyResult.proof_nodes_hex.length}</p>
        <p class="result {verifyResult.verified ? 'good' : 'bad'}">
          Result: {verifyResult.verified ? 'VERIFIED' : 'FAILED'}
        </p>
      </div>

      <h3>Verification steps</h3>
      <div class="scrub">
        <input
          type="range"
          min="0"
          max={verifyResult.verify_steps.length - 1}
          bind:value={verifyStepIndex}
          disabled={verifyResult.verify_steps.length < 2}
        />
        <button type="button" onclick={toggleVerifyPlay} disabled={verifyResult.verify_steps.length < 2}>
          {verifyPlaying ? 'Pause' : 'Play'}
        </button>
      </div>

      {#each verifyResult.verify_steps as s, i}
        <article class="vstep" class:active={i === verifyStepIndex} class:bad={s.ok === false} class:good={s.ok === true}>
          <h4>{s.title}</h4>
          <p>{s.detail}</p>
          {#if s.hash_hex}
            <p class="mono tiny">hash: {s.hash_hex}</p>
          {/if}
          {#if s.expected_state_root_hex}
            <p class="mono tiny">expected state_root: {s.expected_state_root_hex}</p>
          {/if}
          {#if s.proof_index !== undefined}
            <p class="mono tiny">proof index: {s.proof_index}</p>
          {/if}
        </article>
      {/each}
    {/if}
  </section>
</div>

<style>
  .page {
    max-width: 1200px;
    margin: 0 auto;
    padding: 1.25rem 1.5rem 3rem;
  }

  .hero h1 {
    margin: 0 0 0.35rem;
    font-size: 1.65rem;
  }

  .lede {
    margin: 0;
    color: var(--muted);
    max-width: 52rem;
  }

  .banner {
    padding: 0.65rem 1rem;
    border-radius: 8px;
    border: 1px solid var(--border);
    background: var(--surface);
  }

  .banner.bad {
    border-color: var(--bad);
    color: var(--bad);
  }

  .grid {
    display: flex;
    flex-wrap: wrap;
    gap: 1.25rem;
    margin-top: 1.25rem;
    align-items: flex-start;
  }

  .panel {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 12px;
    padding: 1rem 1.15rem;
    flex: 1 1 280px;
  }

  .panel.grow {
    flex: 2 1 420px;
  }

  .graph-panel {
    min-height: 280px;
  }

  .panel h2 {
    margin: 0 0 0.5rem;
    font-size: 1.05rem;
  }

  .panel h3 {
    margin: 1rem 0 0.35rem;
    font-size: 0.95rem;
  }

  .hint {
    margin: 0 0 0.85rem;
    color: var(--muted);
    font-size: 0.92rem;
  }

  .field {
    margin-bottom: 0.65rem;
  }

  .field label {
    display: block;
    font-size: 0.85rem;
    color: var(--muted);
    margin-bottom: 0.2rem;
  }

  .field.inline {
    display: flex;
    flex-wrap: wrap;
    gap: 0.5rem;
    align-items: flex-end;
  }

  .field.inline label {
    flex: 0 0 100%;
  }

  .row-btns {
    display: flex;
    flex-wrap: wrap;
    gap: 0.45rem;
    margin: 0.65rem 0;
  }

  .ops {
    margin: 0;
    padding-left: 1.2rem;
    font-size: 0.9rem;
 color: var(--muted);
  }

  .muted {
    color: var(--muted);
    font-size: 0.92rem;
  }

  .mono {
    font-family: var(--mono);
  }

  .small {
    font-size: 0.82rem;
    word-break: break-all;
  }

  .tiny {
    font-size: 0.75rem;
    word-break: break-all;
    margin: 0.25rem 0 0;
  }

  .root {
    color: var(--accent);
  }

  .scrub {
    display: flex;
    flex-direction: column;
    gap: 0.45rem;
    margin-top: 0.35rem;
  }

  .graph-wrap {
    overflow: auto;
    max-height: 70vh;
    border-radius: 8px;
    background: #fff;
    padding: 0.5rem;
  }

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

  .verify {
    margin-top: 1.25rem;
  }

  .verify-summary {
    margin: 0.75rem 0;
    padding: 0.65rem 0.85rem;
    border-radius: 8px;
    border: 1px solid var(--border);
    background: var(--bg);
  }

  .break {
    word-break: break-all;
  }

  .result {
    font-weight: 700;
    margin: 0.5rem 0 0;
  }

  .result.good {
    color: var(--good);
  }

  .result.bad {
    color: var(--bad);
  }

  .vstep {
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 0.55rem 0.75rem;
    margin: 0.45rem 0;
    opacity: 0.55;
  }

  .vstep.active {
    opacity: 1;
    border-color: var(--accent);
    background: var(--accent-dim);
  }

  .vstep.good {
    border-left: 3px solid var(--good);
  }

  .vstep.bad {
    border-left: 3px solid var(--bad);
  }

  .vstep h4 {
    margin: 0 0 0.25rem;
    font-size: 0.88rem;
  }

  .vstep p {
    margin: 0;
    font-size: 0.88rem;
    color: var(--muted);
  }
</style>
