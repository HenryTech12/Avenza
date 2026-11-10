/** Live-tunable from the dev panel. Start values from the spec. */
export const vadConfig = {
  positiveSpeechThreshold: 0.5,
  negativeSpeechThreshold: 0.35,
  /** Silence that ends a turn. 500 ms cut people off mid-sentence (a pause before the account
   *  number, slower or older speakers; phone test 10 Nov). 1200 ms lets them finish. */
  redemptionMs: 1200,
  minSpeechMs: 250,
  preSpeechPadMs: 300,
}
export type VadConfig = typeof vadConfig
