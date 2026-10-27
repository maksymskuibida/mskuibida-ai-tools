// A not-started item told apart: ready (open circle, normal text), blocked (lock, dim text), else plain planned.
import { describe, expect, test } from 'claude-code/testing'
import { itemLook } from '../src/render/item'
import { iconSource } from '../src/render/look'

const look = (readiness?: 'ready' | 'blocked') => itemLook({ status: 'planned', readiness })

describe('not-started items', () => {
  test('ready is normal text, blocked and plain planned are dim, each with its own glyph', () => {
    expect([look('ready').glyph, look('ready').isDim]).toEqual(['○', false])
    expect([look('blocked').glyph, look('blocked').isDim]).toEqual(['⊘', true])
    expect([look().glyph, look().isDim]).toEqual(['○', true])
  })

  test('the desktop icons differ', () => {
    const icons = new Set([iconSource('planned'), iconSource('ready'), iconSource('blocked')])
    expect(icons.size).toBe(3)
  })
})
