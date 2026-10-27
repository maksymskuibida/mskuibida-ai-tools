import type { EngineInterface, Register } from 'claude-code'

// The question-forms dialogs. The engine keeps AskUserQuestion for the model, so the agent opens each with a placeholder
// and a `metadata.source`; this module puts in the real question, draws what a question form is above it, and records
// the answer with scripts/preference.py (the hook refuses recording it from Bash). Two sources:
//   "question-forms:preference"       the per-user, per-project preference: always / ask / never
//   "question-forms:ask:<file>"       one questions file: open the form, or the developer edits the file
// question_guard.py holds the agent to the answer.

const PREFERENCE = 'question-forms:preference'
const ASK = /^question-forms:ask:(.+)$/

const PREF_QUESTION = 'How should AI-DLC questions files be filled in?'
const PREF_OPTIONS = [
  { label: 'Always show question forms', value: 'always', description: 'Every questions file becomes a form' },
  { label: 'Ask every time', value: 'ask', description: 'You choose for each questions file: form or edit the file' },
  { label: 'Never show', value: 'never', description: 'You edit the questions files yourself; the plugin stays out of the way' },
]
const ASK_OPTIONS = [
  { label: 'Open the form', value: 'form', description: 'The questions as a form in your private artifact' },
  { label: 'Edit the file myself', value: 'edit', description: 'No form for this file' },
]
const WHAT_IS_A_FORM =
  '## Question forms\n\n' +
  'A question form is a stage\'s questions file shown as a form in your private artifact: you answer in the page, ' +
  'and the answers are copied word for word back into the file.'

type Dialog = { kind: 'preference' } | { kind: 'ask'; file: string }

// Open dialogs by their question text, for the render hook.
const open = new Map<string, string>()

const askQuestion = (file: string) => `How do you want to answer \`${file}\`?`

async function run($: EngineInterface, argv: string[], cwd: string): Promise<{ code: number | null; err: string }> {
  const proc = $.process.spawn({ argv, cwd })
  let err = ''
  for await (const { stream, text } of proc) if (stream === 'stderr') err += text
  const done = await proc.result

  return { code: done.code, err }
}

function dialogOf(source: string | undefined): Dialog | undefined {
  if (source === PREFERENCE) return { kind: 'preference' }
  const file = ASK.exec(source ?? '')?.[1]

  return file ? { kind: 'ask', file } : undefined
}

export const register: Register = on => {
  on('tool.call', { tool: 'AskUserQuestion' }, async ($, e, next) => {
    const dialog = dialogOf(e.metadata?.source)
    if (!dialog) return next(e)
    const choices = dialog.kind === 'preference' ? PREF_OPTIONS : ASK_OPTIONS
    const question = dialog.kind === 'preference' ? PREF_QUESTION : askQuestion(dialog.file)
    const text =
      dialog.kind === 'preference'
        ? WHAT_IS_A_FORM
        : `${WHAT_IS_A_FORM}\n\nThe form for \`${dialog.file}\`, or edit that file yourself?`
    open.set(question, text)
    const ran = await next({
      ...e,
      questions: [
        {
          question,
          header: dialog.kind === 'preference' ? 'Forms' : 'This file',
          multiSelect: false,
          options: choices.map(({ label, description }) => ({ label, description })),
        },
      ],
    })
    open.delete(question)
    if (ran.deny !== undefined) return ran
    const answers = (ran.result as { answers?: Record<string, string> } | undefined)?.answers ?? {}
    const picked = choices.find(c => c.label === answers[question])
    const again = `Call AskUserQuestion again exactly as before (metadata {"source": "${e.metadata?.source}"}, the same placeholder). Say nothing else.`
    let line: string
    if (!picked) {
      line = `The answer was not one of the options, so nothing is recorded. ${again}`
    } else {
      const cwd = await $.session.cwd()
      const script = `${$.plugin.root}/scripts/preference.py`
      const argv =
        dialog.kind === 'preference'
          ? ['python3', script, 'set', '--value', picked.value]
          : ['python3', script, 'answer', '--file', dialog.file, '--choice', picked.value]
      const recorded = await run($, argv, cwd).catch(why => ({ code: 1, err: String(why) }))
      if (recorded.code !== 0) {
        line = `The answer could not be recorded (${recorded.err.trim() || 'no output'}). Tell the developer in one line.`
      } else if (dialog.kind === 'preference') {
        line =
          picked.value === 'always'
            ? 'Preference recorded: always. Open the form for each questions file written and not yet in a form (skill question-forms § 2), and send its link in a message of its own.'
            : picked.value === 'ask'
              ? 'Preference recorded: ask. For each questions file written and not yet answered, open the per-file ask: AskUserQuestion with metadata {"source": "question-forms:ask:<repo path of the file>"} and a placeholder question.'
              : 'Preference recorded: never. The developer edits the questions files themselves; tell them the file path, nothing more.'
      } else {
        line =
          picked.value === 'form'
            ? `Recorded for ${dialog.file}: the form. Open it (skill question-forms § 2), and send its link in a message of its own.`
            : `Recorded for ${dialog.file}: the developer edits the file themselves. Tell them the file path; no form.`
      }
    }

    return { ...ran, context: [...(ran.context ?? []), `question-forms: ${line}`] }
  })

  on('ui.render', { component: 'AskUserQuestion' }, async ($, e, next) => {
    const engine = await next(e)
    const first = e.props.questions[0] as { question?: string } | undefined
    const text = open.get(first?.question ?? '')
    if (!text) return engine

    const els = $.ui.resolve(e)
    const { Box, Text } = els
    if (e.surface === 'terminal' || !('Markdown' in els)) {
      return (
        <Box flexDirection="column">
          <Text dimColor>{text.replace(/^## .*\n\n/, '')}</Text>
          {engine}
        </Box>
      )
    }
    const { Markdown } = els

    return (
      <Box flexDirection="column">
        <Markdown text={text} />
        {engine}
      </Box>
    )
  })
}
