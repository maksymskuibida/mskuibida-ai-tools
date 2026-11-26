// The Units graph's arithmetic: which wave each Unit builds in, and which waves are shown by default.
import type { UnitGraphNode } from '../../types'

/** How many waves past the last touched one are shown before "Show later". */
export const WAVES_AFTER_TOUCHED = 3

/**
 * Each Unit's wave: 1 + the longest chain of Units it waits on. A dependency that names no Unit of the list is
 * ignored (as `buildOrder` does). Units in a cycle share one wave, as do those only they wait on.
 * Returns the waves in order, each holding its Units in the list's order.
 */
export function wavesOf(nodes: readonly UnitGraphNode[]): UnitGraphNode[][] {
  const byName = new Map(nodes.map(node => [node.name, node]))
  const wave = new Map<string, number>()
  const visiting = new Set<string>()
  let cycleWave = 0
  const waveOf = (name: string): number => {
    const known = wave.get(name)
    if (known !== undefined) return known
    // Back on a Unit we are still resolving: a cycle; its members settle together below.
    if (visiting.has(name)) return 0
    visiting.add(name)
    const deps = (byName.get(name)?.dependsOn ?? []).filter(dep => byName.has(dep))
    const at = deps.length === 0 ? 1 : Math.max(...deps.map(waveOf)) + 1
    visiting.delete(name)
    wave.set(name, at)
    return at
  }
  for (const node of nodes) waveOf(node.name)
  // Units that sit in a cycle (reach themselves through their dependencies) all take the latest wave of the cycle.
  const reaches = (from: string, target: string, seen = new Set<string>()): boolean => {
    for (const dep of byName.get(from)?.dependsOn ?? []) {
      if (!byName.has(dep) || seen.has(dep)) continue
      if (dep === target) return true
      seen.add(dep)
      if (reaches(dep, target, seen)) return true
    }
    return false
  }
  const inCycle = nodes.filter(node => reaches(node.name, node.name))
  if (inCycle.length > 0) {
    cycleWave = Math.max(...inCycle.map(node => wave.get(node.name) ?? 1))
    for (const node of inCycle) wave.set(node.name, cycleWave)
    // Whatever waits on the cycle comes after it.
    let moved = true
    for (let guard = 0; moved && guard <= nodes.length; guard++) {
      moved = false
      for (const node of nodes) {
        if (inCycle.includes(node)) continue
        const deps = node.dependsOn.filter(dep => byName.has(dep))
        const need = deps.length === 0 ? 1 : Math.max(...deps.map(dep => wave.get(dep) ?? 1)) + 1
        if ((wave.get(node.name) ?? 1) < need) {
          wave.set(node.name, need)
          moved = true
        }
      }
    }
  }
  const last = Math.max(0, ...wave.values())
  const out: UnitGraphNode[][] = Array.from({ length: last }, () => [])
  for (const node of nodes) out[(wave.get(node.name) ?? 1) - 1]!.push(node)
  return out.filter(row => row.length > 0)
}

export type WaveRange = {
  /** Indexes into the waves: `first..last` inclusive are shown by default. */
  first: number
  last: number
}

/**
 * The waves shown by default. First: the earliest wave with a Unit not finished (the last wave when all are). Last: the
 * latest wave holding a touched Unit (claimed or finished), plus WAVES_AFTER_TOUCHED, capped at the last wave; with
 * nothing touched, counted from the first shown wave.
 */
export function rangeOf(waves: readonly (readonly UnitGraphNode[])[]): WaveRange {
  if (waves.length === 0) return { first: 0, last: -1 }
  const unfinished = waves.findIndex(row => row.some(node => node.state !== 'finished'))
  const first = unfinished < 0 ? waves.length - 1 : unfinished
  let touched = -1
  waves.forEach((row, at) => {
    if (row.some(node => node.state === 'claimed' || node.state === 'finished')) touched = at
  })
  const last = Math.min(waves.length - 1, (touched < 0 ? first : Math.max(touched, first)) + WAVES_AFTER_TOUCHED)
  return { first, last }
}
