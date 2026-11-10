import { signal } from '@preact/signals'
import { Icon } from '../../components/Icon/Icon'
import { StatusPanel } from '../../components/StatusPanel/StatusPanel'
import { ListeningOrb } from '../../components/ListeningOrb/ListeningOrb'
import { AmountDisplay } from '../../components/AmountDisplay/AmountDisplay'
import { RecipientCard } from '../../components/RecipientCard/RecipientCard'
import { BigButton } from '../../components/BigButton/BigButton'
import { TranscriptLine } from '../../components/TranscriptLine/TranscriptLine'
import { SimulatedBadge } from '../../components/SimulatedBadge/SimulatedBadge'
import { CountdownRing } from '../../components/CountdownRing/CountdownRing'
import { Wordmark } from '../../components/Wordmark/Wordmark'

const level = signal(0.35)
const speaking = signal(false)

/** Dev-only `/components` route: every component, static. */
export function Preview() {
  return (
    <main class="page" style={{ gap: '32px' }}>
      <Wordmark size="lg" />
      <SimulatedBadge />
      <section><h2>Orb</h2>
        <ListeningOrb mode="listening" level={level} speaking={speaking} />
        <ListeningOrb mode="checking" level={level} speaking={speaking} size={160} />
      </section>
      <StatusPanel icon="check" tone="success" status="Transfer successful" line="Reference AVZ123" />
      <StatusPanel icon="warning" tone="warning" status="Checking the final status" line="Please wait" />
      <StatusPanel icon="cross" tone="danger" status="Transfer failed" line="Your money has not moved." />
      <AmountDisplay amountKobo={500000} />
      <RecipientCard name="Aisha Bello" bankName="GTBank" accountMasked="•••• 4821" isNewRecipient />
      <TranscriptLine text="Send five thousand naira to Aisha Bello" />
      <CountdownRing deadline={Date.now() + 60000} totalMs={60000} />
      <BigButton>Primary</BigButton>
      <BigButton variant="secondary">Secondary</BigButton>
      <BigButton variant="danger">Danger</BigButton>
      <BigButton loading>Loading</BigButton>
      <div style={{ display: 'flex', gap: '12px', flexWrap: 'wrap' }}>
        {(['mic', 'check', 'cross', 'fingerprint', 'bank', 'warning', 'lock', 'wifi-off', 'settings', 'share'] as const).map((n) => (
          <Icon key={n} name={n} />
        ))}
      </div>
    </main>
  )
}
