import { SvelteComponentTyped } from 'svelte'

export type ExpandableHexProps = {
  value: string
  first?: number
  last?: number
  className?: string
}

export default class ExpandableHex extends SvelteComponentTyped<ExpandableHexProps> {}

