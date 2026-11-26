// Construction counted by story points, and a Unit claimed at this checkout: the section fields the renderer draws
// (countLabel, sideCount, titleTag) and the Units section that is no phase (isSupplement).
import { describe, expect, test } from 'claude-code/testing'
import type { On } from 'claude-code'
import type { Engine } from 'claude-code/testing'

import { iconSource } from '../src/render/look'
import { phasesOf } from '../src/render/stepper'
import { MOUNT, item, section, seedModel, stageModel } from './world'
import type { PanelModel, Section } from '../types'

type Surface = 'terminal' | 'desktop'
type Found = { type?: string; text: string; props: Record<string, unknown> }
type Probe = { findAll: (query: { type?: string }) => Promise<Found[]> }

const bare = (text: string) => text.replace(/ /g, ' ').trim()
const shown = async (ui: unknown) => (await (ui as Probe).findAll({})).filter(el => el.type === 'Text').map(el => bare(el.text))

async function draw($: Engine, on: On, model: PanelModel, surface: Surface, columns = 60) {
  seedModel(on, model)
  return $.ui.mount({ ...MOUNT, surface, props: { ...MOUNT.props, bodyColumns: columns } })
}

function claimedModel(): PanelModel {
  const base = stageModel()
  const construction: Section = {
    ...section('CONSTRUCTION', 'Construction', 'active', [
      item('functional-design', 'done', { ordinal: '3.1' }),
      item('nfr-requirements', 'open', { ordinal: '3.2', isCurrent: true }),
      item('nfr-design', 'planned', { ordinal: '3.3' }),
    ]),
    ordinal: '3',
    titleTag: 'U3 u3-day-page',
    caption: 'U3 u3-day-page, 13 pt: claimed at this checkout',
    isDetail: true,
    isCollapsed: false,
  }
  const units: Section = {
    ...section('UNITS', 'Units', 'active', [item('unit:u1', 'done', { title: 'U1 u1-api-core' }), item('unit:u3', 'open', { title: 'U3 u3-day-page' })]),
    countLabel: '13/45 pt',
    sideCount: '1/6 units',
    isSupplement: true,
    isCollapsed: true,
  }
  const sections = base.sections.filter(one => one.id !== 'CONSTRUCTION' && one.id !== 'INCEPTION')
  return { ...base, sections: [...sections.slice(0, 2), construction, units, ...sections.slice(2)] }
}

describe('Construction by story points and a claimed Unit, drawn', () => {
  for (const surface of ['terminal', 'desktop'] as const) {
    test(`the points count stands in for done/total, with the Units done beside it, on ${surface}`, async ($, on) => {
      const ui = await draw($, on, claimedModel(), surface)
      const texts = await shown(ui)
      expect(texts).toContain('13/45 pt')
      expect(texts).toContain('1/6 units')
      expect(texts.indexOf('1/6 units')).toBeLessThan(texts.indexOf('13/45 pt'))
      // The claimed Unit's tag sits beside Construction's title; its stages count as rows.
      expect(texts).toContain('U3 u3-day-page')
      expect(texts).toContain('1/3')
      await ui.unmount()
    })
  }

  test('on the desktop the tag is an accent pill and the Units count a grey one', async ($, on) => {
    const ui = await draw($, on, claimedModel(), 'desktop')
    const all = (await (ui as Probe).findAll({ type: 'Text' })) as Found[]
    const tag = all.find(el => bare(el.text) === 'U3 u3-day-page')
    const side = all.find(el => bare(el.text) === '1/6 units')
    expect(tag?.props.color).toBe('claude')
    expect(typeof tag?.props.backgroundColor).toBe('string')
    expect(typeof side?.props.backgroundColor).toBe('string')
    await ui.unmount()
  })

  test('a built section keeps its ✓ after a points count', async ($, on) => {
    const model = claimedModel()
    const units = model.sections.find(one => one.id === 'UNITS')!
    units.status = 'built'
    units.countLabel = '45/45 pt'
    const ui = await draw($, on, model, 'terminal')
    expect(await shown(ui)).toContain('45/45 pt ✓')
    await ui.unmount()
  })

  test('Units is no phase: the stepper and the phase cards leave it out, the list keeps it', async ($, on) => {
    const model = claimedModel()
    expect(phasesOf(model).map(one => one.id)).not.toContain('UNITS')
    const ui = await draw($, on, model, 'desktop', 110)
    const keys = (await (ui as unknown as { findAll: (q: { type: string }) => Promise<Found[]> }).findAll({ type: 'Button' })).map(b => b.props.key)
    expect(keys).toContain('section:UNITS')
    // The cards are the phases; Units' row stays a list heading under them, with its counts.
    expect(await shown(ui)).toContain('13/45 pt')
    await ui.unmount()
  })
})

describe('stage points, drawn', () => {
  const model = (): PanelModel => {
    const base = stageModel()
    const inception = base.sections.find(one => one.id === 'INCEPTION')!
    inception.items = inception.items.map(one => ({ ...one, points: one.id === 'domain-design' ? '3 pt' : '1 pt' }))
    inception.countLabel = '4/10 pt'
    inception.isCollapsed = false
    return base
  }
  for (const surface of ['terminal', 'desktop'] as const) {
    test(`each stage row shows its points after its chips, and the phase its points count, on ${surface}`, async ($, on) => {
      const ui = await draw($, on, model(), surface)
      const texts = await shown(ui)
      expect(texts).toContain('3 pt')
      expect(texts.filter(text => text === '1 pt').length).toBeGreaterThan(3)
      expect(texts).toContain('4/10 pt')
      const all = (await (ui as Probe).findAll({ type: 'Text' })) as Found[]
      const pill = all.find(el => bare(el.text) === '3 pt')
      if (surface === 'desktop') expect(typeof pill?.props.backgroundColor).toBe('string')
      else expect(pill?.props.dimColor).toBe(true)
      await ui.unmount()
    })
  }
})

describe('the Units graph, drawn', () => {
  const node = (name: string, state: 'blocked' | 'ready' | 'claimed' | 'finished', dependsOn: string[] = [], isMine = false) => ({
    id: `unit:${name}`,
    name,
    label: name,
    dependsOn,
    state,
    isMine,
  })
  const rows = () => [
    item('unit:api-shell', 'planned', { title: 'api-shell', readiness: 'ready' }),
    item('unit:billing', 'open', { title: 'billing' }),
    item('unit:reports', 'planned', { title: 'reports', readiness: 'blocked' }),
    item('unit:setup', 'done', { title: 'setup' }),
  ]
  const graphModel = (): PanelModel => {
    const model = claimedModel()
    const units = model.sections.find(one => one.id === 'UNITS')!
    units.isCollapsed = false
    units.items = rows()
    units.unitGraph = {
      key: 'UNITS@default/shop',
      nodes: [node('api-shell', 'ready'), node('billing', 'claimed', ['api-shell'], true), node('reports', 'blocked', ['billing', 'api-shell']), node('setup', 'finished')],
    }
    return model
  }
  const buttons = async (ui: unknown) => ((await (ui as Probe).findAll({ type: 'Button' })) as Found[]).map(b => String(b.props.key))
  // Hooks register once per test; `view.isGraph` is what the person's saved choice reads at each mount.
  const view = { isGraph: false }
  const hooks = (on: On) => {
    on('clock.now', async () => ({ value: new Date(2026, 8, 4, 12, 3, 0).getTime() }))
    on('state.get', async (_$, e, next) => {
      const held = await next(e)
      if (e.plugin !== 'project-panel') return held
      if (e.key === 'expanded') return { value: { value: { 'UNITS@default/shop#graph': view.isGraph }, version: 0 } }
      if (e.key === 'model') return { value: { value: graphModel(), version: 0 } }
      return held
    })
  }
  const mountGraph = ($: Engine, surface: Surface, isGraph: boolean) => {
    view.isGraph = isGraph
    return $.ui.mount({ ...MOUNT, surface, props: { ...MOUNT.props, bodyColumns: 60 } })
  }
  const drawGraph = async ($: Engine, on: On, surface: Surface, isGraph: boolean) => {
    hooks(on)
    return mountGraph($, surface, isGraph)
  }

  for (const surface of ['terminal', 'desktop'] as const) {
    test(`the list stays by default, with a List / Graph switch, on ${surface}`, async ($, on) => {
      const ui = await draw($, on, graphModel(), surface)
      expect(await buttons(ui)).toEqual(expect.arrayContaining(['graph:UNITS@default/shop', 'glist:UNITS@default/shop']))
      expect(await shown(ui)).not.toContain('Wave 1')
      await ui.unmount()
    })

    test(`the switch marks the view on: List is primary in the list, Graph in the graph, on ${surface}`, async ($, on) => {
      hooks(on)
      for (const isGraph of [false, true]) {
        const ui = await mountGraph($, surface, isGraph)
        const found = (await (ui as Probe).findAll({ type: 'Button' })) as Found[]
        const variant = (key: string) => found.find(b => String(b.props.key) === key)?.props.variant
        expect(variant('glist:UNITS@default/shop')).toBe(isGraph ? 'secondary' : 'primary')
        expect(variant('graph:UNITS@default/shop')).toBe(isGraph ? 'primary' : 'secondary')
        await ui.unmount()
      }
    })

    test(`the graph shows the waves, the legend, yours and what each Unit needs, on ${surface}`, async ($, on) => {
      const ui = await drawGraph($, on, surface, true)
      const texts = await shown(ui)
      expect(texts).toEqual(expect.arrayContaining(['Wave 1', 'Wave 2', 'Wave 3', 'api-shell', 'billing', 'reports', 'blocked', 'ready', 'in progress', 'finished', 'yours']))
      expect(texts).toContain('needs api-shell')
      expect(texts).toContain('needs billing, api-shell')
      if (surface === 'terminal') expect(texts).toContain('◆')
      await ui.unmount()
    })
  }

  test('terminal: the graph draws the list rows\' own glyphs for every state, the blocked one included', async ($, on) => {
    hooks(on)
    const list = await mountGraph($, 'terminal', false)
    const listText = (await shown(list)).join('|')
    await list.unmount()
    const ui = await mountGraph($, 'terminal', true)
    const texts = await shown(ui)
    for (const glyph of ['⊘', '○', '◐', '✓']) {
      expect(listText).toContain(glyph)
      expect(texts).toContain(glyph)
    }
    await ui.unmount()
  })

  test('desktop: the graph draws the same icons as the list rows for every state', async ($, on) => {
    hooks(on)
    const sources = async (isGraph: boolean) => {
      const ui = await mountGraph($, 'desktop', isGraph)
      const all = (await (ui as Probe).findAll({ type: 'Svg' })) as Found[]
      await ui.unmount()
      return new Set(all.map(el => String(el.props.source)))
    }
    const inList = await sources(false)
    const inGraph = await sources(true)
    for (const kind of ['blocked', 'ready', 'live', 'done'] as const) {
      const source = iconSource(kind, kind === 'live' ? '◐' : '')
      expect(inList.has(source)).toBe(true)
      expect(inGraph.has(source)).toBe(true)
    }
  })

  test('a section without Units has no switch', async ($, on) => {
    const ui = await draw($, on, claimedModel(), 'desktop')
    expect((await buttons(ui)).some(key => key.startsWith('graph:'))).toBe(false)
    await ui.unmount()
  })
})
