// The Units graph: the Units grouped by dependency wave, each with the list row's own marker, beside the list.
import { t } from '../strings/en'
import type { Item, UnitGraphNode, UnitGraphState } from '../../types'
import { clip, safely } from './kit'
import type { Bp, Ctx, El } from './kit'
import { statusMarker } from './item'
import { needsOf, rangeOf, wavesOf } from './waves'

/** The ring that marks the Unit claimed at this checkout; apart from every state colour. */
export const MINE_RING = '#4f8cff'
const LABEL_CLIP: Record<Bp, number> = { S: 12, M: 18, L: 26 }
const STATES: UnitGraphState[] = ['blocked', 'ready', 'claimed', 'finished']
const MARK = 14

/** The "yours" ring as an image: drawn over the Unit's own marker, same size. */
export function mineSource(): string {
  return `<svg xmlns="http://www.w3.org/2000/svg" width="${MARK}" height="${MARK}" viewBox="0 0 ${MARK} ${MARK}"><circle cx="${MARK / 2}" cy="${MARK / 2}" r="${MARK / 2 - 0.5}" fill="none" stroke="${MINE_RING}" stroke-width="1.4"/></svg>`
}

/** What a node stands for when its row is not in the section's items: a plain planned row. */
function stand(node: UnitGraphNode): Item {
  const isDone = node.state === 'finished'
  return { id: node.id, title: node.label, status: isDone ? 'done' : node.state === 'claimed' ? 'open' : 'planned', readiness: node.state === 'blocked' ? 'blocked' : 'ready' } as Item
}

/** The Unit's marker: the list row's own (statusMarker), with the "yours" ring laid over it. */
function marker(ctx: Ctx, item: Item, isMine: boolean, alt: string): El {
  const { Box, Text, Svg } = ctx.kit
  const base = statusMarker(ctx, item)
  if (!isMine) return base
  if (Svg) {
    return (
      <Box flexShrink={0}>
        {base}
        <Box position="absolute" left={0} top={0}>
          <Svg source={mineSource()} alt={alt} width={MARK} height={MARK} />
        </Box>
      </Box>
    )
  }
  return (
    <Box flexShrink={0} gap={0}>
      {base}
      <Text color="claude">◆</Text>
    </Box>
  )
}

function unitCell(ctx: Ctx, node: UnitGraphNode, nodes: readonly UnitGraphNode[], items: Map<string, Item>): El {
  const { Box, Text } = ctx.kit
  const state = t(`units.graph.${node.state}`)
  const alt = node.isMine ? t('units.graph.mineAlt', { unit: node.label, state }) : t('units.graph.alt', { unit: node.label, state })
  const needs = needsOf(node, nodes)
  return (
    <Box key={'unit:' + node.id} flexDirection="column" flexShrink={0}>
      <Box gap={1}>
        {marker(ctx, items.get(node.id) ?? stand(node), node.isMine, alt)}
        <Text dimColor={node.state === 'blocked'} bold={node.isMine} wrap="truncate-end">
          {clip(node.label, LABEL_CLIP[ctx.bp])}
        </Text>
      </Box>
      {needs.length > 0 && (
        <Box paddingLeft={2}>
          <Text dimColor wrap="truncate-end">
            {clip(t('units.graph.needs', { units: needs.join(', ') }), LABEL_CLIP[ctx.bp] + 8)}
          </Text>
        </Box>
      )}
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

/** The small legend: the states present, each drawn with the marker of a row in that state, then the "yours" marker. */
function legend(ctx: Ctx, nodes: readonly UnitGraphNode[], items: Map<string, Item>): El {
  const { Box, Text } = ctx.kit
  const mine = nodes.find(node => node.isMine)
  return (
    <Box paddingLeft={2} gap={2} flexWrap="wrap">
      {STATES.map(state => {
        const first = nodes.find(node => node.state === state)
        if (first === undefined) return false
        return (
          <Box key={'legend:' + state} gap={1}>
            {marker(ctx, items.get(first.id) ?? stand(first), false, t(`units.graph.${state}`))}
            <Text dimColor>{t(`units.graph.${state}`)}</Text>
          </Box>
        )
      })}
      {mine !== undefined && (
        <Box key="legend:mine" gap={1}>
          {marker(ctx, items.get(mine.id) ?? stand(mine), true, t('units.graph.mine'))}
          <Text dimColor>{t('units.graph.mine')}</Text>
        </Box>
      )}
    </Box>
  )
}

/** The List / Graph switch: a segmented pair; the view on is the primary button (accent) and bold, the other dim. */
export function viewToggle(ctx: Ctx, key: string, isGraph: boolean): El {
  const { Box, Button } = ctx.kit
  const part = (label: string, isOn: boolean, id: string, press: () => void | Promise<void>) => (
    <Button key={id} variant={isOn ? 'primary' : 'secondary'} dimColor={!isOn} onPress={safely(press)}>
      {isOn ? `● ${label}` : label}
    </Button>
  )
  return (
    <Box paddingLeft={2} gap={0}>
      {part(t('units.view.list'), !isGraph, `glist:${key}`, () => ctx.handlers.onToggle(`${key}#graph`, false))}
      {part(t('units.view.graph'), isGraph, `graph:${key}`, () => ctx.handlers.onToggle(`${key}#graph`, true))}
    </Box>
  )
}

/** The waves in the default range, and the folds for those before and after it. */
export function graphView(ctx: Ctx, key: string, nodes: UnitGraphNode[], expanded: Record<string, boolean>, rows: readonly Item[] = []): El {
  const items = new Map(rows.map(row => [row.id, row]))
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
            {row.map(node => unitCell(ctx, node, nodes, items))}
          </Box>
        </Box>
      ))}
      {later > 0 &&
        foldLink(ctx, `${isLate ? 'unlater' : 'later'}:${key}`, t(isLate ? 'units.graph.hideLater' : 'units.graph.showLater', { count: String(later) }), () =>
          ctx.handlers.onToggle(`${key}#late`, !isLate),
        )}
      {legend(ctx, nodes, items)}
    </Box>
  )
}
