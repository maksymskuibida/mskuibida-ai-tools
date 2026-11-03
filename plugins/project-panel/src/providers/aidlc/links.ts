// The artifact pages and forms made for AI-DLC stages, shown under the stage (or Unit) they belong to. The plugins that
// publish (approval-gates, question-forms) write each publication to one registry file per checkout and intent
// (shared/aidlc-links/aidlc_links.py, see the schema there); this reads it and checks every entry against the intent's
// own state before it is shown: its intent, its stage (in the phase it names) and its Unit must exist, and a Unit's
// design-stage gate under the unit-end rhythm is no page that exists. An entry that fails is dropped, never drawn.
import { join } from '../../fsx'
import type { Fsx } from '../../fsx'
import { t } from '../../strings/en'
import type { Item, ItemLink, Section } from '../../../types'
import { LAST_UNIT_STAGE } from './units'

export type LinkKind = 'gate' | 'unit-plan' | 'unit-end' | 'test-plan' | 'questions-form' | 'findings-form'

export type LinkEntry = {
  url: string
  kind: LinkKind
  intent: string
  phase: string
  stage: string
  unit: string
  rhythm: string
  round: number
  revision: number | undefined
  createdAt: string
}

const KINDS: readonly string[] = ['gate', 'unit-plan', 'unit-end', 'test-plan', 'questions-form', 'findings-form']
/** The pages of a Unit's unit-end gate: only its last stage holds them. */
const UNIT_PAGES: readonly string[] = ['unit-plan', 'unit-end', 'test-plan']

const word = (value: string): string => value.replace(/[^A-Za-z0-9._-]/g, '_')

/** The registry file of a checkout's intent (the key spelling is scripts/aidlc_links.py's: the path, non-word characters `_`). */
export function linksPath(linksDir: string, root: string, space: string, intent: string): string {
  return join(linksDir, 'links', word(root.replace(/\/+$/, '')), word(`${space}--${intent}`) + '.json')
}

const text = (value: unknown): string => (typeof value === 'string' ? value : '')
const whole = (value: unknown): number | undefined => (typeof value === 'number' && Number.isInteger(value) && value > 0 ? value : undefined)

/** The registry's entries; a missing, damaged or foreign file is no entries. An entry that is no entry is left out. */
export function parseLinks(raw: string | null): LinkEntry[] {
  if (raw === null) return []
  try {
    const doc: unknown = JSON.parse(raw)
    const list = doc !== null && typeof doc === 'object' ? (doc as Record<string, unknown>).entries : undefined
    if (!Array.isArray(list)) return []
    const out: LinkEntry[] = []
    for (const row of list) {
      if (row === null || typeof row !== 'object') continue
      const one = row as Record<string, unknown>
      const url = text(one.url)
      const kind = text(one.kind)
      if (!/^https?:\/\/\S+#\S+$/.test(url) || !KINDS.includes(kind) || text(one.stage) === '') continue
      out.push({
        url,
        kind: kind as LinkKind,
        intent: text(one.intent),
        phase: text(one.phase).toLowerCase(),
        stage: text(one.stage),
        unit: text(one.unit),
        rhythm: text(one.rhythm),
        round: whole(one.round) ?? 1,
        revision: whole(one.revision),
        createdAt: text(one.createdAt),
      })
    }
    return out
  } catch {
    return []
  }
}

/** What the intent's own state says exists. */
export type LinkWorld = {
  intent: string
  /** Stage slug → the phase it is listed under (lower case). */
  stages: ReadonlyMap<string, string>
  /** The Units' names; empty when the intent has none (yet). */
  units: ReadonlySet<string>
  /** The Unit this checkout claimed, '' when none. */
  claimed: string
}

/** Whether the entry names an intent, stage and Unit that exist, and a page its Unit's rhythm has. */
export function isShown(entry: LinkEntry, world: LinkWorld): boolean {
  if (entry.intent !== world.intent) return false
  const phase = world.stages.get(entry.stage)
  if (phase === undefined) return false
  if (entry.phase !== '' && phase !== '' && entry.phase !== phase) return false
  if (entry.unit !== '' && !world.units.has(entry.unit)) return false
  if (UNIT_PAGES.includes(entry.kind) && (entry.unit === '' || entry.stage !== LAST_UNIT_STAGE)) return false
  // A Unit under the unit-end rhythm has no page per design stage: its gate pages are the plan and unit-end pages.
  if (entry.kind === 'gate' && entry.rhythm === 'unit-end' && entry.stage !== LAST_UNIT_STAGE) return false
  return true
}

const unitItemId = (name: string): string => `unit:${name}`
const sortKey = (entry: LinkEntry): [string, number] => [entry.createdAt, entry.revision ?? entry.round]
const newestFirst = (a: LinkEntry, b: LinkEntry): number => {
  const [ta, na] = sortKey(a)
  const [tb, nb] = sortKey(b)
  return ta === tb ? nb - na : ta < tb ? 1 : -1
}

function labelOf(entry: LinkEntry): string {
  const rev = entry.revision === undefined ? '' : String(entry.revision)
  switch (entry.kind) {
    case 'gate':
      return t('item.links.gate', { round: String(entry.round) })
    case 'unit-plan':
      return rev === '' ? t('item.links.unitPlanBare') : t('item.links.unitPlan', { revision: rev })
    case 'unit-end':
      return rev === '' ? t('item.links.unitEndBare') : t('item.links.unitEnd', { revision: rev })
    case 'test-plan':
      return rev === '' ? t('item.links.testPlanBare') : t('item.links.testPlan', { revision: rev })
    case 'findings-form':
      return t('item.links.findings')
    default:
      return entry.round > 1 ? t('item.links.questionsRound', { round: String(entry.round) }) : t('item.links.questions')
  }
}

/** Newest first; within one kind (and, on a Unit's row, one stage) every one but the newest is `isOlder`. */
function itemLinks(entries: LinkEntry[], withStage: boolean): ItemLink[] {
  const seen = new Set<string>()
  return [...entries].sort(newestFirst).map(entry => {
    const group = `${entry.kind}|${withStage ? entry.stage : ''}`
    const isOlder = seen.has(group)
    seen.add(group)
    const label = labelOf(entry)
    return { href: entry.url, label: withStage ? t('item.links.stage', { stage: entry.stage, label }) || label : label, isOlder }
  })
}

const isActive = (item: Item): boolean => item.isCurrent || ['open', 'awaiting', 'revising', 'reopened'].includes(item.status)

/**
 * Hangs each shown entry on the row where its stage is: a stage's own row; on a Unit's row (every stage of the Unit,
 * named) when the Unit's stages are not rows of their own; on the claimed Unit's stage row when they are. An entry with
 * no row to hang on is dropped.
 */
export function attachLinks(sections: Section[], entries: readonly LinkEntry[], world: LinkWorld): void {
  const byItem = new Map<Item, { entries: LinkEntry[]; withStage: boolean }>()
  const hang = (item: Item, entry: LinkEntry, withStage: boolean) => {
    const held = byItem.get(item) ?? { entries: [], withStage }
    held.entries.push(entry)
    byItem.set(item, held)
  }
  const seen = new Set<string>()
  for (const entry of entries) {
    if (seen.has(entry.url) || !isShown(entry, world)) continue
    seen.add(entry.url)
    const detail = entry.unit !== '' && entry.unit === world.claimed ? sections.find(section => section.isDetail === true) : undefined
    const stageRow = detail?.items.find(item => item.id === entry.stage)
    if (stageRow) {
      hang(stageRow, entry, false)
      continue
    }
    if (entry.unit !== '') {
      const row = sections.flatMap(section => section.items).find(item => item.id === unitItemId(entry.unit))
      if (row) hang(row, entry, true)
      continue
    }
    const home = sections.filter(section => section.isDetail !== true && section.items.some(item => item.id === entry.stage))
    const own = home.find(section => section.id.toLowerCase() === entry.phase) ?? home[0]
    const row = own?.items.find(item => item.id === entry.stage)
    if (row) hang(row, entry, false)
  }
  for (const [item, held] of byItem) {
    item.links = itemLinks(held.entries, held.withStage)
    item.isLinksOpen = isActive(item)
  }
}

/** Reads the registry of this checkout's intent. */
export async function readLinks(fsx: Fsx, linksDir: string, root: string, space: string, intent: string): Promise<{ path: string; entries: LinkEntry[] }> {
  const path = linksPath(linksDir, root, space, intent)
  return { path, entries: parseLinks(await fsx.read(path)) }
}
