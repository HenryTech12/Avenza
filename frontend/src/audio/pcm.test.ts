import { describe, expect, it } from 'vitest'
import { FrameDownsampler, floatToInt16, int16ToFloat, resampleLinear, rms } from './pcm'

describe('PCM conversion', () => {
  it('converts float to int16 with clipping', () => {
    const out = floatToInt16(Float32Array.from([0, 1, -1, 2, -2, 0.5]))
    expect(Array.from(out)).toEqual([0, 32767, -32768, 32767, -32768, 16384])
  })
  it('round-trips within quantisation error', () => {
    const src = Float32Array.from([0, 0.25, -0.25, 0.9, -0.9])
    const back = int16ToFloat(floatToInt16(src))
    back.forEach((v, i) => expect(Math.abs(v - src[i])).toBeLessThan(1e-3))
  })
})

describe('resampleLinear', () => {
  it('is identity at equal rates', () => {
    const a = Float32Array.from([1, 2, 3])
    expect(resampleLinear(a, 16000, 16000)).toBe(a)
  })
  it('doubles length when upsampling 2x and interpolates', () => {
    const out = resampleLinear(Float32Array.from([0, 1, 0, 1]), 8000, 16000)
    expect(out.length).toBe(8)
    expect(out[1]).toBeCloseTo(0.5)
  })
  it('halves length when downsampling 2x', () => {
    expect(resampleLinear(new Float32Array(480), 48000, 24000).length).toBe(240)
  })
})

describe('FrameDownsampler', () => {
  it('emits 320-sample frames from 48 kHz input', () => {
    const d = new FrameDownsampler(48000)
    // 20 ms at 48k = 960 samples -> one frame (give a little extra for interpolation edge)
    const frames = d.push(new Float32Array(1000))
    expect(frames.length).toBe(1)
    expect(frames[0].length).toBe(320)
  })
  it('is seamless across chunk boundaries (same total as one big push)', () => {
    const input = Float32Array.from({ length: 48000 }, (_, i) => Math.sin(i / 20))
    const whole = new FrameDownsampler(48000).push(input)
    const parts = new FrameDownsampler(48000)
    const framesParts: Int16Array[] = []
    for (let i = 0; i < input.length; i += 128) framesParts.push(...parts.push(input.slice(i, i + 128)))
    expect(framesParts.length).toBe(whole.length)
    expect(Array.from(framesParts[10])).toEqual(Array.from(whole[10]))
  })
  it('passes through 16 kHz input', () => {
    const frames = new FrameDownsampler(16000).push(new Float32Array(641))
    expect(frames.length).toBe(2)
  })
})

describe('rms', () => {
  it('measures level', () => {
    expect(rms(new Float32Array(10))).toBe(0)
    expect(rms(Float32Array.from([1, -1, 1, -1]))).toBeCloseTo(1)
  })
})
