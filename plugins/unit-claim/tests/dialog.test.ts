import type { On } from 'claude-code'
import { describe, expect, test } from 'claude-code/testing'

const UNIT = 'u4-day-navigation'
const STAGES_Q = `Which design stages run for \`${UNIT}\`?`
const RHYTHM_Q = `Which approval rhythm for \`${UNIT}\`?`

const RECOMMENDATION = JSON.stringify({
  run: [{ stage: 'Functional Design', why: 'The calendar has its own rules.' }],
  skip: [
    { stage: 'NFR Requirements', why: 'No new performance or security need.' },
    { stage: 'NFR Design', why: 'It needs NFR Requirements.' },
    { stage: 'Infrastructure Design', why: 'Nothing changes in how it runs.' },
  ],
})

type World = {
  opened: { question: string; options: string[] }[][]
  recorded: string[][]
  resolverSaw: string[]
}

// Stands for the engine beneath the plugin: the dialog (answering with `answers`), the session's folder, the
// processes the plugin runs (the engine's help, claim_choice.py) and the two models.
function world(on: On, answers: Record<string, string>[], resolver = '{}'): World {
  const w: World = { opened: [], recorded: [], resolverSaw: [] }
  let round = 0
  on('tool.call', { tool: 'AskUserQuestion' }, (_, e) => {
    w.opened.push(e.questions.map(q => ({ question: q.question, options: q.options.map(o => o.label) })))

    return { result: { questions: e.questions, answers: answers[round++] ?? {} } }
  })
  on('session.cwd', () => ({ value: '/project' }))
  on('process.spawn', async function* (_, e) {
    if (e.argv[2] === 'engine') {
      yield { stream: 'stdout' as const, text: JSON.stringify({ rhythms: ['per-stage', 'unit-end'], skipStages: true }) }
      return { value: { code: 0, signal: null } }
    }
    if (e.argv[2] === 'brief') {
      yield { stream: 'stdout' as const, text: '{"unit": "u4-day-navigation", "entry": "### U4", "stories": [], "stages": []}' }
      return { value: { code: 0, signal: null } }
    }
    if (e.argv[2] === 'record') {
      w.recorded.push([...e.argv.slice(3)])
      const stages = e.argv[e.argv.indexOf('--stages') + 1] ?? 'none'
      const rhythm = e.argv[e.argv.indexOf('--rhythm') + 1] ?? ''
      const kept = stages === 'none' ? [] : stages.split(',')
      const all = ['functional-design', 'nfr-requirements', 'nfr-design', 'infrastructure-design']
      const out = all.filter(s => !kept.includes(s))
      const claimFlags = `--rhythm ${rhythm}` + (out.length ? ` --skip-stages ${out.join(',')}` : '')
      yield { stream: 'stdout' as const, text: JSON.stringify({ choice: { stages: kept }, notes: [], claimFlags }) }
      return { value: { code: 0, signal: null } }
    }
    return { value: { code: 1, signal: null } }
  })
  on('model.complete', (_, e) => {
    const prompt = String(e.prompt)
    if (e.model === 'claude-haiku-5-5') w.resolverSaw.push(prompt)
    const text = e.model === 'claude-haiku-5-5' ? resolver : RECOMMENDATION

    return { value: { isAnswered: true, text, usage: { input_tokens: 1, output_tokens: 1 } } } as never
  })

  return w
}

function placeholder(source?: string) {
  return {
    tool: 'AskUserQuestion' as const,
    questions: [
      {
        question: `Claim \`${UNIT}\`?`,
        header: 'Claim',
        multiSelect: false,
        options: [
          { label: 'Yes', description: 'Claim it.' },
          { label: 'No', description: 'Not now.' },
        ],
      },
    ],
    ...(source ? { metadata: { source } } : {}),
  }
}

describe('the claim dialog', () => {
  test('a question that is not the claim dialog passes untouched', async ($, on) => {
    const w = world(on, [{}])

    await $.tool.call(placeholder())

    expect(w.opened).toEqual([[{ question: `Claim \`${UNIT}\`?`, options: ['Yes', 'No'] }]])
    expect(w.recorded).toEqual([])
  })

  test('the placeholder becomes Stages and Rhythm, the rhythms read from the engine', async ($, on) => {
    const w = world(on, [{ [STAGES_Q]: 'Suggested stages', [RHYTHM_Q]: 'unit-end' }])

    const result = await $.tool.call(placeholder(`unit-claim:${UNIT}`))

    expect(w.opened).toEqual([
      [
        { question: STAGES_Q, options: ['Suggested stages', 'All four stages'] },
        { question: RHYTHM_Q, options: ['unit-end', 'per-stage'] },
      ],
    ])
    expect(w.recorded).toEqual([['--unit', UNIT, '--stages', 'functional-design', '--rhythm', 'unit-end']])
    expect(result.context?.join(' ')).toContain('Recorded for u4-day-navigation: Functional Design; rhythm unit-end.')
    expect(w.resolverSaw).toEqual([])
  })

  test('typed stages are read by the resolver', async ($, on) => {
    const w = world(on, [{ [STAGES_Q]: 'funtional desgn, infra', [RHYTHM_Q]: 'per-stage' }], JSON.stringify({
      stages: { ok: ['Functional Design', 'Infrastructure Design'] },
    }))

    const result = await $.tool.call(placeholder(`unit-claim:${UNIT}`))

    expect(w.resolverSaw[0]).toContain('Stages input: "funtional desgn, infra"')
    expect(w.resolverSaw[0]).not.toContain('Rhythm input')
    expect(w.recorded).toEqual([['--unit', UNIT, '--stages', 'functional-design,infrastructure-design', '--rhythm', 'per-stage']])
    expect(result.context?.join(' ')).toContain('Claim with `--rhythm per-stage --skip-stages nfr-requirements,nfr-design`')
  })

  test('a refusal records nothing and asks for the same questions again', async ($, on) => {
    const w = world(
      on,
      [{ [STAGES_Q]: 'sfasd', [RHYTHM_Q]: 'unit-end' }, { [STAGES_Q]: 'All four stages', [RHYTHM_Q]: 'unit-end' }],
      JSON.stringify({ stages: { refused: 'Refused: invalid options: sfasd', suggestion: 'Functional Design' } }),
    )

    const first = await $.tool.call(placeholder(`unit-claim:${UNIT}`))

    expect(w.recorded).toEqual([])
    expect(first.context?.join(' ')).toContain('Refused: invalid options: sfasd')
    expect(first.context?.join(' ')).toContain('Call AskUserQuestion again exactly as before')

    await $.tool.call(placeholder(`unit-claim:${UNIT}`))

    expect(w.opened[1]).toEqual(w.opened[0])
    expect(w.recorded).toEqual([
      ['--unit', UNIT, '--stages', 'functional-design,nfr-requirements,nfr-design,infrastructure-design', '--rhythm', 'unit-end'],
    ])
  })

  test("a rhythm the engine does not accept is refused, whatever the resolver says", async ($, on) => {
    const w = world(on, [{ [STAGES_Q]: 'Suggested stages', [RHYTHM_Q]: 'weekly' }], JSON.stringify({ rhythm: { ok: ['weekly'] } }))

    const result = await $.tool.call(placeholder(`unit-claim:${UNIT}`))

    expect(w.recorded).toEqual([])
    expect(result.context?.join(' ')).toContain('is not a rhythm of the pinned engine (unit-end, per-stage)')
  })

  test('a stage the resolver invents is refused', async ($, on) => {
    const w = world(on, [{ [STAGES_Q]: 'security', [RHYTHM_Q]: 'unit-end' }], JSON.stringify({ stages: { ok: ['Security Design'] } }))

    const result = await $.tool.call(placeholder(`unit-claim:${UNIT}`))

    expect(w.recorded).toEqual([])
    expect(result.context?.join(' ')).toContain('Refused')
  })
})
