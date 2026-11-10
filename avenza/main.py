from __future__ import annotations

import asyncio
import hashlib
import hmac
import ipaddress
import json
from pathlib import Path
import logging
import time
from collections import OrderedDict
from contextlib import asynccontextmanager
from datetime import timedelta
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlalchemy import select, text

from . import __version__
from .ai import build_ai
from .audit import AuditService
from .bank import BANK_NAMES, DEMO_ACCOUNTS, BankError, MockBank, build_bank, seed_mock_bank
from .config import Settings, load_settings
from .db import init_db, make_engine, make_session_factory
from .intent import IntentClassifier
from .models import AuditLog, Device, Transfer, User
from .money import format_naira
from .orchestrator import TurnOrchestrator
from .prompts import PROMPTS, PromptLibrary
from .providers import build_stt, build_tts
from .security import ApprovalError, WebAuthnService
from .services import DeviceService, SessionError, SessionService, TransferLocked, TransferNotFound, TransferService
from .timeutil import iso, parse_iso, utcnow
from .ws import websocket_endpoint

logger = logging.getLogger("avenza.api")


class ConsentIn(BaseModel):
    wording_version: str = Field(min_length=1, max_length=32)
    language: str = Field(default="en", max_length=16)


class RegisterOptionsIn(BaseModel):
    display_name: str = Field(default="", max_length=200)
    language: str = Field(default="en", max_length=16)
    user_id: str | None = None
    device_token: str | None = None
    # The customer's own bank account (the debit account) in sandbox mode.
    source_account: str | None = Field(default=None, pattern=r"^\d{10}$")


class SourceAccountIn(BaseModel):
    account_number: str = Field(pattern=r"^\d{10}$")


class WebhookRegisterIn(BaseModel):
    url: str = Field(min_length=8, max_length=500)


# Team-owned accounts in the Forge sandbox (guide §5.4). Synthetic data.
SANDBOX_SOURCE_ACCOUNTS = [
    {"account_number": "0123456789", "account_name": "Adaeze Chiamaka Okonkwo", "tier": "3"},
    {"account_number": "0123456790", "account_name": "Babatunde Olumide Adeyemi", "tier": "3"},
    {"account_number": "0123456791", "account_name": "Musa Ibrahim Abdullahi", "tier": "2"},
    {"account_number": "0123456792", "account_name": "Efosa Godwin Osagie", "tier": "1"},
    {"account_number": "0123456793", "account_name": "Mama Nkechi Provisions Ltd", "tier": "corporate"},
]
# Beneficiaries to say in a demo (guide §5.4), as (internal bank code, account, name).
SANDBOX_BENEFICIARIES = [
    ("000014", "0987654321", "Ngozi Adaobi Eze"),
    ("000014", "0987654322", "Aisha Hauwa Bello"),
    ("058", "0123987001", "Chukwuemeka Ifeanyi Nwosu"),
    ("057", "0123987002", "Funmilayo Abiola Ogunleye"),
    ("011", "0123987003", "Zainab Halima Yusuf"),
    ("033", "0123987004", "Tamunotonye Briggs"),
    ("999992", "8031234506", "Ifeoluwa Grace Adebayo"),
    ("50515", "8051234507", "Iya Bisi Foods Enterprises"),
]


class RegisterVerifyIn(BaseModel):
    challenge_id: str
    credential: dict


class LockUnlockIn(BaseModel):
    challenge_id: str
    credential: dict


class BankModeIn(BaseModel):
    mode: str
    delay_ms: int | None = Field(default=None, ge=0, le=60_000)


class Auth:
    def __init__(self, device: Device, user: User):
        self.device = device
        self.user = user


def _extract_token(authorization: str | None, x_device_token: str | None) -> str | None:
    if x_device_token:
        return x_device_token.strip()
    if authorization and authorization.lower().startswith("bearer "):
        return authorization[7:].strip()
    return None


_LOCAL_HOSTS = {"localhost", "testclient"}


# First path segments that belong to the API. An unknown path under one of
# these is a 404 (JSON), never the frontend's index.html.
API_PREFIXES = {
    "api", "ws", "hooks", "dev", "audit", "me", "transfers", "devices", "consents",
    "locks", "health", "healthz", "config", "prompts", "static", "docs", "redoc", "openapi.json",
}


def _mount_frontend(app: FastAPI, dist: Path) -> None:
    """Serve a built single-page app (Vite) from ``dist`` on the API's origin.

    Same origin as the API means the passkey RP ID, CORS and the WebSocket
    origin need no change. Registered last, so API routes always win:

    * a real file in ``dist`` is served (hashed assets cached for a year);
    * any other GET outside the API prefixes gets ``index.html`` (no-cache),
      so refreshing a client-side route like /settings works.
    """
    root = dist.resolve()

    @app.get("/{path:path}", include_in_schema=False)
    def frontend_app(path: str):
        first = path.split("/", 1)[0]
        if first in API_PREFIXES:
            return JSONResponse({"detail": "Not Found"}, status_code=404)
        if path:
            candidate = (root / path).resolve()
            if candidate.is_file() and root in candidate.parents:
                headers = (
                    {"Cache-Control": "public, max-age=31536000, immutable"}
                    if candidate.parent.name == "assets"
                    else {"Cache-Control": "no-cache"}
                )
                return FileResponse(candidate, headers=headers)
            if "." in path.rsplit("/", 1)[-1]:
                # A missing file (e.g. an old asset hash): a real 404, not HTML.
                return JSONResponse({"detail": "Not Found"}, status_code=404)
        return FileResponse(root / "index.html", headers={"Cache-Control": "no-cache"})


def passkey_address_problem(settings: Settings, origin: str | None, host: str | None) -> str | None:
    """Why a passkey ceremony from this address cannot work, or None.

    The browser only allows a passkey whose RP ID is the page's host (or a parent
    domain of it), and the server only accepts origins listed in WEBAUTHN_ORIGIN.
    """
    from urllib.parse import urlsplit

    if not origin:
        return None  # not a browser page (scripts, tests): nothing to check
    page = urlsplit(origin).hostname or (host or "").split(":")[0]
    if not page:
        return None
    rp_id = settings.webauthn_rp_id.strip().lower()
    page = page.lower()
    allowed = [o.strip().rstrip("/") for o in settings.webauthn_origin.split(",") if o.strip()]
    if not (page == rp_id or page.endswith("." + rp_id)):
        return (
            f"Avenza was opened at {page}, but WEBAUTHN_RP_ID is {rp_id or '(empty)'}. "
            f"Set WEBAUTHN_RP_ID={page} and WEBAUTHN_ORIGIN=https://{page} in .env, then restart Avenza."
        )
    if origin and origin.rstrip("/") not in allowed:
        return (
            f"Avenza was opened at {origin}, which is not in WEBAUTHN_ORIGIN ({', '.join(allowed) or 'empty'}). "
            f"Set WEBAUTHN_ORIGIN={origin.rstrip('/')} in .env, then restart Avenza."
        )
    return None


def verify_forge_signature(raw: bytes, timestamp: str, signature: str, secret: str, now: float | None = None) -> bool:
    """Guide §5.6: sha256=<hex HMAC-SHA256 of "{timestamp}.{raw_body}">, max 5 minutes old."""
    try:
        ts = int(timestamp)
    except (TypeError, ValueError):
        return False
    if abs((now if now is not None else time.time()) - ts) > 300:
        return False
    mac = hmac.new(secret.encode(), timestamp.encode() + b"." + raw, hashlib.sha256).hexdigest()
    return hmac.compare_digest("sha256=" + mac, signature or "")


def _is_local(request: Request) -> bool:
    host = request.client.host if request.client else ""
    if host in _LOCAL_HOSTS:
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or load_settings()
    logging.basicConfig(
        level=getattr(logging, settings.log_level, logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    engine = make_engine(settings.database_url)
    init_db(engine)
    session_factory = make_session_factory(engine)
    if settings.bank_mode == "mock":
        seed_mock_bank(session_factory)

    audit = AuditService(session_factory, engine.dialect.name)
    security = WebAuthnService(settings)
    prompts = PromptLibrary(settings.prompt_dir)
    stt = build_stt(settings)
    tts = build_tts(settings)
    ai = build_ai(settings)
    intent = ai if ai is not None else IntentClassifier(settings)
    bank = build_bank(settings, session_factory)
    devices = DeviceService(session_factory, audit, security, settings)
    sessions = SessionService(session_factory, audit, settings)
    transfers = TransferService(session_factory, audit, bank, security, prompts, settings)
    orchestrator = TurnOrchestrator(
        settings, prompts, stt, tts, intent, bank, transfers, sessions, ai=ai
    )

    settings.web_dir.mkdir(parents=True, exist_ok=True)
    settings.prompt_dir.mkdir(parents=True, exist_ok=True)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        logger.info(
            "Avenza %s starting env=%s bank=%s stt=%s tts=%s db=%s",
            __version__,
            settings.env,
            settings.bank_mode,
            stt.name,
            tts.name,
            engine.dialect.name,
        )
        if settings.allow_dev_approval and not settings.is_production:
            logger.warning(
                "ALLOW_DEV_APPROVAL is enabled: fingerprint approval can be bypassed in tests/demo only"
            )
        from urllib.parse import urlsplit

        for _origin in [o.strip() for o in settings.webauthn_origin.split(",") if o.strip()]:
            _host = (urlsplit(_origin).hostname or "").lower()
            _rp = settings.webauthn_rp_id.strip().lower()
            if _host and not (_host == _rp or _host.endswith("." + _rp)):
                logger.warning(
                    "WEBAUTHN_ORIGIN %s does not match WEBAUTHN_RP_ID %s: fingerprint registration from it will fail",
                    _origin, settings.webauthn_rp_id,
                )
        if not settings.admin_token:
            logger.warning(
                "ADMIN_TOKEN is not set: /audit and /dev/bank endpoints only answer requests from this machine"
            )
        reconciler: asyncio.Task | None = None
        if settings.reconcile_interval_s > 0:
            reconciler = asyncio.create_task(_reconcile_loop())
        # Fixed prompts are synthesised in the background; startup does not wait.
        prewarm = asyncio.create_task(orchestrator.prewarm_tts())
        keepwarm = None
        if settings.yarngpt_modal_keepwarm_s > 0 and hasattr(tts, "keep_warm"):
            keepwarm = asyncio.create_task(tts.keep_warm(settings.yarngpt_modal_keepwarm_s))
        try:
            yield
        finally:
            prewarm.cancel()
            if keepwarm is not None:
                keepwarm.cancel()
            if reconciler is not None:
                reconciler.cancel()
                try:
                    await reconciler
                except (asyncio.CancelledError, Exception):
                    pass
            engine.dispose()

    async def _reconcile_loop() -> None:
        """Resolve unknown bank outcomes and expire drafts with nobody connected."""
        while True:
            await asyncio.sleep(settings.reconcile_interval_s)
            try:
                changed = await transfers.reconcile(
                    stale_after_s=settings.reconcile_stale_s,
                    resubmit_after_s=settings.reconcile_resubmit_s,
                    reversal_watch_s=0 if settings.bank_is_simulated else 180,
                )
                if changed:
                    logger.info(
                        "reconciled %s transfer(s): %s",
                        len(changed),
                        ", ".join(f"{t.id}={t.state}" for t in changed),
                    )
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("reconciliation pass failed")

    app = FastAPI(
        title="Avenza API",
        version=__version__,
        description=(
            "Voice banking layer. Voice only drafts a request; a WebAuthn fingerprint "
            "approval verified by the backend is required before submission. "
            "Avenza holds no funds."
        ),
        lifespan=lifespan,
    )
    app.state.settings = settings
    app.state.engine = engine
    app.state.session_factory = session_factory
    app.state.audit = audit
    app.state.security = security
    app.state.prompts = prompts
    app.state.stt = stt
    app.state.tts = tts
    app.state.intent = intent
    app.state.ai = ai
    app.state.bank = bank
    app.state.devices = devices
    app.state.sessions = sessions
    app.state.transfers = transfers
    app.state.orchestrator = orchestrator

    origins = ["*"] if not settings.is_production else [
        o.strip() for o in settings.webauthn_origin.split(",") if o.strip()
    ]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    def get_auth(
        authorization: str | None = Header(default=None),
        x_device_token: str | None = Header(default=None, alias="X-Device-Token"),
    ) -> Auth:
        token = _extract_token(authorization, x_device_token)
        auth = devices.authenticate(token)
        if auth is None:
            raise HTTPException(status_code=401, detail="device token required or invalid")
        return Auth(*auth)

    def require_admin(
        request: Request, x_admin_token: str | None = Header(default=None, alias="X-Admin-Token")
    ) -> None:
        if settings.admin_token:
            if x_admin_token != settings.admin_token:
                raise HTTPException(status_code=403, detail="admin token required")
            return
        # No token configured: dev tools answer only on this machine, never to
        # other phones and laptops on the demo Wi-Fi.
        if settings.dev_tools and not settings.is_production and _is_local(request):
            return
        raise HTTPException(status_code=403, detail="admin token required (set ADMIN_TOKEN)")

    # ------------------------------------------------------------------
    # Health / config
    # ------------------------------------------------------------------
    @app.get("/healthz")
    def healthz():
        """Cheap readiness probe for Kubernetes: no bank or model calls."""
        try:
            with session_factory() as db:
                db.execute(text("SELECT 1"))
        except Exception:
            return JSONResponse({"ok": False}, status_code=503)
        return {"ok": True}

    @app.get("/health")
    def health():
        db_ok = True
        try:
            with session_factory() as db:
                db.execute(text("SELECT 1"))
        except Exception:
            db_ok = False
        bank_ready = bool(getattr(bank, "ready", True))
        return {
            "status": "ok" if db_ok and bank_ready else "degraded",
            "app": settings.app_name,
            "version": __version__,
            "time": iso(utcnow()),
            "env": settings.env,
            "database": {"dialect": engine.dialect.name, "ok": db_ok},
            "bank": {
                "mode": settings.bank_mode,
                "simulated": settings.bank_is_simulated,
                "ready": bank_ready,
            },
            "stt": {"provider": stt.name, "simulated": stt.simulated},
            "tts": {"provider": tts.name, "simulated": tts.simulated},
            "llm": {
                "enabled": settings.llm_enabled,
                "configured": settings.llm_configured,
                "provider": settings.llm_provider,
                "model": settings.llm_model if settings.llm_configured else None,
                "amount_authority": "deterministic_parser_only",
            },
            "ai": ai.status() if ai is not None else {"enabled": False},
            "webauthn": {
                "rp_id": settings.webauthn_rp_id,
                "origin": settings.webauthn_origin,
                "secure_context_required": True,
            },
            "dev_tools": settings.dev_tools,
            "dev_approval_allowed": security.dev_approval_allowed(),
            "limits": {
                "max_amount_kobo": settings.max_amount_kobo,
                "max_amount_display": format_naira(settings.max_amount_kobo),
                "draft_ttl_s": settings.draft_ttl_s,
                "approval_ttl_s": settings.approval_ttl_s,
            },
            "languages": {
                "verified": prompts.verified_languages(),
                "available_unverified": [k for k in PROMPTS.keys() if k not in prompts.verified_languages()],
            },
        }

    @app.get("/config")
    def public_config():
        demo_accounts = []
        if settings.bank_mode == "sandbox":
            demo_accounts = [
                {
                    "bank_code": code,
                    "bank_name": BANK_NAMES.get(code, code),
                    "account_number": number,
                    "account_name": name,
                }
                for code, number, name in SANDBOX_BENEFICIARIES
            ]
        elif settings.bank_mode == "mock" and settings.dev_tools:
            demo_accounts = [
                {
                    "bank_code": code,
                    "bank_name": BANK_NAMES.get(code, code),
                    "account_number": number,
                    "account_name": name,
                }
                for code, number, name in DEMO_ACCOUNTS
            ]
        return {
            "app": settings.app_name,
            "version": __version__,
            "bank": {"mode": settings.bank_mode, "simulated": settings.bank_is_simulated},
            "webauthn": {"rp_id": settings.webauthn_rp_id, "origin": settings.webauthn_origin},
            "dev_approval_allowed": security.dev_approval_allowed(),
            "allow_text_utterance": settings.allow_text_utterance,
            "limits": {
                "max_amount_display": format_naira(settings.max_amount_kobo),
                "large_amount_display": format_naira(settings.large_amount_threshold_kobo),
                "new_recipient_hold_s": settings.new_recipient_hold_s,
            },
            "languages": {
                "verified": prompts.verified_languages(),
                "available": list(PROMPTS.keys()),
            },
            "demo_accounts": demo_accounts,
            "source_accounts": SANDBOX_SOURCE_ACCOUNTS if settings.bank_mode == "sandbox" else [],
        }

    @app.get("/ai/status")
    def ai_status():
        return {
            "ai": ai.status() if ai is not None else {"enabled": False},
            "amount_authority": "backend_deterministic_parser",
            "approval": "webauthn_backend_verified_only",
        }

    @app.get("/prompts")
    def all_prompts():
        return {
            "verified_languages": prompts.verified_languages(),
            "prompts": PROMPTS,
        }

    # ------------------------------------------------------------------
    # Enrolment and consent
    # ------------------------------------------------------------------
    @app.post("/devices/register/options")
    def register_options(body: RegisterOptionsIn, request: Request):
        # The phone opened Avenza at one address but the passkey settings name another: the browser
        # would refuse before showing the fingerprint prompt. Say exactly what to change instead.
        problem = passkey_address_problem(settings, request.headers.get("origin"), request.headers.get("host"))
        if problem:
            logger.warning("fingerprint registration refused: %s", problem)
            raise HTTPException(status_code=400, detail=problem)
        if not body.user_id and not body.display_name.strip():
            raise HTTPException(status_code=400, detail="display_name is required for a new customer")
        language = body.language if body.language in PROMPTS else "en"
        try:
            return devices.begin_registration(
                display_name=body.display_name,
                language=language,
                user_id=body.user_id,
                device_token=body.device_token,
            )
        except ApprovalError as exc:
            raise HTTPException(status_code=400, detail=str(exc))

    @app.post("/devices/register/verify")
    def register_verify(body: RegisterVerifyIn, request: Request):
        try:
            result = devices.verify_registration(
                challenge_id=body.challenge_id,
                credential=body.credential,
                ip=request.client.host if request.client else "",
                user_agent=request.headers.get("user-agent", ""),
            )
            return result
        except ApprovalError as exc:
            raise HTTPException(status_code=400, detail=str(exc))

    @app.post("/dev/devices/register")
    def dev_register(body: RegisterOptionsIn):
        """Developer-only enrolment used by the PWA demo and automated tests.

        It creates a device with no WebAuthn public key, so it cannot approve a
        payment unless the separately gated ALLOW_DEV_APPROVAL bypass is on.
        Disabled in production.
        """
        if not devices.dev_tools_allowed():
            raise HTTPException(status_code=403, detail="developer enrolment is disabled")
        language = body.language if body.language in PROMPTS else "en"
        try:
            result = devices.dev_register(
                display_name=body.display_name,
                language=language,
            )
        except ApprovalError as exc:
            raise HTTPException(status_code=403, detail=str(exc))
        if body.source_account:
            _set_source_account(result["user_id"], body.source_account)
        return result

    def _set_source_account(user_id: str, account_number: str) -> None:
        with session_factory() as db:
            user = db.get(User, user_id)
            if user is None:
                raise HTTPException(status_code=404, detail="user not found")
            user.source_account = account_number
            db.commit()
        audit.record_standalone(
            "account.source_set", details={"user_id": user_id, "account_last4": account_number[-4:]}
        )

    @app.post("/consents")
    def record_consent(body: ConsentIn, auth: Auth = Depends(get_auth)):
        consent = devices.record_consent(
            user_id=auth.user.id,
            wording_version=body.wording_version,
            language=body.language if body.language in PROMPTS else "en",
        )
        return {
            "consent_id": consent.id,
            "user_id": consent.user_id,
            "wording_version": consent.wording_version,
            "language": consent.language,
            "timestamp": iso(consent.timestamp),
        }

    @app.get("/me")
    def me(auth: Auth = Depends(get_auth)):
        return {
            "user": {
                "id": auth.user.id,
                "display_name": auth.user.display_name,
                "language": auth.user.language,
                "source_account": transfers.customer_ref_for(auth.user.id)
                if not settings.bank_is_simulated
                else auth.user.source_account,
            },
            "device": {"id": auth.device.id, "credential_id": auth.device.credential_id},
        }

    @app.put("/me/source-account")
    def set_source_account(body: SourceAccountIn, auth: Auth = Depends(get_auth)):
        """Choose which of the team's sandbox accounts this customer pays from."""
        _set_source_account(auth.user.id, body.account_number)
        return {"source_account": body.account_number}

    @app.get("/me/balance")
    async def my_balance(auth: Auth = Depends(get_auth)):
        get_balance = getattr(bank, "get_balance", None)
        if get_balance is None:
            raise HTTPException(status_code=404, detail="balance is not available with the mock bank")
        account = transfers.customer_ref_for(auth.user.id)
        try:
            data = await get_balance(account)
        except BankError as exc:
            raise HTTPException(status_code=502, detail=f"bank: {exc.code}")
        available = data.get("available_kobo")
        return {
            **data,
            "available_display": format_naira(available) if available is not None else None,
        }

    # ------------------------------------------------------------------
    # Transfers / history
    # ------------------------------------------------------------------
    @app.get("/transfers")
    def list_transfers(
        start: str | None = Query(default=None),
        end: str | None = Query(default=None),
        limit: int = Query(default=50, ge=1, le=100),
        auth: Auth = Depends(get_auth),
    ):
        end_dt = parse_iso(end) if end else utcnow()
        start_dt = parse_iso(start) if start else end_dt - timedelta(days=30)
        rows = transfers.history(auth.user.id, start_dt, end_dt, limit)
        return {
            "transactions": [TransferService.summary(r) for r in rows],
            "bank_simulated": settings.bank_is_simulated,
        }

    @app.get("/transfers/{transfer_id}")
    def get_transfer(transfer_id: str, auth: Auth = Depends(get_auth)):
        transfer = transfers.get(transfer_id)
        if transfer.user_id != auth.user.id:
            raise HTTPException(status_code=404, detail="transfer not found")
        data = TransferService.summary(transfer)
        data.update(
            {
                "account_number_masked": "*" * 6 + transfer.account_number[-4:],
                "expires_at": iso(transfer.expires_at),
                "approval_expires_at": iso(transfer.approval_expires_at),
                "confirmations_required": transfer.confirmations_required,
                "confirmations_done": transfer.confirmations_done,
            }
        )
        return data

    @app.get("/transfers/{transfer_id}/receipt")
    async def get_receipt(transfer_id: str, auth: Auth = Depends(get_auth)):
        transfer = transfers.get(transfer_id)
        if transfer.user_id != auth.user.id:
            raise HTTPException(status_code=404, detail="transfer not found")
        if not transfer.bank_reference:
            raise HTTPException(status_code=409, detail="transfer has not been submitted")
        try:
            receipt = await bank.get_receipt(transfer.bank_reference)
        except BankError:
            receipt = None
        except Exception:
            logger.exception("receipt lookup failed")
            raise HTTPException(status_code=502, detail="bank receipt unavailable")
        if receipt is None:
            raise HTTPException(status_code=404, detail="receipt not found")
        receipt["simulated"] = settings.bank_is_simulated
        return receipt

    # ------------------------------------------------------------------
    # Emergency lock
    # ------------------------------------------------------------------
    @app.post("/locks")
    def engage_lock(auth: Auth = Depends(get_auth)):
        lock = transfers.engage_lock(auth.user.id, reason="customer_request")
        return {"locked": True, "lock_id": lock.id, "locked_at": iso(lock.locked_at)}

    @app.get("/locks/status")
    def lock_status(auth: Auth = Depends(get_auth)):
        with session_factory() as db:
            locked = transfers.is_locked(db, auth.user.id)
        return {"locked": locked}

    @app.post("/locks/options")
    def lock_options(auth: Auth = Depends(get_auth)):
        with audit.unit_of_work() as db:
            device = db.get(Device, auth.device.id)
            user = db.get(User, auth.user.id)
            options = security.unlock_options(db, user, device)
            return options

    @app.post("/locks/unlock")
    def unlock(body: LockUnlockIn, auth: Auth = Depends(get_auth)):
        try:
            with audit.unit_of_work() as db:
                device = db.get(Device, auth.device.id)
                security.verify_unlock(db, body.challenge_id, device, body.credential)
                audit.record(
                    db,
                    "lock.unlock_verified",
                    details={"user_id": auth.user.id, "device_id": device.id},
                )
            transfers.mark_unlocked(auth.user.id)
            return {"locked": False}
        except ApprovalError as exc:
            raise HTTPException(status_code=400, detail=str(exc))

    # ------------------------------------------------------------------
    # Audit
    # ------------------------------------------------------------------
    @app.get("/audit/verify")
    def verify_audit(_: None = Depends(require_admin)):
        with session_factory() as db:
            result = audit.verify(db)
        return result

    @app.get("/audit/recent")
    def recent_audit(limit: int = Query(default=50, ge=1, le=500), _: None = Depends(require_admin)):
        with session_factory() as db:
            rows = db.scalars(
                select(AuditLog)
                .order_by(AuditLog.seq.desc())
                .limit(limit)
            ).all()
            return {
                "entries": [
                    {
                        "seq": row.seq,
                        "event": row.event,
                        "transfer_id": row.transfer_id,
                        "session_id": row.session_id,
                        "details": row.details,
                        "previous_hash": row.previous_hash,
                        "row_hash": row.row_hash,
                        "created_at": iso(row.created_at),
                    }
                    for row in rows
                ]
            }

    # ------------------------------------------------------------------
    # Dev/demo bank controls
    # ------------------------------------------------------------------
    @app.post("/dev/bank/mode")
    def set_bank_mode(body: BankModeIn, _: None = Depends(require_admin)):
        if not isinstance(bank, MockBank):
            raise HTTPException(status_code=400, detail="bank mode controls are only available in mock mode")
        try:
            bank.set_mode(body.mode, body.delay_ms)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        audit.record_standalone("dev.bank_mode", details={"mode": body.mode, "delay_ms": body.delay_ms})
        return {"bank": {"mode": body.mode, "delay_ms": body.delay_ms, "simulated": True}}

    @app.get("/dev/bank/accounts")
    def demo_accounts(_: None = Depends(require_admin)):
        if not settings.dev_tools:
            raise HTTPException(status_code=403, detail="dev tools disabled")
        return {
            "accounts": [
                {
                    "bank_code": code,
                    "bank_name": BANK_NAMES.get(code, code),
                    "account_number": number,
                    "account_name": name,
                }
                for code, number, name in DEMO_ACCOUNTS
            ],
            "bank": {"mode": settings.bank_mode, "simulated": settings.bank_is_simulated},
        }

    @app.post("/dev/bank/reset")
    async def sandbox_reset(_: None = Depends(require_admin)):
        """POST /admin/reset on the Xtradot sandbox: the team's opening state."""
        reset = getattr(bank, "admin_reset", None)
        if reset is None:
            raise HTTPException(status_code=400, detail="reset is only available in sandbox mode")
        try:
            data = await reset()
        except BankError as exc:
            raise HTTPException(status_code=502, detail=str(exc))
        audit.record_standalone("dev.sandbox_reset", details={})
        return {"reset": True, "bank": data}

    @app.post("/dev/bank/webhook")
    async def sandbox_register_webhook(body: WebhookRegisterIn, _: None = Depends(require_admin)):
        """Register Avenza's webhook with the sandbox.

        The response contains ``webhook_secret`` exactly once. Store it as the
        FORGE_WEBHOOK_SECRET secret and restart the deployment.
        """
        register = getattr(bank, "register_webhook", None)
        if register is None:
            raise HTTPException(status_code=400, detail="webhooks are only available in sandbox mode")
        try:
            data = await register(body.url)
        except BankError as exc:
            raise HTTPException(status_code=502, detail=str(exc))
        audit.record_standalone("dev.webhook_registered", details={"url": body.url})
        return data

    # ------------------------------------------------------------------
    # Bank webhooks (guide §5.6)
    # ------------------------------------------------------------------
    seen_events: OrderedDict[str, float] = OrderedDict()

    @app.post("/hooks/forge")
    async def forge_webhook(request: Request):
        """Signed Xtradot webhook.

        Verifies ``x-forge-signature`` (HMAC-SHA256 of "{timestamp}.{raw body}"),
        rejects timestamps older than 5 minutes, de-duplicates on ``event_id``
        and answers within the 10 s budget. The event is only a hint: the
        transfer's outcome is always read back from the bank before Avenza
        changes anything.
        """
        secret = settings.forge_webhook_secret
        if not secret:
            raise HTTPException(status_code=503, detail="FORGE_WEBHOOK_SECRET is not configured")
        raw = await request.body()
        timestamp = request.headers.get("x-forge-timestamp", "")
        signature = request.headers.get("x-forge-signature", "")
        if not verify_forge_signature(raw, timestamp, signature, secret):
            raise HTTPException(status_code=401, detail="bad signature")
        try:
            payload = json.loads(raw or b"{}")
        except ValueError:
            raise HTTPException(status_code=400, detail="bad json")
        event_id = str(payload.get("event_id") or payload.get("id") or "")
        event = request.headers.get("x-forge-event") or str(payload.get("event") or payload.get("type") or "")
        if event_id:
            if event_id in seen_events:
                return {"ok": True, "duplicate": True}
            seen_events[event_id] = time.time()
            while len(seen_events) > 2000:
                seen_events.popitem(last=False)
        data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
        reference = str(data.get("reference") or "") if isinstance(data, dict) else ""
        audit.record_standalone(
            "bank.webhook", details={"event": event[:60], "event_id": event_id[:80], "reference": reference[:80]}
        )
        if event.startswith("transfer.") and reference:
            asyncio.create_task(_apply_event(reference))
        return {"ok": True}

    async def _apply_event(reference: str) -> None:
        try:
            await transfers.apply_bank_event(reference)
        except Exception:
            logger.exception("applying bank webhook failed")

    # ------------------------------------------------------------------
    # WebSocket
    # ------------------------------------------------------------------
    @app.websocket("/ws")
    async def ws(websocket: WebSocket):
        await websocket_endpoint(websocket)

    # ------------------------------------------------------------------
    # Static PWA
    # ------------------------------------------------------------------
    app.mount("/static", StaticFiles(directory=str(settings.web_dir)), name="static")
    frontend = settings.frontend_dist
    serve_frontend = (frontend / "index.html").is_file()

    # /prompts holds the backend's recorded clips (web/prompts, used as audio_url)
    # and, when the frontend is served, its own prompt manifest (dist/prompts).
    # The frontend fetches /prompts/manifest.json at boot; a 404 there stopped it
    # loading ("Avenza could not finish loading", 10 Nov 2026).
    prompt_dirs = [settings.prompt_dir.resolve()]
    if serve_frontend:
        prompt_dirs.append((frontend / "prompts").resolve())

    @app.get("/prompts/{name:path}", include_in_schema=False)
    def prompt_file(name: str):
        for base in prompt_dirs:
            candidate = (base / name).resolve()
            if candidate.is_file() and base in candidate.parents:
                return FileResponse(candidate, headers={"Cache-Control": "no-cache"})
        return JSONResponse({"detail": "Not Found"}, status_code=404)
    if serve_frontend:
        logger.info("serving the frontend app from %s", frontend)
        _mount_frontend(app, frontend)
    else:
        @app.get("/")
        def index():
            path = settings.web_dir / "index.html"
            if not path.exists():
                return JSONResponse({"detail": "PWA not built"}, status_code=404)
            return FileResponse(path)

        @app.get("/manifest.webmanifest")
        def manifest():
            return FileResponse(settings.web_dir / "manifest.webmanifest", media_type="application/manifest+json")

        @app.get("/sw.js")
        def service_worker():
            return FileResponse(settings.web_dir / "sw.js", media_type="application/javascript")

        @app.get("/favicon.ico")
        def favicon():
            path = settings.web_dir / "icons" / "icon-192.png"
            if path.exists():
                return FileResponse(path)
            return JSONResponse(status_code=204, content=None)

    @app.exception_handler(ApprovalError)
    async def approval_error_handler(request: Request, exc: ApprovalError):
        return JSONResponse(status_code=400, content={"detail": str(exc)})

    @app.exception_handler(TransferNotFound)
    async def transfer_not_found_handler(request: Request, exc: TransferNotFound):
        return JSONResponse(status_code=404, content={"detail": "transfer not found"})

    @app.exception_handler(TransferLocked)
    async def transfer_locked_handler(request: Request, exc: TransferLocked):
        return JSONResponse(status_code=423, content={"detail": "transfers are locked"})

    @app.exception_handler(SessionError)
    async def session_error_handler(request: Request, exc: SessionError):
        return JSONResponse(status_code=400, content={"detail": str(exc)})

    return app
