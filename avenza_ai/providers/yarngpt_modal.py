"""Self-hosted YarnGPT (open-source model on Modal) for Avenza's voice. 10 Nov 2026.

The team deployed the open-source YarnGPT model on Modal so a demo never runs
out of hosted-API credits. Its web endpoint (FastAPI, docs at ``/docs``)::

    POST https://<user>--yarngpt-yarngpt-tts.<region>.modal.run
    {"text": "...", "lang": "english", "speaker": "idera"}   ->  audio/wav

    GET  https://<user>--yarngpt-yarngpt-speakers.<region>.modal.run  -> the voices

The open-source model speaks English, Yoruba, Igbo and Hausa, each with its own
speakers, each with its own voices (``YARNGPT_MODAL_SPEAKERS``; defaults below).

A GPU container that has been idle takes about a minute to start, so the first
call after a pause is slow: the startup pre-warm (long timeout) wakes it, and a
live turn that times out falls back to the hosted API or the phone's voice.
The endpoint is unauthenticated: anyone with the URL can use it, so keep it out
of the repository (``YARNGPT_MODAL_URL`` in ``.env`` / ``.env.forge``).
"""
from __future__ import annotations

import base64
import json
import os
import time
from typing import Dict, Optional

import httpx

from ..types import NotConfigured, ProviderError, TTSProvider, TTSResult, Timing
from .audio import decode_audio_response

LANG_NAMES = {"en": "english", "yo": "yoruba", "ig": "igbo", "ha": "hausa", "pcm": "english"}
# The open-source YarnGPT2 deployment (deploy/modal/yarngpt_modal.py) has separate voices per language,
# and replaces an English voice sent with a local language by no voice at all (a random one each time).
# So each language gets one of its own voices; override with YARNGPT_MODAL_SPEAKERS="en=jude,yo=yoruba_male2".
DEFAULT_SPEAKERS = {"en": "idera", "yo": "yoruba_female2", "ig": "igbo_female2", "ha": "hausa_female1", "pcm": "idera"}


def parse_speakers(spec: str) -> Dict[str, str]:
    out = dict(DEFAULT_SPEAKERS)
    for item in (spec or "").split(","):
        if "=" in item:
            k, v = (x.strip() for x in item.split("=", 1))
            if k and v:
                out[k] = v
    return out


class ModalYarnGPTTTS(TTSProvider):
    name = "yarngpt-modal"
    MIN_CHARS = 2

    def __init__(self, url: Optional[str] = None, speakers: Optional[Dict[str, str]] = None,
                 timeout: float = 15.0, default_sample_rate: int = 24000,
                 client: Optional[httpx.AsyncClient] = None):
        self.url = (url if url is not None else os.getenv("YARNGPT_MODAL_URL", "")).strip().rstrip("/")
        self.speakers = speakers or parse_speakers(os.getenv("YARNGPT_MODAL_SPEAKERS", ""))
        self.timeout, self.default_sample_rate, self._client = timeout, default_sample_rate, client
        self.last_error: Optional[str] = None

    def is_configured(self) -> bool:
        return self.url.startswith("https://") or self.url.startswith("http://")

    def payload(self, text: str, voice: Optional[str], language: str) -> dict:
        lang = language if language in LANG_NAMES else "en"
        return {"text": text, "lang": LANG_NAMES[lang], "speaker": voice or self.speakers.get(lang, DEFAULT_SPEAKERS["en"])}

    async def synthesize(self, text: str, voice: Optional[str], language: str, timeout: Optional[float] = None) -> TTSResult:
        if not self.is_configured():
            raise NotConfigured("YARNGPT_MODAL_URL is not set")
        text = (text or "").strip()
        if len(text) < self.MIN_CHARS:
            raise ProviderError("nothing to synthesize")
        # Modal answers a request that runs past 150 s (a cold GPU start) with 303 See Other and a URL
        # where the result can be collected; following it is how the result is fetched (10 Nov).
        client = self._client or httpx.AsyncClient(timeout=httpx.Timeout(timeout or self.timeout, connect=10.0), follow_redirects=True)
        t0 = time.perf_counter()
        try:
            resp = await client.post(self.url, json=self.payload(text, voice, language), follow_redirects=True)
        except httpx.HTTPError as exc:
            self.last_error = f"{type(exc).__name__} after {(time.perf_counter() - t0) * 1000:.0f} ms"
            raise ProviderError(f"yarngpt-modal: {self.last_error}") from exc
        finally:
            if self._client is None:
                await client.aclose()
        elapsed_ms = (time.perf_counter() - t0) * 1000
        if resp.status_code != 200:
            self.last_error = f"HTTP {resp.status_code} {resp.text[:300]}"
            raise ProviderError(f"yarngpt-modal: {self.last_error}")
        data = resp.content
        ctype = resp.headers.get("content-type", "")
        if "json" in ctype:
            # tolerate {"audio": "<base64 wav>"} or {"audio_base64": ...} responses
            try:
                body = json.loads(data)
                b64 = body.get("audio") or body.get("audio_base64") or body.get("wav")
                data = base64.b64decode(b64) if b64 else b""
            except (ValueError, TypeError, AttributeError):
                data = b""
        if len(data) < 64:
            self.last_error = "empty audio response"
            raise ProviderError("yarngpt-modal: empty audio response")
        pcm, rate = decode_audio_response(data, self.default_sample_rate)
        self.last_error = None
        return TTSResult(pcm, rate, Timing(time_to_first_audio_ms=elapsed_ms))
