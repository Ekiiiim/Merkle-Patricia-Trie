<script lang="ts">
  import { onDestroy, onMount } from 'svelte'
  import cytoscape, { type Core } from 'cytoscape'
  import dagre from 'dagre'
  import cytoscapeDagre from 'cytoscape-dagre'

  cytoscapeDagre(cytoscape, dagre as any)

  type TrieGraph = { nodes: any[]; edges: any[] }

  const {
    graph,
    highlightPath = [],
    highlightCurrent = null,
    selectedId = null,
    onNodeClick,
  } = $props<{
    graph: TrieGraph
    highlightPath?: string[]
    highlightCurrent?: string | null
    selectedId?: string | null
    /** Called when the user taps a trie node (replaces legacy `on:nodeclick`). */
    onNodeClick?: (nodeData: Record<string, unknown>) => void
  }>()

  let el: HTMLDivElement | null = null
  let cy: Core | null = null
  let selectedNodeId: string | null = null

  function buildElements(g: TrieGraph) {
    const nodes = (g?.nodes ?? []).map((n) => ({
      data: {
        ...n,
        id: String(n.id),
        label:
          n.kind === 'leaf'
            ? 'Leaf'
            : n.kind === 'extension'
              ? 'Ext'
              : n.kind === 'branch'
                ? 'Branch'
                : n.kind === 'branch-terminal'
                  ? '$'
                  : String(n.kind ?? 'node'),
      },
    }))
    const edges = (g?.edges ?? []).map((e) => ({
      data: {
        ...e,
        id: String(e.id),
        source: String(e.source),
        target: String(e.target),
        label: e.label ?? '',
      },
    }))
    return { nodes, edges }
  }

  function relayout() {
    if (!cy) return
    // Breadth-first layout is stable and supports explicit ordering.
    // We order nodes by full trie path so screen position matches path prefix.
    const roots = cy.nodes().filter((n) => n.indegree() === 0)
    cy.layout({
      name: 'breadthfirst',
      directed: true,
      padding: 24,
      spacingFactor: 1.15,
      roots,
      sort: (a: any, b: any) => {
        const pa = String(a.data('path_nibbles_hex') ?? '')
        const pb = String(b.data('path_nibbles_hex') ?? '')
        if (pa !== pb) return pa.localeCompare(pb)
        return String(a.id()).localeCompare(String(b.id()))
      },
    } as any).run()
    cy.fit(undefined, 32)
  }

  function applyHighlights() {
    if (!cy) return
    const path = Array.isArray(highlightPath) ? highlightPath : []
    const propCurrent =
      typeof highlightCurrent === 'string' && highlightCurrent ? highlightCurrent : null
    const cur = path.length ? propCurrent : selectedNodeId ?? propCurrent

    cy.elements().removeClass('hl-path hl-current dim')

    // If there's neither a path nor a current node, nothing to highlight.
    if (!path.length && !cur) return

    if (path.length) {
      // Dim everything, then undim the path.
      cy.elements().addClass('dim')
      for (const id of path) {
        cy.getElementById(id).removeClass('dim').addClass('hl-path')
      }

      // Edges along the path are src->dst for consecutive visited nodes.
      for (let i = 0; i + 1 < path.length; i++) {
        const eid = `${path[i]}->${path[i + 1]}`
        cy.getElementById(eid).removeClass('dim').addClass('hl-path')
      }
    }

    if (cur) {
      const n = cy.getElementById(cur)
      n.removeClass('dim').addClass('hl-current')
    }
  }

  $effect(() => {
    if (!cy) return
    const { nodes, edges } = buildElements(graph)
    cy.elements().remove()
    cy.add([...nodes, ...edges])
    relayout()
    applyHighlights()
  })

  $effect(() => {
    if (!selectedId && !highlightCurrent && !(Array.isArray(highlightPath) && highlightPath.length)) {
      selectedNodeId = null
    }
    applyHighlights()
  })

  $effect(() => {
    applyHighlights()
  })

  onMount(() => {
    if (!el) return
    cy = cytoscape({
      container: el,
      elements: [],
      wheelSensitivity: 0.2,
      style: [
        {
          selector: 'node',
          style: {
            'background-color': '#e2e8f0',
            label: 'data(label)',
            'font-family': 'ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", monospace',
            'font-size': 10,
            'text-valign': 'center',
            'text-halign': 'center',
            color: '#0f172a',
            shape: 'round-rectangle',
            width: 'label',
            height: 'label',
            padding: '8px',
            'border-width': 2,
            'border-color': '#94a3b8',
          },
        },
        {
          selector: 'node[kind = "leaf"]',
          style: { 'background-color': '#dcfce7', 'border-color': '#16a34a' },
        },
        {
          selector: 'node[kind = "extension"]',
          style: { shape: 'ellipse', 'background-color': '#dbeafe', 'border-color': '#2563eb' },
        },
        {
          selector: 'node[kind = "branch"]',
          style: { 'background-color': '#ffedd5', 'border-color': '#ea580c' },
        },
        {
          selector: 'node[kind = "branch-terminal"]',
          style: { shape: 'tag', 'background-color': '#fce7f3', 'border-color': '#db2777' },
        },
        {
          selector: 'edge',
          style: {
            width: 2,
            'line-color': '#94a3b8',
            'target-arrow-color': '#94a3b8',
            'target-arrow-shape': 'triangle',
            'curve-style': 'bezier',
            label: 'data(label)',
            'font-size': 10,
            'text-background-color': '#ffffff',
            'text-background-opacity': 1,
            'text-background-padding': '2px',
            'text-rotation': 'autorotate',
            color: '#475569',
          },
        },
        {
          selector: '.dim',
          style: { opacity: 0.2, 'text-opacity': 0.2 },
        },
        {
          selector: '.hl-path',
          style: {
            opacity: 1,
            'text-opacity': 1,
            'border-width': 4,
            'border-color': '#0ea5e9',
            'line-color': '#0ea5e9',
            'target-arrow-color': '#0ea5e9',
          },
        },
        {
          selector: '.hl-current',
          style:
            {
              'underlay-color': '#f59e0b',
              'underlay-opacity': 0.22,
              'underlay-padding': 10,
              'underlay-shape': 'round-rectangle',
            } as any,
        },
      ],
    })

    cy.on('tap', 'node', (evt) => {
      selectedNodeId = evt.target.id()
      applyHighlights()
      onNodeClick?.(evt.target.data() as Record<string, unknown>)
    })

    // Populate immediately (effects may have run before `cy` existed).
    const { nodes, edges } = buildElements(graph)
    cy.elements().remove()
    cy.add([...nodes, ...edges])
    relayout()
    applyHighlights()
  })

  onDestroy(() => {
    if (cy) cy.destroy()
    cy = null
    el = null
  })
</script>

<div class="h-full w-full min-h-[260px]">
  <div class="h-full w-full" bind:this={el} aria-label="Trie graph (interactive)"></div>
</div>
