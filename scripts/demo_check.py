"""Pre-flight check before a rehearsal, a recording or Demo Day. Run it every time.

    python scripts/demo_check.py --public-url https://xxxx.trycloudflare.com
    python scripts/demo_check.py --public-url https://team18.xtradot.co --app http://127.0.0.1:8000
    python scripts/demo_check.py --no-tts          # skip the one paid YarnGPT call

Checks, in the order a demo depends on them: Avenza is up with real speech (not mock),
the passkey settings match the address the phone opens, the frontend is served, the
bank answers, the language model key works (or is switched off), speech keys are
present, one YarnGPT reply comes back within the reply budget, and the fixed-prompt
cache is filled. Prints a fix for every failure. Never prints a key.
"""
from __future__ import annotations

import argparse
import asyncio
import sys
import time
from pathlib import Path
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx  # noqa: E402

from avenza.config import load_settings  # noqa: E402

OK, BAD, WARN = "✓", "✗", "!"
failures = 0


def report(ok: bool | None, what: str, fix: str = "") -> None:
    global failures
    mark = OK if ok else (WARN if ok is None else BAD)
    if ok is False:
        failures += 1
    print(f"  {mark} {what}")
    if fix and not ok:
        print(f"      -> {fix}")


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--app", default="http://127.0.0.1:8000", help="where Avenza runs on this machine")
    ap.add_argument("--public-url", default="", help="the address the phone opens (tunnel or team18.xtradot.co)")
    ap.add_argument("--no-tts", action="store_true", help="skip the paid YarnGPT test call")
    args = ap.parse_args()
    s = load_settings()

    async with httpx.AsyncClient(timeout=15) as http:
        print("Avenza")
        try:
            h = (await http.get(f"{args.app}/health")).json()
        except Exception as exc:  # noqa: BLE001
            report(False, f"Avenza is not answering at {args.app} ({type(exc).__name__})", "start it: python run.py")
            return 1
        report(h.get("status") == "ok", f"health: {h.get('status')}", "check the run.py window for errors")
        report(not h["stt"]["simulated"], f"speech-to-text: {h['stt']['provider']}", "set STT_PROVIDER=ai and the Sahara/YarnGPT keys in .env")
        report(not h["tts"]["simulated"], f"voice: {h['tts']['provider']}", "set TTS_PROVIDER=yarngpt and YARNGPT_API_KEY in .env")
        report(not h.get("dev_approval_allowed"), "fingerprint cannot be bypassed (ALLOW_DEV_APPROVAL off)", "set ALLOW_DEV_APPROVAL=false")
        bank = h["bank"]
        where = "local simulator" if "127.0.0.1" in s.sandbox_base_url or "localhost" in s.sandbox_base_url else s.sandbox_base_url
        report(bank.get("ready", True), f"bank: {bank['mode']} ({'mock' if bank['simulated'] else where})",
               "start the simulator: python -m avenza.bank.xtradot_sim")

        print("Phone address and fingerprint")
        if args.public_url:
            host = urlsplit(args.public_url).hostname or ""
            rp, origin = h["webauthn"]["rp_id"], h["webauthn"]["origin"]
            report(rp == host, f"WEBAUTHN_RP_ID={rp} (phone opens {host})", f"set WEBAUTHN_RP_ID={host} in .env and restart")
            report(args.public_url.rstrip("/") in [o.strip().rstrip("/") for o in origin.split(",")],
                   f"WEBAUTHN_ORIGIN={origin}", f"set WEBAUTHN_ORIGIN={args.public_url.rstrip('/')} in .env and restart")
            try:
                r = await http.get(f"{args.public_url.rstrip('/')}/healthz")
                report(r.status_code == 200, f"the public address reaches Avenza (HTTP {r.status_code})",
                       "is the tunnel running? (cloudflared tunnel --url http://localhost:8000)")
            except Exception as exc:  # noqa: BLE001
                report(False, f"the public address does not answer ({type(exc).__name__})", "start or restart the tunnel")
        else:
            report(None, "no --public-url given: passkey address not checked")

        print("Frontend")
        page = await http.get(f"{args.app}/")
        report(page.status_code == 200 and 'id="app"' in page.text, "the app page is served", "build it: cd frontend && VITE_BACKEND_MODE=live VITE_API_BASE_URL= npm run build")
        man = await http.get(f"{args.app}/prompts/manifest.json")
        report(man.status_code == 200, "prompt manifest (needed at boot)", "rebuild the frontend and pull the latest code")

        print("Bank")
        if s.bank_mode == "sandbox":
            try:
                r = await http.get(f"{s.sandbox_base_url.rstrip('/')}/banks", headers={"x-api-key": s.gateway_key})
                report(r.status_code == 200, f"bank answers at {s.sandbox_base_url} (HTTP {r.status_code})",
                       "local: python -m avenza.bank.xtradot_sim; cluster: check GATEWAY_KEY")
            except Exception as exc:  # noqa: BLE001
                report(False, f"bank not reachable ({type(exc).__name__})", "start the simulator: python -m avenza.bank.xtradot_sim")
        else:
            report(None, f"BANK_MODE={s.bank_mode}: the demo should use sandbox (simulator locally)")

        print("Language model")
        if not s.llm_configured:
            report(True, "off (keyword understanding only: fast and predictable)")
        elif s.llm_provider == "huawei-maas":
            report(None, "Huawei MaaS configured: verify once on the cluster")
        else:
            try:
                r = await http.get(f"{s.llm_base_url.rstrip('/')}/models", headers={"Authorization": f"Bearer {s.llm_api_key}"})
                report(r.status_code == 200, f"{s.llm_provider} key works (HTTP {r.status_code})",
                       "401 = dead key: new key in LLM_API_KEY, or LLM_ENABLED=false")
            except Exception as exc:  # noqa: BLE001
                report(False, f"language model not reachable ({type(exc).__name__})", "LLM_ENABLED=false for the demo")

        print("Speech keys and order")
        choice = s.ai_stt_choice or "(default)"
        report(None if "en=sahara" in choice else True, f"AI_STT_CHOICE={choice}",
               "faster and no 3-a-minute limit: AI_STT_CHOICE=en=yarngpt|sahara,pcm=yarngpt|sahara")
        report(bool(s.yarngpt_api_key or s.yarn_api_key), f"YarnGPT key present ({len(s.yarngpt_api_key or s.yarn_api_key)} chars)", "set YARNGPT_API_KEY")
        if "sahara" in choice:
            report(bool(s.sahara_api_key), f"Sahara key present ({len(s.sahara_api_key)} chars)", "set SAHARA_API_KEY")

    print("Voice")
    if args.no_tts:
        report(None, "skipped (--no-tts)")
    else:
        from avenza_ai.providers.yarngpt_tts import YarnGPTTTS

        tts = YarnGPTTTS(api_key=s.yarngpt_api_key or s.yarn_api_key, default_voice=s.yarngpt_default_voice or None,
                         timeout=max(15.0, s.tts_timeout_s))
        t0 = time.perf_counter()
        try:
            res = await tts.synthesize("Avenza pre-flight check is complete.", None, "en")
            secs = time.perf_counter() - t0
            report(secs <= s.tts_timeout_s, f"YarnGPT replied in {secs:.1f}s ({len(res.pcm) / 2 / res.sample_rate:.1f}s of audio; budget TTS_TIMEOUT_S={s.tts_timeout_s:g})",
                   "slower than the budget: raise TTS_TIMEOUT_S, or the phone voice will take over")
        except Exception as exc:  # noqa: BLE001
            report(False, f"YarnGPT failed: {str(exc)[:160]}", "402 = top up credits; 401 = wrong key")
    cache = Path(s.tts_cache_dir) if s.tts_cache_dir else None
    n = len(list(cache.glob("*.pcm"))) if cache and cache.exists() else 0
    report(n >= 40 or None, f"fixed prompts cached on disk: {n}", "start Avenza once and wait for 'tts prewarm: ... cached'")

    print()
    print("READY FOR THE DEMO" if failures == 0 else f"{failures} problem(s) to fix first")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
