# Avenza: notes for Claude Code

Avenza is a voice banking assistant for the Forge 2026 hackathon (team 18).
A customer speaks a transfer ("send five thousand naira to GTBank 0123987001"),
Avenza reads back the bank-verified name, the customer says yes, and only a
**fingerprint (WebAuthn passkey) moves money**. Voice alone never does.

- Final submission: **Wednesday 11 Nov 2026**. Demo Day: **Friday 13 Nov 2026**.
- Live: https://team18.xtradot.co (Forge Kubernetes cluster, namespace `team18`).
- Repo: `HenryTech12/Avenza`, working branch `feat/backend-ai`.
- Team: Henry and Muiz review backend changes before merge.

## Layout

| Path | What |
| --- | --- |
| `avenza/` | FastAPI backend: `main.py` (REST + lifespan), `ws.py` (voice WebSocket), `orchestrator.py` (turn logic), `services/transfers.py` (money path), `state_machine.py`, `parser.py`, `intent.py`, `security.py` (WebAuthn) |
| `avenza/bank/` | `mock.py` (local), `sandbox.py` (**Xtradot Bank**, the real Forge sandbox), `xtradot_sim.py` (local simulator of the sandbox) |
| `avenza/providers/ai_speech.py` | Live STT (with provider fallback chain) and YarnGPT TTS wrappers |
| `avenza_ai/` | AI package: amount/time parsers, LLM intent, `providers/ws_stt.py` (Deepgram, **YarnGPT ASR**, **Intron Sahara**), `providers/yarngpt_tts.py` |
| `frontend/` | The frontend team's app (Preact + TypeScript + Vite), from PR #1 `add-frontend`. Built inside the Docker image and served by the backend at `/` (same origin as the API). Env: `VITE_BACKEND_MODE`, `VITE_API_BASE_URL` (empty = same origin), `VITE_WS_URL` |
| `web/` | Legacy PWA, served only when `frontend/dist` does not exist |
| `deploy/forge/` | `app.yaml` (ConfigMap, Deployment, Service), `deploy.sh`, `env.forge.example` |
| `scripts/` | `sandbox_smoke.py`, `register_webhook.py`, `latency_probe.py`, `latency_report.py`, `yarngpt_tts_probe.py` |
| `docs/` | `FORGE.md` (platform runbook), `PROTOCOL.md` (WebSocket contract), `SECURITY.md` |
| `CHANGES.md` | Everything changed since the 9 Nov review |

## Everyday commands (Git Bash on Windows)

```bash
python -m pytest -q                               # must stay green (520 tests)
python -m avenza.bank.xtradot_sim                 # local Xtradot simulator on :9100
BANK_MODE=sandbox GATEWAY_KEY=dev-team-key SANDBOX_BASE_URL=http://127.0.0.1:9100/v1 \
  DATABASE_URL=sqlite:///./local-test.db ALLOW_DEV_APPROVAL=true python run.py

export KUBECONFIG=~/forge/team18.yml              # every new terminal
kubectl get pods
kubectl logs deploy/app -f | grep -iE "xtradot|tts|stt|hooks|error"
kubectl exec deploy/app -- python scripts/sandbox_smoke.py [--transfer]
kubectl exec deploy/app -- python scripts/latency_probe.py --turns 3 [--text]
```

Deploy: push to `feat/backend-ai` → GitHub Actions "Forge image" builds
`ghcr.io/henrytech12/avenza:sha-<7 chars>` (tests run first) → then

```bash
sed -i -e 's/^\xEF\xBB\xBF//' -e 's/\r$//' deploy/forge/.env.forge deploy/forge/deploy.sh deploy/forge/app.yaml
SKIP_BUILD=1 deploy/forge/deploy.sh team18 ghcr.io/henrytech12/avenza sha-$(git rev-parse --short=7 HEAD)
```

There is no Docker on this laptop; always `SKIP_BUILD=1`. `deploy.sh` loads
`deploy/forge/.env.forge` into the `avenza-secrets` secret (values there
override the ConfigMap) and uses the `regcred` pull secret automatically.

## Rules

- **Never commit secrets.** `.env`, `deploy/forge/.env.forge`, kubeconfigs
  (`team*.yml`) and tokens are gitignored. A kubeconfig and three API keys
  leaked once already. Never print a key in output; check with `${#VAR}`.
- **Money safety invariants** (judges assess these; tests cover them):
  - Only a verified WebAuthn assertion (user verification required) approves a transfer.
  - **On a bank timeout (504 / no reply) never resend.** Only `GET /transfers/{reference}`
    and `POST /transfers/interbank/requery`. Resending is disabled for Xtradot.
  - One transfer in flight per customer. Idempotency key on every money POST.
  - "Your money has not moved" is only said when it is true (`safe_error_events`).
  - Charges are read from the bank response, never hard-coded.
- **Synthetic data only**: use the guide's fixtures (see `docs/FORGE.md`).
- **Gateway budget**: bank + Huawei MaaS share 60 requests/minute; the limiter
  in `avenza/gateway.py` keeps bank calls first. `/healthz` makes no platform calls.
- Windows line endings break `deploy.sh` and secrets: run the `sed` above after editing.
- Keep `python -m pytest -q` green; add a regression test with every fix.

## Platform facts (Forge Sandbox Participant Platform Guide v1.0)

- Bank: `http://bank-api.ingress-apisix.svc.cluster.local/v1`, header `x-api-key: $GATEWAY_KEY`
  (from the `huawei-gateway` secret). Only reachable inside the cluster.
- Names come back in capitals; `display_name()` turns them into "Ngozi Adaobi Eze".
- Trigger amounts: .01 insufficient funds, .02 timeout then reversed, .03 pending 2 min, .04 settled then reversed.
- Webhook registered at `http://app.team18.svc.cluster.local/hooks/forge`; secret in `.env.forge`.
- Persistent volumes **fail** on the platform (Linode "outstanding balance"), so
  `/data` is an `emptyDir`: **every redeploy wipes enrolments and logs**. Re-enrol the phone after deploys.

## Speech providers (current config in `.env.forge`)

- STT: `AI_STT_CHOICE=en=sahara|yarngpt,pcm=sahara|yarngpt` (Sahara first, YarnGPT fallback).
  - **Intron Sahara** (`wss://infer.voice.intron.io/stt/v1/stream`): implemented from
    https://docs.voice.intron.io/docs/stt/streaming (SESSION_CREATED, base64 JSON chunks
    1–32 KB, COMMIT). Limit: **3 connections/minute**, 3 concurrent. Only `en` language
    code is confirmed; `SAHARA_LANG_MAP` overrides. **Not yet verified on the cluster.**
  - **YarnGPT live ASR** (`wss://api.yarngpt.ai/api/v1/asr/stream`): implemented from the
    YarnGPT API v1 docs (start → audio → finalize). Not yet verified on the cluster.
- TTS: **YarnGPT** conversation route `POST https://api.yarngpt.ai/api/v1/streaming/conversation`,
  `output_format: pcm`, sample rate read from `Content-Type: audio/l16; rate=N`.
  **`voice` is required** (422 without it) — `YARNGPT_DEFAULT_VOICE=adaora`; the code also
  falls back to the catalogue default. Every call spends real credits.
- LLM: Groq for testing (LLM_ lines in `.env.forge`); **Demo Day uses Huawei MaaS**
  (`glm-5.2`, thinking off): delete the LLM_ lines from `.env.forge` and redeploy.

## How Avenza is used (product rule, 10 Nov)

Voice only, nothing to type or find: splash 5 s, then Avenza talks; onboarding
(`/onboarding`: greeting, name, language, consent "I agree", fingerprint) is one spoken conversation;
the mic stays on on every screen; "open settings", "what is my balance", "speak
Yoruba" work by voice. The only touches a browser can force are the first touch
for sound (not needed once installed on the home screen) and, on some browsers,
one before the fingerprint prompt; both make the whole screen the target.
Hausa/Igbo/Yoruba are beta (unverified translations, speech-to-text untested).

## Open issues (as of 10 Nov 2026, morning)

0. **YarnGPT credits ran out** (10 Nov 09:50; new account key added later that day, after deploying `sha-dd2a0de`): 18 credits left,
   402 `QUOTA_EXCEEDED`. Cost is about **1 credit per character**: a read-back is ~180–300,
   the startup pre-warm ~2,900 (50 prompts) **on every pod start**. Until topped up, every prompt
   falls back to the phone's own voice. Set `TTS_PREWARM=false` if credits are scarce.
1. **YarnGPT TTS** (probe run 10 Nov): minimum text is **20 characters** (422
   `INPUT_TOO_SHORT`); shorter text is no longer sent and English prompts are all ≥20.
   First audio is 3.5–4.6 s for 175 characters, arriving almost all at once. Fixed
   prompts are pre-generated at startup (`tts prewarm:` log line; ~50 calls per pod start),
   so only read-backs wait. **Read-backs are close to `TTS_TIMEOUT_S=6`**: a long one (with a
   warning prefix) may time out and fall back to the device voice. Ticket route
   (`YARNGPT_TTS_ROUTE=ticket`) stays opt-in until the probe shows it is consistently faster.
2. **Sahara works on the cluster** (latency probe, 10 Nov, 3 turns): `stt_final_ms` ~5.7–6.0 s
   after end of speech, the largest stage. Its commits are cumulative; two were being joined
   ("…0100010001000. Send ₦5k to GTBank account 0123987001."), fixed by taking the last one.
   Measured: `tts_ttfa_ms` 4584/4894 ms, `reply_ms` median 11392 ms (target ~2000);
   one read-back with a name-mismatch warning hit the 6 s TTS timeout.
   Next: compare `AI_STT_CHOICE=en=yarngpt|sahara` in one probe run.
3. **Cloudflare Access fronts team18.xtradot.co until Demo Day** (organisers, 10 Nov): it is
   intended; access opens only on the day. **Test and record locally** until then: local backend +
   `avenza.bank.xtradot_sim` + real YarnGPT/Sahara keys in `.env`. Build the frontend with
   `VITE_API_BASE_URL=` (empty) or it calls the cluster (`frontend/.env.production` points there).
   Phone: `adb reverse tcp:8000 tcp:8000` and open `http://localhost:8000` (localhost is a secure
   context; a self-signed LAN cert blocks WebAuthn in Chrome). The live phone path is first
   exercised on Demo Day, so the recorded video is the fallback.
4. **Phone end-to-end test not done yet** (voice + fingerprint + WebSocket through the gateway).
5. **Frontend (PR #1)**: backend side of "serve the frontend" is done (Dockerfile node stage +
   `_mount_frontend` in `main.py`, SPA fallback, API prefixes never shadowed). To do: merge PR #1;
   confirm the app treats an empty `VITE_API_BASE_URL` as same origin and derives `wss://` from
   `location`; client-side routes must not reuse API paths (`/me`, `/transfers`, `/locks`,
   `/config`, `/devices`, `/consents`, `/health*`, `/ws`, `/hooks`, `/dev`, `/audit`), because a
   refresh on those would hit the API; check it handles `prompt.play.audio`, `vad_ms`,
   `REVERSED`, `transcript.partial`, close code 4401 (`docs/PROTOCOL.md`). Live flows
   (enrolment, WebSocket, fingerprint) are untested by the frontend team.
6. **Latency numbers for Demo Day**: 20–30 real phone turns, then
   `kubectl exec deploy/app -- python scripts/latency_report.py /data/latency.jsonl`
   (before any redeploy). Consider streaming TTS audio to the phone as it arrives:
   YarnGPT took 3.3–3.9 s to deliver a full long clip.
7. **Security follow-ups**: confirm the organisers revoked the leaked kubeconfig and
   rotated the team key; confirm old Groq/YarnGPT/Deepgram keys are revoked.
8. **Before Demo Day**: switch LLM to Huawei and verify it once on the cluster;
   merge the PR (workflow builds `master` too); tag the submitted commit
   (`git tag submission-2026-11-11`); demo script with fixtures; backup video;
   claim English only unless the Yoruba/Hausa/Igbo language test passes.
