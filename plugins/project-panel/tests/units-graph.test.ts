// The Units graph's arithmetic: waves, the default range, and the counts behind "Show earlier / later".
import { describe, expect, test } from 'claude-code/testing'

import { dotSource, MINE_RING } from '../src/render/graph'
import { rangeOf, wavesOf } from '../src/render/waves'
import type { UnitGraphNode, UnitGraphState } from '../types'

const node = (name: string, dependsOn: string[] = [], state: UnitGraphState = 'blocked', isMine = false): UnitGraphNode => ({
  id: `unit:${name}`,
  name,
  label: name,
  dependsOn,
  state,
  isMine,
})
const names = (waves: UnitGraphNode[][]) => waves.map(row => row.map(one => one.name))

describe('wavesOf', () => {
  test('wave = 1 + the longest chain above; list order within a wave', () => {
    const waves = wavesOf([node('web', ['api', 'auth']), node('auth'), node('api', ['auth']), node('docs'), node('e2e', ['web'])])
    expect(names(waves)).toEqual([['auth', 'docs'], ['api'], ['web'], ['e2e']])
  })

  test('a dependency that names no Unit is ignored', () => {
    expect(names(wavesOf([node('billing', ['ghost']), node('api-shell', ['billing', 'phantom'])]))).toEqual([['billing'], ['api-shell']])
  })

  test('a cycle shares one wave, and what waits on it comes after; no endless recursion', () => {
    const waves = wavesOf([node('a', ['c']), node('b', ['a']), node('c', ['b']), node('base'), node('tail', ['a']), node('own', ['own'])])
    expect(waves.flat().map(one => one.name).sort()).toEqual(['a', 'b', 'base', 'c', 'own', 'tail'])
    const waveOf = (name: string) => waves.findIndex(row => row.some(one => one.name === name))
    expect(waveOf('a')).toBe(waveOf('b'))
    expect(waveOf('b')).toBe(waveOf('c'))
    expect(waveOf('tail')).toBeGreaterThan(waveOf('a'))
    expect(waveOf('base')).toBe(0)
  })

  test('no Units, no waves', () => {
    expect(wavesOf([])).toEqual([])
  })
})

const chain = (states: UnitGraphState[]) => states.map((state, at) => node(`u${at + 1}`, at === 0 ? [] : [`u${at}`], state))
const rangeOfChain = (states: UnitGraphState[]) => rangeOf(wavesOf(chain(states)))

describe('rangeOf', () => {
  test('starts at the first wave with an unfinished Unit; the earlier waves are the count behind "Show earlier"', () => {
    const range = rangeOfChain(['finished', 'finished', 'ready', 'blocked', 'blocked', 'blocked', 'blocked', 'blocked'])
    // Two finished waves sit before it: "Show earlier (2)".
    expect(range.first).toBe(2)
    expect(range.last).toBe(5)
  })

  test('ends 3 waves past the latest touched one, capped at the last wave; the rest is "Show later"', () => {
    const states: UnitGraphState[] = ['finished', 'claimed', 'blocked', 'blocked', 'blocked', 'blocked', 'blocked', 'blocked', 'blocked', 'blocked']
    const range = rangeOfChain(states)
    expect(range).toEqual({ first: 1, last: 4 })
    expect(states.length - 1 - range.last).toBe(5)
    expect(rangeOfChain(['claimed', 'blocked']).last).toBe(1)
  })

  test('nothing touched: counted from the first shown wave', () => {
    expect(rangeOfChain(['ready', 'blocked', 'blocked', 'blocked', 'blocked', 'blocked'])).toEqual({ first: 0, last: 3 })
  })

  test('all finished: only the last wave is first, nothing later', () => {
    expect(rangeOfChain(['finished', 'finished', 'finished'])).toEqual({ first: 2, last: 2 })
  })

  test('counts: earlier is the waves before the range, later the waves after', () => {
    const waves = wavesOf(chain(['finished', 'finished', 'claimed', 'blocked', 'blocked', 'blocked', 'blocked', 'blocked']))
    const range = rangeOf(waves)
    expect(range.first).toBe(2)
    expect(range.last).toBe(5)
    expect(waves.length - 1 - range.last).toBe(2)
  })

  test('no waves, nothing to show', () => {
    expect(rangeOf([])).toEqual({ first: 0, last: -1 })
  })
})

describe('the circle', () => {
  test('the "yours" ring is drawn on the claimed Unit in every state, and on no other', () => {
    for (const state of ['blocked', 'ready', 'claimed', 'finished'] as const) {
      expect(dotSource(state, true)).toContain(MINE_RING)
      expect(dotSource(state, false)).not.toContain(MINE_RING)
    }
  })

  test('each state looks different', () => {
    const looks = new Set((['blocked', 'ready', 'claimed', 'finished'] as const).map(state => dotSource(state, false)))
    expect(looks.size).toBe(4)
  })
})
