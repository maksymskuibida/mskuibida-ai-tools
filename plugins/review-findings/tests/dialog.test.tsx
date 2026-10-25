import type { On } from 'claude-code'
import { describe, expect, test } from 'claude-code/testing'

const QUESTION = '2 review findings are open (1 blocking). What should I do with them?'
const SAVED = '/state/session-1.findings'

const TRIAGE = {
  question: QUESTION,
  header: 'Findings',
  multiSelect: false,
  options: [
    { label: 'Fix', description: 'Fix every open finding.' },
    { label: 'Open in form', description: 'Sort each finding in a form: fix, accept or reject with a reason.' },
  ],
}

// What `findings.py dialog` prints for the brief-open fixture, before and after a suggestion for R-03.
function dialog(suggested?: string) {
  return {
    findings: SAVED,
    question: { questions: [TRIAGE], metadata: { source: 'review-findings' } },
    markdown: [
      '## Review findings · Domain Design',
      '2 open, 1 blocking. Choose below what happens to them.',
      '',
      '### 1 · The `Cart` rule `checkout | expire` is ambiguous.',
      '- **Blocking** · domain model › Cart aggregate, invariants list',
      '- **Suggested:** State the winning event.',
      '',
      '### 2 · The Events table lists `OrderPlaced` but the flow text calls it `CheckoutDone`.',
      '- **Not blocking** · domain model › Events',
      `- **Suggested:** ${suggested ?? 'No change was named by the reviewer: decide in the form whether to fix, accept or reject it.'}`,
    ].join('\n'),
    lines: [
      'Review findings · Domain Design: 2 open, 1 blocking',
      '1. The Cart rule checkout | expire is ambiguous. (blocking)',
      '   Suggested: State the winning event.',
      '2. The Events table lists OrderPlaced but the flow text calls it CheckoutDone.',
      `   Suggested: ${suggested ?? 'No change was named by the reviewer: decide in the form…'}`,
    ],
    needs_suggestion: suggested ? [] : ['R-03'],
    items: [
      { id: 'R-02', n: 1, title: 'The `Cart` rule is ambiguous.', what: 'The `Cart` rule is ambiguous.', where: 'domain model › Cart aggregate', scenario: '' },
      { id: 'R-03', n: 2, title: 'The Events table lists `OrderPlaced`.', what: 'The Events table lists `OrderPlaced`.', where: 'domain model › Events', scenario: '' },
    ],
  }
}

type World = { opened: { header: string; question: string; options: string[] }[][]; spawned: string[][]; modelSaw: string[] }

// Stands for the engine beneath the plugin: the dialog, the session, findings.py (`saved` false: the guard saved no
// findings) and the suggestion model.
function world(on: On, opts: { saved?: boolean; reply?: string } = {}): World {
  const w: World = { opened: [], spawned: [], modelSaw: [] }
  let suggested: string | undefined
  on('tool.call', { tool: 'AskUserQuestion' }, (_, e) => {
    w.opened.push(e.questions.map(q => ({ header: q.header, question: q.question, options: q.options.map(o => o.label) })))

    return { result: { questions: e.questions, answers: {} } }
  })
  on('session.cwd', () => ({ value: '/project' }))
  on('session.id', () => ({ value: 'session-1' }))
  on('process.spawn', async function* (_, e) {
    w.spawned.push([...e.argv.slice(2)])
    if (e.argv[2] === 'dialog' && opts.saved !== false) {
      yield { stream: 'stdout' as const, text: JSON.stringify(dialog(suggested)) }
      return { value: { code: 0, signal: null } }
    }
    if (e.argv[2] === 'suggest') {
      suggested = (JSON.parse(e.argv[e.argv.indexOf('--set') + 1] ?? '{}') as Record<string, string>)['R-03']
      yield { stream: 'stdout' as const, text: '{"set": ["R-03"]}' }
      return { value: { code: 0, signal: null } }
    }
    yield { stream: 'stderr' as const, text: 'findings.py: no such file' }
    return { value: { code: 1, signal: null } }
  })
  on('model.complete', (_, e) => {
    w.modelSaw.push(String(e.prompt))
    const text = opts.reply ?? '{"R-03": "Use one name for the order event in the table and the flow text."}'

    return { value: { isAnswered: true, text, usage: { input_tokens: 1, output_tokens: 1 } } } as never
  })

  return w
}

// The engine's own dialog, beneath the plugin's drawing.
function engineDialog(on: On) {
  on('ui.render', () => ({ type: 'engine' as const, ref: 0 }))
}

function ask(source?: string, header = 'Findings') {
  return {
    tool: 'AskUserQuestion' as const,
    questions: [
      {
        question: 'What about the findings?',
        header,
        multiSelect: false,
        options: [
          { label: 'Fix', description: 'Fix them.' },
          { label: 'Open in form', description: 'A form.' },
        ],
      },
    ],
    ...(source ? { metadata: { source } } : {}),
  }
}

describe('the findings dialog', () => {
  test('another question passes untouched, and findings.py is not run', async ($, on) => {
    const w = world(on)

    await $.tool.call(ask(undefined, 'Approach'))

    expect(w.opened).toEqual([[{ header: 'Approach', question: 'What about the findings?', options: ['Fix', 'Open in form'] }]])
    expect(w.spawned).toEqual([])
  })

  test('the tagged question becomes the one built from the saved findings', async ($, on) => {
    const w = world(on)

    await $.tool.call(ask('review-findings'))

    expect(w.opened).toEqual([[{ header: 'Findings', question: QUESTION, options: ['Fix', 'Open in form'] }]])
    expect(w.spawned[0]).toEqual(['dialog', '--session', 'session-1'])
  })

  test('an untagged triage question is drawn and rewritten the same way', async ($, on) => {
    const w = world(on)

    await $.tool.call(ask())

    expect(w.opened[0]?.[0]?.question).toBe(QUESTION)
  })

  test('with no saved findings the question is left to the guard', async ($, on) => {
    const w = world(on, { saved: false })

    await $.tool.call(ask('review-findings'))

    expect(w.opened[0]?.[0]?.question).toBe('What about the findings?')
    expect(w.modelSaw).toEqual([])
  })

  test('a finding with no action gets a suggestion from the model, once', async ($, on) => {
    const w = world(on)

    await $.tool.call(ask('review-findings'))
    await $.tool.call(ask('review-findings'))

    expect(w.modelSaw.length).toBe(1)
    expect(w.modelSaw[0]).toContain('"id":"R-03"')
    expect(w.modelSaw[0]).not.toContain('"id":"R-02"')
    const suggest = w.spawned.find(argv => argv[0] === 'suggest')
    expect(suggest).toEqual([
      'suggest', '--findings', SAVED, '--set', JSON.stringify({ 'R-03': 'Use one name for the order event in the table and the flow text.' }),
    ])
  })

  for (const [why, reply] of [['carries an id', '{"R-03": "Do what R-02 says."}'], ['is no JSON', 'I cannot help.']]) {
    test(`a suggestion that ${why} is not recorded`, async ($, on) => {
      const w = world(on, { reply })

      await $.tool.call(ask('review-findings'))

      expect(w.modelSaw.length).toBe(1)
      expect(w.spawned.some(argv => argv[0] === 'suggest')).toBe(false)
    })
  }

  test('the findings are drawn above the dialog: Markdown on desktop, plain lines on the terminal', async ($, on) => {
    world(on)
    engineDialog(on)
    await $.tool.call(ask('review-findings'))

    for (const surface of ['desktop', 'terminal'] as const) {
      const ui = await $.ui.mount({
        plugin: 'review-findings',
        surface,
        component: 'AskUserQuestion',
        props: { tool: 'AskUserQuestion', questions: [TRIAGE], metadataSource: 'review-findings' },
      })
      if (surface === 'desktop') {
        const block = await ui.find({ type: 'Markdown' })
        expect(String(block?.props?.text)).toContain('**Suggested:** Use one name for the order event')
      } else {
        expect(await ui.find({ type: 'Markdown' })).toBeUndefined()
        expect((await ui.find({ type: 'Text', text: /^1\. The Cart rule/ }))?.text).toBe(
          '1. The Cart rule checkout | expire is ambiguous. (blocking)',
        )
      }
      await ui.unmount()
    }
  })

  test('a dialog the plugin did not open is drawn as the engine draws it', async ($, on) => {
    world(on)
    engineDialog(on)
    const ui = await $.ui.mount({
      plugin: 'review-findings',
      surface: 'desktop',
      component: 'AskUserQuestion',
      props: { tool: 'AskUserQuestion', questions: [TRIAGE] },
    })
    expect(await ui.find({ type: 'Markdown' })).toBeUndefined()
    await ui.unmount()
  })
})
