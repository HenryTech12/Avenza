"""Diagnose the YarnGPT TTS stall (open issue 1) from inside the cluster.

    kubectl exec deploy/app -- python scripts/yarngpt_tts_probe.py
    kubectl exec deploy/app -- python scripts/yarngpt_tts_probe.py --route ticket
    kubectl exec deploy/app -- python scripts/yarngpt_tts_probe.py --text "Payment settled."

For each route (conversation, ticket) and each text (a short one and the long
read-back), it makes one raw HTTP call and prints:

- the HTTP status, Content-Type and request/trace id,
- the **whole error body** (for the 422),
- time to response headers, time to the first audio byte, total bytes and time,
- whether the stream stalled (no new bytes for --stall seconds) and after how many bytes.

It waits much longer than the live app does (default 45 s) so a stall can be
measured, not just cut off. Every successful call spends real YarnGPT credits:
the default run makes up to 4 calls. The API key is read from YARNGPT_API_KEY
and never printed.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
import uuid

import httpx

BASE = os.getenv("YARNGPT_BASE_URL", "https://api.yarngpt.ai").rstrip("/")
SHORT = "Payment settled."
LONG = ("You are sending five thousand naira to Ngozi Adaobi Eze at GTBank, account ending "
        "seven zero zero one. The charge is ten naira. Say yes to continue, then use your fingerprint.")


def _ids(resp: httpx.Response) -> str:
    keys = ("x-request-id", "x-trace-id", "traceparent", "cf-ray")
    return " ".join(f"{k}={resp.headers[k]}" for k in keys if k in resp.headers) or "-"


async def _read(resp: httpx.Response, t0: float, stall_s: float, max_s: float) -> dict:
    first = None
    total = 0
    stalled_after = None
    it = resp.aiter_bytes().__aiter__()
    while True:
        try:
            chunk = await asyncio.wait_for(it.__anext__(), stall_s)
        except StopAsyncIteration:
            break
        except asyncio.TimeoutError:
            stalled_after = total
            break
        if chunk and first is None:
            first = time.perf_counter() - t0
        total += len(chunk)
        if time.perf_counter() - t0 > max_s:
            break
    return {"first_byte_s": None if first is None else round(first, 2), "bytes": total,
            "total_s": round(time.perf_counter() - t0, 2),
            "stalled_after_bytes": stalled_after}


async def probe(client: httpx.AsyncClient, route: str, text: str, voice: str, key: str,
                stall_s: float, max_s: float) -> dict:
    payload = {"text": text, "output_format": "pcm"}
    if voice:
        payload["voice"] = voice
    headers = {"Authorization": f"Bearer {key}", "Idempotency-Key": uuid.uuid4().hex}
    out: dict = {"route": route, "chars": len(text)}
    t0 = time.perf_counter()
    try:
        if route == "ticket":
            prep = await client.post(BASE + "/api/v1/tts/prepare", json=payload, headers=headers)
            out["prepare_status"] = prep.status_code
            out["prepare_s"] = round(time.perf_counter() - t0, 2)
            out["prepare_body"] = prep.text[:1000]
            out["prepare_ids"] = _ids(prep)
            if prep.status_code >= 300:
                return out
            data = prep.json() if prep.headers.get("content-type", "").startswith("application/json") else {}
            if isinstance(data.get("data"), dict):
                data = {**data["data"], **data}
            url = data.get("stream_url") or data.get("url")
            if url and not str(url).startswith("http"):
                url = BASE + "/" + str(url).lstrip("/")
            ticket = data.get("ticket") or data.get("ticket_id") or data.get("id")
            if not url and not ticket:
                out["error"] = "no ticket in prepare response"
                return out
            url = url or f"{BASE}/api/v1/tts/stream/{ticket}"
            request = client.build_request("GET", url, headers={"Authorization": headers["Authorization"]})
        else:
            request = client.build_request("POST", BASE + "/api/v1/streaming/conversation",
                                           json=payload, headers=headers)
        resp = await client.send(request, stream=True)
        try:
            out["status"] = resp.status_code
            out["headers_s"] = round(time.perf_counter() - t0, 2)
            out["content_type"] = resp.headers.get("content-type", "")
            out["ids"] = _ids(resp)
            if resp.status_code != 200:
                out["error_body"] = (await resp.aread()).decode("utf-8", "replace")[:2000]
            else:
                out.update(await _read(resp, t0, stall_s, max_s))
        finally:
            await resp.aclose()
    except httpx.HTTPError as exc:
        out["exception"] = f"{type(exc).__name__}: {exc}"
        out["after_s"] = round(time.perf_counter() - t0, 2)
    return out


async def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--route", choices=["conversation", "ticket", "both"], default="both")
    ap.add_argument("--text", action="append", help="text to speak (repeatable); default: a short and a long one")
    ap.add_argument("--voice", default=os.getenv("YARNGPT_DEFAULT_VOICE", "adaora"))
    ap.add_argument("--stall", type=float, default=10.0, help="seconds without a byte that count as a stall")
    ap.add_argument("--max", type=float, default=45.0, help="give up on one call after this many seconds")
    args = ap.parse_args()

    key = os.getenv("YARNGPT_API_KEY") or os.getenv("YARN_API_KEY") or ""
    if not key:
        print("YARNGPT_API_KEY is not set", file=sys.stderr)
        return 2
    print(f"base={BASE} voice={args.voice} key_len={len(key)}")
    routes = ["conversation", "ticket"] if args.route == "both" else [args.route]
    texts = args.text or [SHORT, LONG]
    timeout = httpx.Timeout(args.max, connect=10.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        for route in routes:
            for text in texts:
                result = await probe(client, route, text, args.voice, key, args.stall, args.max)
                print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
