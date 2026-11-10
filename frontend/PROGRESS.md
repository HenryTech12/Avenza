# Avenza build progress
STATUS: DONE
Source of truth: Avenza_frontend_prompt.md (phases in section 15). Design context: "Avenza Frontend Design & Build Spec.md".
Update this file after every phase. Set "STATUS: DONE" only when section 16 is satisfied.

## Phases
- [x] 1 Scaffold, tooling, tokens, components
- [x] 2 Protocol, transport, mock, api, config
- [x] 3 State machine + session + tests
- [x] 4 Audio engine
- [x] 5 Screens
- [x] 6 Error handling (verified by e2e)
- [x] 7 PWA (vite-plugin-pwa configured; build passes)
- [x] 8 Stubs + dev panel
- [x] 9 WebSocketTransport + HttpApiClient
- [x] 10 Tests

## Notes / assumptions

### Log
- Phases 2, 3 (machine+tests), most of 4 done: protocol, transport (mock+ws), api, config, machine, audio engine (pcm, player, tones, promptCache, vad, micCapture, latency). 60 unit tests pass.
- Removed `erasableSyntaxOnly` from tsconfig.app.json (parameter properties used).
- Mock-only convention: prompt.play clipUrl "speak:<text>" = client speaks text. Fingerprint cancel/fail is sent as confirm.response "no" (needs backend agreement).
- Next: i18n, webauthn, session.ts, selectors, haptics, components, screens, app router, PWA icons, dev panel, e2e.
- 01:15 Whole app written; `tsc` clean, `vite build` OK, 60 unit tests pass. Remaining: run in browser via Playwright, fix bugs, e2e per scenario, axe, Lighthouse, extra component tests, lazy-load VAD, contrast check, README.
- 01:50 All 12 mock scenarios pass in Playwright (npx vite --port 5180 must be running; tests/scenarios.spec.ts). Remaining: onboarding e2e, axe on all screens/panels, contrast check, component tests, lazy-load VAD, Lighthouse, README. Dev server port 5180 (5173 is used by an unrelated user process).
- Contrast: dark --text-muted changed #A7B0C0 -> #B0B9C9 (AAA on surface-raised). All other pairs pass (src/styles/contrast.test.ts).
- FINAL: 87 unit tests, 20 e2e (12 scenarios, axe, onboarding, PWA offline) pass. Lighthouse mobile: perf 87, a11y 100, best-practices 100. Perf <90 due to main-thread eval of the app chunk (zod etc.); possible follow-up: zod/mini.
- 2026-11-09: live backend integration (api/http, rest, wire, enrich, history/settings/lock screens); backend now behind Cloudflare Access, live e2e blocked
