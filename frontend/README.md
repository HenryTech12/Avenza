# Avenza web (voice banking PWA, frontend)

Voice drafts, fingerprint approves. The customer speaks a transfer, hears the bank-verified recipient and amount read back, approves with their fingerprint (WebAuthn) and hears the result.

Preact + signals, TypeScript strict, Vite, `preact-iso`, `vite-plugin-pwa`, Silero VAD (`@ricky0123/vad-web`), `@simplewebauthn/browser`, `zod`.

## Run

```bash
npm install
npm run dev          # https://localhost:5173 (mock mode) (self-signed; mic and WebAuthn need HTTPS). `vite --host` for a phone.
npm test             # Vitest: schemas, reducer, PCM, player queue, prompts, contrast, components, transports
npm run build        # tsc + production build (live mode) + service worker
npm run build:mock   # same, in mock mode (used by the PWA e2e test)
npm run e2e          # Playwright (needs the dev server on :5180: `npx vite --port 5180`)
```

E2E: `tests/scenarios.spec.ts` (every mock scenario), `tests/a11y.spec.ts` (onboarding + axe on every screen/panel in dark, light and high contrast), `tests/pwa.spec.ts` (needs `npm run build:mock && NO_SSL=1 npx vite preview --port 5182`; service workers reject self-signed certificates, so the PWA check uses plain http on localhost). `tests/live.spec.ts` is a read-only smoke test against the real backend (`LIVE=1`, vite in live mode on :5183).

## Mock vs live (one setting)

Environment variables (see `.env.example`; `.env.development` is mock, `.env.production` is live):

| Variable | Meaning |
| --- | --- |
| `VITE_BACKEND_MODE` | `mock` (built-in scenarios, no backend) or `live` (the Avenza backend) |
| `VITE_API_BASE_URL` | Backend REST base URL, e.g. `https://team18.xtradot.co`. Empty = same origin as the app |
| `VITE_WS_URL` | Optional. Defaults to the base URL with `ws(s)://` and `/ws` |
| `VITE_MOCK_SCENARIO`, `VITE_DEV_PANEL` | Mock scenario and the dev panel |

Only `src/transport/index.ts` and `src/api/index.ts` look at the mode. Screens import only from `src/session/`.

**Live API layer.** `src/api/http.ts` is the one HTTP client (bearer device token, timeout, uniform `ApiError`, 401 handler). `src/api/rest.ts` holds the REST wire schemas and the mapping to domain types, `src/protocol/wire.ts` the WebSocket wire format (snake_case on the wire, camelCase in the app). There is no password login or refresh token: identity is the passkey enrolment, which returns a device token. A 401 (or a `device_not_enrolled` WebSocket error) clears the device and sends the customer to set up again.

**Local dev against the live backend without CORS:** `VITE_BACKEND_MODE=live npx vite` with `VITE_API_BASE_URL` empty; `vite.config.ts` proxies the backend routes to `AVENZA_PROXY_TARGET` (default `https://team18.xtradot.co`). Passkeys are bound to the backend's `WEBAUTHN_RP_ID`/`WEBAUTHN_ORIGIN`, so enrolment only completes when the app is served from that origin (or against a backend configured for your dev origin).

**Deploying:** the backend allows CORS and WebSocket origins only from its `WEBAUTHN_ORIGIN`. Serve the build from that origin, or add yours there.

The dev panel (five taps on the wordmark, dev builds only) can switch mode and scenario at runtime (stored in `sessionStorage`, with a visible "override active" banner), tune VAD thresholds live, show latency, list the last 50 protocol messages (types only) and clear local data. In dev, `?flags=scamPause` turns feature flags on for one page load.

## Mock scenarios

`happy_path`, `say_no`, `repeat_then_yes`, `unclear_twice`, `fingerprint_fail`, `fingerprint_timeout`, `bank_timeout`, `bank_failed`, `provider_down`, `ws_drop`, `slow_network`, `new_recipient_large` (`src/mocks/scenarios/index.ts`, interpreted by `scenarioRunner.ts`).

**Mock answer rule:** after the read-back, a reply comes from the on-screen buttons (`confirm.response`) or, if the customer speaks, the next entry in the scenario's `answers` list (any utterance counts; the last entry repeats). Mock read-back speech is `prompt.play` with `clipUrl: "speak:<text>"`, spoken by `speechSynthesis` through the single playback queue.

The fingerprint step uses the real browser WebAuthn API even in mock mode; the mock accepts any assertion.

## Backend notes

- The backend has no button message: a tapped Yes / Repeat / No is sent as a typed `utterance.text` ("yes", "repeat", "no"), exactly as if spoken. Cancelling the fingerprint sends "no".
- In live mode the server speaks every prompt (`prompt.play` with text, optional PCM or clip URL); the app only adds tones and the device-voice fallback. In mock mode the app speaks its own cached prompts.
- `state.changed` carries only the amount text and recipient, so the bank name and masked account for the read-back come from `GET /transfers/{id}` (once per transfer).
- Consent is recorded after the fingerprint (`POST /consents` needs the device token), so onboarding is language, consent screen, name + fingerprint; the consent is sent to the backend at the end.
- Backend `audio.stream` (base64 PCM inside JSON) is wired but untested: the backend's TTS provider is currently `mock`.
- Not in the customer app by design: `/audit/*`, `/dev/*` (admin token), `/hooks/forge` (bank webhook), `/ai/status`, `/prompts`.

## Privacy

Audio and the 300 ms pre-roll live in RAM. Only `language`, `consentId`, `deviceToken` (the bearer token that identifies this device; it cannot approve a payment, only the fingerprint can), `onboardingComplete`, `theme` and `highContrast` are persisted (`src/lib/settings.ts`; asserted in the onboarding e2e test). No IndexedDB. The service worker caches app files, VAD model, fonts and prompt audio, never audio from the microphone and never WebSocket traffic.

## Prompts

`public/prompts/manifest.json` lists every prompt id with its text. Until real audio exists, entries have no `file` and are spoken with `speechSynthesis`. To add recorded audio, add `"file": "en/listening.mp3"` and put the file in `public/prompts/en/`; nothing else changes. Other languages: add entries with `lang: "yo" | "ha" | "ig"`; English is the fallback. Languages are switched on in `src/config/languages.ts` (`enabled`).

## Design values

Everything is a CSS custom property in `src/styles/tokens.css` (theme in `themes.css`). Dark `--text-muted` was nudged from `#A7B0C0` to `#B0B9C9` so every text pair reaches AAA 7:1 (checked in `src/styles/contrast.test.ts` for dark, light and both high-contrast themes).
