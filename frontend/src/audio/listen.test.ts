import { describe, expect, it } from 'vitest'
import { isAgreement, languageFrom, nameFrom } from './listen'

describe('spoken onboarding answers', () => {
  it('accepts agreement and refuses a negative', () => {
    for (const s of ['I agree', 'yes I agree', 'Okay.', 'Yes', 'agreed']) expect(isAgreement(s), s).toBe(true)
    for (const s of ['I do not agree', "I don't agree", 'no', 'not now', 'hello', 'I need to think', 'eh?']) expect(isAgreement(s), s).toBe(false)
  })
  it('accepts agreement in Yoruba, Hausa and Igbo (beta)', () => {
    for (const s of ['Mo gbà', 'Na yarda', 'Ekwere m', 'Bẹ́ẹ̀ni']) expect(isAgreement(s), s).toBe(true)
    for (const s of ['Rárá', "A'a", 'Mba', 'Ban yarda ba']) expect(isAgreement(s), s).toBe(false)
  })
  it('hears the language the customer names', () => {
    expect(languageFrom('Yoruba please')).toBe('yo')
    expect(languageFrom('I want Hausa')).toBe('ha')
    expect(languageFrom('Igbo')).toBe('ig')
    expect(languageFrom('English')).toBe('en')
    expect(languageFrom('Yorùbá')).toBe('yo')
    expect(languageFrom('hello')).toBeNull()
  })
  it('takes the name out of a sentence', () => {
    expect(nameFrom('my name is ngozi adaobi eze')).toBe('Ngozi Adaobi Eze')
    expect(nameFrom("I'm Tunde.")).toBe('Tunde')
    expect(nameFrom('Chukwuemeka')).toBe('Chukwuemeka')
  })
})
