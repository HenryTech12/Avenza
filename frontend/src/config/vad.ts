/** Live-tunable from the dev panel. Start values from the spec. */
export const vadConfig = {
  positiveSpeechThreshold: 0.5,
  negativeSpeechThreshold: 0.35,
  /** Silence that ends a turn. 500 ms cut people off mid-sentence (phone test 10 Nov); 1200 ms
   *  felt slow; the team chose 900 ms. */
  redemptionMs: 900,
  minSpeechMs: 250,
  preSpeechPadMs: 300,
}
export type VadConfig = typeof vadConfig
