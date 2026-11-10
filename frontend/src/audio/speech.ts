/** speechSynthesis wrapper used as the spoken fallback for missing prompt audio. */
export function speakText(text: string, lang: string): Promise<void> {
  return new Promise<void>((resolve) => {
    if (typeof speechSynthesis === 'undefined' || typeof SpeechSynthesisUtterance === 'undefined') {
      resolve()
      return
    }
    let finished = false
    const finish = () => {
      if (finished) return
      finished = true
      clearTimeout(guard)
      resolve()
    }
    const u = new SpeechSynthesisUtterance(text)
    u.lang = lang
    u.rate = 0.95
    u.onend = finish
    u.onerror = finish
    // some browsers never fire onend: guard by length
    const guard = setTimeout(finish, 2500 + text.length * 90)
    try {
      speechSynthesis.speak(u)
    } catch {
      finish()
    }
  })
}
