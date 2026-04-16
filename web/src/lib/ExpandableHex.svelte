<script lang="ts">
  interface $$Props {
    value: string
    first?: number
    last?: number
    className?: string
  }

  const { value, first = 5, last = 3, className = '' } = $props()

  let expanded = $state(false)

  function truncateMiddle(s: string, a: number, b: number): string {
    const has0x = s.startsWith('0x')
    const raw = has0x ? s.slice(2) : s
    const cleaned = raw.replace(/\s+/g, '')
    if (!cleaned) return s
    if (cleaned.length <= a + b + 1) return s
    return `${has0x ? '0x' : ''}${cleaned.slice(0, a)}…${cleaned.slice(-b)}`
  }

  const display = $derived(expanded ? value : truncateMiddle(value, first, last))
</script>

<button
  type="button"
  class={`inline cursor-pointer underline-offset-2 hover:underline ${className}`}
  onclick={() => {
    expanded = !expanded
  }}
  aria-expanded={expanded ? 'true' : 'false'}
  title={expanded ? 'Click to collapse' : 'Click to expand'}
>
  {display}
</button>

