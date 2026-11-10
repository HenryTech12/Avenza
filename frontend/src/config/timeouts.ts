export const timeouts = {
  /** The opening splash (prototype screen 1) stays this long before Avenza starts talking. */
  splashMs: 5000,
  /** Silence before "I'm still here..."; said at most once per noSpeechCooldownMs (it nagged every 8 s, 10 Nov). */
  noSpeechHintMs: 20000,
  noSpeechCooldownMs: 180000,
  serverReplyMs: 6000,
  fingerprintMs: 60000,
  resultReturnMs: 3000,
  cancelledReturnMs: 3000,
  /** "One moment, I am checking with your bank" only after a real wait, at most once a minute
   *  (at 400 ms it played on every turn, because speech recognition alone takes seconds; 10 Nov). */
  fillerAfterMs: 3500,
  fillerCooldownMs: 60000,
  sendingFillerAfterMs: 1500,
}
