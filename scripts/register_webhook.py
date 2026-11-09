"""Register Avenza's webhook with the Xtradot sandbox (guide §5.6). Run once.

The sandbox only answers inside the team namespace, so run it in the pod:

    kubectl exec deploy/app -- python scripts/register_webhook.py http://app.teamXX.svc.cluster.local/hooks/forge

It prints ``webhook_secret`` (returned only once). Put it in
deploy/forge/.env.forge as FORGE_WEBHOOK_SECRET and run deploy.sh again, or:

    kubectl patch secret avenza-secrets -p '{"stringData":{"FORGE_WEBHOOK_SECRET":"<secret>"}}'
    kubectl rollout restart deployment/app
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import asyncio
import json
import sys

from avenza.bank import XtradotBank
from avenza.config import load_settings


async def main(url: str) -> int:
    bank = XtradotBank(load_settings())
    if not bank.ready:
        print("GATEWAY_KEY is not set; run this inside the cluster pod.", file=sys.stderr)
        return 2
    data = await bank.register_webhook(url)
    print(json.dumps(data, indent=2))
    secret = data.get("webhook_secret")
    if secret:
        print("\nStore this now; the sandbox will not show it again:\n  FORGE_WEBHOOK_SECRET=" + secret)
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(__doc__)
        raise SystemExit(2)
    raise SystemExit(asyncio.run(main(sys.argv[1])))
