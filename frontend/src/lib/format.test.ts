import { describe, expect, it } from 'vitest'
import { amountInWords, formatNaira, numberToWords } from './format'

describe('formatNaira', () => {
  it('formats kobo as naira', () => {
    expect(formatNaira(500000).replace(/\s/g, '')).toBe('₦5,000.00')
    expect(formatNaira(1250000).replace(/\s/g, '')).toBe('₦12,500.00')
    expect(formatNaira(25000000).replace(/\s/g, '')).toBe('₦250,000.00')
  })
})

describe('numberToWords', () => {
  it.each([
    [0, 'zero'],
    [7, 'seven'],
    [21, 'twenty-one'],
    [100, 'one hundred'],
    [101, 'one hundred and one'],
    [5000, 'five thousand'],
    [12500, 'twelve thousand five hundred'],
    [250000, 'two hundred and fifty thousand'],
    [1000001, 'one million and one'],
  ])('%i -> %s', (n, w) => expect(numberToWords(n)).toBe(w))
  it('handles invalid input', () => {
    expect(numberToWords(-1)).toBe('')
    expect(numberToWords(NaN)).toBe('')
  })
})

describe('amountInWords', () => {
  it('appends naira and kobo', () => {
    expect(amountInWords(500000)).toBe('five thousand naira')
    expect(amountInWords(500050)).toBe('five thousand naira, fifty kobo')
  })
})
