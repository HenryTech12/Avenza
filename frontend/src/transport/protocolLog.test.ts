import { describe, expect, it } from 'vitest'
import { effect, signal } from '@preact/signals'
import { logMessage, protocolLog } from './protocolLog'
import { addChat, conversation } from '../session/session'

describe('signals written from inside effects', () => {
  it('logging a sent message inside an effect does not throw (reconnect -> session.start)', () => {
    const status = signal('reconnecting')
    const stop = effect(() => {
      if (status.value === 'open') logMessage('out', 'session.start')
    })
    expect(() => (status.value = 'open')).not.toThrow()
    expect(protocolLog.value.at(-1)?.type).toBe('session.start')
    stop()
  })
  it('adding a chat line inside an effect does not throw', () => {
    const tick = signal(0)
    const stop = effect(() => {
      if (tick.value > 0) addChat('avenza', `line ${tick.value}`)
    })
    expect(() => (tick.value = 1)).not.toThrow()
    expect(() => (tick.value = 2)).not.toThrow()
    expect(conversation.value.at(-1)?.text).toBe('line 2')
    stop()
  })
})
