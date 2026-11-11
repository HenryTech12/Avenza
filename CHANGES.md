# Changes: review fixes, 9 November 2026

All 481 tests pass (415 existing + 66 new in `tests/test_fixes.py`). 51 of the
new tests fail on the previous code, which shows they catch the defects below.


## 10 November 2026 (late): replies always in the chosen language

- The language chosen in onboarding (or by saying "speak Yoruba") is kept.
  Automatic detection is now off by default (`LANGUAGE_DETECTION=true` to turn
  it on): a customer who chose Yoruba but says the request in English still
  hears Yoruba.
- Every server reply now exists in Yoruba, Hausa and Igbo (20 were missing and
  fell back to English, e.g. "I could not find that account"); a test keeps it so.
- The app's own short lines (yes/no/repeat, fingerprint retry, connection and
  error messages, warnings) are served in the chosen language too.
- "Cancel" in Yoruba, Hausa and Igbo (fagilé, soke, kagbuo).
- All Hausa/Igbo/Yoruba text is unverified: a native-speaker check is needed.

## 10 November 2026 (late): the chosen language from the first word; phone fixes

Phone test: Yoruba chosen, but onboarding, "checking with your bank" and "I'm
still here" stayed English; "I agree" was not heard; the fingerprint prompt did
not open by itself.

- `GET /voice/{lang}/{line_id}` (`avenza/client_lines.py`): the app's own fixed
  lines (onboarding, fillers) in English, Yoruba, Hausa and Igbo, voiced by the
  server's TTS and cached on disk. Fixed ids only, never free text. The app plays
  them instead of the phone's voice (phones rarely have a Yoruba voice, and a
  missing voice also delayed listening). Hausa/Igbo/Yoruba text is unverified.
- Onboarding confirms the language in that language, then speaks every step in it.
- "I agree" is listened for in Nigerian English and accepted in all four
  languages (also "mogba", "nayarda", "a kwere m").
- Fingerprint: Chrome on Android opens the prompt only right after a touch, so
  Avenza now says "Touch the screen anywhere, then place your finger on the
  sensor" and the whole screen is the target (where the browser allows it, the
  prompt still opens by itself).

## 10 November 2026 (night): fixed prompts cached on disk

- The audio of every fixed prompt is saved under `TTS_CACHE_DIR` (default
  `data/tts-cache`, gitignored; `/data/tts-cache` on the cluster). A restart
  replays them with no TTS calls: no credits, no waiting for Modal. The key
  includes provider and voice, so changing either generates afresh. Read-backs
  (names, amounts) are never written to disk. `TTS_CACHE_DIR=` turns it off.

## 10 November 2026 (night): self-hosted YarnGPT on Modal

- `TTS_PROVIDER=yarngpt-modal` with `YARNGPT_MODAL_URL`: Avenza's voice from the
  team's own deployment of the open-source YarnGPT (`POST {text, lang, speaker}` ->
  wav), so the demo does not depend on hosted-API credits. Speaker per language
  (`YARNGPT_MODAL_SPEAKERS`; English, Yoruba, Igbo, Hausa). Falls back to the hosted
  YarnGPT API when Modal fails fast, then to the phone's voice.
- A cold Modal container takes about a minute: the pre-warm waits up to 120 s for it;
  `YARNGPT_MODAL_KEEPWARM_S=90` pings it so it stays warm during a demo.
- `scripts/modal_tts_probe.py`: cold and warm timings per language, `--save` writes clips.
- Measured: cold 42 s, warm 21–27 s for 3–5 s of speech. `YARNGPT_MODAL_MODE=prewarm`
  (default) uses Modal only for the fixed prompts cached at startup; live replies go to
  the hosted API (or the phone's voice at once) instead of waiting 6 s and timing out.

## 10 November 2026 (evening): animated splash, onboarding as one conversation

- **Splash**: full-window animated scene (letters, rising pearl with moving
  light, ripples, particles, "Avenza is ready" status), also on desktop.
- **Console warning fixed** ("The AudioContext was not allowed to start"):
  prompt clips decode on an OfflineAudioContext, and the real AudioContext is
  only created after a touch or when the browser allows sound (installed app,
  page already touched). Otherwise the splash becomes one "touch anywhere" button.
- **Onboarding** is one screen (`/onboarding`) and one short conversation:
  greeting, name, language, one-sentence consent ("Do you agree?"),
  fingerprint (opens by itself), "You're all set". Progress shown as 4 steps.
  Voice first; each step also has one small control (type the name, tap a
  language, I agree, register). Re-asks only after real silence; when speech
  recognition is unavailable it asks once and the controls take over.

## 10 November 2026: voice only, from opening to payment

Avenza is meant to be used without touching the screen (blind and low-vision
customers first).

- **Opening**: the prototype's first screen (dawn sky, pearl, "Your voice.
  Your bank. Always.") for 5 s, then Avenza speaks. Browsers allow sound only
  after one touch unless Avenza is installed on the home screen; when sound is
  blocked the whole screen is a single button and screen readers announce
  "touch anywhere".
- **Onboarding by voice**: Avenza asks for the language, reads the consent and
  waits for "I agree", asks the customer's name, then opens the fingerprint
  prompt itself. Every question is asked again when nothing is heard. If the
  browser needs a touch before the fingerprint prompt, Avenza says "touch
  anywhere" and the whole screen is the target.
- **Voice everywhere**: the microphone stays on across screens. New voice
  commands: "what is my balance" (bank figure, never invented), "open
  settings", "go home", "show my transactions" (`navigate` event). A payment
  always brings the customer back to the main screen. The greeting now says
  what can be asked.
- **Languages (beta)**: "speak Yoruba/Hausa/Igbo/English" switches Avenza's
  replies and the next turn's speech-to-text; Avenza also switches when the
  words clearly belong to another language (`avenza/langdetect.py`, cautious:
  several marker words or language-only letters). Hausa, Igbo and Yoruba are
  marked Beta in the app: the translations are unverified.
  `LANGUAGE_DETECTION`, `SWITCH_LANGUAGES`, `BETA_LANGUAGES`.

## 10 November 2026: frontend redesign (prototype)

- **Look**: warm "pearl" theme is the default (dark and high contrast stay in
  Settings), spaced AVENZA wordmark, pearl orb with mic-level bars.
- **Home** (no transfer in progress): greeting by name, "Listening · Always
  on", the last few lines of the conversation as chat bubbles, balance card
  (hidden until tapped, from `GET /me/balance`), quick actions (send money
  hint, check balance, history, lock), "You can also say" examples, bottom
  navigation (Home, Transactions, Settings).
- **Transfer screens**: read-back unchanged; fingerprint step as a "Verify your
  identity" card; success screen with a check mark, reference and date.
- **Voice onboarding**: the consent is read aloud and "I agree" can be said;
  the fingerprint step asks for the name by voice and then opens the
  fingerprint prompt. Buttons and typing still work. Uses the browser's speech
  recognition (no server session exists before enrolment), so the consent now
  names it. Consent text also corrected to the real providers (it named
  Google Cloud and Anthropic); consent version `2026-11-v2`.
- The current state stays the page's `<h1>`, so screen readers and the e2e
  tests see "Listening", "Approve with your fingerprint", "Transfer successful".
- Not built (no backend support): bills and services, airtime, several
  accounts, a typed send-money form.

## 10 November 2026: Sahara transcripts doubled

Latency probe on the cluster: Sahara sends a mid-utterance
`COMMITTED_TRANSCRIPT` and then a full one after our COMMIT, each covering the
whole session. Both were joined, giving "Send ₦5k to GTBank account
0100010001000. Send ₦5k to GTBank account 0123987001." and, in another turn,
a false name-mismatch warning ("I heard extradition"). Sahara is now marked
`cumulative_finals`, and the live path (`ai_speech`) honours that flag as the
batch path already did: the last commit wins. Regression test in
`tests/ai/test_providers.py` (fails on the old code).

## 10 November 2026: YarnGPT TTS stall (open issue 1)

- **The 422 reason was dropped.** YarnGPT puts it in `error.details` (and some
  422s use `{"detail": [...]}`); the log line now keeps it, so the next
  `tts failed:` warning says which field or limit was wrong.
- **A stall now says where it stalled**: `ReadTimeout after N ms, B bytes
  received (conversation route)`, so "200 then nothing" and "200 then cut off
  mid-clip" can be told apart in `kubectl logs`.
- **Ticket route, opt-in**: `YARNGPT_TTS_ROUTE=ticket` uses
  `POST /api/v1/tts/prepare` then `GET /api/v1/tts/stream/{ticket}`. Written
  from the route names only and **not verified live**; the default is still the
  conversation route.
- **`scripts/yarngpt_tts_probe.py`**: runs both routes with a short and a long
  text from inside the pod and prints status, full error body, trace ids, time
  to headers and first byte, bytes, and whether and where it stalled
  (up to 4 paid calls).
- 9 regression tests in `tests/ai/test_providers.py`.

### Probe results (cluster, 10 Nov) and follow-up

- **YarnGPT's minimum is 20 characters** (`422 INPUT_TOO_SHORT`). Shorter text
  is no longer sent (`MIN_CHARS`); the device voice speaks it. English prompts
  lengthened: `listening_resume` "I am listening again.", `unlock_success`
  "Transfers are unlocked now.", `charges` "The bank charge was {charges}."
  A test keeps every English prompt at 20 characters or more.
- **First audio takes 3.5-4.6 s for 175 characters** and arrives almost all at
  once. All 50 fixed English prompts are now synthesised in the background at
  startup (`TurnOrchestrator.prewarm_tts`, concurrency 2, kept apart from the
  read-back LRU so they are never evicted). Only read-backs and other prompts
  with variable parts pay the TTS wait. Settings: `TTS_PREWARM`,
  `TTS_PREWARM_LANGUAGES`, `TTS_PREWARM_CONCURRENCY`, `TTS_PREWARM_TIMEOUT_S`.
  Log line: `tts prewarm: N of M fixed prompts cached in S s`.

## Act now

- **Three live API keys were in `.env.example`** (Groq `LLM_API_KEY`, YarnGPT
  `YARN_API_KEY`, Deepgram `DEEPGRAM_API_KEY`). They were uncommitted local
  edits, not in git history, but they were in the shared zip. All three are
  blanked here. Revoke and reissue all three, then put the new ones in `.env`
  (gitignored). `.env.example` is back to mock providers; set
  `STT_PROVIDER=ai` and `TTS_PROVIDER=yarngpt` in `.env` for the live demo.

## Bugs fixed

| # | Defect | Fix | Where |
| --- | --- | --- | --- |
| 1 | Sandbox bank raised `TypeError` (headers passed twice) on every transfer, so nothing could ever settle | Headers merged once; `Idempotency-Key` and auth both sent | `avenza/bank/sandbox.py` |
| 2 | Duplicate, new-recipient and name-mismatch warnings were stored but never spoken | Warnings prefixed to every read-back (template or AI); repeat payments explain the second "yes" | `orchestrator._readback_prompt`, `TransferService.warnings_for` |
| 3 | "not correct", "I'm not sure", "yes no", "is it correct" counted as YES; "don't send it" as TRANSFER | Negation and contradiction handling, hedges, questions; contractions rejoined; short words like "to" no longer confirm | `avenza/intent.py` |
| 4 | A late "yes" could expire mid-fingerprint (draft expiry ignored the approval window) | Draft expiry extended through risk hold and approval window on every (re)issue | `TransferService.record_confirmation / issue_approval / reissue_approval` |
| 5 | `approval.rejected` was rolled back with the failed transaction, so failed fingerprints left no audit trace | Recorded in its own transaction; failure count read from the audit log | `TransferService.approve_and_submit`, `approval_failures` |
| 6 | A reconnect started a new session and orphaned the transfer; a second draft could start; PENDING_UNKNOWN was never resolved if the customer left | Transfers looked up per customer; resume on `session.start`; one in-flight transfer per customer; background reconciler (status check, safe resend with the same key after 60 s, expiry, stuck APPROVED) | `orchestrator.start_events`, `TransferService.create_draft / reconcile`, `main._reconcile_loop` |
| 7 | Any exception in a turn closed the socket with "internal error" | Per-message error handling; the spoken message is true for the customer's state ("money has not moved" only if it hasn't) | `ws.py`, `orchestrator.safe_error_events` |
| 8 | Sandbox: status 404 raised instead of NOT_FOUND; a 4xx refusal became "pending"; receipt 404 gave HTTP 500; amount not checked | 404 → NOT_FOUND; 402/400/422 → FAILED with reason; 409 → status lookup; amount mismatch → PENDING; receipt 404 → 404 | `avenza/bank/sandbox.py`, `main.get_receipt` |
| 9 | "$50" read as ₦50 (backend); AI parser ignored currency entirely | Currency symbols survive normalisation and are rejected; AI parser returns `unsupported_currency` | `parser.normalize`, `avenza_ai/parsing/*` |
| 10 | Multi-word numerals counted every word: Hausa "goma sha biyar" (15) → ₦45, Igbo "iri na ise" → ₦45, Yoruba "márùn-ún" → +5 | Only the first token of a phrase carries the value | `parser._classify_tokens / _word_runs` |
| 11 | Recipient hint grabbed spoken digits, "at", "my mum on", "for rent" → false name-mismatch | Hint stops at prepositions, numbers and bank names; relationships are not names | `parser.extract_recipient_hint` |
| 12 | STT timeout 30 s; STT failure reported as "I did not hear you" | 8 s default, every STT call has a timeout; failures use `error_stt` | `config`, `orchestrator._process_audio` |
| 13 | `/audit/*` and `/dev/bank/*` open to anyone on the network by default | Without `ADMIN_TOKEN` they answer only localhost | `main.require_admin` |
| 14 | Session TTL never enforced | Checked on every message; `session_expired` then close code 4401; activity touches the session | `ws.py` |
| 15 | Duplicate check only looked at SETTLED transfers | Also APPROVED, SUBMITTED, PENDING_UNKNOWN | `TransferService.create_draft` |
| 16 | "today"/"yesterday"/"last week" used UTC midnight | Lagos (WAT) boundaries; AI time phrases tried first | `parser.parse_history_query` |
| 17 | AI parser missed plain "marun", "ogorun", "aadorun" | Added | `avenza_ai/parsing/lexicon.py` |
| 18 | A recorded WAV for a prompt with variables (read-back) would play the wrong amount | `audio_url` only for fixed prompts | `prompts.PromptLibrary.render` |
| 19 | A late bank reply after another path finished the transfer raised `TransitionError` | Finishing a terminal transfer is a no-op (conflicts audited) | `TransferService._finish_submission` |
| 20 | Risk-hold timer could race a voice reply; cancel during APPROVED raised | Timer takes the session lock and re-checks state; APPROVED is not cancellable | `orchestrator._delayed_approval`, `TransferService.cancel` |

## Features completed (from the technical documentation)

- **Server TTS (YarnGPT).** Every spoken prompt, including the read-back with
  the bank-verified name, is synthesised server-side, cached and sent inside
  `prompt.play` as `audio` (PCM). The device voice is the fallback. `audio.stream`
  is now queued by the client rather than played over other prompts.
- **Live STT streaming.** With `STT_PROVIDER=ai`, audio frames go to the
  provider while the customer speaks; `transcript.partial` events are sent; the
  whole utterance is retried in batch if the live stream fails.
- **AI amount cross-check on by default.** It asks again only when the two
  parsers hear different amounts or a foreign currency; it stays silent when it
  simply cannot read a phrase (kobo, a language not enabled).
- **History from the bank.** `list_transactions` adds payments Avenza did not
  draft; spoken receipts come from `get_receipt`. Falls back to local records.
- **Per-stage latency log** (`reports/latency.jsonl`): VAD tolerance, STT first
  partial and final, STT wait, intent, name enquiry, TTS first audio, reply.
  `python scripts/latency_report.py` prints median/p90 against the 2 s / 3.5 s
  targets. The PWA now sends `vad_ms` with `utterance.end`.
- **Local-language confirmations** (unverified until the language test):
  "bẹ́ẹ̀ni", "ee", "toh", "oya" (yes); "a'a", "babu" (no).

## Frontend changes (web/app.js)

Small and backwards compatible: play `prompt.play.audio` when present, queue
`audio.stream`, send `vad_ms`, send `X-Admin-Token` from
`localStorage['avenza.adminToken']` for bank controls. Service worker cache
bumped to `avenza-v2` so phones pick up the new script.

## Still open (needs people or credentials, not code)

- Sandbox paths and field names are placeholders marked `CONFIRM`.
- YarnGPT/Sahara live ASR protocols are scaffolds marked `CONFIRM`; Deepgram is concrete.
- Language test recordings (`data/language_test/`) are not recorded yet.
- Fingerprint fallback policy: implemented as three failed reads then cancel; state it openly.
- The `venv/` folder was in the zip; it is excluded from this package.

---

# Forge 2026 sandbox integration (9 November 2026, evening)

Built from the *Sandbox Participant Platform Guide* v1.0. 505 tests pass
(476 before + 29 in `tests/test_xtradot.py`). Runbook: `docs/FORGE.md`.

## Xtradot Bank (`BANK_MODE=sandbox`, `avenza/bank/sandbox.py`)

- Real contract: `x-api-key`, the success/error envelope, `/transfers/intra*`
  and `/transfers/interbank*`, NIP bank codes, NGN decimals, UUID
  `Idempotency-Key`, single-use `name_enquiry_ref` (refreshed after 8 min;
  payment stops if the bank's name changed), charges read from the response.
- **504 / no reply: never resent.** Status by our own reference (known before
  the call) and `requery`; the reconciler keeps checking. Resending after a
  status NOT_FOUND is now disabled for this bank.
- Requests that certainly never reached the bank (connection refused, the
  fresh name check failed, 401, our own rate budget) fail cleanly as "no money
  moved" instead of hanging as "pending".
- Every §5.7 error code maps to a spoken reason.
- New `REVERSED` state (settled, then reversed by the bank); recent settlements
  are re-checked for 3 minutes and reversals are announced once.
- History from `GET /transactions`, receipts from `GET /transactions/{ref}`,
  balance from `GET /accounts/{n}/balance` (`GET /me/balance`).
- Each customer has a debit account (`users.source_account`, default
  `SANDBOX_SOURCE_ACCOUNT`); `PUT /me/source-account`. Older databases gain
  the column automatically on start.
- "Xtradot bank" and the mis-hearing "extra dot" are recognised; "Access Bank"
  is not mapped (in the sandbox, CBN 044 is Xtradot).
- `POST /hooks/forge`: signed webhooks (HMAC-SHA256, 5-minute window,
  `event_id` de-duplication); the event only triggers a status check.
- Admin: `POST /dev/bank/reset` (sandbox `/admin/reset`), `POST /dev/bank/webhook`.

## Platform

- One shared limiter for the 60 requests/min budget; model calls stop while
  20 slots remain so bank calls always get through.
- Huawei MaaS: `LLM_PROVIDER=huawei-maas` sends the team key as `apikey`,
  uses `glm-5.2` with thinking off, and parses JSON from free text.
- After approval, if the bank is slow, Avenza says "Approved. Sending it to
  the bank now." so the customer never hears silence.
- Container: port 8080, `/healthz` (no platform calls), `--ws-ping-interval`.
- `deploy/forge/`: manifest (PVC, ConfigMap, Deployment with Recreate,
  Service `app:80`), `deploy.sh`, `env.forge.example`.
- `scripts/sandbox_smoke.py` (in-cluster checks, optional ₦100.00 transfer),
  `scripts/register_webhook.py`.
- `avenza/bank/xtradot_sim.py`: a local simulator of the sandbox (fixtures and
  trigger values) for laptops and tests.

## Still to confirm on the cluster

- Response field names the guide does not show (the adapter accepts several
  spellings). Run `scripts/sandbox_smoke.py --transfer` first.
- The body of `POST /transfers/interbank/requery` (sent as `{"reference": ...}`).
- WebSockets through Cloudflare and the gateway; a default StorageClass for
  the volume.

## 11 Nov: deploy

- Deployed `sha-a3bc665` to team18. The pod could not start: `exceeded quota: team-quota`
  (requests.cpu 150m + 300m held > 400m). Fixed on the cluster with
  `kubectl set resources deployment/app --requests=cpu=50m`; `deploy/forge/app.yaml` now asks for 50m
  (limit still 500m). Test: `tests/test_forge_manifest.py`.
- Slow or flaky connection to the cluster API: `kubectl set image deployment/app app=<image>` is the
  smallest deploy (secrets first with `kubectl apply --validate=false`).
