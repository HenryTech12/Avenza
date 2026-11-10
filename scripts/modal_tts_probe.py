"""Measure the self-hosted YarnGPT on Modal: cold start, warm speed, and each language's speaker.

    python scripts/modal_tts_probe.py                 # uses YARNGPT_MODAL_URL from .env
    python scripts/modal_tts_probe.py --url https://...modal.run --save

Prints, per call: language, speaker, seconds, audio seconds produced. With --save
the clips are written to reports/modal-<lang>.wav so you can listen to them.
The first call after the container has been idle includes the GPU start (about a minute).
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dotenv import load_dotenv  # noqa: E402

from avenza_ai.providers.audio import pcm_to_wav_bytes  # noqa: E402
from avenza_ai.providers.yarngpt_modal import ModalYarnGPTTTS, parse_speakers  # noqa: E402

LINES = {
    "en": "You are about to send five thousand naira to Chukwuemeka Ifeanyi Nwosu at GTBank. Say yes to continue.",
    "yo": "O fẹ́ fi ẹgbẹ̀rún márùn-ún náírà ránṣẹ́. Sọ bẹ́ẹ̀ni láti tẹ̀síwájú.",
    "ha": "Za ka aika naira dubu biyar. Ka ce eh don ci gaba.",
    "ig": "Ị chọrọ iziga puku naira ise. Kwuo ee iji gaa n'ihu.",
}


async def main() -> int:
    load_dotenv(Path(__file__).resolve().parents[1] / ".env")
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default=os.getenv("YARNGPT_MODAL_URL", ""))
    ap.add_argument("--langs", default="en,en,yo,ha,ig", help="calls in order; en twice shows cold then warm")
    ap.add_argument("--save", action="store_true")
    args = ap.parse_args()
    if not args.url:
        print("Set YARNGPT_MODAL_URL in .env or pass --url", file=sys.stderr)
        return 2
    tts = ModalYarnGPTTTS(url=args.url, speakers=parse_speakers(os.getenv("YARNGPT_MODAL_SPEAKERS", "")), timeout=180)
    for lang in [x.strip() for x in args.langs.split(",") if x.strip()]:
        text = LINES.get(lang, LINES["en"])
        t0 = time.perf_counter()
        try:
            res = await tts.synthesize(text, None, lang)
        except Exception as exc:  # noqa: BLE001
            print(f"{lang:3} {tts.speakers.get(lang):16} FAILED after {time.perf_counter() - t0:5.1f}s: {exc}")
            continue
        secs = time.perf_counter() - t0
        audio_s = len(res.pcm) / 2 / res.sample_rate
        print(f"{lang:3} {tts.speakers.get(lang):16} {secs:5.1f}s for {audio_s:4.1f}s of audio at {res.sample_rate} Hz ({len(text)} chars)")
        if args.save:
            out = Path("reports") / f"modal-{lang}.wav"
            out.parent.mkdir(exist_ok=True)
            out.write_bytes(pcm_to_wav_bytes(res.pcm, res.sample_rate))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
