"""YarnGPT text-to-speech for spoken replies (API v1, "Conversation").

Uses the real-time single-turn route, which returns raw audio in the response.
``voice`` is required on this route (422 "Field required" without it, seen on
9 Nov 2026), so when none is configured the account's default voice from
GET /api/v1/voices is used.


    POST https://api.yarngpt.ai/api/v1/streaming/conversation
    Authorization: Bearer <key>
    Idempotency-Key: <fresh per turn>   (optional; avoids a double charge on retry)
    {"text": "...", "voice": "<id>", "output_format": "pcm"}

PCM comes back as raw signed 16-bit little-endian with ``Content-Type:
audio/l16; rate=<N>; channels=1``: the sample rate is read from that header,
never assumed. Text is 1-5,000 characters. Errors use the YarnGPT envelope
``{"error": {"code", "message", "trace_id", ...}}``.

The job route (POST /api/v1/tts) is asynchronous (job_id + polling) and is
not suitable for a voice turn, so a URL pointing at it, or at the ASR stream,
is replaced by the conversation route.
"""
from __future__ import annotations

import logging
import os
import re
import time
import uuid
from typing import Optional

import httpx

from ..types import NotConfigured, ProviderError, TTSProvider, TTSResult, Timing
from .audio import decode_audio_response

logger = logging.getLogger("avenza_ai.yarngpt_tts")

YARNGPT_BASE_URL = "https://api.yarngpt.ai"
CONVERSATION_PATH = "/api/v1/streaming/conversation"
MAX_CHARS = 5000


def conversation_url(configured: Optional[str]) -> str:
    base = os.getenv("YARNGPT_BASE_URL", YARNGPT_BASE_URL).rstrip("/")
    url = (configured or "").strip()
    if not url:
        return base + CONVERSATION_PATH
    if url.startswith(("ws://", "wss://")) or "/asr" in url or url.rstrip("/").endswith("/api/v1/tts"):
        fixed = re.sub(r"^wss?://", "https://", url.split("/api/")[0]) + CONVERSATION_PATH
        logger.warning("YARNGPT_TTS_URL %s is not the conversation route; using %s", url, fixed)
        return fixed
    return url


class YarnGPTTTS(TTSProvider):
    name = "yarngpt"

    def __init__(self, api_key: Optional[str] = None, url: Optional[str] = None,
                 default_voice: Optional[str] = None, response_format: str = "pcm",
                 default_sample_rate: int = 24000, timeout: float = 15.0,
                 client: Optional[httpx.AsyncClient] = None):
        self.api_key = api_key if api_key is not None else os.getenv("YARNGPT_API_KEY", "")
        self.url = conversation_url(url if url is not None else os.getenv("YARNGPT_TTS_URL", ""))
        self.default_voice = default_voice or os.getenv("YARNGPT_DEFAULT_VOICE") or None
        self.response_format, self.default_sample_rate = response_format, default_sample_rate
        self.timeout, self._client = timeout, client
        self.last_error: Optional[str] = None
        self._resolved_voice: Optional[str] = None

    async def _voice(self, client: httpx.AsyncClient) -> Optional[str]:
        """The configured voice, else the catalogue default (looked up once)."""
        if self.default_voice:
            return self.default_voice
        if self._resolved_voice:
            return self._resolved_voice
        base = self.url.split("/api/")[0]
        try:
            resp = await client.get(f"{base}/api/v1/voices", headers={"Authorization": f"Bearer {self.api_key}"})
            voices = resp.json() if resp.status_code == 200 else []
        except (httpx.HTTPError, ValueError):
            voices = []
        if isinstance(voices, dict):
            voices = voices.get("voices") or voices.get("data") or []
        names = [v for v in voices if isinstance(v, dict) and v.get("name")]
        chosen = next((v["name"] for v in names if v.get("default")), None) or (names[0]["name"] if names else None)
        if chosen:
            self._resolved_voice = chosen
            logger.info("YARNGPT_DEFAULT_VOICE not set; using %s", chosen)
        return chosen

    def is_configured(self) -> bool:
        return bool(self.api_key)

    async def synthesize(self, text: str, voice: Optional[str], language: str) -> TTSResult:
        if not self.is_configured():
            raise NotConfigured("YARNGPT_API_KEY is not set")
        text = (text or "").strip()
        if not text:
            raise ProviderError("nothing to synthesize")
        client = self._client or httpx.AsyncClient(timeout=self.timeout)
        payload = {"text": text[:MAX_CHARS], "output_format": self.response_format}
        v = voice or await self._voice(client)
        if v:
            payload["voice"] = v
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Idempotency-Key": uuid.uuid4().hex,
            "Content-Type": "application/json",
        }
        t0 = time.perf_counter()
        first_audio_ms: Optional[float] = None
        chunks: list[bytes] = []
        try:
            async with client.stream("POST", self.url, json=payload, headers=headers) as resp:
                if resp.status_code != 200:
                    body = await resp.aread()
                    self.last_error = _error_text(resp.status_code, body, resp.headers.get("x-request-id"))
                    raise ProviderError(f"yarngpt tts: {self.last_error}")
                content_type = resp.headers.get("content-type", "")
                async for chunk in resp.aiter_bytes():
                    if chunk and first_audio_ms is None:
                        first_audio_ms = (time.perf_counter() - t0) * 1000
                    chunks.append(chunk)
        except httpx.HTTPError as exc:
            self.last_error = f"{type(exc).__name__}: {exc}"
            raise ProviderError(f"yarngpt tts: {self.last_error}") from exc
        finally:
            if self._client is None:
                await client.aclose()
        data = b"".join(chunks)
        if len(data) < 2:
            self.last_error = "empty audio response"
            raise ProviderError("yarngpt tts: empty audio response")
        if "audio/l16" in content_type or "audio/pcm" in content_type:
            match = re.search(r"rate=(\d+)", content_type)
            rate = int(match.group(1)) if match else self.default_sample_rate
            pcm = data[: len(data) - (len(data) % 2)]
        else:
            pcm, rate = decode_audio_response(data, self.default_sample_rate)
        self.last_error = None
        return TTSResult(pcm, rate, Timing(time_to_first_audio_ms=first_audio_ms))


def _error_text(status: int, body: bytes, request_id: Optional[str]) -> str:
    import json

    code = message = ""
    try:
        err = json.loads(body or b"{}").get("error") or {}
        code, message = str(err.get("code", "")), str(err.get("message", ""))
        request_id = err.get("trace_id") or request_id
    except (ValueError, AttributeError):
        message = (body or b"")[:120].decode("utf-8", "replace")
    return f"HTTP {status} {code} {message} trace={request_id or '-'}".strip()
