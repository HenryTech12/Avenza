"""Avenza against the Xtradot Bank sandbox contract (Forge guide §5).

The real sandbox only answers inside the team's Kubernetes namespace, so these
tests drive the real adapter against ``avenza.bank.xtradot_sim``, which follows
the guide: envelope, x-api-key, idempotency, single-use name-enquiry refs,
intra vs interbank, fixtures (§5.4) and trigger values (§5.5).
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
import uuid
from datetime import timedelta

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from avenza.bank import XtradotBank
from avenza.bank.adapter import BankNotFound, BankUnavailable
from avenza.bank.xtradot_sim import DEV_KEY, Simulator, create_sim_app
from avenza.config import Settings
from avenza.main import create_app, verify_forge_signature
from avenza.models import Transfer, User
from avenza.state_machine import TransferState
from avenza.timeutil import utcnow
from tests.conftest import make_customer

INTRA = "send five thousand naira to xtradot bank 0987654322"  # Aisha Hauwa Bello
INTER = "send five thousand naira to gtbank 0123987001"  # Chukwuemeka Ifeanyi Nwosu


def sandbox_settings(**changes) -> Settings:
    base = {
        "bank_mode": "sandbox",
        "gateway_key": DEV_KEY,
        "sandbox_base_url": "http://xtradot.test/v1",
        "sandbox_source_account": "0123456790",
        "sandbox_settle_wait_s": 1.0,
        "gateway_requests_per_min": 100_000,
        "forge_webhook_secret": "whsec_test",
    }
    base.update(changes)
    return Settings().for_test(**base)


@pytest.fixture()
def sim(monkeypatch):
    simulator = Simulator(settle_s=0.2)
    sim_app = create_sim_app(simulator)
    real = httpx.AsyncClient

    def factory(*args, **kwargs):
        kwargs["transport"] = httpx.ASGITransport(app=sim_app)
        return real(*args, **kwargs)

    monkeypatch.setattr("avenza.bank.sandbox.httpx.AsyncClient", factory)
    monkeypatch.setattr(XtradotBank, "__init__", _fast_init(XtradotBank.__init__))
    return simulator


def _fast_init(original):
    def init(self, settings):
        original(self, settings)
        self.poll_interval_s = 0.05

    return init


@pytest.fixture()
def settings(sim):
    return sandbox_settings()


def prompts_of(events):
    return [e for e in events if e.get("type") == "prompt.play"]


def states(events):
    return [e["state"] for e in events if e.get("type") == "state.changed"]


def posts(sim, path):
    return [c for c in sim.calls if c == ("POST", path)]


async def pay(services, text):
    o = services["orchestrator"]
    c = make_customer(services)
    readback = await o.process_text(c.ctx, text)
    await o.process_text(c.ctx, "yes")
    done = await o.handle_approval(c.ctx, None, dev=True)
    return c, readback, done


def only_transfer(services) -> Transfer:
    with services["session_factory"]() as db:
        rows = db.scalars(select(Transfer)).all()
    assert len(rows) == 1
    return rows[0]


# ---------------------------------------------------------------------------
# Happy paths
# ---------------------------------------------------------------------------


async def test_intra_transfer_settles_with_the_bank_verified_name(services, sim):
    c, readback, done = await pay(services, INTRA)
    assert "Aisha Hauwa Bello" in prompts_of(readback)[-1]["text"]
    assert states(done) == [TransferState.SETTLED.value]
    t = only_transfer(services)
    sent = sim.transfers[t.bank_reference]
    assert sent.kind == "intra" and sent.source == "0123456790"
    assert sent.amount_kobo == 500_000 and sent.fee_kobo == 0
    assert t.bank_reference.startswith("AVZ-")
    assert "Charges" not in prompts_of(done)[-1]["text"]  # intrabank: no fee


async def test_interbank_transfer_waits_for_settlement_and_speaks_charges(services, sim):
    _c, readback, done = await pay(services, INTER)
    assert "Chukwuemeka Ifeanyi Nwosu" in prompts_of(readback)[-1]["text"]
    assert states(done) == [TransferState.SETTLED.value]
    text = prompts_of(done)[-1]["text"]
    # Sandbox NIP schedule: ₦10 for amounts up to ₦5,000, plus 7.5% VAT.
    assert "Charges ₦10.75." in text
    assert posts(sim, "/v1/transfers/interbank/name-enquiry")
    assert len(posts(sim, "/v1/transfers/interbank")) == 1


async def test_request_carries_the_documented_headers_and_body(services, sim, monkeypatch):
    seen = {}
    original = XtradotBank._call

    async def spy(self, method, path, **kwargs):
        if method == "POST" and path == "/transfers/interbank":
            seen.update(kwargs)
            seen["headers_out"] = self._headers(kwargs.get("headers"))
        return await original(self, method, path, **kwargs)

    monkeypatch.setattr(XtradotBank, "_call", spy)
    await pay(services, INTER)
    body = seen["json"]
    assert body["destination_bank_code"] == "000013"  # GTBank's NIP code, not CBN 058
    assert body["amount"] == 5000.0  # NGN with two decimals, not kobo
    assert body["name_enquiry_ref"] and body["reference"].startswith("AVZ-")
    uuid.UUID(seen["headers_out"]["Idempotency-Key"])  # a real UUID
    assert seen["headers_out"]["x-api-key"] == DEV_KEY


async def test_mis_heard_bank_name_extra_dot_resolves_to_xtradot(services, sim):
    _c, readback, _done = await pay(services, "send five thousand naira to extra dot bank 0987654322")
    assert "Aisha Hauwa Bello" in prompts_of(readback)[-1]["text"]


# ---------------------------------------------------------------------------
# Trigger values (§5.5) and refusals
# ---------------------------------------------------------------------------


async def test_insufficient_funds_trigger_is_a_spoken_failure(services, sim):
    _c, _r, done = await pay(services, "send 5000.01 naira to xtradot bank 0987654322")
    assert states(done) == [TransferState.FAILED.value]
    assert "not have enough money" in prompts_of(done)[-1]["text"]


async def test_timeout_is_never_resent_only_requeried(services, sim):
    """§5.2: on 504 TIMEOUT never resend. Amount .02 then fails and reverses after 30 s."""
    transfers = services["transfers"]
    _c, _r, done = await pay(services, "send 5000.02 naira to gtbank 0123987001")
    assert states(done) == [TransferState.PENDING_UNKNOWN.value]
    assert len(posts(sim, "/v1/transfers/interbank")) == 1

    t = only_transfer(services)
    with services["session_factory"]() as db:
        row = db.get(Transfer, t.id)
        row.submitted_at = utcnow() - timedelta(seconds=120)
        db.commit()
    await transfers.reconcile(stale_after_s=0, resubmit_after_s=60)
    assert len(posts(sim, "/v1/transfers/interbank")) == 1  # still never resent
    assert transfers.get(t.id).state == TransferState.PENDING_UNKNOWN.value

    sim.advance(31)
    await transfers.reconcile(stale_after_s=0, resubmit_after_s=60)
    final = transfers.get(t.id)
    assert final.state == TransferState.FAILED.value and final.failure_reason == "reversed"
    assert len(posts(sim, "/v1/transfers/interbank")) == 1


async def test_pending_two_minutes_then_successful(services, sim):
    transfers = services["transfers"]
    _c, _r, done = await pay(services, "send 5000.03 naira to xtradot bank 0987654322")
    assert states(done) == [TransferState.PENDING_UNKNOWN.value]
    t = only_transfer(services)
    sim.advance(121)
    await transfers.reconcile(stale_after_s=0)
    assert transfers.get(t.id).state == TransferState.SETTLED.value


async def test_settled_then_reversed_is_announced(services, sim):
    o = services["orchestrator"]
    transfers = services["transfers"]
    c, _r, done = await pay(services, "send 5000.04 naira to gtbank 0123987001")
    assert states(done) == [TransferState.SETTLED.value]
    t = only_transfer(services)
    sim.advance(61)
    changed = await transfers.reconcile(stale_after_s=0, reversal_watch_s=180)
    assert [x.state for x in changed] == [TransferState.REVERSED.value]
    events = await o.tick(c.ctx)
    assert states(events) == [TransferState.REVERSED.value]
    assert "reversed by the bank" in prompts_of(events)[-1]["text"]
    assert await o.tick(c.ctx) == []  # announced once


@pytest.mark.parametrize(
    "text",
    [
        "send 2000 naira to xtradot bank 0987654399",  # dormant
        "send 2000 naira to wema bank 0123987098",  # frozen
    ],
)
async def test_dormant_and_frozen_beneficiaries_stop_at_name_enquiry(services, sim, text):
    o = services["orchestrator"]
    c = make_customer(services)
    events = await o.process_text(c.ctx, text)
    assert prompts_of(events)[-1]["id"] == "name_cannot_receive"
    with services["session_factory"]() as db:
        assert db.scalars(select(Transfer)).all() == []


async def test_unknown_account_and_enquiry_timeout(services, sim):
    o = services["orchestrator"]
    c = make_customer(services)
    events = await o.process_text(c.ctx, "send 2000 naira to gtbank 0000000001")
    assert prompts_of(events)[-1]["id"] == "name_not_found"
    events = await o.process_text(c.ctx, "send 2000 naira to gtbank 0000000002")
    assert prompts_of(events)[-1]["id"] == "error_bank"


async def test_kyc_limit_is_reported(services, sim):
    o = services["orchestrator"]
    c = make_customer(services)
    with services["session_factory"]() as db:
        db.get(User, c.user_id).source_account = "0123456792"  # tier 1: ₦50,000 single
        db.commit()
    await o.process_text(c.ctx, "send sixty thousand naira to xtradot bank 0987654322")
    await o.process_text(c.ctx, "yes")
    done = await o.handle_approval(c.ctx, None, dev=True)
    assert states(done) == [TransferState.FAILED.value]
    assert "transfer limit" in prompts_of(done)[-1]["text"]


async def test_access_bank_is_not_sent_to_xtradot(services, sim):
    """In the sandbox CBN 044 is Xtradot; "Access Bank" must not resolve to it."""
    bank = services["bank"]
    with pytest.raises(BankNotFound):
        await bank.name_enquiry("044", "0987654322")


async def test_wrong_team_key_is_bank_unavailable(services, sim):
    sim.api_key = "another-team"
    with pytest.raises(BankUnavailable):
        await services["bank"].name_enquiry("000014", "0987654322")


# ---------------------------------------------------------------------------
# Name-enquiry reference rules
# ---------------------------------------------------------------------------


async def test_stale_enquiry_ref_is_refreshed_before_sending(services, sim):
    bank = services["bank"]
    await bank.name_enquiry("058", "0123987001")
    for ref in bank._refs.values():
        ref.at -= 9 * 60  # older than Avenza's 8-minute refresh window
    result = await bank.create_transfer(
        idempotency_key="avz_refresh",
        customer_ref="0123456790",
        amount_kobo=200_000,
        bank_code="058",
        account_number="0123987001",
        recipient_name="Chukwuemeka Ifeanyi Nwosu",
        nonce="n",
    )
    assert result.status == "SETTLED"
    assert len(posts(sim, "/v1/transfers/interbank/name-enquiry")) == 2


async def test_a_changed_beneficiary_name_stops_the_payment(services, sim):
    bank = services["bank"]
    result = await bank.create_transfer(
        idempotency_key="avz_changed",
        customer_ref="0123456790",
        amount_kobo=200_000,
        bank_code="058",
        account_number="0123987001",
        recipient_name="Someone Else",
        nonce="n",
    )
    assert result.status == "FAILED" and result.failure_reason == "recipient_changed"
    assert posts(sim, "/v1/transfers/interbank") == []


async def test_repeating_a_transfer_never_pays_twice(services, sim):
    bank = services["bank"]
    kwargs = dict(
        idempotency_key="avz_twice",
        customer_ref="0123456790",
        amount_kobo=300_000,
        bank_code="000014",
        account_number="0987654321",
        recipient_name="Ngozi Adaobi Eze",
        nonce="n",
    )
    first = await bank.create_transfer(**kwargs)
    second = await bank.create_transfer(**kwargs)
    assert first.status == second.status == "SETTLED"
    assert first.reference == second.reference
    assert len(sim.transfers) == 1


# ---------------------------------------------------------------------------
# History, receipts, balance
# ---------------------------------------------------------------------------


async def test_history_and_receipt_come_from_the_bank(services, sim):
    o = services["orchestrator"]
    c, _r, _d = await pay(services, INTRA)
    events = await o.process_text(c.ctx, "show my transactions today")
    data = next(e for e in events if e["type"] == "history.data")
    assert data["bank_history"] is True
    assert len(data["transactions"]) == 1  # Avenza row and bank row de-duplicated
    events = await o.process_text(c.ctx, "read my last receipt")
    assert "Aisha Hauwa Bello" in prompts_of(events)[-1]["text"]


def _register(client, source_account=None):
    body = {"display_name": "Sandbox Tester"}
    if source_account:
        body["source_account"] = source_account
    data = client.post("/dev/devices/register", json=body).json()
    return data["device_token"]


def test_balance_and_source_account_endpoints(sim):
    with TestClient(create_app(sandbox_settings())) as client:
        token = _register(client, source_account="0123456791")
        auth = {"Authorization": f"Bearer {token}"}
        assert client.get("/me", headers=auth).json()["user"]["source_account"] == "0123456791"
        balance = client.get("/me/balance", headers=auth).json()
        assert balance["available_display"] == "₦250,000.00"
        assert client.put("/me/source-account", json={"account_number": "0123456789"}, headers=auth).status_code == 200
        assert client.get("/me/balance", headers=auth).json()["available_display"] == "₦1,500,000.00"
        cfg = client.get("/config").json()
        assert any(a["account_name"] == "Aisha Hauwa Bello" for a in cfg["demo_accounts"])
        assert len(cfg["source_accounts"]) == 5


def test_healthz_is_cheap_and_ok(sim):
    with TestClient(create_app(sandbox_settings())) as client:
        before = len(sim.calls)
        assert client.get("/healthz").json() == {"ok": True}
        assert len(sim.calls) == before  # no bank call


def test_sandbox_reset_is_admin_only(sim):
    with TestClient(create_app(sandbox_settings()), client=("10.1.2.3", 1)) as remote:
        assert remote.post("/dev/bank/reset").status_code == 403
    with TestClient(create_app(sandbox_settings(admin_token="t")), client=("10.1.2.3", 1)) as remote:
        assert remote.post("/dev/bank/reset", headers={"X-Admin-Token": "t"}).json()["reset"] is True


# ---------------------------------------------------------------------------
# Webhooks (§5.6)
# ---------------------------------------------------------------------------


def _signed(body: dict, secret="whsec_test", ts: int | None = None):
    raw = json.dumps(body).encode()
    ts = str(ts if ts is not None else int(time.time()))
    sig = "sha256=" + hmac.new(secret.encode(), ts.encode() + b"." + raw, hashlib.sha256).hexdigest()
    return raw, {"x-forge-timestamp": ts, "x-forge-signature": sig, "x-forge-event": body.get("event", "")}


def test_signature_check_matches_the_guide():
    raw = b'{"a":1}'
    ts = str(int(time.time()))
    good = "sha256=" + hmac.new(b"s", ts.encode() + b"." + raw, hashlib.sha256).hexdigest()
    assert verify_forge_signature(raw, ts, good, "s")
    assert not verify_forge_signature(raw, ts, good, "other")
    assert not verify_forge_signature(raw + b" ", ts, good, "s")
    old = str(int(time.time()) - 301)
    old_sig = "sha256=" + hmac.new(b"s", old.encode() + b"." + raw, hashlib.sha256).hexdigest()
    assert not verify_forge_signature(raw, old, old_sig, "s")


def test_webhook_rejects_bad_signatures_and_duplicates(sim):
    with TestClient(create_app(sandbox_settings())) as client:
        body = {"event_id": "evt_1", "event": "webhook.test", "data": {}}
        raw, headers = _signed(body)
        assert client.post("/hooks/forge", content=raw, headers=headers).json() == {"ok": True}
        assert client.post("/hooks/forge", content=raw, headers=headers).json()["duplicate"] is True
        raw2, headers2 = _signed({"event_id": "evt_2"}, secret="wrong")
        assert client.post("/hooks/forge", content=raw2, headers=headers2).status_code == 401
    with TestClient(create_app(sandbox_settings(forge_webhook_secret=""))) as client:
        raw, headers = _signed({"event_id": "evt_3"})
        assert client.post("/hooks/forge", content=raw, headers=headers).status_code == 503


async def test_webhook_event_settles_a_pending_transfer_after_rechecking(services, sim):
    transfers = services["transfers"]
    _c, _r, done = await pay(services, "send 5000.03 naira to xtradot bank 0987654322")
    assert states(done) == [TransferState.PENDING_UNKNOWN.value]
    t = only_transfer(services)
    # A webhook alone changes nothing: the bank still says pending.
    await transfers.apply_bank_event(t.bank_reference)
    assert transfers.get(t.id).state == TransferState.PENDING_UNKNOWN.value
    sim.advance(121)
    await transfers.apply_bank_event(t.bank_reference)
    assert transfers.get(t.id).state == TransferState.SETTLED.value


# ---------------------------------------------------------------------------
# Huawei MaaS (§6) and the shared rate limit (§7.2)
# ---------------------------------------------------------------------------


async def test_huawei_maas_request_shape(monkeypatch):
    from avenza.intent import IntentClassifier

    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["headers"] = dict(request.headers)
        captured["body"] = json.loads(request.content)
        reply = 'Sure: {"intent":"HISTORY","confidence":0.8}'
        return httpx.Response(200, json={"choices": [{"message": {"content": reply}}]})

    real = httpx.AsyncClient

    def factory(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return real(*args, **kwargs)

    monkeypatch.setattr("avenza.intent.httpx.AsyncClient", factory)
    settings = Settings().for_test(
        llm_enabled=True,
        llm_provider="huawei-maas",
        llm_base_url="http://huawei-maas.ingress-apisix.svc.cluster.local/openai/v1",
        llm_model="glm-5.2",
        gateway_key="team-key",
        gateway_requests_per_min=100_000,
    )
    result = await IntentClassifier(settings).classify("what did I do with my money lately")
    assert result.source == "llm" and result.intent.value == "HISTORY"
    assert captured["url"].endswith("/openai/v1/chat/completions")
    assert captured["headers"]["apikey"] == "team-key"
    assert captured["body"]["model"] == "glm-5.2"
    assert captured["body"]["chat_template_kwargs"] == {"thinking": False}
    assert "response_format" not in captured["body"]


async def test_ai_llm_client_sends_maas_headers():
    from avenza_ai.intent.llm import LlamaIntentClassifier

    seen = {}

    def handler(request):
        seen["headers"] = dict(request.headers)
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"choices": [{"message": {"content": '{"intent":"unclear"}'}}]})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    llm = LlamaIntentClassifier(
        base_url="http://maas/openai/v1",
        api_key="unused",
        model="glm-5.2",
        client=client,
        extra_headers={"apikey": "team-key"},
        extra_body={"chat_template_kwargs": {"thinking": False}},
    )
    await llm.classify("hello there")
    assert seen["headers"]["apikey"] == "team-key"
    assert seen["body"]["chat_template_kwargs"] == {"thinking": False}
    await client.aclose()


async def test_gateway_limiter_reserves_budget_for_the_bank():
    from avenza.gateway import GatewayBusy, GatewayLimiter

    limiter = GatewayLimiter(per_minute=5)
    assert all(limiter.try_acquire(reserve=2) for _ in range(3))
    assert not limiter.try_acquire(reserve=2)  # model calls stop here
    await limiter.acquire(max_wait_s=0.1)  # the bank still gets its slots
    await limiter.acquire(max_wait_s=0.1)
    with pytest.raises(GatewayBusy):
        await limiter.acquire(max_wait_s=0.1)


# ---------------------------------------------------------------------------
# Database upgrade
# ---------------------------------------------------------------------------


def test_existing_database_gains_the_source_account_column(tmp_path):
    from sqlalchemy import create_engine, inspect

    from avenza.db import init_db

    path = tmp_path / "old.db"
    engine = create_engine(f"sqlite:///{path}")
    with engine.begin() as conn:
        conn.exec_driver_sql(
            "CREATE TABLE users (id VARCHAR(64) PRIMARY KEY, display_name VARCHAR(200), language VARCHAR(16), created_at DATETIME)"
        )
    init_db(engine)
    columns = {c["name"] for c in inspect(engine).get_columns("users")}
    assert "source_account" in columns
    engine.dispose()


# ---------------------------------------------------------------------------
# The simulator itself follows the guide
# ---------------------------------------------------------------------------


def test_simulator_idempotency_replay_and_conflict():
    sim = Simulator()
    with TestClient(create_sim_app(sim)) as client:
        h = {"x-api-key": DEV_KEY}
        ref = client.post(
            "/v1/transfers/intra/name-enquiry", json={"account_number": "0987654321"}, headers=h
        ).json()["data"]["name_enquiry_ref"]
        body = {
            "source_account": "0123456790",
            "destination_account": "0987654321",
            "name_enquiry_ref": ref,
            "amount": 1000.0,
            "narration": "t",
            "reference": "TRF-1",
        }
        key = {**h, "Idempotency-Key": str(uuid.uuid4())}
        first = client.post("/v1/transfers/intra", json=body, headers=key)
        again = client.post("/v1/transfers/intra", json=body, headers=key)
        assert first.status_code == again.status_code == 201
        assert again.headers["Idempotent-Replayed"] == "true"
        changed = client.post("/v1/transfers/intra", json={**body, "amount": 1001.0}, headers=key)
        assert changed.status_code == 409
        assert client.get("/v1/banks", headers={"x-api-key": "nope"}).status_code == 401
