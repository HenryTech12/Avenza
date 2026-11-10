/** Live-tunable from the dev panel. Start values from the spec. */
export const vadConfig = {
  positiveSpeechThreshold: 0.5,
  negativeSpeechThreshold: 0.35,
  redemptionMs: 500,
  minSpeechMs: 250,
  preSpeechPadMs: 300,
}
export type VadConfig = typeof vadConfig
