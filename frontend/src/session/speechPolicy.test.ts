import { describe, expect, it } from 'vitest'
import { cutsSpeech, micMayListen } from './speechPolicy'

describe('speech policy (phone test, 11 Nov: replies cut each other off)', () => {
  it('never cuts a live server reply because a result or an unclear error arrived', () => {
    for (const e of ['result', 'cancelled', 'unclear'] as const) {
      expect(cutsSpeech(e, true)).toBe(false)
      expect(cutsSpeech(e, false)).toBe(true) // mock mode keeps its old behaviour
    }
  })

  it('closes the microphone while Avenza speaks, so it cannot hear itself', () => {
    expect(micMayListen(true, true, false)).toBe(false)
    expect(micMayListen(true, false, false)).toBe(true)
    expect(micMayListen(false, false, false)).toBe(false)
  })

  it('never cuts off a customer who is already talking', () => {
    expect(micMayListen(false, true, true)).toBe(true)
  })
})
