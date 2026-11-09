# Avenza on the Forge 2026 sandbox

How Avenza runs on the organisers' platform, following the *Sandbox
Participant Platform Guide* v1.0 (9 Nov 2026). Section numbers (§) refer to
that guide.

## What runs where

| Piece | Where | How Avenza uses it |
| --- | --- | --- |
| Avenza (API, WebSocket, PWA) | Your namespace, `app` Service on port 80 → `https://teamXX.xtradot.co` | One pod, SQLite on a 1 Gi volume |
| Xtradot Bank sandbox (§5) | `http://bank-api.ingress-apisix.svc.cluster.local/v1` | `BANK_MODE=sandbox`: name enquiry, transfers, status, history, receipts, balance |
| Huawei MaaS (§6) | `http://huawei-maas.ingress-apisix.svc.cluster.local/openai/v1` | `LLM_PROVIDER=huawei-maas`: intent fallback only, `glm-5.2`, thinking off |
| Team key | Secret `huawei-gateway` (field `GATEWAY_KEY`) | Injected by the manifest; `x-api-key` for the bank, `apikey` for MaaS |

Both platform APIs only answer from inside your namespace. From a laptop they
time out by design (§8.1). For local work use the simulator (below).

## Deploy (first time)

```bash
export KUBECONFIG=~/forge/teamXX.yaml
cp deploy/forge/env.forge.example deploy/forge/.env.forge   # fill in speech keys + ADMIN_TOKEN
deploy/forge/deploy.sh teamXX ghcr.io/<you>/avenza v1
```

`deploy.sh` builds for `linux/amd64`, pushes, creates the `avenza-secrets`
secret from `.env.forge`, applies `deploy/forge/app.yaml` with your team ID,
waits for the rollout and checks `https://teamXX.xtradot.co/healthz`.

For a private image, create `regcred` once (§4.1) and uncomment
`imagePullSecrets` in `app.yaml`.

Then, once:

```bash
# 1. Check the bank from inside the pod (read-only; add --transfer to send ₦100.00)
kubectl exec deploy/app -- python scripts/sandbox_smoke.py

# 2. Register the webhook. The secret is printed once.
kubectl exec deploy/app -- python scripts/register_webhook.py http://app.teamXX.svc.cluster.local/hooks/forge
kubectl patch secret avenza-secrets -p '{"stringData":{"FORGE_WEBHOOK_SECRET":"<secret>"}}'
kubectl rollout restart deployment/app
```

Also add `FORGE_WEBHOOK_SECRET` to `.env.forge` so the next `deploy.sh` keeps it.

Release updates with a new tag every time (`v2`, `v3` or a git SHA; never
`latest`, §4.4). Roll back with `kubectl rollout undo deployment/app`.

## How the bank contract is handled

| Guide rule | Avenza |
| --- | --- |
| Name enquiry before transfer; show the resolved name (§5.2) | The read-back speaks the bank's name; the customer approves that name |
| `name_enquiry_ref` single-use, expires in 10 min, destination must match | Ref from the read-back is reused if under 8 min old and unused; otherwise a fresh enquiry runs. If the bank now shows a different name, the payment stops (`recipient_changed`) |
| Intra vs interbank | Xtradot (NIP 000014) uses `/transfers/intra*`; others `/transfers/interbank*`. Parser bank codes are mapped to NIP codes; "extra dot" is heard as Xtradot |
| Access Bank | Not mapped: in the sandbox CBN 044 is Xtradot itself |
| `Idempotency-Key: <uuid>` | A UUID derived from the transfer's idempotency key; replays return the original |
| Amounts NGN with two decimals | Kobo inside Avenza, converted at the edge |
| **504 TIMEOUT: never resend** | Never resent. Status by `GET /transfers/{reference}` (our reference is known before the call), `requery` for interbank. The reconciler keeps checking; after 15 min with no record at all, the payment is marked failed (`not_received_by_bank`) |
| Interbank 202 pending, settles in ~5 s | Avenza waits up to 6 s (polls every 2 s), saying "Approved. Sending it to the bank now." if it takes longer than 1.5 s |
| Charges in every response | Read from the response and spoken: "Charges ₦10.75." Never hard-coded |
| Reversals (amount .04, webhooks) | New terminal state `REVERSED`; settled payments are re-checked for 3 min, and a reversal is spoken once |
| Error codes (§5.7) | Spoken reasons: not enough money, KYC limit, restricted account, beneficiary can't receive, bank unavailable, busy |
| Webhooks (§5.6) | `POST /hooks/forge`: HMAC-SHA256 of `{timestamp}.{raw body}`, 5-minute window, `event_id` de-duplication, answers at once. The event only triggers a status check; the bank's answer decides |
| 60 requests/min shared (§7.2) | One limiter for bank + MaaS (55/min). Model calls stop when 20 slots are left, so the bank always gets through. `/healthz` makes no platform calls |
| Synthetic data only (§7.3) | Only the guide's fixtures are used |
| Public by default (§7.3) | `APP_ENV=production`: developer enrolment and the fingerprint bypass are off; `/audit` and `/dev/bank/*` need `X-Admin-Token` |

## Accounts

Each customer pays from a team-owned account (§5.4). The default is
`SANDBOX_SOURCE_ACCOUNT` (0123456790, Babatunde Olumide Adeyemi, tier 3,
₦5,000,000). Change it per customer with `PUT /me/source-account`; check it
with `GET /me/balance`.

Beneficiaries to say in a demo (all synthetic):

| Say | Name the bank returns |
| --- | --- |
| "…to Xtradot bank 0987654322" | Aisha Hauwa Bello (intrabank, no fee) |
| "…to Xtradot bank 0987654321" | Ngozi Adaobi Eze |
| "…to GTBank 0123987001" | Chukwuemeka Ifeanyi Nwosu (interbank) |
| "…to Zenith 0123987002" | Funmilayo Abiola Ogunleye |
| "…to First Bank 0123987003" | Zainab Halima Yusuf |
| "…to UBA 0123987004" | Tamunotonye Briggs |
| "…to OPay 8031234506" | Ifeoluwa Grace Adebayo |

Failure paths to show judges (§5.5): an amount ending **.01** (insufficient
funds), **.02** (timeout, then failed and reversed: watch Avenza refuse to
resend), **.03** (pending for 2 minutes, then settled), **.04** (settled, then
reversed after a minute). Dormant `0987654399` and frozen Wema `0123987098`
are refused at the name check. Amounts ending .00 never trigger anything.

Reset the team's bank data before a run: `POST /dev/bank/reset` with
`X-Admin-Token` (calls the sandbox's `/admin/reset`). Bank data is in memory
on the platform and resets on platform restarts (§7.3); Avenza keeps its own
records in SQLite.

## Local development with the simulator

```bash
python -m avenza.bank.xtradot_sim          # Xtradot simulator on :9100
BANK_MODE=sandbox GATEWAY_KEY=dev-team-key SANDBOX_BASE_URL=http://127.0.0.1:9100/v1 python run.py
GATEWAY_KEY=dev-team-key SANDBOX_BASE_URL=http://127.0.0.1:9100/v1 python scripts/sandbox_smoke.py --transfer
```

The simulator follows the guide's summary, fixtures and trigger values, and
`tests/test_xtradot.py` runs the real adapter against it. It is a stand-in:
response field names the guide does not show are best guesses, and the
adapter reads several spellings. **Run `scripts/sandbox_smoke.py` inside the
cluster before relying on the real sandbox**, and quote `request_id` from the
logs (`kubectl logs deploy/app | grep xtradot`) in support requests.

## Known limits

- One pod (SQLite and per-connection state). Fine for the event; Postgres
  would need a second pod within the 768 Mi request quota.
- The default WebSocket path goes through Cloudflare and the APISIX gateway.
  If WebSockets are blocked there, ask the platform team (§9).
- WebAuthn passkeys are bound to `teamXX.xtradot.co`: enrol on that URL.
- Huawei MaaS model availability varies (§6). If `glm-5.2` returns not found,
  set `LLM_MODEL` to another listed model. The LLM is optional: keyword intent
  works without it.
