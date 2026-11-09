"""Measure Avenza's voice turn on the cluster, stage by stage, with real providers.

    kubectl exec deploy/app -- python scripts/latency_probe.py            # 5 turns
    kubectl exec deploy/app -- python scripts/latency_probe.py --turns 3
    kubectl exec deploy/app -- python scripts/latency_probe.py --text     # skip speech-to-text

For each turn:

1. YarnGPT (the configured TTS) speaks a payment request, e.g. "Send five
   thousand naira to GTBank account zero one two three nine eight seven zero
   zero one".
2. That audio is streamed to the configured speech-to-text (Sahara, Deepgram...)
   in 20 ms frames at real-time pace, like a phone would.
3. The real turn runs: intent, the Xtradot name enquiry, the read-back, and the
   read-back is synthesised by YarnGPT.
4. The draft is cancelled ("no"). No money moves.

Timings are written to /data/latency-probe.jsonl (separate from real phone
turns) and summarised at the end. It uses a temporary probe customer, not a
real enrolment, and about one bank request per turn (limit: 60 a minute).

What it does not include: the phone's microphone and VAD, the network between
the phone and the cluster, and audio playback on the phone. Real phone turns
are logged to /data/latency.jsonl; run scripts/latency_report.py on that.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
import uuid
from array import array

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Before importing the app: no background reconciler in this process, and a
# separate latency file so probe turns never mix with real phone turns.
os.environ["RECONCILE_INTERVAL_S"] = "0"
_data_dir = "/data" if os.path.isdir("/data") else "reports"
os.environ["LATENCY_LOG"] = os.environ.get("PROBE_LATENCY_LOG", f"{_data_dir}/latency-probe.jsonl")

from avenza.config import load_settings  # noqa: E402
from avenza.db import init_db  # noqa: E402
from avenza.main import create_app  # noqa: E402
from avenza.models import Device, User  # noqa: E402
from avenza.orchestrator import SessionContext  # noqa: E402

PHRASES = [
    "Send five thousand naira to GTBank account zero one two three nine eight seven zero zero one",
    "Send two thousand naira to Xtradot bank account zero nine eight seven six five four three two two",
    "Send ten thousand naira to Zenith bank account zero one two three nine eight seven zero zero two",
    "Send three thousand naira to UBA account zero one two three nine eight seven zero zero four",
    "Send one thousand five hundred naira to First Bank account zero one two three nine eight seven zero zero three",
]
STAGES = ["stt_ttfp_ms", "stt_final_ms", "stt_wait_ms", "intent_ms", "name_enquiry_ms", "tts_ttfa_ms", "reply_ms"]


def resample_16k(pcm: bytes, rate: int) -> bytes:
    """Linear resample of 16-bit mono PCM to 16 kHz (no extra dependencies)."""
    if rate == 16000 or not pcm:
        return pcm
    src = array("h")
    src.frombytes(pcm[: len(pcm) - (len(pcm) % 2)])
    n_out = int(len(src) * 16000 / rate)
    out = array("h", bytes(2 * n_out))
    step = rate / 16000
    last = len(src) - 1
    for i in range(n_out):
        x = i * step
        j = int(x)
        frac = x - j
        a = src[j]
        b = src[j + 1] if j < last else a
        out[i] = int(a + (b - a) * frac)
    return out.tobytes()


def probe_customer(app) -> SessionContext:
    """A throwaway customer that can draft but never approve (no passkey)."""
    devices, sessions = app.state.devices, app.state.sessions
    with app.state.session_factory() as db:
        user = User(id=f"usr_probe_{uuid.uuid4().hex[:10]}", display_name="Latency probe", language="en")
        db.add(user)
        device = Device(
            id=f"dev_probe_{uuid.uuid4().hex[:10]}",
            user_id=user.id,
            credential_id=f"probe-{uuid.uuid4().hex}",
            public_key=b"",
            device_token_hash=uuid.uuid4().hex,
        )
        db.add(device)
        db.commit()
        user_id, device_id = user.id, device.id
    consent = devices.record_consent(user_id=user_id, wording_version="probe", language="en")
    consent_id = consent.id if hasattr(consent, "id") else consent["consent_id"]
    session = sessions.start(user_id=user_id, device_id=device_id, consent_id=consent_id)
    return SessionContext(session_id=session.id, user_id=user_id, device_id=device_id, language="en")


async def speak(tts, text: str) -> tuple[bytes, int]:
    result = await tts.synthesize(text, language="en")
    if result.is_empty:
        raise RuntimeError(f"TTS returned no audio: {getattr(tts, 'last_error', None) or 'see logs'}")
    return result.pcm, int(result.sample_rate)


async def listen(stt, pcm16: bytes):
    """Stream 20 ms frames at real-time pace, then end the utterance."""
    stream = stt.stream("en", 16000)
    frame = 640  # 20 ms of 16 kHz 16-bit mono
    for i in range(0, len(pcm16), frame):
        await stream.push(pcm16[i : i + frame])
        await asyncio.sleep(0.02)
    started = time.perf_counter()
    result = await stream.end()
    return result, int((time.perf_counter() - started) * 1000)


async def run(turns: int, text_only: bool) -> int:
    settings = load_settings()
    app = create_app(settings)
    init_db(app.state.engine)
    o, stt, tts = app.state.orchestrator, app.state.stt, app.state.tts
    print(f"STT: {stt.name} (simulated={stt.simulated})   TTS: {tts.name} (simulated={tts.simulated})   bank: {settings.bank_mode}")
    use_speech = not text_only and not stt.simulated and not tts.simulated
    if not use_speech and not text_only:
        print("Real STT or TTS is not configured, so this run sends text (no speech stages).")
    ctx = probe_customer(app)
    log_path = os.environ["LATENCY_LOG"]
    failures = 0

    for n in range(turns):
        phrase = PHRASES[n % len(PHRASES)]
        print(f"\n--- turn {n + 1}: \"{phrase}\"")
        try:
            if use_speech:
                t0 = time.perf_counter()
                pcm, rate = await speak(tts, phrase)
                print(f"  TTS made {len(pcm) / 2 / rate:.1f}s of audio at {rate} Hz in {int((time.perf_counter() - t0) * 1000)} ms")
                pcm16 = resample_16k(pcm, rate)
                transcript, wait_ms = await listen(stt, pcm16)
                if transcript.error and transcript.error != "no_speech":
                    print(f"  STT ERROR: {transcript.error}")
                    failures += 1
                    continue
                print(f"  STT heard: \"{transcript.text}\" (confidence {transcript.confidence:.2f})")
                events = await o.process_audio(ctx, pcm16, 16000, transcript=transcript, vad_ms=0, stt_wait_ms=wait_ms)
            else:
                events = await o.process_audio(ctx, b"", 16000, provided_text=phrase)
            events = await o.render_audio(ctx, events)
            o.finish_turn(ctx, events)
            prompts = [e for e in events if e.get("type") == "prompt.play"]
            last = prompts[-1] if prompts else {}
            voiced = "YarnGPT audio" if last.get("audio") else f"no server audio ({last.get('tts_error', 'device voice')})"
            print(f"  Avenza said [{last.get('id')}, {voiced}]: {str(last.get('text', ''))[:110]}")
            with open(log_path, encoding="utf-8") as fh:
                record = json.loads(fh.readlines()[-1])
            print("  " + "  ".join(f"{k.replace('_ms', '')}={record[k]}ms" for k in STAGES if k in record))
            if last.get("id") != "readback":
                failures += 1
        except Exception as exc:  # noqa: BLE001 - report and continue
            failures += 1
            print(f"  FAILED: {type(exc).__name__}: {exc}")
        finally:
            # Cancel any draft: no money moves, and the next turn can start.
            try:
                await o.process_text(ctx, "no")
            except Exception:  # noqa: BLE001
                pass

    print(f"\nWrote {turns} turn(s) to {log_path}\n")
    from scripts.latency_report import main as report

    report([log_path])
    return 1 if failures else 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--turns", type=int, default=5)
    parser.add_argument("--text", action="store_true", help="send text instead of speech (no STT stages)")
    args = parser.parse_args()
    raise SystemExit(asyncio.run(run(max(1, min(args.turns, 20)), args.text)))
