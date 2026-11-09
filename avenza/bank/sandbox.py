"""Xtradot Bank sandbox adapter (Forge 2026 Sandbox Participant Platform Guide v1.0, §5).

Contract followed here, from the guide:

* Base URL ``http://bank-api.ingress-apisix.svc.cluster.local/v1``, reachable
  only from the team's Kubernetes namespace. Header ``x-api-key: <team key>``.
* One envelope: ``{"status":"success","data":{...}}`` or
  ``{"status":"error","error":{"code":...,"message":...,"field":...}}``.
* A transfer is two calls: name enquiry, then the transfer carrying the
  single-use ``name_enquiry_ref`` (expires after 10 minutes, destination must
  match). Xtradot-to-Xtradot uses ``/transfers/intra*`` (201, final at once, no
  fee); other banks use ``/transfers/interbank*`` (202 pending, settles in about
  5 seconds).
* ``Idempotency-Key: <uuid>`` on every POST that moves money. Same key and body
  replays the original response; same key, different body returns 409.
* Amounts are NGN with two decimals. Avenza stores kobo and converts at the edge.
* **On 504 TIMEOUT, never resend.** Query ``GET /transfers/{reference}`` or
  ``POST /transfers/interbank/requery`` until the status is final.
* Charges (``fee``, ``vat``, ``stamp_duty``, ``total_debit``) are read from each
  response, never hard-coded.

Field names inside ``data`` are read defensively (several spellings are
accepted) because the guide shows the requests but not every response body.
The authoritative contract is the organisers' Sandbox API Mock Specification v2.
"""

from __future__ import annotations

import asyncio
import logging
import time
import unicodedata
import uuid
from dataclasses import dataclass
from datetime import datetime

import httpx

from ..config import Settings
from ..gateway import GatewayBusy, gateway_limiter
from .adapter import (
    AccountInfo,
    BankAccountRestricted,
    BankAdapter,
    BankNotFound,
    BankNotSent,
    BankResult,
    BankTimeout,
    BankUnavailable,
)

logger = logging.getLogger("avenza.bank.xtradot")

XTRADOT_NIP = "000014"

# Avenza's internal bank code (from the voice parser) -> sandbox NIP code (§5.4).
# Access Bank (044) is deliberately absent: in the sandbox, CBN code 044 is
# Xtradot Bank itself, so mapping it would send "Access Bank" money to Xtradot.
NIP_BY_CODE = {
    "000014": XTRADOT_NIP,  # Xtradot Bank
    "058": "000013",  # GTBank
    "057": "000015",  # Zenith
    "011": "000016",  # First Bank
    "033": "000004",  # UBA
    "035": "000017",  # Wema
    "999992": "100004",  # OPay
    "50515": "090405",  # Moniepoint
}

_STATUS_MAP = {
    "SUCCESS": "SETTLED",
    "SUCCESSFUL": "SETTLED",
    "SETTLED": "SETTLED",
    "COMPLETED": "SETTLED",
    "FAILED": "FAILED",
    "FAILURE": "FAILED",
    "DECLINED": "FAILED",
    "REJECTED": "FAILED",
    "REVERSED": "REVERSED",
    "PENDING": "PENDING",
    "PROCESSING": "PENDING",
    "TIMEOUT": "PENDING",
    "NOT_FOUND": "NOT_FOUND",
}

# Business errors that are definitive refusals: the money did not move.
_DEFINITIVE_FAILURES = {
    "INSUFFICIENT_FUNDS": "insufficient_funds",
    "ACCOUNT_RESTRICTED": "source_restricted",
    "ACCOUNT_DORMANT": "beneficiary_restricted",
    "BENEFICIARY_FROZEN": "beneficiary_restricted",
    "LIMIT_EXCEEDED": "limit_exceeded",
    "NAME_ENQUIRY_EXPIRED": "name_check_expired",
    "NAME_ENQUIRY_MISMATCH": "name_check_expired",
    "INVALID_REQUEST": "bank_declined",
    "ACCOUNT_NOT_FOUND": "account_not_found",
    "BANK_UNAVAILABLE": "bank_unavailable",
}

# A name enquiry ref expires after 10 minutes; refresh well before that.
_REF_TTL_S = 8 * 60
_NARRATION = "Avenza voice transfer"


def _map_status(raw: object) -> str:
    # Anything unknown stays PENDING: it leads to a status check, never to a
    # claim of success.
    return _STATUS_MAP.get(str(raw or "").strip().upper(), "PENDING")


def _parse_time(value: object) -> datetime | None:
    if not value:
        return None
    try:
        from ..timeutil import parse_iso

        return parse_iso(str(value))
    except ValueError:
        return None


def _first(data: dict, *keys: str, default=None):
    for key in keys:
        value = data.get(key)
        if value not in (None, ""):
            return value
    return default


def _to_kobo(value: object) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(round(float(value) * 100))
    except (TypeError, ValueError):
        return None


def _naira(kobo: int) -> float:
    return round(kobo / 100, 2)


def _same_name(a: str, b: str) -> bool:
    def fold(text: str) -> str:
        text = unicodedata.normalize("NFKD", text or "")
        text = "".join(ch for ch in text if not unicodedata.combining(ch))
        return " ".join(text.casefold().split())

    return fold(a) == fold(b)


@dataclass
class _EnquiryRef:
    ref: str
    name: str
    at: float
    used: bool = False


class _Refused(Exception):
    """A definitive refusal before or at the transfer call: no money moved."""

    def __init__(self, reason: str, raw: dict | None = None):
        super().__init__(reason)
        self.reason = reason
        self.raw = raw or {}


class XtradotBank(BankAdapter):
    name = "xtradot"
    simulated = False
    # §5.2: never resend after a timeout. Status checks only.
    allows_resend_on_not_found = False

    def __init__(self, settings: Settings):
        self.settings = settings
        self.base_url = settings.sandbox_base_url.rstrip("/")
        self.api_key = settings.sandbox_api_key
        self.timeout_s = settings.sandbox_timeout_s
        self.settle_wait_s = settings.sandbox_settle_wait_s
        # Interbank settles in about 5 s: 2 s polls cost ~3 gateway requests.
        self.poll_interval_s = 2.0
        self.limiter = gateway_limiter(settings.gateway_requests_per_min)
        self._refs: dict[tuple[str, str], _EnquiryRef] = {}
        self._banks: list[dict] | None = None

    # ------------------------------------------------------------------
    # Plumbing
    # ------------------------------------------------------------------
    @property
    def ready(self) -> bool:
        return bool(self.base_url and self.api_key)

    def _headers(self, extra: dict | None = None) -> dict:
        headers = {"x-api-key": self.api_key, "Content-Type": "application/json", "Accept": "application/json"}
        if self.settings.sandbox_test_outcome and not self.settings.is_production:
            # Demo control (§5.1 forced outcomes). Never in production.
            headers["x-test-outcome"] = self.settings.sandbox_test_outcome
        headers.update(extra or {})
        return headers

    @staticmethod
    def reference_for(idempotency_key: str) -> str:
        """Stable transfer reference derived from Avenza's idempotency key.

        Known before the call, so a timed-out transfer can be looked up with
        ``GET /transfers/{reference}``. Never starts with ``DUP-`` (a trigger).
        """
        core = "".join(ch for ch in idempotency_key if ch.isalnum()).upper()
        return f"AVZ-{core[-24:]}"

    @staticmethod
    def idempotency_uuid(idempotency_key: str) -> str:
        """The guide asks for a UUID; derive one deterministically from our key."""
        return str(uuid.uuid5(uuid.NAMESPACE_URL, f"avenza:{idempotency_key}"))

    async def _call(
        self,
        method: str,
        path: str,
        *,
        json: dict | None = None,
        params: dict | None = None,
        headers: dict | None = None,
        timeout_s: float | None = None,
    ) -> httpx.Response:
        """One gateway call. Raises httpx errors to the caller to classify."""
        if not self.ready:
            raise BankUnavailable("Xtradot sandbox is not configured: set GATEWAY_KEY (and run inside the cluster)")
        try:
            await self.limiter.acquire(max_wait_s=10.0)
        except GatewayBusy as exc:
            raise BankUnavailable(str(exc)) from exc
        async with httpx.AsyncClient(timeout=timeout_s or self.timeout_s) as client:
            resp = await client.request(
                method, f"{self.base_url}{path}", json=json, params=params, headers=self._headers(headers)
            )
        request_id = None
        try:
            body = resp.json()
            request_id = body.get("request_id") if isinstance(body, dict) else None
        except ValueError:
            body = None
        logger.info(
            "xtradot %s %s -> %s request_id=%s", method, path, resp.status_code, request_id or "-"
        )
        return resp

    @staticmethod
    def _envelope(resp: httpx.Response) -> tuple[object, dict | None]:
        """(data, error) from the sandbox envelope."""
        try:
            body = resp.json()
        except ValueError:
            body = None
        if not isinstance(body, dict):
            return body, None if resp.is_success else {"code": f"HTTP_{resp.status_code}", "message": ""}
        if body.get("status") == "error" or ("error" in body and not resp.is_success):
            err = body.get("error") if isinstance(body.get("error"), dict) else {}
            err = {**err, "request_id": body.get("request_id")}
            return None, err
        if not resp.is_success:
            # The gateway may return its own short body (e.g. a bare 401).
            return None, {"code": f"HTTP_{resp.status_code}", "message": str(body)[:200]}
        return body.get("data", body), None

    # ------------------------------------------------------------------
    # Reference data
    # ------------------------------------------------------------------
    async def banks(self) -> list[dict]:
        if self._banks is None:
            resp = await self._call("GET", "/banks", params={"per_page": 100})
            data, err = self._envelope(resp)
            if err:
                raise BankUnavailable(f"bank list unavailable: {err.get('code')}")
            items = data if isinstance(data, list) else (data or {}).get("items", []) if isinstance(data, dict) else []
            self._banks = [b for b in items if isinstance(b, dict)]
        return self._banks

    async def _nip(self, bank_code: str) -> str:
        if bank_code in NIP_BY_CODE:
            return NIP_BY_CODE[bank_code]
        if len(bank_code) == 6 and bank_code.isdigit():
            return bank_code
        # Not in the static table: look the bank up by name in GET /banks.
        from .mock import BANK_NAMES

        wanted = BANK_NAMES.get(bank_code, "").casefold()
        if wanted:
            try:
                for bank in await self.banks():
                    name = str(_first(bank, "name", "bank_name", default="")).casefold()
                    nip = str(_first(bank, "nip_code", "code", default=""))
                    if nip and name and (wanted in name or name in wanted):
                        NIP_BY_CODE[bank_code] = nip
                        return nip
            except BankUnavailable:
                pass
        raise BankNotFound(f"bank {bank_code} is not available in the sandbox")

    # ------------------------------------------------------------------
    # Name enquiry
    # ------------------------------------------------------------------
    async def _enquire(self, nip: str, account_number: str) -> tuple[str, str]:
        """Return (account_name, name_enquiry_ref)."""
        intra = nip == XTRADOT_NIP
        path = "/transfers/intra/name-enquiry" if intra else "/transfers/interbank/name-enquiry"
        body = {"account_number": account_number}
        if not intra:
            body["destination_bank_code"] = nip
        try:
            resp = await self._call("POST", path, json=body)
        except httpx.TimeoutException as exc:
            raise BankUnavailable("name enquiry timed out") from exc
        except httpx.HTTPError as exc:
            raise BankUnavailable(f"name enquiry failed: {type(exc).__name__}") from exc
        data, err = self._envelope(resp)
        if err is not None:
            code = str(err.get("code", "")).upper()
            if resp.status_code == 404 or code in {"ACCOUNT_NOT_FOUND", "NOT_FOUND", "INVALID_REQUEST"}:
                raise BankNotFound(f"account not found ({code})")
            if code in {"ACCOUNT_DORMANT", "BENEFICIARY_FROZEN", "ACCOUNT_RESTRICTED"} or resp.status_code in {403, 422}:
                raise BankAccountRestricted(f"beneficiary cannot receive ({code})")
            raise BankUnavailable(f"name enquiry error {resp.status_code} {code}")
        data = data if isinstance(data, dict) else {}
        name = str(
            _first(data, "account_name", "name", "beneficiary_name", "destination_account_name", default="")
        ).strip()
        ref = str(_first(data, "name_enquiry_ref", "reference", "session_id", default="")).strip()
        if not name:
            raise BankNotFound("sandbox returned no account name")
        return name, ref

    async def name_enquiry(self, bank_code: str, account_number: str) -> AccountInfo:
        nip = await self._nip(bank_code)
        name, ref = await self._enquire(nip, account_number)
        self._refs[(nip, account_number)] = _EnquiryRef(ref=ref, name=name, at=time.monotonic())
        from .mock import BANK_NAMES

        return AccountInfo(
            bank_code=bank_code,
            bank_name=BANK_NAMES.get(bank_code, nip),
            account_number=account_number,
            account_name=name,
        )

    async def _ref_for_transfer(self, nip: str, account_number: str, approved_name: str) -> str:
        """A valid, unused enquiry ref whose name still matches what was approved.

        The ref from the read-back is reused when it is fresh; otherwise a new
        enquiry is made. If the bank now returns a different name, the payment
        is refused: the customer approved a different person.
        """
        key = (nip, account_number)
        cached = self._refs.get(key)
        if cached and not cached.used and cached.ref and time.monotonic() - cached.at < _REF_TTL_S:
            ref, name = cached.ref, cached.name
        else:
            try:
                name, ref = await self._enquire(nip, account_number)
            except BankNotFound as exc:
                raise _Refused("account_not_found") from exc
            except BankAccountRestricted as exc:
                raise _Refused("beneficiary_restricted") from exc
            except BankUnavailable as exc:
                raise BankNotSent(f"fresh name enquiry failed: {exc}", reason="bank_unavailable") from exc
            self._refs[key] = _EnquiryRef(ref=ref, name=name, at=time.monotonic())
        if approved_name and not _same_name(name, approved_name):
            raise _Refused("recipient_changed", {"bank_name": name})
        if not ref:
            raise BankNotSent("name enquiry returned no reference", reason="bank_unavailable")
        return ref

    # ------------------------------------------------------------------
    # Transfers
    # ------------------------------------------------------------------
    async def create_transfer(
        self,
        *,
        idempotency_key: str,
        customer_ref: str,
        amount_kobo: int,
        bank_code: str,
        account_number: str,
        recipient_name: str,
        nonce: str,
    ) -> BankResult:
        reference = self.reference_for(idempotency_key)

        def refused(reason: str, raw: dict | None = None) -> BankResult:
            return BankResult(
                status="FAILED",
                reference=reference,
                amount_kobo=amount_kobo,
                account_number=account_number,
                recipient_name=recipient_name,
                failure_reason=reason,
                raw={"reference": reference, **(raw or {})},
            )

        try:
            nip = await self._nip(bank_code)
        except BankNotFound:
            return refused("bank_not_supported")
        except BankUnavailable as exc:
            raise BankNotSent(str(exc)) from exc
        intra = nip == XTRADOT_NIP
        try:
            enquiry_ref = await self._ref_for_transfer(nip, account_number, recipient_name)
        except _Refused as exc:
            return refused(exc.reason, exc.raw)

        body: dict = {
            "source_account": customer_ref,
            "destination_account": account_number,
            "name_enquiry_ref": enquiry_ref,
            "amount": _naira(amount_kobo),
            "narration": _NARRATION,
            "reference": reference,
        }
        if not intra:
            body["destination_bank_code"] = nip
        path = "/transfers/intra" if intra else "/transfers/interbank"
        headers = {"Idempotency-Key": self.idempotency_uuid(idempotency_key)}

        resp = None
        for attempt in range(2):
            try:
                resp = await self._call("POST", path, json=body, headers=headers)
            except BankUnavailable as exc:
                # Not configured or our own budget is spent: nothing was sent.
                raise BankNotSent(str(exc)) from exc
            except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
                raise BankNotSent(f"could not reach the bank: {type(exc).__name__}") from exc
            except httpx.HTTPError as exc:
                # Sent, no answer: outcome unknown. Never resend; requery.
                self._mark_used(nip, account_number)
                raise BankTimeout(f"no response from the bank: {type(exc).__name__}") from exc
            if resp.status_code == 429 and attempt == 0:
                # Rate limited at the gateway: not processed. The same key and
                # body is safe to send again (the bank replays, never doubles).
                try:
                    wait = float(resp.headers.get("Retry-After", "2"))
                except ValueError:
                    wait = 2.0
                await asyncio.sleep(min(max(wait, 0.5), 5.0))
                continue
            break
        assert resp is not None
        self._mark_used(nip, account_number)
        data, err = self._envelope(resp)

        if err is not None:
            code = str(err.get("code", "")).upper()
            raw = {"http_status": resp.status_code, "error": err}
            if resp.status_code == 504 or code == "TIMEOUT":
                # §5.2: outcome unknown. Never resend. Requery until final.
                raise BankTimeout(f"bank timeout ({err.get('request_id') or 'no request id'})")
            if resp.status_code == 429:
                raise BankNotSent("bank rate limit", reason="bank_busy")
            if resp.status_code == 401 or code == "UNAUTHORIZED":
                logger.error("xtradot rejected the team key (401): check GATEWAY_KEY")
                raise BankNotSent("bank rejected the team key", reason="bank_unavailable")
            if code == "DUPLICATE_REQUEST":
                status = await self.get_transfer_status(reference=reference)
                if status.status != "NOT_FOUND":
                    return status
                return refused("duplicate_request", raw)
            if code in _DEFINITIVE_FAILURES:
                return refused(_DEFINITIVE_FAILURES[code], raw)
            if resp.status_code in {400, 402, 403, 409, 422}:
                return refused("bank_declined", raw)
            if resp.status_code == 404:
                raise BankNotSent(f"transfer endpoint not found ({code})")
            # 5xx without a known code: it may have been processed.
            raise BankTimeout(f"bank error {resp.status_code} {code}")

        result = self._result(
            data if isinstance(data, dict) else {},
            expected_kobo=amount_kobo,
            reference=reference,
            account_number=account_number,
            recipient_name=recipient_name,
        )
        if result.status == "PENDING" and not intra and self.settle_wait_s > 0:
            result = await self._wait_for_final(result, self.settle_wait_s)
        return result

    def _mark_used(self, nip: str, account_number: str) -> None:
        cached = self._refs.get((nip, account_number))
        if cached:
            cached.used = True

    def _result(
        self,
        data: dict,
        *,
        expected_kobo: int | None,
        reference: str,
        account_number: str = "",
        recipient_name: str = "",
    ) -> BankResult:
        status = _map_status(_first(data, "status", "transfer_status", default="PENDING"))
        amount = _to_kobo(_first(data, "amount"))
        if expected_kobo is not None and amount is not None and amount != expected_kobo:
            # Never trust a settlement for a different amount; reconcile instead.
            logger.error("xtradot amount mismatch for %s: sent %s kobo, bank says %s", reference, expected_kobo, amount)
            status = "PENDING"
        charges = {
            key: data.get(key)
            for key in ("fee", "vat", "stamp_duty", "total_debit", "session_id", "currency")
            if data.get(key) is not None
        }
        failure = _first(data, "failure_reason", "reason", "status_reason")
        return BankResult(
            status=status,
            reference=str(_first(data, "reference", default=reference)),
            amount_kobo=amount if amount is not None else (expected_kobo or 0),
            account_number=str(_first(data, "destination_account", "account_number", default=account_number)),
            recipient_name=str(
                _first(data, "destination_account_name", "beneficiary_name", "account_name", default=recipient_name)
            ),
            failure_reason=str(failure).lower() if failure and status == "FAILED" else None,
            raw={"reference": reference, **charges, "bank_status": data.get("status")},
            created_at=_parse_time(_first(data, "created_at", "timestamp")),
        )

    async def _wait_for_final(self, pending: BankResult, wait_s: float) -> BankResult:
        """Interbank settles in about 5 s: check a few times before answering."""
        deadline = time.monotonic() + wait_s
        latest = pending
        while time.monotonic() < deadline:
            await asyncio.sleep(self.poll_interval_s)
            try:
                latest_status = await self._status(pending.reference, requery=False)
            except BankUnavailable:
                break
            if latest_status.status in {"SETTLED", "FAILED", "REVERSED"}:
                return BankResult(
                    status=latest_status.status,
                    reference=latest_status.reference,
                    amount_kobo=latest_status.amount_kobo,
                    account_number=latest_status.account_number or pending.account_number,
                    recipient_name=latest_status.recipient_name or pending.recipient_name,
                    failure_reason=latest_status.failure_reason,
                    raw={**(pending.raw or {}), **(latest_status.raw or {})},
                    created_at=latest_status.created_at or pending.created_at,
                )
            if latest_status.status == "PENDING":
                latest = pending
        return latest

    async def get_transfer_status(
        self, reference: str | None = None, idempotency_key: str | None = None
    ) -> BankResult:
        ref = reference or (self.reference_for(idempotency_key) if idempotency_key else None)
        if not ref:
            return BankResult(status="NOT_FOUND", reference=None)
        return await self._status(ref, requery=True)

    async def _status(self, ref: str, *, requery: bool) -> BankResult:
        try:
            resp = await self._call("GET", f"/transfers/{ref}")
        except BankUnavailable:
            raise
        except httpx.HTTPError as exc:
            raise BankUnavailable(f"status check failed: {type(exc).__name__}") from exc
        if resp.status_code == 404:
            return BankResult(status="NOT_FOUND", reference=ref)
        data, err = self._envelope(resp)
        if err is not None:
            raise BankUnavailable(f"status check error {resp.status_code} {err.get('code')}")
        data = data if isinstance(data, dict) else {}
        result = self._result(data, expected_kobo=None, reference=ref)
        if (
            requery
            and result.status == "PENDING"
            and str(data.get("destination_bank_code", "")) not in {"", XTRADOT_NIP}
        ):
            result = await self._requery(ref, result)
        return result

    async def _requery(self, reference: str, fallback: BankResult) -> BankResult:
        """Ask NIP for the outcome of a pending interbank transfer (§5.2)."""
        try:
            resp = await self._call("POST", "/transfers/interbank/requery", json={"reference": reference})
        except (BankUnavailable, httpx.HTTPError):
            return fallback
        data, err = self._envelope(resp)
        if err is not None or not isinstance(data, dict):
            return fallback
        return self._result(data, expected_kobo=None, reference=reference)

    # ------------------------------------------------------------------
    # Accounts, history, receipts
    # ------------------------------------------------------------------
    async def get_balance(self, account_number: str) -> dict:
        try:
            resp = await self._call("GET", f"/accounts/{account_number}/balance")
        except httpx.HTTPError as exc:
            raise BankUnavailable(f"balance unavailable: {type(exc).__name__}") from exc
        data, err = self._envelope(resp)
        if err is not None:
            if resp.status_code == 404:
                raise BankNotFound("account not found")
            raise BankUnavailable(f"balance error {err.get('code')}")
        data = data if isinstance(data, dict) else {}
        return {
            "account_number": account_number,
            "available_kobo": _to_kobo(_first(data, "available_balance", "balance", "ledger_balance")),
            "ledger_kobo": _to_kobo(_first(data, "ledger_balance", "balance")),
            "currency": data.get("currency", "NGN"),
        }

    async def list_transactions(
        self, customer_ref: str, start: datetime, end: datetime, limit: int = 50
    ) -> list[BankResult]:
        params = {
            "account_number": customer_ref,
            "from": start.replace(microsecond=0).isoformat() + "Z",
            "to": end.replace(microsecond=0).isoformat() + "Z",
            "page": 1,
            "per_page": max(1, min(limit, 100)),
        }
        try:
            resp = await self._call("GET", "/transactions", params=params)
        except httpx.HTTPError as exc:
            raise BankUnavailable(f"history unavailable: {type(exc).__name__}") from exc
        if resp.status_code == 404:
            return []
        data, err = self._envelope(resp)
        if err is not None:
            raise BankUnavailable(f"history error {err.get('code')}")
        items = data if isinstance(data, list) else (data or {}).get("items", []) if isinstance(data, dict) else []
        results: list[BankResult] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            created = _parse_time(_first(item, "created_at", "timestamp", "date", "value_date"))
            if created is not None and not (start <= created <= end):
                continue
            direction = str(_first(item, "type", "direction", "entry_type", default="debit")).lower()
            status = _map_status(_first(item, "status", default="SUCCESSFUL"))
            if direction in {"credit", "cr", "inflow"} and status == "SETTLED":
                status = "RECEIVED"
            results.append(
                BankResult(
                    status=status,
                    reference=_first(item, "reference", "transaction_reference"),
                    amount_kobo=_to_kobo(_first(item, "amount")) or 0,
                    account_number=str(_first(item, "counterparty_account", "destination_account", default="")),
                    recipient_name=str(
                        _first(
                            item,
                            "counterparty_name",
                            "beneficiary_name",
                            "destination_account_name",
                            "narration",
                            default="",
                        )
                    ),
                    failure_reason=None,
                    raw={"direction": direction, **item},
                    created_at=created,
                )
            )
        return results[:limit]

    async def get_receipt(self, reference: str) -> dict | None:
        for path in (f"/transactions/{reference}", f"/transfers/{reference}"):
            try:
                resp = await self._call("GET", path)
            except (BankUnavailable, httpx.HTTPError):
                return None
            if resp.status_code == 404:
                continue
            data, err = self._envelope(resp)
            if err is not None or not isinstance(data, dict):
                continue
            return {
                "reference": reference,
                "amount_kobo": _to_kobo(_first(data, "amount")),
                "recipient_name": _first(
                    data, "destination_account_name", "beneficiary_name", "counterparty_name", "account_name"
                ),
                "status": _map_status(_first(data, "status")),
                "fee": data.get("fee"),
                "vat": data.get("vat"),
                "stamp_duty": data.get("stamp_duty"),
                "total_debit": data.get("total_debit"),
                "session_id": data.get("session_id"),
                "created_at": _first(data, "created_at", "timestamp"),
                "simulated": False,
                "bank": "Xtradot Bank sandbox",
            }
        return None

    # ------------------------------------------------------------------
    # Team admin (demo preparation only)
    # ------------------------------------------------------------------
    async def admin_reset(self) -> dict:
        resp = await self._call("POST", "/admin/reset", json={}, headers={"Idempotency-Key": str(uuid.uuid4())})
        data, err = self._envelope(resp)
        if err is not None:
            raise BankUnavailable(f"reset failed: {err.get('code')}")
        self._refs.clear()
        return data if isinstance(data, dict) else {"ok": True}

    async def register_webhook(self, url: str, events: list[str] | None = None) -> dict:
        resp = await self._call(
            "POST",
            "/webhooks",
            json={"url": url, "events": events or ["*"]},
            headers={"Idempotency-Key": str(uuid.uuid4())},
        )
        data, err = self._envelope(resp)
        if err is not None:
            raise BankUnavailable(f"webhook registration failed: {err.get('code')} {err.get('message')}")
        return data if isinstance(data, dict) else {}


# Backwards-compatible name.
SandboxBank = XtradotBank
