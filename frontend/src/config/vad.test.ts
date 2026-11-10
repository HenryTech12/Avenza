import { describe, expect, it } from 'vitest'
import { vadConfig } from './vad'

describe('end of speech', () => {
  it('waits long enough for a natural pause mid-sentence (phone test, 10 Nov)', () => {
    expect(vadConfig.redemptionMs).toBeGreaterThanOrEqual(800) // 500 ms cut people off
    expect(vadConfig.redemptionMs).toBeLessThanOrEqual(1600) // longer feels unresponsive
  })
})
