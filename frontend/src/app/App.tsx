import { LocationProvider, Router, Route, useLocation, lazy } from 'preact-iso'
import { useEffect } from 'preact/hooks'
import { env } from '../config/env'
import { booted, onboardingComplete, updateAvailable, toast, devPanelOpen, locked } from '../session/session'
import { StatusAnnouncer } from '../components/StatusAnnouncer/StatusAnnouncer'
import { Toast } from '../components/Toast/Toast'
import { Boot } from '../screens/Boot/Boot'
import { Voice } from '../screens/Voice/Voice'
import { applyServiceWorkerUpdate } from './pwa'
import { nav } from './nav'
import { t } from '../i18n'

const Settings = lazy(() => import('../screens/Settings/Settings').then((m) => m.Settings))
const History = lazy(() => import('../screens/History/History').then((m) => m.History))
const Lock = lazy(() => import('../screens/Lock/Lock').then((m) => m.Lock))
const DevPanel = lazy(() => import('../screens/DevPanel/DevPanel').then((m) => m.DevPanel))
const Preview = lazy(() => import('../screens/Preview/Preview').then((m) => m.Preview))
const FingerprintSetup = lazy(() => import('../screens/FingerprintSetup/FingerprintSetup').then((m) => m.FingerprintSetup))
const Consent = lazy(() => import('../screens/Consent/Consent').then((m) => m.Consent))
const Language = lazy(() => import('../screens/Language/Language').then((m) => m.Language))

/** Sends the user to /boot until boot has finished, and to onboarding until it is complete. */
function Guard({ children, needsOnboarding = true }: { children: preact.ComponentChildren; needsOnboarding?: boolean }) {
  const { route } = useLocation()
  const ready = booted.value
  const done = onboardingComplete.value
  useEffect(() => {
    if (!ready) {
      if (location.pathname !== '/boot') nav.pending = location.pathname
      route('/boot', true)
    }
    else if (needsOnboarding && !done) route('/onboarding/language', true)
    else if (needsOnboarding && locked.value && location.pathname !== '/lock') route('/lock', true)
  }, [ready, done, needsOnboarding, locked.value])
  if (!ready || (needsOnboarding && !done)) return null
  return <>{children}</>
}

export function App() {
  return (
    <LocationProvider>
      <StatusAnnouncer />
      <Router>
        <Route path="/boot" component={Boot} />
        <Route path="/onboarding/language" component={() => <Guard needsOnboarding={false}><Language /></Guard>} />
        <Route path="/onboarding/consent" component={() => <Guard needsOnboarding={false}><Consent /></Guard>} />
        <Route path="/onboarding/fingerprint" component={() => <Guard needsOnboarding={false}><FingerprintSetup /></Guard>} />
        <Route path="/settings" component={() => <Guard><Settings /></Guard>} />
        <Route path="/history" component={() => <Guard><History /></Guard>} />
        <Route path="/lock" component={() => <Guard><Lock /></Guard>} />
        <Route path="/components" component={env.DEV_PANEL ? Preview : () => <Guard><Voice /></Guard>} />
        <Route path="/" component={() => <Guard><Voice /></Guard>} />
        <Route default component={() => <Guard><Voice /></Guard>} />
      </Router>
      {devPanelOpen.value && env.DEV_PANEL ? <DevPanel /> : null}
      {updateAvailable.value ? (
        <Toast action={<button type="button" onClick={applyServiceWorkerUpdate}>{t('update.reload')}</button>}>
          {t('update.available')}
        </Toast>
      ) : toast.value ? (
        <Toast>{toast.value}</Toast>
      ) : null}
    </LocationProvider>
  )
}
