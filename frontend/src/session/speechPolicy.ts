/**
 * When Avenza may be interrupted, and when the microphone may listen.
 *
 * Phone test on the cluster, 11 Nov 2026: a reply was cut off mid-sentence and another one
 * started. Two causes:
 *  1. The microphone stayed open while Avenza started speaking, so it could hear Avenza's own
 *     voice from the speaker, send it as an utterance, and get an "unclear" reply back.
 *  2. Arriving results and "unclear" errors called `player.stop()`, cutting whatever the server
 *     was still saying. With live server voices, the server's prompts already arrive in order.
 */

/** Things that used to stop playback even though the customer did nothing. */
export type AutoCut = 'result' | 'cancelled' | 'unclear'

/**
 * Should this event stop what Avenza is saying? Only in mock mode, where the app voices its own
 * prompts and the cut makes room for the next one. With live server voices, never: the server's
 * next prompt is queued behind the current one.
 */
export function cutsSpeech(_event: AutoCut, serverVoices: boolean): boolean {
  return !serverVoices
}

/**
 * May the microphone be open right now? Never while Avenza is speaking (it would hear itself),
 * except to finish an utterance the customer had already started.
 */
export function micMayListen(wantsMic: boolean, avenzaSpeaking: boolean, customerMidUtterance: boolean): boolean {
  if (customerMidUtterance) return true
  return wantsMic && !avenzaSpeaking
}
