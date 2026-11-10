import { describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen } from '@testing-library/preact'
import { AmountDisplay } from './AmountDisplay/AmountDisplay'
import { BigButton } from './BigButton/BigButton'
import { CountdownRing } from './CountdownRing/CountdownRing'
import { Icon } from './Icon/Icon'
import { RecipientCard } from './RecipientCard/RecipientCard'
import { Sheet } from './Sheet/Sheet'
import { SimulatedBadge } from './SimulatedBadge/SimulatedBadge'
import { StatusPanel } from './StatusPanel/StatusPanel'
import { TranscriptLine } from './TranscriptLine/TranscriptLine'

describe('components', () => {
  it('StatusPanel shows a status word as the heading plus an icon', () => {
    const { container } = render(<StatusPanel icon="check" tone="success" status="Transfer successful" line="Done" />)
    expect(screen.getByRole('heading', { level: 1 }).textContent).toBe('Transfer successful')
    expect(container.querySelector('svg[aria-hidden="true"]')).toBeTruthy()
    expect(screen.getByText('Done')).toBeTruthy()
  })

  it('AmountDisplay formats kobo and adds the spoken words', () => {
    render(<AmountDisplay amountKobo={500000} />)
    expect(screen.getAllByText(/5,000\.00/).length).toBeGreaterThan(0)
    expect(screen.getByText('five thousand naira')).toBeTruthy()
  })

  it('RecipientCard shows the verified label, name, bank and masked account', () => {
    render(<RecipientCard name="Aisha Bello" bankName="GTBank" accountMasked="•••• 4821" isNewRecipient />)
    expect(screen.getAllByText('Verified by your bank').length).toBeGreaterThan(0)
    expect(screen.getByText('Aisha Bello')).toBeTruthy()
    expect(screen.getByText(/GTBank/)).toBeTruthy()
    expect(screen.getByText(/4821/)).toBeTruthy()
    expect(screen.getByText('New recipient')).toBeTruthy()
  })

  it('BigButton fires clicks, and is disabled and busy while loading', () => {
    const onClick = vi.fn()
    const { rerender } = render(<BigButton onClick={onClick}>Go</BigButton>)
    fireEvent.click(screen.getByRole('button', { name: 'Go' }))
    expect(onClick).toHaveBeenCalledTimes(1)
    rerender(
      <BigButton onClick={onClick} loading>
        Go
      </BigButton>,
    )
    const b = screen.getByRole('button', { name: 'Go' }) as HTMLButtonElement
    expect(b.disabled).toBe(true)
    expect(b.getAttribute('aria-busy')).toBe('true')
  })

  it('SimulatedBadge says Simulated bank', () => {
    render(<SimulatedBadge />)
    expect(screen.getByRole('status').textContent).toContain('Simulated bank')
  })

  it('TranscriptLine prefixes "I heard:" and renders nothing visible when empty', () => {
    const { rerender, container } = render(<TranscriptLine text="send 5000" />)
    expect(screen.getByText('I heard: send 5000')).toBeTruthy()
    rerender(<TranscriptLine text="" />)
    expect(container.textContent).toBe('')
  })

  it('CountdownRing exposes the seconds left to assistive tech', () => {
    render(<CountdownRing deadline={Date.now() + 30_000} totalMs={60_000} />)
    expect(screen.getByRole('timer').getAttribute('aria-label')).toMatch(/\d+ seconds left/)
  })

  it('Icon is hidden unless labelled', () => {
    const { container, rerender } = render(<Icon name="mic" />)
    expect(container.querySelector('svg')?.getAttribute('aria-hidden')).toBe('true')
    rerender(<Icon name="mic" label="Microphone" />)
    expect(screen.getByRole('img', { name: 'Microphone' })).toBeTruthy()
  })

  it('Sheet is a modal dialog, traps focus, and Escape closes when allowed', () => {
    const onClose = vi.fn()
    render(
      <Sheet title="Heads up" message="Your money has not moved." onClose={onClose}>
        <button type="button">One</button>
        <button type="button">Two</button>
      </Sheet>,
    )
    const dialog = screen.getByRole('alertdialog')
    expect(dialog.getAttribute('aria-modal')).toBe('true')
    expect(document.activeElement?.textContent).toBe('One')
    screen.getByText('Two').focus()
    fireEvent.keyDown(document, { key: 'Tab' })
    expect(document.activeElement?.textContent).toBe('One')
    fireEvent.keyDown(document, { key: 'Escape' })
    expect(onClose).toHaveBeenCalled()
  })

  it('Sheet without onClose ignores Escape', () => {
    render(<Sheet title="Wait" message="Reconnecting" />)
    fireEvent.keyDown(document, { key: 'Escape' })
    expect(screen.getByRole('alertdialog')).toBeTruthy()
  })
})
