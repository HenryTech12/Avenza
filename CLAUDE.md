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
| `scripts/` | `sandbox_smoke.py`, `register_webhook.py`, `latency_probe.py`, `latency_report.py` |
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

## Open issues (as of 10 Nov 2026, morning)

1. **YarnGPT TTS stalls**: `200 OK` then no bytes for 40 s on a long sentence
   (trace `9bff69a89f3da93d573b6b2a59b10485`); a short "Payment settled." got a
   `422` even with a voice (trace `368442d03167d955c282d8946386e125`). Next: print
   the 422 body, and test `POST /api/v1/tts/prepare` → `GET /api/v1/tts/stream/{ticket}`
   as an alternative route. If that works, switch `yarngpt_tts.py` to it.
   Email YarnGPT support with the trace ids if both stall.
2. **Sahara on the cluster is unverified.** Run the latency probe once TTS works
   (≤3 turns a minute), or a direct Sahara test with a WAV.
3. **Cloudflare Access now fronts team18.xtradot.co**: every request gets a 302 to
   `centrictech.cloudflareaccess.com` (since 9 Nov ~22:20). Ask the Forge organisers whether it
   is intended and how judges/phones get in. With the frontend served on the same origin
   (done), a browser that has logged in to Access carries the cookie to the API and WebSocket.
   Cross-origin hosting (Vercel) would not work behind Access. In-cluster calls (bank webhooks
   to `app.team18.svc.cluster.local`) are unaffected.
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
