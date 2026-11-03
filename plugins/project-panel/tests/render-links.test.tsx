// The links under a stage row: open by default for the stage in progress, folded for a finished one, each an
// underlined accent link; a press opens or folds them, and the older rounds of a kind sit behind "n older".
import { describe, expect, test } from 'claude-code/testing'
import type { On } from 'claude-code'
import type { Engine } from 'claude-code/testing'

import { pressAction } from '../src/render/press'
import { MOUNT, seedModel, stageModel } from './world'
import type { PanelModel } from '../types'

type Surface = 'terminal' | 'desktop'
type Found = { type?: string; text: string; props: Record<string, unknown> }
type Probe = { findAll: (query: { type?: string }) => Promise<Found[]> }

const bare = (text: string) => text.replace(/ /g, ' ').trim()
const shown = async (ui: unknown) => (await (ui as Probe).findAll({})).filter(el => el.type === 'Text').map(el => bare(el.text))
const hrefs = async (ui: unknown) => (await (ui as Probe).findAll({ type: 'Link' })).map(el => String(el.props.href))

const ART = 'https://claude.ai/artifact/abc123'

function modelWithLinks(): PanelModel {
  const base = stageModel()
  const inception = base.sections.find(one => one.id === 'INCEPTION')!
  const links = (rows: string[][]) => rows.map(([label, row, old]) => ({ label: label!, href: `${ART}#${row}`, isOlder: old === 'old' }))
  inception.items = inception.items.map(item =>
    item.id === 'domain-design'
      ? { ...item, isLinksOpen: true, links: links([['Gate page · round 2', 'g2'], ['Gate page · round 1', 'g1', 'old'], ['Questions form', 'f1']]) }
      : item.id === 'user-stories'
        ? { ...item, isLinksOpen: false, links: links([['Gate page · round 1', 'us1']]) }
        : item,
  )
  return base
}

async function draw($: Engine, on: On, model: PanelModel, surface: Surface) {
  seedModel(on, model)
  return $.ui.mount({ ...MOUNT, surface, props: { ...MOUNT.props, bodyColumns: 60 } })
}

describe('stage links, drawn', () => {
  for (const surface of ['terminal', 'desktop'] as const) {
    test(`the stage in progress shows its newest links, the finished one only a toggle, on ${surface}`, async ($, on) => {
      const ui = await draw($, on, modelWithLinks(), surface)
      const texts = await shown(ui)
      expect(texts).toContain('▾ Links (3)')
      expect(texts).toContain('↗ Gate page · round 2')
      expect(texts).toContain('↗ Questions form')
      expect(texts).not.toContain('↗ Gate page · round 1')
      expect(texts).toContain('1 older')
      expect(texts).toContain('▸ Links (1)')
      expect(await hrefs(ui)).toEqual([`${ART}#g2`, `${ART}#f1`])
      await ui.unmount()
    })
  }

  test('a link is underlined and in the accent colour', async ($, on) => {
    const ui = await draw($, on, modelWithLinks(), 'desktop')
    const link = (await (ui as Probe).findAll({ type: 'Text' })).find(el => bare(el.text) === '↗ Questions form')
    expect(link?.props.underline).toBe(true)
    expect(link?.props.color).toBe('claude')
    await ui.unmount()
  })

  test('pressing the toggle opens a folded stage and folds an open one; the press is the same one the engine hands back', async ($, on) => {
    const ui = await draw($, on, modelWithLinks(), 'desktop')
    await ui.press({ key: 'links:INCEPTION|user-stories' })
    expect(await shown(ui)).toContain('▾ Links (1)')
    expect(await hrefs(ui)).toContain(`${ART}#us1`)
    await ui.press({ key: 'links:INCEPTION|domain-design' })
    expect(await shown(ui)).not.toContain('↗ Questions form')
    expect(await shown(ui)).toContain('▸ Links (3)')
    await ui.unmount()
  })

  test('the older rounds show behind their count and hide again', async ($, on) => {
    const ui = await draw($, on, modelWithLinks(), 'terminal')
    await ui.press({ key: 'linksolder:INCEPTION|domain-design' })
    expect(await shown(ui)).toContain('↗ Gate page · round 1')
    expect(await shown(ui)).toContain('Hide older')
    await ui.press({ key: 'linksolder:INCEPTION|domain-design' })
    expect(await shown(ui)).not.toContain('↗ Gate page · round 1')
    await ui.unmount()
  })
})

describe('pressAction for the links', () => {
  const model = modelWithLinks()
  test('a toggle means the opposite of what is drawn now, by default and by the person\'s own choice', () => {
    expect(pressAction(model, {}, 'links:INCEPTION|user-stories')).toEqual({ kind: 'toggle', key: 'INCEPTION|user-stories#links', isOpen: true })
    expect(pressAction(model, {}, 'links:INCEPTION|domain-design')).toEqual({ kind: 'toggle', key: 'INCEPTION|domain-design#links', isOpen: false })
    expect(pressAction(model, { 'INCEPTION|domain-design#links': false }, 'links:INCEPTION|domain-design')).toMatchObject({ isOpen: true })
    expect(pressAction(model, {}, 'linksolder:INCEPTION|domain-design')).toEqual({ kind: 'toggle', key: 'INCEPTION|domain-design#older', isOpen: true })
  })

  test('an item with no links, or a section that is not drawn, is no press', () => {
    expect(pressAction(model, {}, 'links:INCEPTION|requirements-analysis')).toBeNull()
    expect(pressAction(model, {}, 'links:NOWHERE|domain-design')).toBeNull()
  })
})
