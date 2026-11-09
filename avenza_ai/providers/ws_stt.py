"""WebSocket speech-to-text providers: Deepgram (concrete) and YarnGPT/Sahara (CONFIRM scaffolds)."""
from __future__ import annotations

import asyncio
import json
import os
from typing import Dict, List, Optional
from urllib.parse import urlencode

from ..types import (NotConfigured, ProviderError, STTProvider, STTStream, TranscriptEvent,
                     UnsupportedLanguage)


class _WSStream(STTStream):
    def __init__(self, provider: "WebSocketSTTProvider", language: str, sample_rate: int):
        super().__init__()
        self._p, self._lang, self._rate = provider, language, sample_rate
        self._ws = None
        self._reader: Optional[asyncio.Task] = None
        self._open_lock = asyncio.Lock()
        self._state: dict = {}  # per-stream scratch space for provider framing

    async def _ensure_open(self) -> None:
        async with self._open_lock:
            if self._ws is not None:
                return
            if not self._p.is_configured():
                raise NotConfigured(f"{self._p.name} is not configured (see .env.example)")
            from websockets.asyncio.client import connect  # imported lazily

            try:
                self._ws = await connect(self._p.url(self._lang, self._rate),
                                         additional_headers=self._p.headers(),
                                         open_timeout=self._p.connect_timeout, max_size=None)
                start = self._p.start_message(self._lang, self._rate)
                if start:
                    await self._ws.send(start)
                # Some providers must confirm the session before audio is sent.
                await asyncio.wait_for(self._p.await_ready(self._ws), self._p.connect_timeout)
            except ProviderError:
                raise
            except Exception as exc:  # noqa: BLE001
                raise ProviderError(f"{self._p.name}: could not connect: {exc}") from exc
            self._reader = asyncio.create_task(self._read())

    async def _read(self) -> None:
        try:
            async for msg in self._ws:
                if isinstance(msg, str):
                    for ev in self._p.parse_message(msg):
                        self._emit(ev)
        except Exception as exc:  # noqa: BLE001
            self._emit_error(ProviderError(f"{self._p.name}: {exc}"))
            return
        self._emit_end()

    async def _send(self, pcm: bytes) -> None:
        await self._ensure_open()
        for message in self._p.frame_audio(self._state, pcm):
            await self._ws.send(message)

    async def _finish(self) -> None:
        await self._ensure_open()
        for message in self._p.flush_audio(self._state):
            await self._ws.send(message)
        end = self._p.end_message()
        if end is not None:
            await self._ws.send(end)

    async def aclose(self) -> None:
        if self._reader and not self._reader.done():
            try:
                await asyncio.wait_for(asyncio.shield(self._reader), 0.05)
            except Exception:  # noqa: BLE001
                pass
        if self._ws is not None:
            try:
                await self._ws.close()
            except Exception:  # noqa: BLE001
                pass
        if self._reader and not self._reader.done():
            self._reader.cancel()
        self._emit_end()


class WebSocketSTTProvider(STTProvider):
    """Subclasses define url/headers/messages. One stream per turn."""

    connect_timeout = 5.0

    def stream(self, language_hint: str, sample_rate: int) -> STTStream:
        if not self.supports(language_hint):
            raise UnsupportedLanguage(f"{self.name} does not support {language_hint}")
        return _WSStream(self, language_hint, sample_rate)

    # hooks -------------------------------------------------------------------------
    def url(self, language: str, sample_rate: int) -> str: raise NotImplementedError
    def headers(self) -> Dict[str, str]: return {}
    def start_message(self, language: str, sample_rate: int) -> Optional[str]: return None
    async def await_ready(self, ws) -> None: return None
    def frame_audio(self, state: dict, pcm: bytes) -> list: return [pcm]
    def flush_audio(self, state: dict) -> list: return []
    def end_message(self) -> Optional[str]: return None
    def parse_message(self, raw: str) -> List[TranscriptEvent]: raise NotImplementedError


class DeepgramSTTProvider(WebSocketSTTProvider):
    """Deepgram live streaming (wss://api.deepgram.com/v1/listen).

    Deepgram is the reliable English baseline. It may not cover Yoruba, Hausa or
    Igbo: the language test decides. Override the map with DEEPGRAM_LANG_MAP,
    e.g. 'ha=sw' (never do this without measuring the result).
    """

    name = "deepgram"
    DEFAULT_LANGS = {"en": "en", "pcm": "en"}

    def __init__(self, api_key: Optional[str] = None, model: Optional[str] = None,
                 base_url: str = "wss://api.deepgram.com/v1/listen", endpointing_ms: int = 300,
                 lang_map: Optional[Dict[str, str]] = None):
        self.api_key = api_key if api_key is not None else os.getenv("DEEPGRAM_API_KEY", "")
        self.model = model or os.getenv("DEEPGRAM_MODEL", "nova-2")
        self.base_url, self.endpointing_ms = base_url, endpointing_ms
        self.lang_map = dict(self.DEFAULT_LANGS)
        env_map = os.getenv("DEEPGRAM_LANG_MAP", "")
        for pair in filter(None, env_map.split(",")):
            k, _, v = pair.partition("=")
            self.lang_map[k.strip()] = v.strip()
        if lang_map:
            self.lang_map.update(lang_map)

    def is_configured(self) -> bool:
        return bool(self.api_key)

    def supports(self, language: str) -> bool:
        return language in self.lang_map

    def url(self, language: str, sample_rate: int) -> str:
        q = {"model": self.model, "language": self.lang_map[language], "encoding": "linear16",
             "sample_rate": sample_rate, "channels": 1, "interim_results": "true",
             "punctuate": "false", "endpointing": self.endpointing_ms}
        return f"{self.base_url}?{urlencode(q)}"

    def headers(self) -> Dict[str, str]:
        return {"Authorization": f"Token {self.api_key}"}

    def end_message(self) -> Optional[str]:
        return json.dumps({"type": "CloseStream"})

    def parse_message(self, raw: str) -> List[TranscriptEvent]:
        try:
            msg = json.loads(raw)
        except json.JSONDecodeError:
            return []
        if msg.get("type") == "Error" or "err_code" in msg:
            raise ProviderError(f"deepgram error: {msg.get('description') or msg.get('err_msg') or msg}")
        if msg.get("type") != "Results":
            return []
        alts = (msg.get("channel") or {}).get("alternatives") or []
        if not alts:
            return []
        text = (alts[0].get("transcript") or "").strip()
        if not text:
            return []
        return [TranscriptEvent(text, bool(msg.get("is_final")), alts[0].get("confidence"))]


class _GenericWSProvider(WebSocketSTTProvider):
    """CONFIRM scaffold for providers whose live-ASR protocol is not documented to us yet.

    Assumptions to verify on Day 1 (change the hooks if they differ):
    - URL comes from <PREFIX>_ASR_WS_URL, key from <PREFIX>_API_KEY as a Bearer token.
    - Audio is sent as binary 16-bit mono PCM frames.
    - Replies are JSON with a text under 'transcript' or 'text' and a final flag.
    Until the URL is set, is_configured() is False and the language test skips this provider.
    """

    prefix = "GENERIC"
    cumulative_finals = False

    def __init__(self, url: Optional[str] = None, api_key: Optional[str] = None,
                 languages: Optional[Dict[str, str]] = None):
        self._url = url if url is not None else os.getenv(f"{self.prefix}_ASR_WS_URL", "")
        self._key = api_key if api_key is not None else os.getenv(f"{self.prefix}_API_KEY", "")
        # language code sent to the provider; CONFIRM which of yo/ha/ig/en it accepts
        self.languages = languages or {"en": "en", "yo": "yo", "ha": "ha", "ig": "ig", "pcm": "pcm"}

    def is_configured(self) -> bool:
        return bool(self._url)

    def supports(self, language: str) -> bool:
        return language in self.languages

    def url(self, language: str, sample_rate: int) -> str:
        sep = "&" if "?" in self._url else "?"
        return f"{self._url}{sep}{urlencode({'language': self.languages[language], 'sample_rate': sample_rate})}"

    def headers(self) -> Dict[str, str]:
        return {"Authorization": f"Bearer {self._key}"} if self._key else {}

    def parse_message(self, raw: str) -> List[TranscriptEvent]:
        try:
            msg = json.loads(raw)
        except json.JSONDecodeError:
            return []
        if not isinstance(msg, dict):
            return []
        if msg.get("error"):
            raise ProviderError(f"{self.name} error: {msg['error']}")
        body = msg.get("result") if isinstance(msg.get("result"), dict) else msg
        text = (body.get("transcript") or body.get("text") or "").strip()
        if not text:
            return []
        final = body.get("is_final", body.get("final", body.get("isFinal", msg.get("type") == "final")))
        return [TranscriptEvent(text, bool(final), body.get("confidence"))]


YARNGPT_BASE_URL = "https://api.yarngpt.ai"


class YarnGPTSTTProvider(_GenericWSProvider):
    """YarnGPT live transcription (API v1, "Live transcription (streaming)").

    Protocol, from the YarnGPT docs:
    - WebSocket ``wss://api.yarngpt.ai/api/v1/asr/stream``, no query parameters,
      key as ``Authorization: Bearer`` in the handshake.
    - First a text ``start`` message declaring pcm_s16le mono audio and its rate,
      then binary PCM at real-time pace (max 2x after a 5 s allowance, at most
      65,536 bytes per message), then ``{"type":"finalize"}``.
    - Replies: ``status``, ``started``, ``partial`` (may change), ``final``
      (fixed), ``done``, or a single ``error``. The transcript is every final's
      text in segment order. There is no language hint and no confidence.
    """

    name = "yarngpt"
    prefix = "YARNGPT"
    cumulative_finals = False
    # 5 s may be sent at once, then at most twice real time (with a margin).
    pace = (4.0, 1.8)

    def __init__(self, url: Optional[str] = None, api_key: Optional[str] = None,
                 languages: Optional[Dict[str, str]] = None, endpoint_silence_ms: int = 500):
        base = os.getenv("YARNGPT_BASE_URL", YARNGPT_BASE_URL).rstrip("/")
        default_url = base.replace("https://", "wss://").replace("http://", "ws://") + "/api/v1/asr/stream"
        super().__init__(url=url or os.getenv("YARNGPT_ASR_WS_URL") or default_url,
                         api_key=api_key, languages=languages)
        self.endpoint_silence_ms = max(200, min(3000, endpoint_silence_ms))

    def is_configured(self) -> bool:
        return bool(self._url and self._key)

    def supports(self, language: str) -> bool:
        return True  # no language parameter: the model covers its own language list

    def url(self, language: str, sample_rate: int) -> str:
        return self._url  # "There are no query parameters"

    def start_message(self, language: str, sample_rate: int) -> Optional[str]:
        return json.dumps({
            "type": "start",
            "audio": {"encoding": "pcm_s16le", "sample_rate": int(sample_rate), "channels": 1},
            "options": {"endpoint_silence_ms": self.endpoint_silence_ms, "partials": True},
        })

    def end_message(self) -> Optional[str]:
        return json.dumps({"type": "finalize"})

    def parse_message(self, raw: str) -> List[TranscriptEvent]:
        try:
            msg = json.loads(raw)
        except json.JSONDecodeError:
            return []
        if not isinstance(msg, dict):
            return []
        kind = msg.get("type")
        if kind == "error":
            err = msg.get("error") if isinstance(msg.get("error"), dict) else {}
            raise ProviderError(
                f"yarngpt asr: {err.get('code', 'ERROR')} {err.get('message', '')} trace={err.get('trace_id', '-')}"
            )
        if kind in ("partial", "final"):
            text = str(msg.get("text") or "").strip()
            if text:
                return [TranscriptEvent(text, kind == "final", None)]
        return []  # status, started, done, translation, and unknown types


INTRON_STREAM_URL = "wss://infer.voice.intron.io/stt/v1/stream"


class SaharaSTTProvider(_GenericWSProvider):
    """Intron Sahara streaming speech-to-text (docs.voice.intron.io/docs/stt/streaming).

    Protocol, from Intron's documentation:
    - ``wss://infer.voice.intron.io/stt/v1/stream?use_language_asr_input=<code>
      &sample_rate=16000&bit_rate=16&num_channels=1`` with ``Authorization: Bearer``.
    - Wait for ``SESSION_CREATED`` before sending audio.
    - Audio goes as JSON text frames ``{"message_type": "INPUT_AUDIO_CHUNK",
      "audio_base_64": ...}``; each chunk 1-32 KB of PCM16.
    - ``{"message_type": "COMMIT"}`` ends the utterance; the server answers
      ``COMMITTED_TRANSCRIPT`` (``transcript_text``) and closes.
    - Partial text arrives as ``PARTIAL_TRANSCRIPT`` (``transcript``).
    - Limits: 3 connections a minute, 3 at once, 300 s per session.
    Language codes: only ``en`` is confirmed in the docs; override others with
    SAHARA_LANG_MAP, e.g. ``pcm=en,yo=yo``.
    """

    name = "sahara"
    prefix = "SAHARA"
    cumulative_finals = False
    MIN_CHUNK = 1024
    TARGET_CHUNK = 8000  # 0.25 s at 16 kHz, as in Intron's example
    MAX_CHUNK = 32 * 1024
    ERRORS = {
        "ERROR", "INPUT_ERROR", "AUTHENTICATION_ERROR", "RESOURCE_EXHAUSTED", "QUOTA_EXCEEDED",
        "CHUNK_SIZE_TOO_SMALL", "CHUNK_SIZE_TOO_LARGE", "INSUFFICIENT_AUDIO_ACTIVITY",
        "SESSION_TIME_LIMIT_EXCEEDED", "CHUNK_ID_MISMATCH_WITH_TOTAL",
    }

    def __init__(self, url: Optional[str] = None, api_key: Optional[str] = None,
                 languages: Optional[Dict[str, str]] = None):
        langs = {"en": "en", "pcm": "pcm", "yo": "yo", "ha": "ha", "ig": "ig"}
        for item in os.getenv("SAHARA_LANG_MAP", "").split(","):
            if "=" in item:
                k, v = (x.strip() for x in item.split("=", 1))
                if k and v:
                    langs[k] = v
        super().__init__(url=url or os.getenv("SAHARA_ASR_WS_URL") or INTRON_STREAM_URL,
                         api_key=api_key, languages=languages or langs)
        self._url = self._url.split("?")[0]

    def is_configured(self) -> bool:
        return bool(self._url and self._key)

    def url(self, language: str, sample_rate: int) -> str:
        return f"{self._url}?" + urlencode({
            "sample_rate": int(sample_rate), "bit_rate": 16, "num_channels": 1,
            "use_language_asr_input": self.languages.get(language, language),
        })

    async def await_ready(self, ws) -> None:
        async for raw in ws:
            if not isinstance(raw, str):
                continue
            msg = json.loads(raw)
            kind = msg.get("message_type")
            if kind == "SESSION_CREATED":
                return
            if kind in self.ERRORS:
                raise ProviderError(f"sahara: {kind} {msg.get('message') or msg.get('status') or ''}".strip())
        raise ProviderError("sahara: connection closed before SESSION_CREATED")

    def _chunk(self, pcm: bytes) -> str:
        import base64

        return json.dumps({"message_type": "INPUT_AUDIO_CHUNK",
                           "audio_base_64": base64.b64encode(pcm).decode("ascii")})

    def frame_audio(self, state: dict, pcm: bytes) -> list:
        # Buffer to 1-32 KB chunks: browser frames are often smaller than 1 KB.
        buf = state.setdefault("buf", bytearray())
        buf.extend(pcm)
        out = []
        while len(buf) >= self.TARGET_CHUNK:
            out.append(self._chunk(bytes(buf[: self.TARGET_CHUNK])))
            del buf[: self.TARGET_CHUNK]
        return out

    def flush_audio(self, state: dict) -> list:
        buf = state.get("buf") or bytearray()
        if not buf:
            return []
        tail = bytes(buf)
        state["buf"] = bytearray()
        if len(tail) % 2:
            tail = tail[:-1]
        if len(tail) < self.MIN_CHUNK:
            tail = tail + b"\x00" * (self.MIN_CHUNK - len(tail))  # pad with silence, never drop speech
        return [self._chunk(tail[i : i + self.MAX_CHUNK]) for i in range(0, len(tail), self.MAX_CHUNK)]

    def end_message(self) -> Optional[str]:
        return json.dumps({"message_type": "COMMIT"})

    def parse_message(self, raw: str) -> List[TranscriptEvent]:
        try:
            msg = json.loads(raw)
        except json.JSONDecodeError:
            return []
        if not isinstance(msg, dict):
            return []
        kind = msg.get("message_type")
        if kind in self.ERRORS:
            raise ProviderError(f"sahara: {kind} {msg.get('message') or msg.get('status') or ''}".strip())
        if kind == "PARTIAL_TRANSCRIPT":
            text = str(msg.get("transcript") or "").strip()
            return [TranscriptEvent(text, False, None)] if text else []
        if kind == "COMMITTED_TRANSCRIPT":
            text = str(msg.get("transcript_text") or "").strip()
            return [TranscriptEvent(text, True, None)] if text else []
        return []  # SESSION_CREATED, AUDIO_CHUNK_ACK, unknown types
