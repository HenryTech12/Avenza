import type { MicVAD } from '@ricky0123/vad-web'
import { getAudioContext } from './audioContext'
import { vadConfig } from '../config/vad'

export interface VadEvents {
  onSpeechStart(): void
  onSpeechEnd(): void
}

/**
 * Silero VAD (via @ricky0123/vad-web) on the shared AudioContext and shared mic stream.
 * Model and WASM are self-hosted in /vad/, so it works offline.
 *
 * - `onSpeechRealStart` (after minSpeechMs) starts an utterance; misfires send nothing.
 * - pause()/resume() implement half-duplex: the VAD is paused while the app speaks.
 */
export class Vad {
  private vad: MicVAD | null = null
  private running = false

  private loading: Promise<void> | null = null

  load(getStream: () => Promise<MediaStream>, events: VadEvents): Promise<void> {
    this.loading ??= this.doLoad(getStream, events).catch((e) => {
      this.loading = null
      throw e
    })
    return this.loading
  }

  private async doLoad(getStream: () => Promise<MediaStream>, events: VadEvents): Promise<void> {
    const { MicVAD: Mic } = await import('@ricky0123/vad-web') // lazy: keeps ONNX runtime out of the main bundle
    this.vad = await Mic.new({
      model: 'v5',
      audioContext: getAudioContext(),
      baseAssetPath: '/vad/',
      onnxWASMBasePath: '/vad/',
      startOnLoad: false,
      getStream,
      // the shared stream stays open; pausing the VAD must not stop the mic tracks
      pauseStream: async () => undefined,
      resumeStream: async () => getStream(),
      positiveSpeechThreshold: vadConfig.positiveSpeechThreshold,
      negativeSpeechThreshold: vadConfig.negativeSpeechThreshold,
      redemptionMs: vadConfig.redemptionMs,
      minSpeechMs: vadConfig.minSpeechMs,
      preSpeechPadMs: vadConfig.preSpeechPadMs,
      onSpeechRealStart: () => events.onSpeechStart(),
      onSpeechEnd: () => events.onSpeechEnd(),
      onVADMisfire: () => undefined, // too short: send nothing
    })
  }

  get loaded(): boolean {
    return !!this.vad
  }

  async resume(): Promise<void> {
    if (!this.vad || this.running) return
    this.running = true
    await this.vad.start()
  }

  async pause(): Promise<void> {
    if (!this.vad || !this.running) return
    this.running = false
    await this.vad.pause()
  }

  /** Live threshold changes from the dev panel. */
  applyConfig(): void {
    this.vad?.setOptions({
      positiveSpeechThreshold: vadConfig.positiveSpeechThreshold,
      negativeSpeechThreshold: vadConfig.negativeSpeechThreshold,
      redemptionMs: vadConfig.redemptionMs,
      minSpeechMs: vadConfig.minSpeechMs,
      preSpeechPadMs: vadConfig.preSpeechPadMs,
    })
  }
}
