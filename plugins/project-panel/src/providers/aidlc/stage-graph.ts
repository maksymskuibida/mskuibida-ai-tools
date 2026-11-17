// The project's stage graph (`.claude/tools/data/stage-graph.json`): the engine merges upstream's stages and the ones
// engine plugins add (`aidlc-plugins/<plugin>/stages/<phase>/<slug>.md`) into it. The panel reads it for which stages
// run once per Unit (`for_each: unit-of-work`), in what order, and for the names of the stages a plugin added. With no
// graph (or one that holds no per-Unit stage) it falls back to upstream's own list.
import { join } from '../../fsx'
import type { Fsx } from '../../fsx'

/** Where a runtime installs the engine's files under a workspace, by agent; the first one present counts. */
export const INSTALL_DIRS = ['.claude', '.aidlc', '.kiro', '.codex', '.cursor', '.github']

/** upstream's per-unit Construction stages, in walk order (stage-graph.json `for_each: unit-of-work`). */
export const UPSTREAM_PER_UNIT_STAGES: readonly string[] = [
  'functional-design',
  'nfr-requirements',
  'nfr-design',
  'infrastructure-design',
  'code-generation',
]

/** The per-unit stage whose receipts keep their meaning whatever runs after it: it builds the Unit, and a merge lands it. */
export const BUILD_STAGE = 'code-generation'

/** One stage of the graph. */
export type GraphStage = { slug: string; name: string; phase: string; forEach: string; plugin: string }

/** What the panel derives from the graph. */
export type UnitStages = {
  /** The per-Unit stages, in graph order. */
  perUnit: readonly string[]
  /** Display names of the stages a plugin added, by slug (upstream's stages show their slug). */
  names: ReadonlyMap<string, string>
  /** Every graph stage, for reading stage definitions. */
  graph: readonly GraphStage[]
}

export const DEFAULT_UNIT_STAGES: UnitStages = { perUnit: UPSTREAM_PER_UNIT_STAGES, names: new Map(), graph: [] }

const text = (value: unknown): string => (typeof value === 'string' ? value : '')

/** The graph's stages from its JSON (a list, or an object holding one under `stages`); null when it is none. */
export function parseStageGraph(raw: string | null): GraphStage[] | null {
  if (raw === null) return null
  try {
    const doc: unknown = JSON.parse(raw)
    const list = Array.isArray(doc) ? doc : doc !== null && typeof doc === 'object' ? (doc as Record<string, unknown>).stages : undefined
    if (!Array.isArray(list)) return null
    const out: GraphStage[] = []
    for (const row of list) {
      if (row === null || typeof row !== 'object') continue
      const one = row as Record<string, unknown>
      const slug = text(one.slug)
      if (!/^[A-Za-z0-9][A-Za-z0-9._-]*$/.test(slug)) continue
      out.push({ slug, name: text(one.name), phase: text(one.phase).toLowerCase(), forEach: text(one.for_each), plugin: text(one.plugin) })
    }
    return out
  } catch {
    return null
  }
}

/** The per-Unit stages and names of a graph; upstream's list when the graph names no per-Unit stage or lacks the build stage. */
export function unitStagesOf(graph: readonly GraphStage[] | null): UnitStages {
  if (graph === null) return DEFAULT_UNIT_STAGES
  const perUnit = graph.filter(stage => stage.forEach === 'unit-of-work').map(stage => stage.slug)
  if (!perUnit.includes(BUILD_STAGE)) return DEFAULT_UNIT_STAGES
  const names = new Map(graph.filter(stage => stage.plugin !== '' && stage.name !== '').map(stage => [stage.slug, stage.name] as const))
  return { perUnit, names, graph }
}

/** The project's stage graph, as the panel uses it. */
export async function readUnitStages(fsx: Fsx, root: string): Promise<UnitStages> {
  for (const dir of INSTALL_DIRS) {
    const path = join(root, dir, 'tools', 'data', 'stage-graph.json')
    if (await fsx.exists(path)) return unitStagesOf(parseStageGraph(await fsx.read(path)))
  }
  return DEFAULT_UNIT_STAGES
}

/** The last stage that applies to a Unit: the last per-Unit stage that is not in `skipped` (the build stage never is). */
export function lastStageOf(stages: UnitStages, skipped: readonly string[] = []): string {
  return stages.perUnit.filter(stage => stage === BUILD_STAGE || !skipped.includes(stage)).at(-1) ?? BUILD_STAGE
}
