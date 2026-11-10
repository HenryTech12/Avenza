"""Regression tests for the review fixes of 9 November 2026.

Each test names the defect it guards against. They are written to fail on the
code before the fix.
"""

from __future__ import annotations

import asyncio
import json
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from avenza.config import Settings
from avenza.intent import Intent, keyword_intent
from avenza.main import create_app
from avenza.models import AuditLog, BankTransfer, Transfer
from avenza.orchestrator import SessionContext
from avenza.parser import extract_recipient_hint, extract_transfer_fields, parse_amount
from avenza.prompts import PromptLibrary
from avenza.providers.base import AudioResult, STTProvider, STTStream, TranscriptResult
from avenza.state_machine import TransferState
from avenza.timeutil import utcnow
from tests.conftest import make_customer

REQUEST = "Send five thousand naira to GTBank account 0123456789"


def prompts_of(events: list[dict]) -> list[dict]:
    return [e for e in events if e.get("type") == "prompt.play"]


def states(events: list[dict]) -> list[str]:
    return [e["state"] for e in events if e.get("type") == "state.changed"]


def audit_events(services) -> list[str]:
    with services["session_factory"]() as db:
        return [r.event for r in db.scalars(select(AuditLog).order_by(AuditLog.seq)).all()]


def new_ctx(services, customer) -> SessionContext:
    """A second connection for the same customer (phone reconnect)."""
    session = services["sessions"].start(
        user_id=customer.user_id, device_id=customer.device_id, consent_id=customer.consent_id
    )
    return SessionContext(
        session_id=session.id, user_id=customer.user_id, device_id=customer.device_id, language="en"
    )


# ---------------------------------------------------------------------------
# 1. Sandbox bank adapter: see tests/test_xtradot.py (real Forge contract)
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# 2. Risk warnings are spoken
# ---------------------------------------------------------------------------


async def test_duplicate_warning_is_spoken_and_second_yes_is_explained(services):
    o = services["orchestrator"]
    c = make_customer(services)
    await o.process_text(c.ctx, REQUEST)
    await o.process_text(c.ctx, "yes")
    await o.handle_approval(c.ctx, None, dev=True)

    events = await o.process_text(c.ctx, REQUEST)
    readback = prompts_of(events)[-1]
    assert "recently to the same account" in readback["text"]
    assert "duplicate" in readback["warnings"]

    events = await o.process_text(c.ctx, "yes")
    assert "confirm once more" in prompts_of(events)[-1]["text"]


async def test_new_recipient_large_amount_warning_is_spoken(services):
    o = services["orchestrator"]
    c = make_customer(services)
    events = await o.process_text(c.ctx, "Send one hundred thousand naira to GTBank 0123456789")
    assert "new recipient and a large amount" in prompts_of(events)[-1]["text"]


async def test_name_mismatch_warning_is_spoken_for_a_real_name_only(services):
    o = services["orchestrator"]
    c = make_customer(services)
    events = await o.process_text(c.ctx, "Send five thousand naira to Tunde on GTBank 0123456789")
    text = prompts_of(events)[-1]["text"]
    assert "I heard tunde" in text
    assert "Aisha Bello" in text


async def test_spoken_account_digits_do_not_raise_a_false_name_warning(services):
    o = services["orchestrator"]
    c = make_customer(services)
    events = await o.process_text(
        c.ctx, "send two thousand naira to zero one two three four five six seven eight nine gtbank"
    )
    readback = prompts_of(events)[-1]
    assert "name_mismatch" not in readback["warnings"]


# ---------------------------------------------------------------------------
# 3. Confirmation words
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "reply,expected",
    [
        ("yes", Intent.YES),
        ("yes that's right", Intent.YES),
        ("okay go ahead", Intent.YES),
        ("not correct", Intent.NO),
        ("no it's not correct", Intent.NO),
        ("that's not who I wanted to pay", Intent.NO),
        ("don't send it", Intent.NO),
        ("it's the wrong account", Intent.NO),
        ("a'a", Intent.NO),
        ("yes no", Intent.UNCLEAR),
        ("no, yes", Intent.UNCLEAR),
        ("I'm not sure", Intent.UNCLEAR),
        ("I want to think about it", Intent.UNCLEAR),
        ("is it correct", Intent.UNCLEAR),
        ("yes but change the amount", Intent.UNCLEAR),
        ("don't cancel", Intent.UNCLEAR),
    ],
)
def test_readback_replies(reply, expected):
    """Was: 'not correct', 'I'm not sure' and 'yes no' all confirmed."""
    assert keyword_intent(reply, "READBACK_PLAYED").intent == expected


async def test_a_negated_reply_cancels_rather_than_confirms(services):
    o = services["orchestrator"]
    c = make_customer(services)
    await o.process_text(c.ctx, REQUEST)
    events = await o.process_text(c.ctx, "no that is not correct")
    assert states(events) == [TransferState.CANCELLED.value]


# ---------------------------------------------------------------------------
# 4. Expiry follows the fingerprint window
# ---------------------------------------------------------------------------


async def test_late_yes_does_not_expire_during_the_fingerprint_prompt(services):
    o = services["orchestrator"]
    c = make_customer(services)
    await o.process_text(c.ctx, REQUEST)
    with services["session_factory"]() as db:
        t = db.scalars(select(Transfer)).first()
        t.expires_at = utcnow() + timedelta(seconds=3)  # yes said at the end of the window
        db.commit()
    await o.process_text(c.ctx, "yes")
    with services["session_factory"]() as db:
        t = db.scalars(select(Transfer)).first()
        assert t.state == TransferState.AWAITING_BIOMETRIC.value
        assert t.expires_at >= t.approval_expires_at


# ---------------------------------------------------------------------------
# 5. Rejected approvals are audited and counted across reconnects
# ---------------------------------------------------------------------------


async def test_rejected_approval_is_in_the_audit_log(services):
    o = services["orchestrator"]
    c = make_customer(services)
    await o.process_text(c.ctx, REQUEST)
    await o.process_text(c.ctx, "yes")
    await o.handle_approval(c.ctx, {"id": "forged"}, dev=False)
    assert "approval.rejected" in audit_events(services)
    assert services["audit"].verify(services["session_factory"]()).get("ok") is True


async def test_failed_reads_are_not_reset_by_reconnecting(services):
    o = services["orchestrator"]
    c = make_customer(services)
    await o.process_text(c.ctx, REQUEST)
    await o.process_text(c.ctx, "yes")
    await o.handle_approval(c.ctx, {"id": "forged"}, dev=False)
    await o.handle_approval(c.ctx, {"id": "forged"}, dev=False)
    ctx2 = new_ctx(services, c)
    await o.start_events(ctx2)
    events = await o.handle_approval(ctx2, {"id": "forged"}, dev=False)
    assert states(events) == [TransferState.CANCELLED.value]


# ---------------------------------------------------------------------------
# 6. Reconnect resumes; one transfer in flight per customer
# ---------------------------------------------------------------------------


async def test_reconnect_resumes_the_fingerprint_approval(services):
    o = services["orchestrator"]
    c = make_customer(services)
    await o.process_text(c.ctx, REQUEST)
    await o.process_text(c.ctx, "yes")
    ctx2 = new_ctx(services, c)
    events = await o.start_events(ctx2)
    assert any(e["type"] == "approval.request" for e in events)
    done = await o.handle_approval(ctx2, None, dev=True)
    assert states(done) == [TransferState.SETTLED.value]


async def test_reconnect_resumes_the_readback(services):
    o = services["orchestrator"]
    c = make_customer(services)
    await o.process_text(c.ctx, REQUEST)
    events = await o.start_events(new_ctx(services, c))
    assert prompts_of(events)[-1]["text"].startswith("Welcome back")


async def test_no_second_draft_while_one_is_awaiting_approval(services):
    o = services["orchestrator"]
    c = make_customer(services)
    await o.process_text(c.ctx, REQUEST)
    await o.process_text(c.ctx, "yes")
    ctx2 = new_ctx(services, c)
    await o.process_text(ctx2, "Send two thousand naira to Access 0690000031")
    with services["session_factory"]() as db:
        assert len(db.scalars(select(Transfer)).all()) == 1


async def test_reconciler_resolves_an_unknown_outcome_with_nobody_connected(services):
    o = services["orchestrator"]
    transfers = services["transfers"]
    bank = services["bank"]
    c = make_customer(services)
    await o.process_text(c.ctx, REQUEST)
    await o.process_text(c.ctx, "yes")
    bank.set_mode("unavailable")
    events = await o.handle_approval(c.ctx, None, dev=True)
    assert states(events) == [TransferState.PENDING_UNKNOWN.value]
    c.ctx.closed = True  # customer walked away

    bank.set_mode("normal")
    with services["session_factory"]() as db:
        t = db.scalars(select(Transfer)).first()
        t.submitted_at = utcnow() - timedelta(seconds=120)
        db.commit()
    changed = await transfers.reconcile(stale_after_s=0, resubmit_after_s=60)
    assert [t.state for t in changed] == [TransferState.SETTLED.value]
    with services["session_factory"]() as db:
        assert len(db.scalars(select(BankTransfer)).all()) == 1  # paid exactly once


async def test_reconciler_expires_abandoned_drafts(services):
    o = services["orchestrator"]
    c = make_customer(services)
    await o.process_text(c.ctx, REQUEST)
    with services["session_factory"]() as db:
        t = db.scalars(select(Transfer)).first()
        t.expires_at = utcnow() - timedelta(seconds=1)
        db.commit()
    changed = await services["transfers"].reconcile()
    assert [t.state for t in changed] == [TransferState.EXPIRED.value]


async def test_finishing_an_already_settled_transfer_is_harmless(services):
    """Was: a late bank reply after the reconciler raised TransitionError."""
    o = services["orchestrator"]
    transfers = services["transfers"]
    c = make_customer(services)
    await o.process_text(c.ctx, REQUEST)
    await o.process_text(c.ctx, "yes")
    done = await o.handle_approval(c.ctx, None, dev=True)
    tid = done[0]["transfer_id"]
    status = await services["bank"].get_transfer_status(idempotency_key=transfers.get(tid).idempotency_key)
    assert transfers._finish_submission(tid, status).state == TransferState.SETTLED.value


# ---------------------------------------------------------------------------
# 7. One failing turn does not end the session or misreport money
# ---------------------------------------------------------------------------


def _ws_customer(client):
    data = client.post("/dev/devices/register", json={"display_name": "Fix Test", "language": "en"}).json()
    token = data["device_token"]
    consent = client.post(
        "/consents",
        json={"wording_version": "v1", "language": "en"},
        headers={"Authorization": f"Bearer {token}"},
    ).json()
    return token, consent["consent_id"]


def _drain_until(ws, kind: str, limit: int = 20) -> list[dict]:
    seen = []
    for _ in range(limit):
        event = ws.receive_json()
        seen.append(event)
        if event.get("type") == kind:
            return seen
    raise AssertionError(f"no {kind} in {seen}")


def test_an_exception_in_a_turn_keeps_the_socket_open(client):
    token, consent_id = _ws_customer(client)
    orchestrator = client.app.state.orchestrator

    async def boom(*args, **kwargs):
        raise RuntimeError("unexpected")

    with client.websocket_connect("/ws") as ws:
        ws.send_json({"type": "session.start", "device_token": token, "consent_id": consent_id})
        _drain_until(ws, "listening")
        original = orchestrator.process_audio
        orchestrator.process_audio = boom
        try:
            ws.send_json({"type": "utterance.text", "text": "hello", "final": True})
            events = _drain_until(ws, "listening")
        finally:
            orchestrator.process_audio = original
        assert any(e.get("prompt_id") == "error_generic" for e in events if e["type"] == "error")
        ws.send_json({"type": "ping"})
        assert ws.receive_json()["type"] == "pong"


def test_an_error_after_approval_never_says_money_did_not_move(services):
    o = services["orchestrator"]
    c = make_customer(services)
    asyncio.run(o.process_text(c.ctx, REQUEST))
    asyncio.run(o.process_text(c.ctx, "yes"))
    services["bank"].set_mode("unavailable")
    asyncio.run(o.handle_approval(c.ctx, None, dev=True))
    events = o.safe_error_events(c.ctx)
    ids = [e["id"] for e in prompts_of(events)]
    assert ids == ["error_after_submit"]


def test_expired_session_is_closed(client):
    token, consent_id = _ws_customer(client)
    with client.websocket_connect("/ws") as ws:
        ws.send_json({"type": "session.start", "device_token": token, "consent_id": consent_id})
        ready = _drain_until(ws, "session.ready")[-1]
        _drain_until(ws, "listening")
        from avenza.models import Session as SessionModel

        with client.app.state.session_factory() as db:
            db.get(SessionModel, ready["session_id"]).expires_at = utcnow() - timedelta(seconds=1)
            db.commit()
        ws.send_json({"type": "ping"})
        events = _drain_until(ws, "prompt.play")
        assert events[-1]["id"] == "session_expired"


# ---------------------------------------------------------------------------
# 8. Parsers
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text,kobo",
    [
        ("goma sha biyar naira", 1_500),  # Hausa 15; was 45
        ("iri na ise naira", 1_500),  # Igbo 15; was 45
        ("ogorun un naira", 10_000),  # Yoruba 100; was 200
        ("ẹgbẹ̀rún márùn-ún naira", 500_000),  # Yoruba 5,000; was 5,005
        ("egberun marun naira", 500_000),
        ("five thousand naira", 500_000),
    ],
)
def test_multiword_numerals_are_counted_once(text, kobo):
    assert parse_amount(text).kobo == kobo


@pytest.mark.parametrize("text", ["send $50 to GTBank 0123456789", "send £20 to GTBank 0123456789", "send €5 to UBA 2033445566"])
def test_currency_symbols_are_rejected_not_read_as_naira(text):
    """Was: '$50' was read as fifty naira."""
    assert extract_transfer_fields(text).amount_error == "unsupported_currency"


def test_ai_parser_rejects_foreign_currency_and_reads_plain_yoruba():
    from avenza_ai.parsing.amount import AmountStatus
    from avenza_ai.parsing.amount import parse_amount as ai_parse

    assert ai_parse("send 50 dollars").status is AmountStatus.UNSUPPORTED_CURRENCY
    assert ai_parse("egberun marun naira", languages=("yo",)).kobo == 500_000


@pytest.mark.parametrize(
    "text,hint",
    [
        ("send 5000 naira to Aisha on GTBank 0123456789", "aisha"),
        ("send 5000 naira to Aisha Bello GTBank 0123456789", "aisha bello"),
        ("send 5000 naira to my mum on GTBank 0123456789", None),
        ("send 5000 naira to account 0123456789 at first bank", None),
        ("send 3000 naira to UBA 2033445566 for rent", None),
        ("transfer 2000 naira to zero one two three four five six seven eight nine gtbank", None),
    ],
)
def test_recipient_hint_is_a_name_or_nothing(text, hint):
    assert extract_recipient_hint(text) == hint


# ---------------------------------------------------------------------------
# 9. Admin endpoints are not open to the demo Wi-Fi
# ---------------------------------------------------------------------------


def test_admin_routes_refuse_remote_callers_without_a_token(settings):
    with TestClient(create_app(settings), client=("192.168.1.40", 5000)) as remote:
        assert remote.get("/audit/recent").status_code == 403
        assert remote.post("/dev/bank/mode", json={"mode": "fail"}).status_code == 403
    with TestClient(create_app(settings), client=("127.0.0.1", 5000)) as local:
        assert local.get("/audit/recent").status_code == 200


def test_admin_token_opens_admin_routes_remotely():
    app = create_app(Settings().for_test(admin_token="t0ken"))
    with TestClient(app, client=("192.168.1.40", 5000)) as remote:
        assert remote.get("/audit/recent").status_code == 403
        assert remote.get("/audit/recent", headers={"X-Admin-Token": "t0ken"}).status_code == 200


# ---------------------------------------------------------------------------
# 10. Speech providers: errors, TTS, live STT, latency
# ---------------------------------------------------------------------------


class BrokenSTT(STTProvider):
    name = "broken"
    simulated = False

    async def transcribe(self, pcm, sample_rate, language_hint="en", provided_text=None):
        return TranscriptResult("", 0.0, self.name, error="ai_stt_error:ConnectionError")


async def test_stt_failure_is_reported_as_unavailable_not_silence(services):
    o = services["orchestrator"]
    o.stt = BrokenSTT()
    c = make_customer(services)
    events = await o.process_audio(c.ctx, b"\x00\x00" * 1600, 16000)
    assert [e["id"] for e in prompts_of(events)] == ["error_stt"]


class FakeTTS:
    name = "fake"
    simulated = False

    def __init__(self):
        self.calls = 0

    async def synthesize(self, text, voice="", language="en"):
        self.calls += 1
        return AudioResult(b"\x01\x00" * 10, 24000, self.name, ttfa_ms=42, text=text)


async def test_tts_audio_is_attached_to_prompts_and_cached(services):
    o = services["orchestrator"]
    o.tts = FakeTTS()
    c = make_customer(services)
    events = await o.render_audio(c.ctx, await o.process_text(c.ctx, REQUEST))
    readback = prompts_of(events)[-1]
    assert readback["audio"]["encoding"] == "pcm_s16le"
    assert readback["audio"]["sample_rate"] == 24000
    calls = o.tts.calls
    await o.render_audio(c.ctx, [dict(readback, audio=None)])
    assert o.tts.calls == calls  # cached


async def test_simulated_tts_leaves_prompts_for_the_device_voice(services):
    o = services["orchestrator"]
    c = make_customer(services)
    events = await o.render_audio(c.ctx, await o.process_text(c.ctx, REQUEST))
    assert all("audio" not in e for e in prompts_of(events))


class LiveStream(STTStream):
    def __init__(self):
        self.on_partial = None
        self.frames = 0

    async def push(self, pcm):
        self.frames += 1
        if self.on_partial:
            await self.on_partial("send five thousand")

    async def end(self):
        return TranscriptResult(REQUEST, 0.95, "live", ttfp_ms=120, final_ms=200)


class LiveSTT(STTProvider):
    name = "live"
    simulated = False

    def __init__(self):
        self.streams: list[LiveStream] = []

    async def transcribe(self, *args, **kwargs):
        raise AssertionError("batch path must not run when the live stream works")

    def stream(self, language_hint="en", sample_rate=16000):
        stream = LiveStream()
        self.streams.append(stream)
        return stream


def test_live_stt_streams_partials_and_logs_latency(tmp_path):
    log = tmp_path / "latency.jsonl"
    app = create_app(Settings().for_test(latency_log=str(log)))
    stt = LiveSTT()
    app.state.stt = stt
    app.state.orchestrator.stt = stt
    with TestClient(app) as client:
        token, consent_id = _ws_customer(client)
        with client.websocket_connect("/ws") as ws:
            ws.send_json({"type": "session.start", "device_token": token, "consent_id": consent_id})
            _drain_until(ws, "listening")
            ws.send_json({"type": "utterance.start", "sample_rate": 16000})
            ws.send_bytes(b"\x00\x00" * 1600)
            assert ws.receive_json() == {"type": "transcript.partial", "text": "send five thousand"}
            ws.send_json({"type": "utterance.end", "vad_ms": 800})
            events = _drain_until(ws, "listening")
    final = next(e for e in events if e["type"] == "transcript.final")
    assert final["text"] == REQUEST
    assert stt.streams[0].frames == 1
    record = json.loads(log.read_text().splitlines()[-1])
    assert record["vad_ms"] == 800
    assert record["stt_ttfp_ms"] == 120
    assert "name_enquiry_ms" in record and "reply_ms" in record and "intent_ms" in record


def test_latency_report_summarises_the_log(tmp_path, capsys):
    from scripts.latency_report import main

    log = tmp_path / "latency.jsonl"
    log.write_text(
        "\n".join(json.dumps({"provider": "ai:deepgram", "reply_ms": ms, "stt_final_ms": ms // 2}) for ms in (900, 1500, 2100))
    )
    assert main([str(log)]) == 0
    out = capsys.readouterr().out
    assert "median 1500 ms" in out


# ---------------------------------------------------------------------------
# 11. History uses the bank's ledger and receipts
# ---------------------------------------------------------------------------


async def test_history_includes_bank_payments_avenza_did_not_draft(services):
    o = services["orchestrator"]
    c = make_customer(services)
    await services["bank"].create_transfer(
        idempotency_key="outside_avenza",
        customer_ref=c.user_id,
        amount_kobo=250_000,
        bank_code="044",
        account_number="0690000031",
        recipient_name="Chinedu Okafor",
        nonce="x",
    )
    events = await o.process_text(c.ctx, "show my transactions today")
    data = next(e for e in events if e["type"] == "history.data")
    assert data["bank_history"] is True
    assert [t["source"] for t in data["transactions"]] == ["bank"]
    assert "Chinedu Okafor" in prompts_of(events)[-1]["text"]


async def test_spoken_receipt_comes_from_the_bank(services):
    o = services["orchestrator"]
    c = make_customer(services)
    await o.process_text(c.ctx, REQUEST)
    await o.process_text(c.ctx, "yes")
    await o.handle_approval(c.ctx, None, dev=True)
    events = await o.process_text(c.ctx, "read my last receipt")
    text = prompts_of(events)[-1]["text"]
    assert text.startswith("Receipt for ₦5,000.00 to Aisha Bello")
    assert "Reference AVZ" in text


# ---------------------------------------------------------------------------
# 12. Recorded prompt clips are never used for prompts with variables
# ---------------------------------------------------------------------------


def test_recorded_clip_is_not_used_for_a_readback(tmp_path):
    (tmp_path / "en-readback.wav").write_bytes(b"RIFF")
    (tmp_path / "en-cancelled.wav").write_bytes(b"RIFF")
    library = PromptLibrary(tmp_path)
    assert library.render("readback", recipient="A").audio_url is None
    assert library.render("cancelled").audio_url == "/prompts/en-cancelled.wav"


# ---------------------------------------------------------------------------
# 13. The frontend app is served on the API's origin
# ---------------------------------------------------------------------------


def _frontend_client(tmp_path):
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<html>frontend app</html>")
    (dist / "assets" / "app-1a2b3c.js").write_text("console.log(1)")
    (dist / "sw.js").write_text("self.addEventListener('fetch', () => {})")
    (tmp_path / "secret.txt").write_text("outside dist")
    return TestClient(create_app(Settings().for_test(frontend_dist=dist)))


def test_frontend_is_served_at_root_with_client_side_routes(tmp_path):
    with _frontend_client(tmp_path) as client:
        assert client.get("/").text == "<html>frontend app</html>"
        refreshed = client.get("/settings")  # a client-side route
        assert refreshed.text == "<html>frontend app</html>"
        assert refreshed.headers["cache-control"] == "no-cache"
        asset = client.get("/assets/app-1a2b3c.js")
        assert asset.text == "console.log(1)" and "immutable" in asset.headers["cache-control"]
        assert client.get("/sw.js").headers["content-type"].startswith(("application/javascript", "text/javascript"))


def test_frontend_never_shadows_the_api(tmp_path):
    with _frontend_client(tmp_path) as client:
        assert client.get("/healthz").json() == {"ok": True}
        assert client.get("/config").status_code == 200
        assert client.get("/me").status_code == 401  # the API answered, not index.html
        unknown_api = client.get("/transfers/does/not/exist")
        assert unknown_api.status_code == 404 and unknown_api.headers["content-type"].startswith("application/json")
        assert client.get("/assets/old-hash.js").status_code == 404  # missing file: not HTML
        assert client.get("/../secret.txt").status_code in {404, 200} and "outside dist" not in client.get("/../secret.txt").text
        assert "outside dist" not in client.get("/%2e%2e/secret.txt").text


def test_legacy_pwa_is_served_without_a_frontend_build(tmp_path):
    with TestClient(create_app(Settings().for_test(frontend_dist=tmp_path / "missing"))) as client:
        assert client.get("/").status_code in {200, 404}
        assert client.get("/sw.js").status_code == 200
