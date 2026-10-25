import type { EngineInterface, Register } from 'claude-code'

// /aidlc-ids:sync builds or brings up to date the id map of the session's AI-DLC project, without a model turn: the
// command runs scripts/aidlc_ids.py sync and answers with what it printed. Agents run the same script before they
// build a page; the command is for the developer, and for a session that wants the map fresh without spending tokens.

const COMMAND = 'sync'

async function sync($: EngineInterface, args: string): Promise<string> {
  const argv = ['python3', `${$.plugin.root}/scripts/aidlc_ids.py`, 'sync']
  if (/(^|\s)--force(\s|$)/.test(args)) argv.push('--force')
  const proc = $.process.spawn({ argv, cwd: await $.session.cwd() })
  let out = ''
  for await (const { text } of proc) out += text
  const done = await proc.result

  return done.code === 0 ? out.trim() : `The id map could not be synced: ${out.trim() || `exit ${done.code}`}`
}

export const register: Register = on => {
  on('session.start', async ($, e, next) => {
    await $.command.register({
      name: COMMAND,
      description: "Build or bring up to date this AI-DLC project's id map (US, AC, FR, NFR, BR, Q, U, ADR, ...)",
      argumentHint: '[--force]',
      immediate: true,
    })

    return next(e)
  })

  on('command.run', { command: COMMAND }, async ($, e) => ({ text: await sync($, e.args) }))
}
