import type { On } from 'claude-code'
import { describe, expect, test } from 'claude-code/testing'

// Stands for the engine beneath the plugin: the session's folder and the script it runs.
function world(on: On, code = 0, out = 'demo: id map written (/maps/x.json); 708 ids; 134 documents read, 0 unchanged, 0 gone') {
  const ran: string[][] = []
  on('session.cwd', () => ({ value: '/project' }))
  on('process.spawn', async function* (_, e) {
    ran.push([...e.argv.slice(2)])
    yield { stream: 'stdout' as const, text: out }
    return { value: { code, signal: null } }
  })

  return ran
}

describe('/aidlc-ids:sync', () => {
  test('runs the sync and answers with what it printed', async ($, on) => {
    const ran = world(on)

    const result = await $.command.run({ command: 'sync', args: '' })

    expect(ran).toEqual([['sync']])
    expect(JSON.stringify(result)).toContain('708 ids')
  })

  test('--force is passed on', async ($, on) => {
    const ran = world(on)

    await $.command.run({ command: 'sync', args: '--force' })

    expect(ran).toEqual([['sync', '--force']])
  })

  test('a failure says so', async ($, on) => {
    world(on, 1, 'aidlc_ids.py: no active intent folder found; pass --intent-dir')

    const result = await $.command.run({ command: 'sync', args: '' })

    expect(JSON.stringify(result)).toContain('could not be synced: aidlc_ids.py: no active intent folder found')
  })
})
