// The Units graph: the Units grouped by dependency wave, one small circle each, beside the list.
import { t } from '../strings/en'
import type { UnitGraphNode, UnitGraphState } from '../../types'
import { clip, safely } from './kit'
import type { Bp, Ctx, El } from './kit'
import { RING_ARC, RING_DONE, RING_TRACK } from './ring'
import { rangeOf, wavesOf } from './waves'

const DOT = 16
/** The ring that marks the Unit claimed at this checkout; apart from every state colour. */
export const MINE_RING = '#4f8cff'
const LABEL_CLIP: Record<Bp, number> = { S: 12, M: 18, L: 26 }
const STATES: UnitGraphState[] = ['blocked', 'ready', 'claimed', 'finished']

/** One Unit's circle: outlined muted (blocked), accent outline (ready), accent fill (in progress), success fill (finished). */
export function dotSource(state: UnitGraphState, isMine: boolean): string {
  const mid = DOT / 2
  const r = 4.5
  const look: Record<UnitGraphState, string> = {
    blocked: `fill="none" stroke="${RING_TRACK}" stroke-opacity="0.7" stroke-width="1.5"`,
    ready: `fill="none" stroke="${RING_ARC}" stroke-width="1.6"`,
    claimed: `fill="${RING_ARC}" stroke="${RING_ARC}" stroke-width="1.6"`,
    finished: `fill="${RING_DONE}" stroke="${RING_DONE}" stroke-width="1.6"`,
  }
  const mine = isMine ? `<circle cx="${mid}" cy="${mid}" r="7" fill="none" stroke="${MINE_RING}" stroke-width="1.4"/>` : ''
  return `<svg xmlns="http://www.w3.org/2000/svg" width="${DOT}" height="${DOT}" viewBox="0 0 ${DOT} ${DOT}">${mine}<circle cx="${mid}" cy="${mid}" r="${r}" ${look[state]}/></svg>`
}

const GLYPH: Record<UnitGraphState, { glyph: string; color: string | undefined; isDim: boolean }> = {
  blocked: { glyph: '○', color: undefined, isDim: true },
  ready: { glyph: '○', color: 'claude', isDim: false },
  claimed: { glyph: '●', color: 'claude', isDim: false },
  finished: { glyph: '●', color: 'success', isDim: false },
}

function dot(ctx: Ctx, state: UnitGraphState, isMine: boolean, alt: string): El {
  const { Box, Text, Svg } = ctx.kit
  if (Svg) {
    return (
      <Box flexShrink={0}>
        <Svg source={dotSource(state, isMine)} alt={alt} width={DOT} height={DOT} />
      </Box>
    )
  }
  const look = GLYPH[state]
  return (
    <Box flexShrink={0} gap={0}>
      <Text color={look.color} dimColor={look.isDim}>
        {look.glyph}
      </Text>
      {isMine && <Text color="claude">◆</Text>}
    </Box>
  )
}

function unitCell(ctx: Ctx, node: UnitGraphNode): El {
  const { Box, Text } = ctx.kit
  const state = t(`units.graph.${node.state}`)
  const alt = node.isMine ? t('units.graph.mineAlt', { unit: node.label, state }) : t('units.graph.alt', { unit: node.label, state })
  return (
    <Box key={'unit:' + node.id} gap={1} flexShrink={0}>
      {dot(ctx, node.state, node.isMine, alt)}
      <Text dimColor={node.state === 'blocked'} bold={node.isMine} wrap="truncate-end">
        {clip(node.label, LABEL_CLIP[ctx.bp])}
      </Text>
    </Box>
  )
}

function foldLink(ctx: Ctx, key: string, label: string, press: () => void | Promise<void>): El | false {
  const { Box, Button } = ctx.kit
  if (label === '') return false
  return (
    <Box paddingLeft={2}>
      <Button plain key={key} onPress={safely(press)}>
        {label}
      </Button>
    </Box>
  )
}

/** The small legend: the four states, then the "yours" marker. */
function legend(ctx: Ctx): El {
  const { Box, Text } = ctx.kit
  return (
    <Box paddingLeft={2} gap={2} flexWrap="wrap">
      {STATES.map(state => (
        <Box key={'legend:' + state} gap={1}>
          {dot(ctx, state, false, t(`units.graph.${state}`))}
          <Text dimColor>{t(`units.graph.${state}`)}</Text>
        </Box>
      ))}
      <Box key="legend:mine" gap={1}>
        {dot(ctx, 'ready', true, t('units.graph.mine'))}
        <Text dimColor>{t('units.graph.mine')}</Text>
      </Box>
    </Box>
  )
}

/** The List / Graph switch on the Units heading's row. */
export function viewToggle(ctx: Ctx, key: string, isGraph: boolean): El {
  const { Box, Text, Button } = ctx.kit
  const part = (label: string, isOn: boolean, id: string, press: () => void | Promise<void>) => (
    <Button plain key={id} onPress={safely(press)}>
      <Text bold={isOn} dimColor={!isOn}>
        {label}
      </Text>
    </Button>
  )
  return (
    <Box paddingLeft={2} gap={1}>
      {part(t('units.view.list'), !isGraph, `glist:${key}`, () => ctx.handlers.onToggle(`${key}#graph`, false))}
      <Text dimColor>·</Text>
      {part(t('units.view.graph'), isGraph, `graph:${key}`, () => ctx.handlers.onToggle(`${key}#graph`, true))}
    </Box>
  )
}

/** The waves in the default range, and the folds for those before and after it. */
export function graphView(ctx: Ctx, key: string, nodes: UnitGraphNode[], expanded: Record<string, boolean>): El {
  const { Box, Text } = ctx.kit
  const waves = wavesOf(nodes)
  const range = rangeOf(waves)
  const isEarly = expanded[`${key}#early`] === true
  const isLate = expanded[`${key}#late`] === true
  const from = isEarly ? 0 : range.first
  const to = isLate ? waves.length - 1 : range.last
  const earlier = range.first
  const later = waves.length - 1 - range.last
  return (
    <Box flexDirection="column">
      {earlier > 0 &&
        foldLink(ctx, `${isEarly ? 'unearlier' : 'earlier'}:${key}`, t(isEarly ? 'units.graph.hideEarlier' : 'units.graph.showEarlier', { count: String(earlier) }), () =>
          ctx.handlers.onToggle(`${key}#early`, !isEarly),
        )}
      {waves.slice(from, to + 1).map((row, offset) => (
        <Box key={'wave:' + (from + offset)} paddingLeft={2} gap={1}>
          <Box flexShrink={0} minWidth={7}>
            <Text dimColor>{t('units.graph.wave', { n: String(from + offset + 1) })}</Text>
          </Box>
          <Box flexWrap="wrap" columnGap={2} flexShrink={1}>
            {row.map(node => unitCell(ctx, node))}
          </Box>
        </Box>
      ))}
      {later > 0 &&
        foldLink(ctx, `${isLate ? 'unlater' : 'later'}:${key}`, t(isLate ? 'units.graph.hideLater' : 'units.graph.showLater', { count: String(later) }), () =>
          ctx.handlers.onToggle(`${key}#late`, !isLate),
        )}
      {legend(ctx)}
    </Box>
  )
}
