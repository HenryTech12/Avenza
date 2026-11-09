"""Check the Xtradot sandbox from inside the cluster before a demo.

    kubectl exec deploy/app -- python scripts/sandbox_smoke.py            # read-only checks
    kubectl exec deploy/app -- python scripts/sandbox_smoke.py --transfer # also sends ₦100.00 intrabank

Read-only checks: the team key works, the bank list loads, the source account
balance, and name enquiries for the guide's fixtures (one active, one dormant,
one interbank). With --transfer it sends ₦100.00 (an amount ending .00, which
never triggers a test outcome) to Ngozi Adaobi Eze at Xtradot Bank and prints
the charges from the response. About 8 gateway requests; the limit is 60 a minute.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import argparse
import asyncio
import sys
import uuid

from avenza.bank import BankAccountRestricted, BankError, XtradotBank
from avenza.config import load_settings
from avenza.money import format_naira


async def main(send: bool) -> int:
    settings = load_settings()
    bank = XtradotBank(settings)
    ok = True

    def report(label: str, value: object, good: bool = True) -> None:
        nonlocal ok
        ok = ok and good
        print(f"[{'ok' if good else 'FAIL'}] {label}: {value}")

    if not bank.ready:
        print("GATEWAY_KEY is not set. Run inside the pod (kubectl exec deploy/app -- ...).", file=sys.stderr)
        return 2
    try:
        banks = await bank.banks()
        report("bank list", f"{len(banks)} banks", bool(banks))
        source = settings.sandbox_source_account
        balance = await bank.get_balance(source)
        report(f"balance {source}", format_naira(balance.get("available_kobo") or 0))
        info = await bank.name_enquiry("000014", "0987654321")
        report("intra name enquiry 0987654321", info.account_name, info.account_name == "Ngozi Adaobi Eze")
        info = await bank.name_enquiry("058", "0123987001")
        report("interbank name enquiry GTBank 0123987001", info.account_name)
        try:
            await bank.name_enquiry("000014", "0987654399")
            report("dormant account is refused", "accepted", False)
        except BankAccountRestricted:
            report("dormant account is refused", "refused")
        if send:
            result = await bank.create_transfer(
                idempotency_key=f"avz_smoke_{uuid.uuid4().hex}",
                customer_ref=source,
                amount_kobo=10_000,
                bank_code="000014",
                account_number="0987654321",
                recipient_name="Ngozi Adaobi Eze",
                nonce=uuid.uuid4().hex,
            )
            report("₦100.00 intrabank transfer", f"{result.status} ref={result.reference} charges={result.raw}",
                   result.status == "SETTLED")
    except BankError as exc:
        report("sandbox call", f"{type(exc).__name__}: {exc}", False)
    print("\nAll checks passed." if ok else "\nSome checks failed. Quote request_id from the logs in support requests.")
    return 0 if ok else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--transfer", action="store_true", help="also send ₦100.00 intrabank")
    raise SystemExit(asyncio.run(main(parser.parse_args().transfer)))
