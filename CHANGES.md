# Changes: review fixes, 9 November 2026

All 481 tests pass (415 existing + 66 new in `tests/test_fixes.py`). 51 of the
new tests fail on the previous code, which shows they catch the defects below.


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
