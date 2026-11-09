"""AI speech providers adapted to the backend ``STTProvider`` / ``TTSProvider`` contracts.

The AI package speaks a streaming protocol (``send_audio`` / ``finish`` /
``events``). The backend orchestrator consumes a single ``transcribe`` result, so
these adapters use the AI package's own ``transcribe`` convenience wrapper. No
behaviour in the approval path changes: speech only produces text.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Awaitable, Callable

from avenza_ai.providers import (
    DeepgramSTTProvider,
    ProviderChoice,
    SaharaSTTProvider,
    YarnGPTSTTProvider,
    YarnGPTTTS,
)
from avenza_ai.types import NotConfigured, ProviderError

from ..config import Settings
from .base import AudioResult, ProviderNotConfigured, STTProvider, STTStream, TranscriptResult, TTSProvider

logger = logging.getLogger("avenza.stt")

PartialCallback = Callable[[str], Awaitable[None]]


class AILiveStream(STTStream):
    """One live speech-to-text stream per turn.

    Audio frames are forwarded to the provider while the customer speaks, so
    the final transcript is ready almost as soon as VAD ends the utterance.
    Interim text is passed to ``on_partial`` for ``transcript.partial`` events.
    """

    def __init__(self, owner: "AIWebSocketSTT", language_hint: str, sample_rate: int):
        self.owner = owner
        self.language_hint = language_hint
        self.language, self.provider = owner._provider_for(language_hint)
        self.sample_rate = sample_rate
        self.on_partial: PartialCallback | None = None
        self._stream = None
        self._task: asyncio.Task | None = None
        self._finals: list = []
        self._interim = ""
        self._error: BaseException | None = None
        self._started = time.perf_counter()

    async def _ensure(self) -> None:
        if self._stream is None:
            self._stream = self.provider.stream(self.language, self.sample_rate)
            self._task = asyncio.create_task(self._consume())

    async def _consume(self) -> None:
        try:
            async for event in self._stream.events():
                if event.is_final:
                    self._finals.append(event)
                    self._interim = ""
                else:
                    self._interim = event.text
                if self.on_partial is not None:
                    text = " ".join([f.text for f in self._finals] + ([self._interim] if self._interim else []))
                    try:
                        await self.on_partial(text.strip())
                    except Exception:  # noqa: BLE001 - display only
                        pass
        except Exception as exc:  # noqa: BLE001
            self._error = exc

    async def push(self, pcm: bytes) -> None:
        await self._ensure()
        await self._stream.send_audio(pcm)

    async def abort(self) -> None:
        if self._stream is not None:
            try:
                await self._stream.aclose()
            except Exception:  # noqa: BLE001
                pass
        if self._task is not None and not self._task.done():
            self._task.cancel()

    async def end(self) -> TranscriptResult:
        name = f"ai:{self.provider.name}"
        try:
            await self._ensure()
            await self._stream.finish()
            await asyncio.wait_for(asyncio.shield(self._task), self.owner.settings.ai_stt_timeout_s)
        except Exception as exc:  # noqa: BLE001
            await self.abort()
            return TranscriptResult(
                "", 0.0, name, language=self.language, error=f"ai_stt_error:{type(exc).__name__}"
            )
        finally:
            if self._stream is not None:
                try:
                    await self._stream.aclose()
                except Exception:  # noqa: BLE001
                    pass
        if self._error is not None:
            return TranscriptResult(
                "", 0.0, name, language=self.language, error=f"ai_stt_error:{type(self._error).__name__}"
            )
        text = " ".join(f.text.strip() for f in self._finals if f.text.strip()).strip()
        confs = [f.confidence for f in self._finals if f.confidence is not None]
        timing = self._stream.timing
        return TranscriptResult(
            text=text,
            confidence=float(sum(confs) / len(confs)) if confs else 0.0,
            provider=name,
            ttfp_ms=int(timing.time_to_first_partial_ms or 0),
            final_ms=int(timing.time_to_final_ms or 0),
            language=self.language,
            simulated=False,
            error=None if text else "no_speech",
        )


_STT_NAMES = {"deepgram", "yarngpt", "sahara"}


def _choice_from_settings(settings: Settings) -> ProviderChoice:
    """AI_STT_CHOICE ("en=sahara,pcm=sahara") wins over the language-test file.

    Lets the team pick a provider per language on the cluster, where the
    language-test output (reports/provider_choice.json) is not in the image.
    """
    raw = settings.ai_stt_choice
    if not raw:
        return ProviderChoice.load(settings.ai_provider_choice)
    choice: dict[str, str] = {}
    for item in raw.split(","):
        if "=" not in item:
            continue
        language, provider = (part.strip().lower() for part in item.split("=", 1))
        if language and provider in _STT_NAMES:
            choice[language] = provider
    if not choice:
        raise ProviderNotConfigured(f"AI_STT_CHOICE has no valid entries: {raw!r}")
    return ProviderChoice(choice, list(choice))


class AIWebSocketSTT(STTProvider):
    """Language-aware streaming STT from the AI provider registry."""

    name = "ai"
    simulated = False

    def __init__(self, settings: Settings):
        self.settings = settings
        self.choice = _choice_from_settings(settings)
        self.default_language = settings.ai_default_language
        self.factories = {
            "deepgram": lambda: DeepgramSTTProvider(
                api_key=settings.deepgram_api_key,
                model=settings.deepgram_model,
            ),
            "yarngpt": lambda: YarnGPTSTTProvider(
                url=settings.yarngpt_asr_url or settings.yarn_asr_url or None,
                api_key=settings.yarngpt_api_key or settings.yarn_api_key or None,
            ),
            "sahara": lambda: SaharaSTTProvider(
                url=settings.sahara_asr_url or None,
                api_key=settings.sahara_api_key or None,
            ),
        }
        try:
            default = self.choice.stt_for(self.default_language, self.factories)
        except (KeyError, LookupError) as exc:
            raise ProviderNotConfigured(f"AI STT default language unavailable: {exc}") from exc
        if not default.is_configured():
            raise ProviderNotConfigured(
                f"AI STT provider {default.name!r} has no credentials or URL"
            )
        self.name = f"ai:{default.name}"

    def _provider_for(self, language: str):
        language = language if self.choice.is_enabled(language) else self.default_language
        return language, self.choice.stt_for(language, self.factories)

    def stream(self, language_hint: str = "en", sample_rate: int = 16000) -> STTStream:
        """A live stream when STT_STREAMING is on, else the buffered default."""
        if not self.settings.stt_streaming:
            return super().stream(language_hint, sample_rate)
        return AILiveStream(self, language_hint, sample_rate)

    async def transcribe(
        self,
        pcm: bytes,
        sample_rate: int,
        language_hint: str = "en",
        provided_text: str | None = None,
    ) -> TranscriptResult:
        if provided_text:
            return TranscriptResult(provided_text.strip(), 0.99, self.name, language=language_hint)
        if not pcm:
            return TranscriptResult("", 0.0, self.name, language=language_hint, error="no_speech")

        try:
            language, provider = self._provider_for(language_hint)
            result = await provider.transcribe(
                pcm,
                language,
                sample_rate,
                timeout=self.settings.ai_stt_timeout_s,
            )
        except Exception as exc:  # noqa: BLE001 - surfaced honestly to the client
            return TranscriptResult(
                "",
                0.0,
                self.name,
                language=language_hint,
                error=f"ai_stt_error:{type(exc).__name__}",
            )

        text = (result.text or "").strip()
        timing = result.timing
        return TranscriptResult(
            text=text,
            confidence=float(result.confidence or 0.0),
            provider=f"ai:{provider.name}",
            ttfp_ms=int(timing.time_to_first_partial_ms or 0),
            final_ms=int(timing.time_to_final_ms or 0),
            language=language,
            simulated=False,
            error=None if text else "no_speech",
        )


class AIYarnTTS(TTSProvider):
    """YarnGPT TTS from the AI package, mapped to ``AudioResult``."""

    name = "ai:yarngpt"
    simulated = False

    def __init__(self, settings: Settings):
        self.settings = settings
        self.tts = YarnGPTTTS(
            api_key=settings.yarngpt_api_key or settings.yarn_api_key or None,
            url=settings.yarngpt_tts_url or settings.yarn_tts_url or None,
            default_voice=settings.yarngpt_default_voice or settings.yarn_tts_voice or None,
        )
        if not self.tts.is_configured():
            raise ProviderNotConfigured("YARNGPT_API_KEY / YARN_API_KEY is not set")

    async def synthesize(self, text: str, voice: str = "", language: str = "en") -> AudioResult:
        start = time.perf_counter()
        try:
            result = await self.tts.synthesize(text, voice or None, language)
        except (NotConfigured, ProviderError):
            return AudioResult(b"", 24000, self.name, text=text, simulated=False)
        elapsed = int((time.perf_counter() - start) * 1000)
        return AudioResult(
            result.pcm,
            result.sample_rate,
            self.name,
            ttfa_ms=int(result.timing.time_to_first_audio_ms or elapsed),
            total_ms=elapsed,
            text=text,
        )
