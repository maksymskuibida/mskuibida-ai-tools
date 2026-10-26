import type { EngineInterface, Register } from 'claude-code'

// The claim dialog of a team Unit. The engine keeps AskUserQuestion for the model (a mod asks one question at a time,
// with $.ui.ask), so the agent opens it with a placeholder and `metadata.source` "unit-claim:<unit>"; this module puts
// in its two questions (Stages, Rhythm), draws its stage recommendation above them, resolves what the developer typed
// under Other, and records the answer with claim_choice.py. A refusal is drawn above the same questions, asked again.
// claim_guard.py refuses the claim until an answer is recorded.

const SOURCE = /^unit-claim:([A-Za-z0-9][A-Za-z0-9._-]*)$/
const STAGES_LINE = /^Which design stages run for `([^`]+)`\?$/

const STAGES = [
  { slug: 'functional-design', name: 'Functional Design' },
  { slug: 'nfr-requirements', name: 'NFR Requirements' },
  { slug: 'nfr-design', name: 'NFR Design' },
  { slug: 'infrastructure-design', name: 'Infrastructure Design' },
] as const
const NAMES: readonly string[] = STAGES.map(s => s.name)
const SUGGESTED = 'Suggested stages'
const ALL = 'All four stages'
// What each rhythm the plugin knows means; one the engine adds later is offered with its name alone.
const RHYTHM_NOTES: Record<string, string> = {
  'unit-end': 'Design stages run without a stop; you look at the plan page, then the unit-end page',
  'per-stage': 'An approval after every stage',
}

type Advice = { stage: string; why: string }
type Recommendation = { run: Advice[]; skip: Advice[] } | { error: string }
type Resolved = { ok: string[] } | { refused: string; suggestion?: string }
type Refusal = { refused: string; suggestion?: string }
type Claim = { recommendation: Recommendation; rhythms: string[]; refusals: Refusal[] }

// Per Unit, while its dialog is open or asked again: the recommendation and the engine's rhythms are read once.
const claims = new Map<string, Claim>()

const stagesQuestion = (unit: string) => `Which design stages run for \`${unit}\`?`
const rhythmQuestion = (unit: string) => `Which approval rhythm for \`${unit}\`?`

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

/** The rhythms the pinned engine accepts, read from its claim usage line by `claim_choice.py engine` (not by running
 *  `aidlc`, which fails while the project's pin is not registered); the plugin's two when it names none. */
async function rhythmsOf($: EngineInterface, cwd: string): Promise<string[]> {
  const script = `${$.plugin.root}/scripts/claim_choice.py`
  const eng = await run($, ['python3', script, 'engine'], cwd).catch(() => ({ code: 1, out: '', err: '' }))
  const found = ((jsonOf(eng.out) as { rhythms?: string[] } | undefined)?.rhythms ?? []).filter(Boolean)

  // unit-end first: the rhythm the plugin exists for.
  return (found.length >= 2 ? found : Object.keys(RHYTHM_NOTES)).sort((a, b) => Number(b === 'unit-end') - Number(a === 'unit-end'))
}

async function recommend($: EngineInterface, model: string, unit: string, cwd: string): Promise<Recommendation> {
  const script = `${$.plugin.root}/scripts/claim_choice.py`
  const brief = await run($, ['python3', script, 'brief', '--unit', unit], cwd).catch(why => ({ code: 1, out: '', err: String(why) }))
  if (brief.code !== 0) return { error: `the Unit's brief could not be read (${brief.err.trim() || 'no output'})` }
  const reply = await $.model.complete({
    model,
    maxTokens: 1200,
    system:
      'You decide which AI-DLC design stages a Unit of work needs. Judge each stage only against its own condition and ' +
      'what the Unit delivers. A stage that needs another (NFR Design needs NFR Requirements) is skipped when that one is.',
    prompt: [
      'The Unit, its stories and the four design stages with their conditions, as JSON:',
      brief.out,
      '',
      'Put every one of the four stages in exactly one list: run or skip. Give each a reason of one plain sentence, at',
      'most 20 words, saying what in this Unit makes the condition true or false. Answer with JSON only:',
      '{"run": [{"stage": "Functional Design", "why": "..."}], "skip": [{"stage": "NFR Requirements", "why": "..."}]}',
    ].join('\n'),
  })
  if (!reply.isAnswered) return { error: `the recommendation could not be made (${reply.reason})` }
  const json = jsonOf(reply.text) as { run?: Advice[]; skip?: Advice[] } | undefined
  const listed = [...(json?.run ?? []), ...(json?.skip ?? [])].map(a => a.stage)
  if (!json || listed.length !== 4 || NAMES.some(name => !listed.includes(name))) {
    return { error: 'the recommendation did not name each design stage once' }
  }

  return { run: json.run ?? [], skip: json.skip ?? [] }
}

function resolverPrompt(stages: string | undefined, rhythm: string | undefined, rhythms: string[]): string {
  return [
    'Resolve what a developer typed into known options. They may misspell, abbreviate or use other words.',
    `Valid stages: ${NAMES.join(', ')}.`,
    `Valid rhythms: ${rhythms.join(', ')}.`,
    '',
    'Stages: split the input into the parts it names. Map a part to a stage only when it clearly means that stage.',
    'Refuse the whole input when a part maps to no stage ("Refused: invalid options: <those parts>") or when a stage is',
    'named more than once ("Refused: duplicated: <stage>:<count>" for each). "none" or "no stages" is an empty list.',
    'Rhythm: map the input to one rhythm only when it clearly means it; otherwise refuse and say why.',
    'With every refusal give a suggestion: what they probably meant, in valid option names.',
    '',
    'Answer with JSON only, keys only for the inputs given:',
    '{"stages": {"ok": ["Functional Design"]} or {"refused": "Refused: ...", "suggestion": "..."},',
    ' "rhythm": {"ok": ["unit-end"]} or {"refused": "Refused: ...", "suggestion": "..."}}',
    '',
    ...(stages !== undefined ? [`Stages input: ${JSON.stringify(stages)}`] : []),
    ...(rhythm !== undefined ? [`Rhythm input: ${JSON.stringify(rhythm)}`] : []),
  ].join('\n')
}

async function resolve(
  $: EngineInterface,
  model: string,
  stages: string | undefined,
  rhythm: string | undefined,
  rhythms: string[],
): Promise<{ stages?: Resolved; rhythm?: Resolved }> {
  const failed: Resolved = { refused: 'Refused: the typed answer could not be resolved; please answer again.' }
  const reply = await $.model.complete({ model, prompt: resolverPrompt(stages, rhythm, rhythms), maxTokens: 400 })
  const json = reply.isAnswered ? (jsonOf(reply.text) as { stages?: Resolved; rhythm?: Resolved } | undefined) : undefined
  const out: { stages?: Resolved; rhythm?: Resolved } = {}
  if (stages !== undefined) {
    const s = json?.stages ?? failed
    // The resolver is held to the four stages.
    out.stages = 'ok' in s && s.ok.some(name => !NAMES.includes(name)) ? failed : s
  }
  if (rhythm !== undefined) {
    const r = json?.rhythm ?? failed
    // And to the engine's own rhythms.
    out.rhythm =
      'ok' in r && !rhythms.includes(r.ok[0] ?? '')
        ? { refused: `Refused: "${rhythm}" is not a rhythm of the pinned engine (${rhythms.join(', ')}).` }
        : r
  }

  return out
}

function questions(unit: string, claim: Claim) {
  const rec = claim.recommendation
  const suggested = 'run' in rec ? rec.run.map(a => a.stage) : []

  return [
    {
      question: stagesQuestion(unit),
      header: 'Stages',
      multiSelect: false,
      options: [
        { label: SUGGESTED, description: 'run' in rec ? suggested.join(', ') || 'No design stage' : `No suggestion: ${rec.error}` },
        { label: ALL, description: NAMES.join(', ') },
      ],
    },
    {
      question: rhythmQuestion(unit),
      header: 'Rhythm',
      multiSelect: false,
      options: claim.rhythms.slice(0, 4).map(r => ({ label: r, description: RHYTHM_NOTES[r] ?? `The engine's ${r} rhythm` })),
    },
  ]
}

function reasoning(rec: Recommendation): string {
  if ('error' in rec) return `# Suggested design stages\n\nNo suggestion: ${rec.error}. Pick the stages yourself.`
  const block = (list: Advice[]) => (list.length ? list.map(a => `### ${a.stage}\n${a.why}`).join('\n') : 'None.')

  return ['# Suggested design stages', '## Recommended stages', block(rec.run), '## Skip these', block(rec.skip)].join('\n')
}

async function settle(
  $: EngineInterface,
  model: string,
  unit: string,
  claim: Claim,
  answers: Record<string, string>,
  cwd: string,
): Promise<string> {
  const rec = claim.recommendation
  const pick = answers[stagesQuestion(unit)] ?? ''
  const pace = answers[rhythmQuestion(unit)] ?? ''
  const typedStages = pick === SUGGESTED || pick === ALL ? undefined : pick
  const typedRhythm = claim.rhythms.includes(pace) ? undefined : pace
  const got =
    typedStages === undefined && typedRhythm === undefined ? {} : await resolve($, model, typedStages, typedRhythm, claim.rhythms)

  claim.refusals = [got.stages, got.rhythm].filter((r): r is Refusal => !!r && 'refused' in r)
  if (pick === SUGGESTED && 'error' in rec) {
    claim.refusals.unshift({ refused: 'Refused: there is no suggestion to take.', suggestion: `Pick "${ALL}" or type the stages.` })
  }
  if (claim.refusals.length) {
    return (
      `${claim.refusals.map(r => r.refused).join(' ')} Call AskUserQuestion again exactly as before (metadata ` +
      `{"source": "unit-claim:${unit}"}, the same placeholder); the mod shows the refusal above the same questions. ` +
      'Say nothing else.'
    )
  }

  const names =
    pick === SUGGESTED ? ('run' in rec ? rec.run.map(a => a.stage) : [])
    : pick === ALL ? [...NAMES]
    : got.stages && 'ok' in got.stages ? got.stages.ok
    : []
  const rhythm = got.rhythm && 'ok' in got.rhythm ? (got.rhythm.ok[0] ?? pace) : pace
  const slugs = STAGES.filter(s => names.includes(s.name)).map(s => s.slug)
  const script = `${$.plugin.root}/scripts/claim_choice.py`
  const recorded = await run(
    $,
    ['python3', script, 'record', '--unit', unit, '--stages', slugs.join(',') || 'none', '--rhythm', rhythm],
    cwd,
  ).catch(why => ({ code: 1, out: '', err: String(why) }))
  if (recorded.code !== 0) {
    return `The answer could not be recorded (${recorded.err.trim() || 'no output'}). Tell the developer in one line; do not claim.`
  }
  claims.delete(unit)
  const { choice, notes, claimFlags } = (jsonOf(recorded.out) ?? {}) as {
    choice?: { stages: string[] }
    notes?: string[]
    claimFlags?: string
  }
  const chosen = STAGES.filter(s => choice?.stages.includes(s.slug)).map(s => s.name)

  return (
    `Recorded for ${unit}: ${chosen.join(', ') || 'no design stage'}; rhythm ${rhythm}. ` +
    (notes?.length ? `Tell the developer in one line: ${notes.join(' ')} ` : '') +
    `Claim with \`${claimFlags || `--rhythm ${rhythm}`}\` added to the engine's claim command.`
  )
}

export const register: Register = (on, options) => {
  const recommendModel = String(options.recommendModel ?? '') || 'claude-sonnet-5-5'
  const resolveModel = String(options.resolveModel ?? '') || 'claude-haiku-5-5'

  on('tool.call', { tool: 'AskUserQuestion' }, async ($, e, next) => {
    const unit = SOURCE.exec(e.metadata?.source ?? '')?.[1]
    if (!unit) return next(e)
    let cwd: string
    let claim = claims.get(unit)
    try {
      cwd = await $.session.cwd()
      if (!claim) {
        const [recommendation, rhythms] = await Promise.all([recommend($, recommendModel, unit, cwd), rhythmsOf($, cwd)])
        claim = { recommendation, rhythms, refusals: [] }
        claims.set(unit, claim)
      }
    } catch (why) {
      return { deny: `unit-claim could not open the claim dialog for ${unit} (${String(why)}). Tell the developer.` }
    }
    const ran = await next({ ...e, questions: questions(unit, claim) })
    if (ran.deny !== undefined) return ran
    const answers = (ran.result as { answers?: Record<string, string> } | undefined)?.answers ?? {}
    const line = await settle($, resolveModel, unit, claim, answers, cwd).catch(
      why => `The answer could not be settled (${String(why)}). Ask the claim dialog again.`,
    )

    return { ...ran, context: [...(ran.context ?? []), `unit-claim: ${line}`] }
  })

  on('ui.render', { component: 'AskUserQuestion' }, async ($, e, next) => {
    const engine = await next(e)
    const first = e.props.questions[0] as { question?: string } | undefined
    const claim = claims.get(STAGES_LINE.exec(first?.question ?? '')?.[1] ?? '')
    if (!claim) return engine

    const els = $.ui.resolve(e)
    const { Box, Text } = els
    const rec = claim.recommendation
    if (e.surface === 'terminal' || !('Markdown' in els)) {
      const lines = claim.refusals.length
        ? claim.refusals.flatMap(r => [r.refused, ...(r.suggestion ? [`Suggestion: ${r.suggestion}`] : [])])
        : 'error' in rec
          ? [`No suggestion: ${rec.error}.`]
          : [`Run: ${rec.run.map(a => a.stage).join(', ') || 'none'}`, `Skip: ${rec.skip.map(a => a.stage).join(', ') || 'none'}`]

      return (
        <Box flexDirection="column">
          {lines.map(line => (
            <Text color={claim.refusals.length ? 'red' : undefined} dimColor={!claim.refusals.length}>
              {line}
            </Text>
          ))}
          {engine}
        </Box>
      )
    }
    const { Markdown } = els
    const text = claim.refusals.length
      ? claim.refusals.map(r => `**${r.refused}**${r.suggestion ? `\n\nSuggestion: ${r.suggestion}` : ''}`).join('\n\n')
      : reasoning(rec)

    return (
      <Box flexDirection="column">
        <Markdown text={text} />
        {engine}
      </Box>
    )
  })
}
