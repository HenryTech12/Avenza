"""Local simulator of the Xtradot Bank sandbox (Forge guide §5), for development.

The real sandbox only answers from inside the team's Kubernetes namespace, so
this simulator lets the team run Avenza with ``BANK_MODE=sandbox`` on a laptop
and lets the tests exercise the real adapter end to end.

    python -m avenza.bank.xtradot_sim            # http://127.0.0.1:9100/v1
    SANDBOX_BASE_URL=http://127.0.0.1:9100/v1 GATEWAY_KEY=dev-team-key BANK_MODE=sandbox python run.py

It follows the guide's operational summary: the envelope, ``x-api-key``,
idempotency replay and 409, single-use name-enquiry refs that expire after 10
minutes, intra (201, final) versus interbank (202, settles in ~5 s), the test
fixtures in §5.4 and the trigger values in §5.5. It is a stand-in, not the
organisers' implementation: behaviour the guide does not describe (exact
response field names, history filters) is a reasonable guess. Always re-test
against the real sandbox from inside the cluster before Demo Day.
"""

from __future__ import annotations

import hashlib
import json
import time
import uuid
from dataclasses import dataclass, field
from typing import Callable

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

DEV_KEY = "dev-team-key"
XTRADOT = "000014"

BANKS = [
    {"nip_code": "000014", "cbn_code": "044", "name": "Xtradot Bank"},
    {"nip_code": "000013", "cbn_code": "058", "name": "GTBank"},
    {"nip_code": "000015", "cbn_code": "057", "name": "Zenith Bank"},
    {"nip_code": "000016", "cbn_code": "011", "name": "First Bank"},
    {"nip_code": "000004", "cbn_code": "033", "name": "UBA"},
    {"nip_code": "000017", "cbn_code": "035", "name": "Wema Bank"},
    {"nip_code": "100004", "cbn_code": "", "name": "OPay"},
    {"nip_code": "090405", "cbn_code": "", "name": "Moniepoint"},
]

# Team-owned accounts (§5.4): number -> (holder, tier, opening balance kobo, state)
TEAM_ACCOUNTS = {
    "0123456789": ("Adaeze Chiamaka Okonkwo", "3", 150_000_000, "active"),
    "0123456790": ("Babatunde Olumide Adeyemi", "3", 500_000_000, "active"),
    "0123456791": ("Musa Ibrahim Abdullahi", "2", 25_000_000, "active"),
    "0123456792": ("Efosa Godwin Osagie", "1", 4_000_000, "active"),
    "0123456793": ("Mama Nkechi Provisions Ltd", "corporate", 1_200_000_000, "active"),
}
# Beneficiaries (§5.4): (nip, account) -> (holder, state)
BENEFICIARIES = {
    (XTRADOT, "0987654321"): ("Ngozi Adaobi Eze", "active"),
    (XTRADOT, "0987654322"): ("Aisha Hauwa Bello", "active"),
    (XTRADOT, "0987654399"): ("Obinna Kelechi Okafor", "dormant"),
    ("000013", "0123987001"): ("Chukwuemeka Ifeanyi Nwosu", "active"),
    ("000013", "0123987099"): ("Garba Sani Danjuma", "pnd"),
    ("000015", "0123987002"): ("Funmilayo Abiola Ogunleye", "active"),
    ("000016", "0123987003"): ("Zainab Halima Yusuf", "active"),
    ("000004", "0123987004"): ("Tamunotonye Briggs", "active"),
    ("000017", "0123987098"): ("Blessing Oghenekaro Edeh", "frozen"),
    ("100004", "8031234506"): ("Ifeoluwa Grace Adebayo", "active"),
    ("090405", "8051234507"): ("Iya Bisi Foods Enterprises", "active"),
}
for _number, (_holder, _tier, _bal, _state) in TEAM_ACCOUNTS.items():
    BENEFICIARIES[(XTRADOT, _number)] = (_holder, _state)

# KYC single-transfer limits in kobo (§5.2).
SINGLE_LIMIT = {"1": 5_000_000, "2": 10_000_000, "3": 500_000_000, "corporate": 1_000_000_000}


@dataclass
class SimTransfer:
    reference: str
    kind: str  # intra | interbank
    source: str
    nip: str
    destination: str
    name: str
    amount_kobo: int
    fee_kobo: int
    vat_kobo: int
    created: float
    trigger: str  # "", "02", "03", "04"
    narration: str = ""
    created_iso: str = ""

    @property
    def total_debit_kobo(self) -> int:
        return self.amount_kobo + self.fee_kobo + self.vat_kobo


@dataclass
class Simulator:
    settle_s: float = 5.0
    clock: Callable[[], float] = time.monotonic
    offset: float = 0.0
    api_key: str = DEV_KEY
    balances: dict[str, int] = field(default_factory=dict)
    refs: dict[str, dict] = field(default_factory=dict)
    transfers: dict[str, SimTransfer] = field(default_factory=dict)
    idempotency: dict[str, tuple[str, int, dict]] = field(default_factory=dict)
    calls: list[tuple[str, str]] = field(default_factory=list)
    webhooks: list[dict] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.reset()

    def now(self) -> float:
        return self.clock() + self.offset

    def advance(self, seconds: float) -> None:
        self.offset += seconds

    def reset(self) -> None:
        self.balances = {n: bal for n, (_h, _t, bal, _s) in TEAM_ACCOUNTS.items()}
        self.refs.clear()
        self.transfers.clear()
        self.idempotency.clear()

    # -- outcomes ---------------------------------------------------------
    def status_of(self, t: SimTransfer) -> str:
        age = self.now() - t.created
        if t.trigger == "02":
            return "pending" if age < 30 else "reversed"
        if t.trigger == "03":
            return "pending" if age < 120 else "successful"
        if t.kind == "intra":
            return "successful"
        if age < self.settle_s:
            return "pending"
        if t.trigger == "04" and age >= 60:
            return "reversed"
        return "successful"

    def transfer_body(self, t: SimTransfer) -> dict:
        return {
            "reference": t.reference,
            "status": self.status_of(t),
            "amount": t.amount_kobo / 100,
            "currency": "NGN",
            "source_account": t.source,
            "destination_bank_code": t.nip,
            "destination_account": t.destination,
            "destination_account_name": t.name,
            "narration": t.narration,
            "fee": t.fee_kobo / 100,
            "vat": t.vat_kobo / 100,
            "stamp_duty": 0.0,
            "total_debit": t.total_debit_kobo / 100,
            "session_id": "0000" + hashlib.sha1(t.reference.encode()).hexdigest()[:26],
            "created_at": t.created_iso,
        }


def _ok(data, status_code: int = 200, headers: dict | None = None, meta=None) -> JSONResponse:
    return JSONResponse(
        {"status": "success", "message": "ok", "data": data, "meta": meta, "request_id": "req_" + uuid.uuid4().hex[:8]},
        status_code=status_code,
        headers=headers,
    )


def _err(code: str, http: int, message: str = "", field: str | None = None) -> JSONResponse:
    return JSONResponse(
        {
            "status": "error",
            "error": {"code": code, "message": message or code.replace("_", " ").lower(), "field": field},
            "request_id": "req_" + uuid.uuid4().hex[:8],
        },
        status_code=http,
    )


def _nip_fee_kobo(amount_kobo: int) -> int:
    naira = amount_kobo / 100
    return 1_000 if naira <= 5_000 else 2_500 if naira <= 50_000 else 5_000


def create_sim_app(sim: Simulator | None = None) -> FastAPI:
    sim = sim or Simulator()
    app = FastAPI(title="Xtradot Bank sandbox simulator")
    app.state.sim = sim

    @app.middleware("http")
    async def auth(request: Request, call_next):
        sim.calls.append((request.method, request.url.path))
        if request.headers.get("x-api-key") != sim.api_key:
            return JSONResponse({"message": "Unauthorized"}, status_code=401)
        return await call_next(request)

    @app.get("/v1/banks")
    def banks():
        return _ok(BANKS, meta={"page": 1, "per_page": 100, "total": len(BANKS)})

    async def _enquiry(request: Request, kind: str):
        body = await request.json()
        account = str(body.get("account_number", ""))
        nip = XTRADOT if kind == "intra" else str(body.get("destination_bank_code", ""))
        if kind == "interbank" and not nip:
            return _err("INVALID_REQUEST", 400, field="destination_bank_code")
        if account == "0000000001":
            return _err("ACCOUNT_NOT_FOUND", 404)
        if account == "0000000002":
            return _err("TIMEOUT", 504, "name enquiry timed out after 10 s")
        if nip == "999999":
            return _err("BANK_UNAVAILABLE", 503)
        found = BENEFICIARIES.get((nip, account))
        if found is None:
            return _err("ACCOUNT_NOT_FOUND", 404)
        holder, state = found
        if state == "dormant":
            return _err("ACCOUNT_DORMANT", 422)
        if state == "frozen":
            return _err("BENEFICIARY_FROZEN", 422)
        ref = ("NE" if kind == "interbank" else "IE") + uuid.uuid4().hex[:14].upper()
        sim.refs[ref] = {"nip": nip, "account": account, "kind": kind, "at": sim.now(), "used": False, "name": holder}
        return _ok(
            {
                # The real sandbox returns names in capitals (seen 9 Nov 2026).
                "account_name": holder.upper(),
                "account_number": account,
                "bank_code": nip,
                "name_enquiry_ref": ref,
            }
        )

    @app.post("/v1/transfers/intra/name-enquiry")
    async def intra_enquiry(request: Request):
        return await _enquiry(request, "intra")

    @app.post("/v1/transfers/interbank/name-enquiry")
    async def inter_enquiry(request: Request):
        return await _enquiry(request, "interbank")

    async def _transfer(request: Request, kind: str):
        raw = await request.body()
        key = request.headers.get("idempotency-key")
        if not key:
            return _err("INVALID_REQUEST", 400, "Idempotency-Key header is required", "Idempotency-Key")
        digest = hashlib.sha256(raw).hexdigest()
        if key in sim.idempotency:
            prior_digest, prior_status, prior_body = sim.idempotency[key]
            if prior_digest != digest:
                return _err("DUPLICATE_REQUEST", 409, "idempotency key reused with a different body")
            return JSONResponse(prior_body, status_code=prior_status, headers={"Idempotent-Replayed": "true"})

        def remember(resp: JSONResponse) -> JSONResponse:
            sim.idempotency[key] = (digest, resp.status_code, json.loads(resp.body))
            return resp

        body = json.loads(raw or b"{}")
        reference = str(body.get("reference", ""))
        source = str(body.get("source_account", ""))
        destination = str(body.get("destination_account", ""))
        nip = XTRADOT if kind == "intra" else str(body.get("destination_bank_code", ""))
        ref = str(body.get("name_enquiry_ref", ""))
        try:
            amount_kobo = int(round(float(body.get("amount")) * 100))
        except (TypeError, ValueError):
            return _err("INVALID_REQUEST", 400, field="amount")
        if amount_kobo <= 0 or not reference or not source or not destination:
            return _err("INVALID_REQUEST", 400)
        if reference.startswith("DUP-") or reference in sim.transfers:
            return remember(_err("DUPLICATE_REQUEST", 409, "reference already used", "reference"))
        enquiry = sim.refs.get(ref)
        if enquiry is None or enquiry["kind"] != kind:
            return remember(_err("NAME_ENQUIRY_MISMATCH", 409, field="name_enquiry_ref"))
        if enquiry["used"]:
            return remember(_err("DUPLICATE_REQUEST", 409, "name enquiry ref already used", "name_enquiry_ref"))
        if sim.now() - enquiry["at"] > 600:
            return remember(_err("NAME_ENQUIRY_EXPIRED", 409))
        if enquiry["nip"] != nip or enquiry["account"] != destination:
            return remember(_err("NAME_ENQUIRY_MISMATCH", 409))
        team = TEAM_ACCOUNTS.get(source)
        if team is None:
            return remember(_err("ACCOUNT_NOT_FOUND", 404, field="source_account"))
        cents = amount_kobo % 100
        if cents == 1:
            return remember(_err("INSUFFICIENT_FUNDS", 402))
        if amount_kobo > SINGLE_LIMIT.get(team[1], 0):
            return remember(_err("LIMIT_EXCEEDED", 422, "KYC single-transfer limit"))
        fee = 0 if kind == "intra" else _nip_fee_kobo(amount_kobo)
        vat = int(round(fee * 0.075))
        if sim.balances[source] < amount_kobo + fee + vat:
            return remember(_err("INSUFFICIENT_FUNDS", 402))
        enquiry["used"] = True
        trigger = {2: "02", 3: "03", 4: "04"}.get(cents, "")
        transfer = SimTransfer(
            reference=reference,
            kind=kind,
            source=source,
            nip=nip,
            destination=destination,
            name=enquiry["name"],
            amount_kobo=amount_kobo,
            fee_kobo=fee,
            vat_kobo=vat,
            created=sim.now(),
            trigger=trigger,
            narration=str(body.get("narration", "")),
            created_iso=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        )
        sim.transfers[reference] = transfer
        sim.balances[source] -= transfer.total_debit_kobo
        if trigger == "02":
            return remember(_err("TIMEOUT", 504, "outcome unknown: requery, never resend"))
        return remember(_ok(sim.transfer_body(transfer), status_code=201 if kind == "intra" else 202))

    @app.post("/v1/transfers/intra")
    async def intra(request: Request):
        return await _transfer(request, "intra")

    @app.post("/v1/transfers/interbank")
    async def interbank(request: Request):
        return await _transfer(request, "interbank")

    @app.get("/v1/transfers/{reference}")
    def get_transfer(reference: str):
        t = sim.transfers.get(reference)
        if t is None:
            return _err("NOT_FOUND", 404)
        return _ok(sim.transfer_body(t))

    @app.post("/v1/transfers/interbank/requery")
    async def requery(request: Request):
        body = await request.json()
        t = sim.transfers.get(str(body.get("reference", "")))
        if t is None:
            return _err("NOT_FOUND", 404)
        return _ok(sim.transfer_body(t))

    @app.get("/v1/accounts/{number}/balance")
    def balance(number: str):
        if number not in sim.balances:
            return _err("ACCOUNT_NOT_FOUND", 404)
        value = sim.balances[number] / 100
        return _ok({"account_number": number, "available_balance": value, "ledger_balance": value, "currency": "NGN"})

    @app.get("/v1/transactions")
    def transactions(account_number: str = "", page: int = 1, per_page: int = 20):
        rows = [
            {
                "reference": t.reference,
                "type": "debit",
                "amount": t.amount_kobo / 100,
                "status": sim.status_of(t),
                "counterparty_name": t.name,
                "counterparty_account": t.destination,
                "created_at": t.created_iso,
            }
            for t in sim.transfers.values()
            if not account_number or t.source == account_number
        ]
        per_page = max(1, min(per_page, 100))
        start = (page - 1) * per_page
        return _ok(rows[start : start + per_page], meta={"page": page, "per_page": per_page, "total": len(rows)})

    @app.get("/v1/transactions/{reference}")
    def transaction(reference: str):
        t = sim.transfers.get(reference)
        if t is None:
            return _err("NOT_FOUND", 404)
        return _ok(sim.transfer_body(t))

    @app.post("/v1/webhooks")
    async def webhooks(request: Request):
        body = await request.json()
        hook = {"id": "wh_" + uuid.uuid4().hex[:8], "url": body.get("url"), "events": body.get("events", ["*"])}
        sim.webhooks.append(hook)
        return _ok({**hook, "webhook_secret": "whsec_" + uuid.uuid4().hex}, status_code=201)

    @app.post("/v1/admin/reset")
    def admin_reset():
        sim.reset()
        return _ok({"reset": True})

    @app.api_route("/v1/{path:path}", methods=["GET", "POST", "DELETE"])
    def not_implemented(path: str):
        return _err("NOT_FOUND", 404, "not available in the sandbox build")

    return app


def main() -> None:  # pragma: no cover - manual tool
    import uvicorn

    uvicorn.run(create_sim_app(), host="127.0.0.1", port=9100)


if __name__ == "__main__":  # pragma: no cover
    main()
