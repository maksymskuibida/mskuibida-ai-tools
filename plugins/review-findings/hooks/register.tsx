import type { EngineInterface, Register } from 'claude-code'

// The triage question of review findings (header Findings: Fix / Accept / Open in form). The agent asks it with
// `metadata.source` "review-findings" (`findings.py question` prints it so); this module puts in the question built
// from the findings the guard saved for this session, has a model write a suggested action for each finding the
// reviewer named none for, and draws every open finding in plain words above the dialog. findings_guard.py still
// checks the question and records the answer; with no saved findings the call passes untouched.

const SOURCE = 'review-findings'
const HEADER = 'Findings'
const FINDING_ID = /\b[RF]-\d+\b/

type Question = { question: string; header: string; options: { label: string; description: string }[]; multiSelect: boolean }
type Item = { id: string; n: number; title: string; what: string; where: string; scenario: string }
type Dialog = {
  findings: string
  question: { questions: Question[] }
  markdown: string
  lines: string[]
  needs_suggestion: string[]
  items: Item[]
}

// What the last triage call asked, by its question text: the render hook draws it above that dialog.
const shown = new Map<string, Dialog>()
// The findings each suggestion was asked for once (file and ids), so asking again does not wait on the model again.
const asked = new Set<string>()

async function run($: EngineInterface, argv: string[], cwd: string): Promise<{ code: number | null; out: string; err: string }> {
  const proc = $.process.spawn({ argv, cwd })
  let out = ''
  let err = ''
  for await (const { stream, text } of proc) {
    if (stream === 'stdout') out += text
    else err += text
  }
  const done = await proc.result

  return { code: done.code, out, err }
}

function jsonOf(text: string): unknown {
  try {
    return JSON.parse(/\{[\s\S]*\}/.exec(text)?.[0] ?? '')
  } catch {
    return undefined
  }
}

function isTriage(q: { header?: string; options?: { label?: string }[] }): boolean {
  const labels = (q.options ?? []).map(o => String(o.label ?? '').trim().toLowerCase())

  return String(q.header ?? '').trim().toLowerCase() === 'findings' && labels.includes('fix') && labels.includes('open in form')
}

/** The dialog findings.py builds from the saved findings; undefined when there are none or they cannot be read. */
async function dialogOf($: EngineInterface, args: string[], cwd: string): Promise<Dialog | undefined> {
  const script = `${$.plugin.root}/scripts/findings.py`
  const got = await run($, ['python3', script, 'dialog', ...args], cwd).catch(() => undefined)
  if (!got || got.code !== 0) return undefined
  const dialog = jsonOf(got.out) as Dialog | undefined

  return dialog?.question?.questions?.length && typeof dialog.markdown === 'string' ? dialog : undefined
}

/** Asks the model for a suggested action per finding that has none; keeps only plain, short, id-free answers. */
async function suggestions($: EngineInterface, model: string, dialog: Dialog): Promise<Record<string, string>> {
  const wanted = dialog.items.filter(i => dialog.needs_suggestion.includes(i.id))
  const reply = await $.model.complete({
    model,
    maxTokens: 800,
    system:
      'You turn review findings into one suggested action each, for a developer who decides whether to fix them. ' +
      'Stay with what the finding says; never add a requirement it does not imply.',
    prompt: [
      'The findings, as JSON (id, title, what is wrong, where, what goes wrong when it is left):',
      JSON.stringify(wanted.map(i => ({ id: i.id, title: i.title, what: i.what, where: i.where, scenario: i.scenario }))),
      '',
      'For each, write one plain sentence, at most 25 words, that starts with a verb and says what to change. No ids,',
      'no file paths, no line numbers. Answer with JSON only: {"<id>": "<suggested action>"}',
    ].join('\n'),
  })
  if (!reply.isAnswered) return {}
  const json = (jsonOf(reply.text) ?? {}) as Record<string, unknown>
  const out: Record<string, string> = {}
  for (const { id } of wanted) {
    const text = typeof json[id] === 'string' ? json[id].replace(/\s+/g, ' ').trim() : ''
    if (text && text.length <= 300 && !FINDING_ID.test(text)) out[id] = text
  }

  return out
}

async function open($: EngineInterface, model: string): Promise<Dialog | undefined> {
  const cwd = await $.session.cwd()
  const dialog = await dialogOf($, ['--session', await $.session.id()], cwd)
  if (!dialog || !dialog.needs_suggestion.length || !model) return dialog
  const once = `${dialog.findings}#${dialog.needs_suggestion.join(',')}`
  if (asked.has(once)) return dialog
  asked.add(once)
  const found = await suggestions($, model, dialog).catch(() => ({}))
  if (!Object.keys(found).length) return dialog
  const script = `${$.plugin.root}/scripts/findings.py`
  const set = await run($, ['python3', script, 'suggest', '--findings', dialog.findings, '--set', JSON.stringify(found)], cwd).catch(
    () => undefined,
  )
  if (!set || set.code !== 0) return dialog

  return (await dialogOf($, ['--findings', dialog.findings], cwd)) ?? dialog
}

export const register: Register = (on, options) => {
  const configured = String(options.suggestModel ?? '').trim()
  const model = configured === 'off' ? '' : configured || 'claude-haiku-5-5'

  on('tool.call', { tool: 'AskUserQuestion' }, async ($, e, next) => {
    if (e.metadata?.source !== SOURCE && !e.questions.some(isTriage)) return next(e)
    const dialog = await open($, model).catch(() => undefined)
    if (!dialog) return next(e)
    const questions = dialog.question.questions
    shown.clear()
    shown.set(questions[0]?.question ?? '', dialog)

    return next({ ...e, questions })
  })

  on('ui.render', { component: 'AskUserQuestion' }, async ($, e, next) => {
    const engine = await next(e)
    const first = e.props.questions[0] as { question?: string; header?: string } | undefined
    const dialog = shown.get(first?.question ?? '')
    if (!dialog || first?.header !== HEADER) return engine

    const els = $.ui.resolve(e)
    const { Box, Text } = els
    if (e.surface === 'terminal' || !('Markdown' in els)) {
      return (
        <Box flexDirection="column">
          {dialog.lines.map((line, i) => (
            <Text bold={i === 0} dimColor={i > 0 && line.startsWith(' ')}>
              {line}
            </Text>
          ))}
          {engine}
        </Box>
      )
    }
    const { Markdown } = els

    return (
      <Box flexDirection="column">
        <Markdown text={dialog.markdown} />
        {engine}
      </Box>
    )
  })
}
