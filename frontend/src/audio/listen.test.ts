import { describe, expect, it } from 'vitest'
import { isAgreement, nameFrom } from './listen'

describe('spoken onboarding answers', () => {
  it('accepts agreement and refuses a negative', () => {
    for (const s of ['I agree', 'yes I agree', 'Okay.', 'Yes', 'agreed']) expect(isAgreement(s), s).toBe(true)
    for (const s of ['I do not agree', "I don't agree", 'no', 'not now', 'hello']) expect(isAgreement(s), s).toBe(false)
  })
  it('takes the name out of a sentence', () => {
    expect(nameFrom('my name is ngozi adaobi eze')).toBe('Ngozi Adaobi Eze')
    expect(nameFrom("I'm Tunde.")).toBe('Tunde')
    expect(nameFrom('Chukwuemeka')).toBe('Chukwuemeka')
  })
})
