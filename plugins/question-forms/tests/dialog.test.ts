import type { On } from 'claude-code'
import { describe, expect, test } from 'claude-code/testing'

const PREF_Q = 'How should AI-DLC questions files be filled in?'
const FILE = 'aidlc/spaces/default/intents/261027-x/construction/u12/functional-design/functional-design-questions.md'
const ASK_Q = `How do you want to answer \`${FILE}\`?`

type World = { opened: { question: string; options: string[] }[][]; recorded: string[][] }

// Stands for the engine beneath the plugin: the dialog (answering with `answers`), the session's folder and the
// processes the plugin runs (preference.py).
function world(on: On, answers: Record<string, string>[]): World {
  const w: World = { opened: [], recorded: [] }
  let round = 0
  on('tool.call', { tool: 'AskUserQuestion' }, (_, e) => {
    w.opened.push(e.questions.map(q => ({ question: q.question, options: q.options.map(o => o.label) })))

    return { result: { questions: e.questions, answers: answers[round++] ?? {} } }
  })
  on('session.cwd', () => ({ value: '/project' }))
  on('process.spawn', async function* (_, e) {
    w.recorded.push([...e.argv.slice(2)])
    yield { stream: 'stdout' as const, text: '{}' }
    return { value: { code: 0, signal: null } }
  })

  return w
}

function placeholder(source?: string) {
  return {
    tool: 'AskUserQuestion' as const,
    questions: [
      {
        question: 'Show question forms?',
        header: 'Forms',
        multiSelect: false,
        options: [
          { label: 'Always', description: 'Yes.' },
          { label: 'Ask', description: 'Sometimes.' },
        ],
      },
    ],
    ...(source ? { metadata: { source } } : {}),
  }
}

describe('the preference dialog', () => {
  test('a question that is not a question-forms dialog passes untouched', async ($, on) => {
    const w = world(on, [{}])

    await $.tool.call(placeholder())

    expect(w.opened).toEqual([[{ question: 'Show question forms?', options: ['Always', 'Ask'] }]])
    expect(w.recorded).toEqual([])
  })

  test('the placeholder becomes the three options and the choice is recorded', async ($, on) => {
    const w = world(on, [{ [PREF_Q]: 'Ask every time' }])

    const result = await $.tool.call(placeholder('question-forms:preference'))

    expect(w.opened).toEqual([[{ question: PREF_Q, options: ['Always show question forms', 'Ask every time', 'Never show'] }]])
    expect(w.recorded[0]).toEqual(['set', '--value', 'ask'])
    expect(result.context?.join(' ')).toContain('Preference recorded: ask.')
  })

  test('an answer that is not an option records nothing and asks again', async ($, on) => {
    const w = world(on, [{ [PREF_Q]: 'whatever' }])

    const result = await $.tool.call(placeholder('question-forms:preference'))

    expect(w.recorded).toEqual([])
    expect(result.context?.join(' ')).toContain('Call AskUserQuestion again exactly as before')
  })
})

describe('the per-file ask', () => {
  test('edit records the answer for that one file', async ($, on) => {
    const w = world(on, [{ [ASK_Q]: 'Edit the file myself' }])

    const result = await $.tool.call(placeholder(`question-forms:ask:${FILE}`))

    expect(w.opened[0]?.[0]).toEqual({ question: ASK_Q, options: ['Open the form', 'Edit the file myself'] })
    expect(w.recorded[0]).toEqual(['answer', '--file', FILE, '--choice', 'edit'])
    expect(result.context?.join(' ')).toContain('the developer edits the file themselves')
  })

  test('the form is recorded as such', async ($, on) => {
    const w = world(on, [{ [ASK_Q]: 'Open the form' }])

    await $.tool.call(placeholder(`question-forms:ask:${FILE}`))

    expect(w.recorded[0]).toEqual(['answer', '--file', FILE, '--choice', 'form'])
  })
})
