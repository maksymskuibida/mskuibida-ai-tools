// The pages and forms made for a stage or Unit, drawn under its row: a toggle with the count, then each one as an
// underlined accent link (↗), newest first; the older rounds of a kind fold behind "n older". The fold is the item's own
// (open for a stage in progress or awaiting approval) until the person presses it.
import { t } from '../strings/en'
import type { Item, PanelModel } from '../../types'
import { safely, uniqueIds } from './kit'
import type { Ctx, El } from './kit'

/** The fold key of an item's links in the pane's `expanded` state; `#older` is the key of the folded older rounds. */
export const linksKey = (sectionId: string, itemId: string): string => `${sectionId}|${itemId}#links`
export const olderKey = (sectionId: string, itemId: string): string => `${sectionId}|${itemId}#older`

/** Whether an item's links are drawn open: the person's choice, else the item's default. */
export const isLinksOpen = (item: Item, sectionId: string, expanded: Record<string, boolean>): boolean =>
  expanded[linksKey(sectionId, item.id)] ?? item.isLinksOpen ?? false

/** The item a press on `links:<section>|<item>` or `linksolder:<section>|<item>` means: its fold keys and state now. */
export function linksTarget(
  model: PanelModel,
  expanded: Record<string, boolean>,
  element: string,
): { key: string; isOpen: boolean } | null {
  const kind = element.startsWith('linksolder:') ? 'older' : element.startsWith('links:') ? 'links' : null
  if (kind === null) return null
  const [sectionId, itemId] = element.slice(element.indexOf(':') + 1).split('|')
  const ids = uniqueIds(model.sections.map(one => one.id))
  const section = model.sections[ids.indexOf(sectionId ?? '')]
  const item = section?.items.find(one => one.id === itemId)
  if (!section || !item || (item.links ?? []).length === 0) return null
  if (kind === 'links') return { key: linksKey(sectionId!, item.id), isOpen: !isLinksOpen(item, sectionId!, expanded) }
  return { key: olderKey(sectionId!, item.id), isOpen: expanded[olderKey(sectionId!, item.id)] !== true }
}

export function linksBlock(ctx: Ctx, item: Item, sectionId: string, expanded: Record<string, boolean>): El | false {
  const { Box, Text, Button, Link } = ctx.kit
  const links = (item.links ?? []).filter(link => link.label !== '' && link.href !== '')
  if (links.length === 0) return false
  const isOpen = isLinksOpen(item, sectionId, expanded)
  const title = t('item.links.toggle', { count: String(links.length) })
  const current = links.filter(link => !link.isOlder)
  const older = links.filter(link => link.isOlder)
  const showOlder = isOpen && expanded[olderKey(sectionId, item.id)] === true
  const drawn = showOlder ? links : current
  const mark = t('item.links.open')
  const line = (link: (typeof links)[number], isOld: boolean) => (
    <Box paddingLeft={8} gap={1}>
      <Link href={link.href} label={link.label}>
        <Text color="claude" underline dimColor={isOld} wrap="truncate-end">
          {mark === '' ? link.label : `${mark} ${link.label}`}
        </Text>
      </Link>
    </Box>
  )
  const key = `${sectionId}|${item.id}`
  return (
    <Box flexDirection="column">
      <Box paddingLeft={6}>
        <Button plain key={`links:${key}`} onPress={safely(() => ctx.handlers.onToggle(linksKey(sectionId, item.id), !isOpen))}>
          <Text dimColor>{`${isOpen ? '▾' : '▸'} ${title}`}</Text>
        </Button>
      </Box>
      {isOpen && drawn.map(link => line(link, link.isOlder))}
      {isOpen && older.length > 0 && (
        <Box paddingLeft={8}>
          <Button plain key={`linksolder:${key}`} onPress={safely(() => ctx.handlers.onToggle(olderKey(sectionId, item.id), !showOlder))}>
            <Text dimColor>{showOlder ? t('item.links.olderHide') : t('item.links.older', { count: String(older.length) })}</Text>
          </Button>
        </Box>
      )}
    </Box>
  )
}
