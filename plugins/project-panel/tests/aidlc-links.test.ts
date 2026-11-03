// The artifact links under each AI-DLC stage: the registry's reader, the check against the intent's state, where each
// entry is hung (per-stage Units, unit-end Units, a Unit's own row), and the default fold.
import { describe, expect, test } from 'claude-code/testing'
import { aidlc } from '../src/providers/aidlc'
import { isShown, linksPath, parseLinks } from '../src/providers/aidlc/links'
import type { LinkWorld } from '../src/providers/aidlc/links'
import * as s from '../fixtures/scenarios'
import type { VirtualTree } from '../fixtures/virtual'
import type { Item, PanelModel } from '../types'
import { ctxOf, mockHost, OPTIONS } from './world'

const INTENT_DIR = `${s.ROOT}/aidlc/spaces/default/intents/${s.INTENT}`
const UNITS_DIR = `${INTENT_DIR}/inception/units-generation`
const DATA = '/home/dev/.claude/plugins/data/aidlc-artifacts'
const ART = 'https://claude.ai/artifact/abc123'
const REGISTRY = linksPath(DATA, s.ROOT, 'default', s.INTENT)

const DEPENDENCY = '```yaml\nunits:\n  - name: api-core\n    kind: service\n    depends_on: []\n  - name: api-billing\n    kind: service\n    depends_on: [api-core]\n```\n'
const INDEX = '| Unit ID | Directory | Repo | Kind | Jira | Stories |\n|---|---|---|---|---|---|\n| U1 | `u1-api-core` | api | service | SHOP-11 | US1.1 |\n| U3 | `u3-api-billing` | api | service | SHOP-13 | US2.1 |\n'
const AUDIT = [
  '# AI-DLC Audit Log',
  '',
  ...[
    ['2026-10-02T10:00:00Z', 'UNIT_STARTED', 'functional-design', 'api-billing'],
    ['2026-10-02T11:00:00Z', 'UNIT_COMPLETED', 'functional-design', 'api-billing'],
    ['2026-10-02T12:00:00Z', 'UNIT_STARTED', 'nfr-requirements', 'api-billing'],
  ].map(([at, event, stage, unit]) => `## Unit\n**Timestamp**: ${at}\n**Event**: ${event}\n**Stage**: ${stage}\n**Unit**: ${unit}\n**Run floor**: x\n\n---\n`),
].join('\n')

const stateText = (): string =>
  s
    .stateOf({
      lifecycle: 'CONSTRUCTION',
      current: 'nfr-requirements',
      progress: { Inception: 'Verified', Construction: 'Active' },
      phases: {
        INCEPTION: ['- [x] requirements-analysis — EXECUTE', '- [x] units-generation — EXECUTE'],
        CONSTRUCTION: [
          'Per unit: [TBD]',
          ...['functional-design', 'nfr-requirements', 'nfr-design', 'infrastructure-design', 'code-generation', 'build-and-test', 'ci-pipeline'].map(slug => `- [ ] ${slug} — EXECUTE`),
        ],
      },
    })
    .replace('- **Revision Count**: 3', '- **Revision Count**: 3\n- **Construction Checkpoints**: enabled\n- **Active Unit**: api-billing\n- **Unit State**: in-progress')

type Entry = Record<string, unknown>
const entry = (kind: string, stage: string, row: string, extra: Entry = {}): Entry => ({
  url: `${ART}#${row}`,
  artifact: ART,
  row,
  kind,
  intent: s.INTENT,
  space: 'default',
  phase: ['requirements-analysis', 'units-generation', 'user-stories'].includes(stage) ? 'inception' : 'construction',
  stage,
  round: 1,
  title: '',
  createdAt: '2026-10-02T10:00:00Z',
  session: 's1',
  ...extra,
})

function world(entries: Entry[] | null, opts: { claimed?: string | null } = {}): VirtualTree {
  const claimed = opts.claimed === undefined ? 'api-billing' : opts.claimed
  const files: Record<string, string> = {
    [s.paths.statePath]: stateText(),
    [`${s.ROOT}/aidlc/spaces/default/intents/active-intent`]: `${s.INTENT}\n`,
    [`${UNITS_DIR}/unit-of-work-dependency.md`]: DEPENDENCY,
    [`${UNITS_DIR}/unit-of-work.md`]: INDEX,
    [`${INTENT_DIR}/audit/host-a.md`]: AUDIT,
    [`${s.ROOT}/aidlc/.aidlc-sessions/${s.SESSION}.binding.json`]: JSON.stringify({ space: 'default', intent: s.INTENT, boundAt: '2026-10-01T00:00:00Z' }),
    [`${s.ROOT}/.git/HEAD`]: 'ref: refs/heads/dev/SHOP-7/nfr-requirements\n',
  }
  if (claimed !== null) files[`${s.ROOT}/aidlc/.aidlc-unit-scope.json`] = JSON.stringify({ version: 1, space: 'default', intent_uuid: '01a1-test', intent_id8: 'test', unit: claimed, owner: 'A', generation: 1 })
  if (entries !== null) files[REGISTRY] = JSON.stringify({ schema: 'aidlc-artifact-links/1', intent: s.INTENT, entries })
  return { files }
}

async function load(t: VirtualTree, withDir = true): Promise<PanelModel> {
  const ctx = { ...ctxOf(t, s.ROOT, s.SESSION, OPTIONS, mockHost()), ...(withDir ? { linksDir: DATA } : {}) }
  const detection = await aidlc.detect(ctx)
  if (!detection) throw new Error('expected a detection')
  return aidlc.load(ctx, detection)
}

const find = (model: PanelModel, sectionId: string, itemId: string): Item => {
  const found = model.sections.find(one => one.id === sectionId)?.items.find(one => one.id === itemId)
  if (!found) throw new Error(`no ${sectionId}/${itemId}`)
  return found
}
const labels = (item: Item) => (item.links ?? []).map(link => [link.label, link.isOlder])

describe('the registry file', () => {
  test('its path is the checkout, spelled with non-word characters as _, and the space--intent', () => {
    expect(linksPath('/d', '/work/app', 'default', '261027-demo')).toBe('/d/links/_work_app/default--261027-demo.json')
    expect(linksPath('/d', '/Users/dev/my project/', 'default', 'x')).toBe('/d/links/_Users_dev_my_project/default--x.json')
  })

  test('a missing, damaged or foreign file is no entries; a malformed entry is skipped', () => {
    expect(parseLinks(null)).toEqual([])
    expect(parseLinks('{nope')).toEqual([])
    expect(parseLinks('{"entries": 3}')).toEqual([])
    const got = parseLinks(
      JSON.stringify({ entries: [entry('gate', 'user-stories', 'a'), { kind: 'gate', stage: 'x' }, entry('essay', 'x', 'b'), entry('gate', 'x', 'c', { url: 'javascript:alert(1)' })] }),
    )
    expect(got.map(one => one.url)).toEqual([`${ART}#a`])
    expect(got[0]).toMatchObject({ kind: 'gate', round: 1, unit: '', phase: 'inception' })
  })
})

describe('the check before a link is shown', () => {
  const w: LinkWorld = {
    intent: s.INTENT,
    stages: new Map([['user-stories', 'inception'], ['functional-design', 'construction'], ['code-generation', 'construction']]),
    units: new Set(['api-billing']),
    claimed: '',
  }
  const one = (extra: Entry) => parseLinks(JSON.stringify({ entries: [entry('gate', 'user-stories', 'r', extra)] }))[0]!

  test('the intent, the stage and the Unit must exist', () => {
    expect(isShown(one({}), w)).toBe(true)
    expect(isShown(one({ intent: 'other' }), w)).toBe(false)
    expect(isShown(one({ stage: 'mystery' }), w)).toBe(false)
    expect(isShown(one({ phase: 'construction' }), w)).toBe(false)
    expect(isShown(one({ stage: 'functional-design', phase: 'construction', unit: 'gone' }), w)).toBe(false)
    expect(isShown(one({ stage: 'functional-design', phase: 'construction', unit: 'api-billing' }), w)).toBe(true)
  })

  test("a unit-end Unit's design stage has no gate page, and the Unit's pages belong to code-generation only", () => {
    const design = { stage: 'functional-design', phase: 'construction', unit: 'api-billing' }
    expect(isShown(one({ ...design, rhythm: 'unit-end' }), w)).toBe(false)
    expect(isShown(one({ ...design, rhythm: 'per-stage' }), w)).toBe(true)
    const end = (extra: Entry) => parseLinks(JSON.stringify({ entries: [entry('unit-end', 'code-generation', 'u', { unit: 'api-billing', rhythm: 'unit-end', ...extra })] }))[0]!
    expect(isShown(end({}), w)).toBe(true)
    expect(isShown(end({ stage: 'functional-design' }), w)).toBe(false)
    expect(isShown(end({ unit: '' }), w)).toBe(false)
  })
})

describe('links under the stages of a phase', () => {
  test('a stage gets its pages newest first, the older rounds of a kind behind the newest', async () => {
    const model = await load(
      world([
        entry('gate', 'requirements-analysis', 'g1', { round: 1, createdAt: '2026-10-01T09:00:00Z' }),
        entry('gate', 'requirements-analysis', 'g2', { round: 2, createdAt: '2026-10-01T11:00:00Z' }),
        entry('questions-form', 'requirements-analysis', 'f1', { createdAt: '2026-10-01T08:00:00Z' }),
      ]),
    )
    const item = find(model, 'INCEPTION', 'requirements-analysis')
    expect(labels(item)).toEqual([['Gate page · round 2', false], ['Gate page · round 1', true], ['Questions form', false]])
    expect(item.links?.map(link => link.href)).toEqual([`${ART}#g2`, `${ART}#g1`, `${ART}#f1`])
  })

  test('the registry file is watched, and nothing is read without the folder', async () => {
    const t = world([entry('gate', 'requirements-analysis', 'g1')])
    expect((await load(t)).watch).toContain(REGISTRY)
    const bare = await load(t, false)
    expect(bare.watch).not.toContain(REGISTRY)
    expect(find(bare, 'INCEPTION', 'requirements-analysis').links).toBeUndefined()
  })

  test('entries of a stage, intent or Unit that does not exist are not drawn', async () => {
    const model = await load(
      world([
        entry('gate', 'mystery', 'a'),
        entry('gate', 'requirements-analysis', 'b', { intent: '260101-other' }),
        entry('questions-form', 'functional-design', 'c', { unit: 'u9-gone' }),
      ]),
    )
    expect(model.sections.flatMap(one => one.items).filter(item => item.links !== undefined)).toEqual([])
  })
})

describe('the default fold', () => {
  test('a stage in progress is open, a finished one and a later one are folded', async () => {
    const model = await load(
      world([
        entry('gate', 'requirements-analysis', 'done'),
        entry('questions-form', 'nfr-requirements', 'now', { unit: 'api-billing' }),
        entry('questions-form', 'nfr-design', 'later', { unit: 'api-billing' }),
      ]),
    )
    expect(find(model, 'INCEPTION', 'requirements-analysis')).toMatchObject({ status: 'done', isLinksOpen: false })
    expect(find(model, 'CONSTRUCTION', 'nfr-requirements')).toMatchObject({ status: 'open', isLinksOpen: true })
    expect(find(model, 'CONSTRUCTION', 'nfr-design')).toMatchObject({ status: 'planned', isLinksOpen: false })
  })

  test('a stage awaiting approval is open', async () => {
    const t = world([entry('gate', 'nfr-requirements', 'g', { unit: 'api-billing', rhythm: 'per-stage' })])
    t.files[s.paths.statePath] = stateText().replace('- [ ] nfr-requirements', '- [?] nfr-requirements')
    expect(find(await load(t), 'CONSTRUCTION', 'nfr-requirements')).toMatchObject({ status: 'awaiting', isLinksOpen: true })
  })
})

describe('Units and rhythm', () => {
  test("a per-stage Unit's gate pages hang under each stage of the claimed Unit, with later rounds on the same stage", async () => {
    const model = await load(
      world([
        entry('gate', 'functional-design', 'fd1', { unit: 'api-billing', rhythm: 'per-stage', round: 1, createdAt: '2026-10-02T10:30:00Z' }),
        entry('gate', 'functional-design', 'fd2', { unit: 'api-billing', rhythm: 'per-stage', round: 2, createdAt: '2026-10-02T10:50:00Z' }),
        entry('gate', 'nfr-requirements', 'nr1', { unit: 'api-billing', rhythm: 'per-stage' }),
      ]),
    )
    expect(labels(find(model, 'CONSTRUCTION', 'functional-design'))).toEqual([['Gate page · round 2', false], ['Gate page · round 1', true]])
    expect(labels(find(model, 'CONSTRUCTION', 'nfr-requirements'))).toEqual([['Gate page · round 1', false]])
  })

  test("a unit-end Unit: the plan page, the unit-end page and the test plans sit under code-generation, its forms under their own stage, and no design-stage gate", async () => {
    const unit = { unit: 'api-billing', rhythm: 'unit-end' }
    const model = await load(
      world([
        entry('questions-form', 'functional-design', 'q1', { unit: 'api-billing' }),
        entry('gate', 'functional-design', 'bad', { ...unit }),
        entry('unit-plan', 'code-generation', 'plan', { ...unit, revision: 1, createdAt: '2026-10-02T13:00:00Z' }),
        entry('unit-end', 'code-generation', 'end6', { ...unit, revision: 6, createdAt: '2026-10-02T15:00:00Z' }),
        entry('unit-end', 'code-generation', 'end5', { ...unit, revision: 5, createdAt: '2026-10-02T14:00:00Z' }),
        entry('test-plan', 'code-generation', 'tp2', { ...unit, revision: 2, createdAt: '2026-10-02T16:00:00Z' }),
      ]),
    )
    expect(labels(find(model, 'CONSTRUCTION', 'functional-design'))).toEqual([['Questions form', false]])
    expect(labels(find(model, 'CONSTRUCTION', 'code-generation'))).toEqual([
      ['Test plan v2', false],
      ['Unit-end page v6', false],
      ['Unit-end page v5', true],
      ['Unit plan page v1', false],
    ])
  })

  test("a Unit nobody here claimed gets its pages on its own row, each with its stage", async () => {
    const model = await load(
      world(
        [
          entry('questions-form', 'functional-design', 'q1', { unit: 'api-core' }),
          entry('unit-end', 'code-generation', 'e1', { unit: 'api-core', rhythm: 'unit-end', revision: 3, createdAt: '2026-10-02T15:00:00Z' }),
        ],
        { claimed: null },
      ),
    )
    expect(labels(find(model, 'CONSTRUCTION', 'unit:api-core'))).toEqual([['code-generation · Unit-end page v3', false], ['functional-design · Questions form', false]])
  })
})
