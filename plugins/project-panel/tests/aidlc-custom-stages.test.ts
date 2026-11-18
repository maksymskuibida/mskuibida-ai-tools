// Custom stages an engine plugin adds (a `demo-assessment` plugin: a per-Unit stage after code-generation and a stage
// that runs once): the panel reads them from the project's stage graph instead of upstream's hardcoded list.
import { test, expect, describe } from 'claude-code/testing'
import { aidlc } from '../src/providers/aidlc'
import { DEFAULT_UNIT_STAGES, lastStageOf, parseStageGraph, unitStagesOf } from '../src/providers/aidlc/stage-graph'
import { readUnitMatrix, stageApplies } from '../src/providers/aidlc/unit-matrix'
import { isShown } from '../src/providers/aidlc/links'
import type { LinkEntry } from '../src/providers/aidlc/links'
import { parseUnitProgress, progressOf, unitStageStatuses, withReceipts } from '../src/providers/aidlc/units'
import type { UnitEvent, UnitFacts } from '../src/providers/aidlc/units'
import { parseState } from '../src/providers/aidlc/parse-state'
import { fsxOf } from '../fixtures/virtual'
import type { VirtualTree } from '../fixtures/virtual'
import * as s from '../fixtures/scenarios'
import type { PanelModel } from '../types'
import { ctxOf, mockHost, OPTIONS } from './world'

const GRAPH = JSON.stringify([
  { slug: 'requirements-analysis', number: '1.1', name: 'Requirements Analysis', phase: 'inception', for_each: null, plugin: null },
  { slug: 'functional-design', number: '3.1', name: 'Functional Design', phase: 'construction', for_each: 'unit-of-work', plugin: null },
  { slug: 'nfr-requirements', number: '3.2', name: 'NFR Requirements', phase: 'construction', for_each: 'unit-of-work', plugin: null },
  { slug: 'nfr-design', number: '3.3', name: 'NFR Design', phase: 'construction', for_each: 'unit-of-work', plugin: null },
  { slug: 'infrastructure-design', number: '3.4', name: 'Infrastructure Design', phase: 'construction', for_each: 'unit-of-work', plugin: null },
  { slug: 'code-generation', number: '3.5', name: 'Code Generation', phase: 'construction', for_each: 'unit-of-work', plugin: null },
  { slug: 'demo-assessment-unit', number: '3.8', name: 'Demo Assessment (Unit)', phase: 'construction', for_each: 'unit-of-work', plugin: 'demo-assessment', requires_stage: 'code-generation' },
  { slug: 'build-and-test', number: '3.6', name: 'Build and Test', phase: 'construction', for_each: null, plugin: null },
  { slug: 'demo-assessment-intent', number: '3.9', name: 'Demo Assessment (Intent)', phase: 'construction', for_each: null, plugin: 'demo-assessment' },
])

const STAGES = unitStagesOf(parseStageGraph(GRAPH))

describe('the stage graph', () => {
  test('per-Unit stages in graph order, with the names of the stages a plugin added', () => {
    expect(STAGES.perUnit).toEqual(['functional-design', 'nfr-requirements', 'nfr-design', 'infrastructure-design', 'code-generation', 'demo-assessment-unit'])
    expect([...STAGES.names]).toEqual([
      ['demo-assessment-unit', 'Demo Assessment (Unit)'],
      ['demo-assessment-intent', 'Demo Assessment (Intent)'],
    ])
  })

  test('no graph, a damaged one, or one without code-generation falls back to upstream', () => {
    expect(unitStagesOf(null)).toBe(DEFAULT_UNIT_STAGES)
    expect(unitStagesOf(parseStageGraph('{not json'))).toBe(DEFAULT_UNIT_STAGES)
    expect(unitStagesOf(parseStageGraph('[]'))).toBe(DEFAULT_UNIT_STAGES)
    expect(unitStagesOf(parseStageGraph(JSON.stringify({ stages: [{ slug: 'x', for_each: 'unit-of-work' }] })))).toBe(DEFAULT_UNIT_STAGES)
  })

  test('a Unit’s last stage is the last per-Unit stage that applies to it', () => {
    expect(lastStageOf(STAGES)).toBe('demo-assessment-unit')
    expect(lastStageOf(STAGES, ['demo-assessment-unit'])).toBe('code-generation')
    expect(lastStageOf(STAGES, ['code-generation'])).toBe('demo-assessment-unit')
    expect(lastStageOf(DEFAULT_UNIT_STAGES)).toBe('code-generation')
  })
})

const table = [
  '## Unit Progress',
  '',
  '| unit | owner | code-generation | demo-assessment-unit | gate | merged |',
  '| --- | --- | --- | --- | --- | --- |',
  '| a | X | [x] | [ ] | [ ] | [ ] |',
  '| b | X | [x] | [S] | [ ] | [ ] |',
  '',
  '## Current Status',
].join('\n')

const ev = (event: UnitEvent['event'], stage: string, unit: string): UnitEvent => ({ event, stage, unit, at: '' })
const facts = (events: UnitEvent[]): UnitFacts => ({ events, builtByFiles: new Set(), startedByFiles: new Map() })
const units = [
  { name: 'a', kind: '', dependsOn: [], id: 'U1', jira: '' },
  { name: 'b', kind: '', dependsOn: [], id: 'U2', jira: '' },
]
const stateText = (marks: Record<string, string> = {}) =>
  s.stateOf({
    lifecycle: 'CONSTRUCTION',
    current: 'code-generation',
    progress: { Inception: 'Verified', Construction: 'Active' },
    phases: {
      INCEPTION: ['- [x] units-generation — EXECUTE'],
      CONSTRUCTION: ['Per unit: [TBD]', ...['code-generation', 'demo-assessment-unit', 'build-and-test', 'demo-assessment-intent'].map(slug => `- [${marks[slug] ?? ' '}] ${slug} — EXECUTE`)],
    },
  }).replace('- **Revision Count**: 3', '- **Revision Count**: 3\n- **Construction Checkpoints**: enabled')

describe('a Unit with a custom stage after code-generation', () => {
  test('the table’s custom column is read; without the graph it is not', () => {
    expect([...(parseUnitProgress(table, STAGES).get('a') ?? [])]).toEqual([['code-generation', 'x'], ['demo-assessment-unit', ' ']])
    expect([...(parseUnitProgress(table).get('a') ?? [])]).toEqual([['code-generation', 'x']])
  })

  test('built by code-generation alone is not done; done once its last stage settles', () => {
    const built = [ev('UNIT_COMPLETED', 'code-generation', 'a'), ev('UNIT_COMPLETED', 'code-generation', 'b')]
    const rows = (events: UnitEvent[]) => withReceipts(parseUnitProgress(table, STAGES), events, STAGES)
    const before = progressOf(units, parseState(stateText()), facts(built), rows(built), new Set(), STAGES)
    expect(before.get('a')?.phase).not.toBe('done')
    // b skips the custom stage: code-generation is its last, so it is done.
    expect(before.get('b')?.phase).toBe('done')
    const after = [...built, ev('UNIT_COMPLETED', 'demo-assessment-unit', 'a')]
    expect(progressOf(units, parseState(stateText()), facts(after), rows(after), new Set(), STAGES).get('a')?.phase).toBe('done')
  })

  test('a merge, by receipt or by the table’s merged column, still lands the Unit', () => {
    const merged = [ev('UNIT_MERGED', 'code-generation', 'a')]
    const got = progressOf(units, parseState(stateText()), facts(merged), withReceipts(parseUnitProgress(table, STAGES), merged, STAGES), new Set(), STAGES)
    expect(got.get('a')?.phase).toBe('done')
    const byColumn = progressOf(units, parseState(stateText()), facts([]), parseUnitProgress(table, STAGES), new Set(['a']), STAGES)
    expect(byColumn.get('a')?.phase).toBe('done')
  })

  test('without a table, the ledger needs the last stage’s receipt', () => {
    const noTable = new Map()
    const built = [ev('UNIT_COMPLETED', 'code-generation', 'a')]
    expect(progressOf(units, parseState(stateText()), facts(built), noTable, new Set(), STAGES).get('a')).toEqual({ phase: 'between', stage: 'code-generation' })
    const all = [...built, ev('UNIT_COMPLETED', 'demo-assessment-unit', 'a')]
    expect(progressOf(units, parseState(stateText()), facts(all), noTable, new Set(), STAGES).get('a')?.phase).toBe('done')
  })

  test('the stage checkbox of the last per-Unit stage settles every Unit', () => {
    const state = parseState(stateText({ 'code-generation': 'x' }))
    expect(progressOf(units, state, facts([]), new Map(), new Set(), STAGES).get('a')?.phase).toBe('planned')
    const all = parseState(stateText({ 'code-generation': 'x', 'demo-assessment-unit': 'x' }))
    expect(progressOf(units, all, facts([]), new Map(), new Set(), STAGES).get('a')?.phase).toBe('done')
  })

  test('the stage statuses include the custom stage', () => {
    expect([...unitStageStatuses({ phase: 'between', stage: 'code-generation' }, STAGES)].at(-1)).toEqual(['demo-assessment-unit', 'planned'])
  })
})

const ROOT = s.ROOT
describe('stage definitions in plugin folders', () => {
  const upstream = '---\nproduces: [spec]\nproduces_kinds:\n  spec: [service]\n---\n'
  const custom = '---\nproduces: [assessment]\nproduces_kinds:\n  assessment: [ui]\n---\n'
  test('read from aidlc-plugins/<plugin>/stages/<phase>/ beside upstream’s', async () => {
    const files = {
      [`${ROOT}/.claude/aidlc-common/stages/construction/functional-design.md`]: upstream,
      [`${ROOT}/aidlc-plugins/demo-assessment/stages/construction/demo-assessment-unit.md`]: custom,
    }
    const matrix = await readUnitMatrix(fsxOf({ files }), ROOT, STAGES)
    expect([...matrix.keys()]).toEqual(['functional-design', 'demo-assessment-unit'])
    expect(stageApplies(matrix, 'demo-assessment-unit', 'service')).toBe(false)
    expect(stageApplies(matrix, 'demo-assessment-unit', 'ui')).toBe(true)
    // Without the graph the custom stage is no per-Unit stage, so its file is not read.
    expect([...(await readUnitMatrix(fsxOf({ files }), ROOT)).keys()]).toEqual(['functional-design'])
  })
})

describe('the pages of a Unit’s unit-end gate', () => {
  const entry = (stage: string): LinkEntry => ({ url: 'https://x.test/p#a', kind: 'unit-end', intent: 'i', phase: 'construction', stage, unit: 'a', rhythm: 'unit-end', round: 1, revision: undefined, createdAt: '' })
  const world = (unitEndStages?: string[]) => ({ intent: 'i', stages: new Map([['code-generation', 'construction'], ['demo-assessment-unit', 'construction']]), units: new Set(['a']), claimed: '', unitEndStages })
  test('on code-generation as ever, and on the last stage of the graph', () => {
    expect(isShown(entry('code-generation'), world())).toBe(true)
    expect(isShown(entry('demo-assessment-unit'), world())).toBe(false)
    expect(isShown(entry('demo-assessment-unit'), world(['demo-assessment-unit']))).toBe(true)
  })
})

// ── the whole panel ──────────────────────────────────────────────────────────

const INTENT_DIR = `${s.ROOT}/aidlc/spaces/default/intents/${s.INTENT}`
const UNITS_DIR = `${INTENT_DIR}/inception/units-generation`
const DEPENDENCY = '```yaml\nunits:\n  - name: api-core\n    kind: service\n    depends_on: []\n  - name: web-shell\n    kind: ui\n    depends_on: []\n```\n'
const POINTS = 'unit,points,source\napi-core,3,human\nweb-shell,2,human\n'

const audit = (...rows: [string, string, string, string][]) =>
  ['# Audit', '', ...rows.map(([at, event, stage, unit]) => `**Timestamp**: ${at}\n**Event**: ${event}\n**Stage**: ${stage}\n**Unit**: ${unit}\n\n---\n`)].join('\n')

function world(withGraph: boolean, rows: [string, string, string, string][]): VirtualTree {
  return {
    files: {
      [s.paths.statePath]: stateText(),
      [`${s.ROOT}/aidlc/spaces/default/intents/active-intent`]: `${s.INTENT}\n`,
      [`${UNITS_DIR}/unit-of-work-dependency.md`]: DEPENDENCY,
      [`${INTENT_DIR}/unit-points.csv`]: POINTS,
      [`${INTENT_DIR}/audit/host-a.md`]: audit(...rows),
      ...(withGraph ? { [`${s.ROOT}/.claude/tools/data/stage-graph.json`]: GRAPH } : {}),
    },
  }
}

async function load(t: VirtualTree): Promise<PanelModel> {
  const ctx = ctxOf(t, s.ROOT, s.SESSION, OPTIONS, mockHost())
  const detection = await aidlc.detect(ctx)
  if (!detection) throw new Error('expected a detection')
  return aidlc.load(ctx, detection)
}

describe('the panel with a custom per-Unit stage and a custom run-once stage', () => {
  const built: [string, string, string, string][] = [['2026-10-02T10:00:00Z', 'UNIT_COMPLETED', 'code-generation', 'api-core']]

  test('a Unit built by code-generation is not done until the custom stage runs; the run-once stage shows its graph name', async () => {
    const section = (await load(world(true, built))).sections.find(one => one.id === 'CONSTRUCTION')!
    expect(section.items.map(item => [item.id, item.title, item.status])).toEqual([
      ['unit:api-core', 'api-core', 'partial'],
      ['unit:web-shell', 'web-shell', 'planned'],
      ['build-and-test', 'build-and-test', 'planned'],
      ['demo-assessment-intent', 'Demo Assessment (Intent)', 'planned'],
    ])
    expect(section.counts).toEqual({ done: 0, total: 4 })
  })

  test('done once its last stage is settled; a merge also lands it', async () => {
    const done = [...built, ['2026-10-02T11:00:00Z', 'UNIT_COMPLETED', 'demo-assessment-unit', 'api-core'] as [string, string, string, string]]
    const settled = (await load(world(true, done))).sections.find(one => one.id === 'CONSTRUCTION')!
    expect(settled.items.find(item => item.id === 'unit:api-core')?.status).toBe('done')
    const merged: [string, string, string, string][] = [['2026-10-02T10:00:00Z', 'UNIT_MERGED', 'code-generation', 'api-core']]
    expect((await load(world(true, merged))).sections.find(one => one.id === 'CONSTRUCTION')!.items.find(item => item.id === 'unit:api-core')?.status).toBe('done')
  })

  test('with no graph, upstream’s list stands: code-generation alone builds a Unit', async () => {
    const section = (await load(world(false, built))).sections.find(one => one.id === 'CONSTRUCTION')!
    expect(section.items.find(item => item.id === 'unit:api-core')?.status).toBe('done')
    expect(section.items.find(item => item.id === 'demo-assessment-intent')?.title).toBe('demo-assessment-intent')
  })
})
