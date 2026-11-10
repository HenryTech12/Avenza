import src from '../../public/pcm-worklet.js?raw'
import { describe, expect, it } from 'vitest'
import { FrameDownsampler } from './pcm'

/** Runs public/pcm-worklet.js in a fake worklet scope and compares its output to src/audio/pcm.ts. */
describe('pcm-worklet.js stays in sync with FrameDownsampler', () => {
  it('produces identical frames', () => {
    let Ctor: new () => { process(i: Float32Array[][]): boolean; port: { postMessage(m: { frame?: ArrayBuffer }): void } }
    class FakeProcessor {
      port = { postMessage: (m: { frame?: ArrayBuffer }) => posted.push(m) }
    }
    const posted: Array<{ frame?: ArrayBuffer }> = []
    new Function('sampleRate', 'registerProcessor', 'AudioWorkletProcessor', src)(48000, (_n: string, c: typeof Ctor) => (Ctor = c), FakeProcessor)
    const proc = new Ctor!()
    const input = Float32Array.from({ length: 9600 }, (_, i) => Math.sin(i / 17) * 0.5)
    for (let i = 0; i < input.length; i += 128) proc.process([[input.slice(i, i + 128)]])
    const expected = new FrameDownsampler(48000).push(input)
    const got = posted.filter((m) => m.frame).map((m) => new Int16Array(m.frame!))
    expect(got.length).toBe(expected.length)
    got.forEach((g, i) => expect(Array.from(g)).toEqual(Array.from(expected[i])))
  })
})
