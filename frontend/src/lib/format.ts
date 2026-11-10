const ngn = new Intl.NumberFormat('en-NG', { style: 'currency', currency: 'NGN' })

/** Display-only formatting of an integer kobo amount received from the server. */
export function formatNaira(kobo: number): string {
  return ngn.format(kobo / 100)
}

const ones = [
  'zero', 'one', 'two', 'three', 'four', 'five', 'six', 'seven', 'eight', 'nine', 'ten',
  'eleven', 'twelve', 'thirteen', 'fourteen', 'fifteen', 'sixteen', 'seventeen', 'eighteen', 'nineteen',
]
const tens = ['', '', 'twenty', 'thirty', 'forty', 'fifty', 'sixty', 'seventy', 'eighty', 'ninety']
const scales: Array<[number, string]> = [
  [1_000_000_000, 'billion'],
  [1_000_000, 'million'],
  [1_000, 'thousand'],
]

function below1000(n: number): string {
  const parts: string[] = []
  if (n >= 100) {
    parts.push(`${ones[Math.floor(n / 100)]} hundred`)
    n %= 100
    if (n > 0) parts.push('and')
  }
  if (n >= 20) {
    parts.push(n % 10 ? `${tens[Math.floor(n / 10)]}-${ones[n % 10]}` : tens[Math.floor(n / 10)])
  } else if (n > 0) {
    parts.push(ones[n])
  }
  return parts.join(' ')
}

/** English words for a whole number. Display and speech helper only. */
export function numberToWords(n: number): string {
  if (!Number.isFinite(n) || n < 0) return ''
  n = Math.floor(n)
  if (n === 0) return 'zero'
  const parts: string[] = []
  for (const [size, name] of scales) {
    if (n >= size) {
      parts.push(`${below1000(Math.floor(n / size))} ${name}`)
      n %= size
    }
  }
  if (n > 0) {
    if (parts.length > 0 && n < 100) parts.push('and')
    parts.push(below1000(n))
  }
  return parts.join(' ')
}

/** "five thousand naira" or "five thousand naira, fifty kobo". */
export function amountInWords(kobo: number): string {
  const naira = Math.floor(kobo / 100)
  const k = kobo % 100
  const nairaWords = `${numberToWords(naira)} ${naira === 1 ? 'naira' : 'naira'}`
  return k > 0 ? `${nairaWords}, ${numberToWords(k)} kobo` : nairaWords
}

export function formatTime(d: Date): string {
  return new Intl.DateTimeFormat('en-NG', { dateStyle: 'medium', timeStyle: 'short' }).format(d)
}
