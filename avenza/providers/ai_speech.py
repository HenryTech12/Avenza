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
        # Primary provider first, then configured fallbacks ("en=sahara|yarngpt").
        self.language, self.providers = owner._providers_for(language_hint)
        self.provider = self.providers[0]
        self.sample_rate = sample_rate
        self._audio = bytearray()  # kept so a fallback provider can hear the whole turn
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
        self._audio.extend(pcm)
        try:
            await self._ensure()
            await self._stream.send_audio(pcm)
        except Exception as exc:  # noqa: BLE001
            if not await self._switch(exc):
                raise

    def _next_provider(self):
        index = self.providers.index(self.provider)
        return self.providers[index + 1] if index + 1 < len(self.providers) else None

    async def _switch(self, exc: BaseException) -> bool:
        """Move the live stream to the next provider and replay the audio so far."""
        nxt = self._next_provider()
        if nxt is None:
            return False
        logger.warning("live STT %s failed (%s); switching to %s", self.provider.name, exc, nxt.name)
        await self.abort()
        self.provider = nxt
        self._stream, self._task, self._finals, self._interim, self._error = None, None, [], "", None
        await self._ensure()
        audio = bytes(self._audio)
        for i in range(0, len(audio), 8000):
            await self._stream.send_audio(audio[i : i + 8000])
        return True

    async def _fallback_batch(self, reason: str) -> TranscriptResult | None:
        """The live stream failed at the end: transcribe the whole turn elsewhere."""
        audio = bytes(self._audio)
        nxt = self._next_provider()
        while nxt is not None and audio:
            logger.warning("live STT %s failed (%s); transcribing with %s", self.provider.name, reason, nxt.name)
            self.provider = nxt
            try:
                result = await nxt.transcribe(
                    audio, self.language, self.sample_rate, timeout=self.owner.settings.ai_stt_timeout_s
                )
            except Exception as exc:  # noqa: BLE001
                reason = type(exc).__name__
                nxt = self._next_provider()
                continue
            text = (result.text or "").strip()
            return TranscriptResult(
                text=text,
                confidence=float(result.confidence or 0.0),
                provider=f"ai:{nxt.name}",
                ttfp_ms=int(result.timing.time_to_first_partial_ms or 0),
                final_ms=int(result.timing.time_to_final_ms or 0),
                language=self.language,
                simulated=False,
                error=None if text else "no_speech",
            )
        return None

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
            fallback = await self._fallback_batch(type(exc).__name__)
            if fallback is not None:
                return fallback
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
            fallback = await self._fallback_batch(type(self._error).__name__)
            if fallback is not None:
                return fallback
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


def _choice_from_settings(settings: Settings) -> tuple[ProviderChoice, dict[str, list[str]]]:
    """AI_STT_CHOICE wins over the language-test file.

    ``en=sahara|yarngpt,pcm=sahara`` means: English goes to Sahara, and to
    YarnGPT if Sahara refuses or fails (for example its 3-connections-a-minute
    limit). Lets the team pick providers on the cluster, where the
    language-test output (reports/provider_choice.json) is not in the image.
    """
    raw = settings.ai_stt_choice
    if not raw:
        return ProviderChoice.load(settings.ai_provider_choice), {}
    choice: dict[str, str] = {}
    fallbacks: dict[str, list[str]] = {}
    for item in raw.split(","):
        if "=" not in item:
            continue
        language, providers = (part.strip().lower() for part in item.split("=", 1))
        names = [p.strip() for p in providers.split("|") if p.strip() in _STT_NAMES]
        if language and names:
            choice[language] = names[0]
            fallbacks[language] = names[1:]
    if not choice:
        raise ProviderNotConfigured(f"AI_STT_CHOICE has no valid entries: {raw!r}")
    return ProviderChoice(choice, list(choice)), fallbacks


class AIWebSocketSTT(STTProvider):
    """Language-aware streaming STT from the AI provider registry."""

    name = "ai"
    simulated = False

    def __init__(self, settings: Settings):
        self.settings = settings
        self.choice, self.fallbacks = _choice_from_settings(settings)
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

    def _providers_for(self, language: str):
        """Primary provider, then configured fallbacks that have credentials."""
        language, primary = self._provider_for(language)
        chain = [primary]
        for name in self.fallbacks.get(language, []):
            factory = self.factories.get(name)
            if factory is None:
                continue
            provider = factory()
            if provider.is_configured() and provider.name != primary.name:
                chain.append(provider)
        return language, chain

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

        result = provider = None
        error = "no provider"
        language, chain = self._providers_for(language_hint)
        for candidate in chain:
            try:
                result = await candidate.transcribe(
                    pcm,
                    language,
                    sample_rate,
                    timeout=self.settings.ai_stt_timeout_s,
                )
                provider = candidate
                break
            except Exception as exc:  # noqa: BLE001 - try the next provider
                error = type(exc).__name__
                logger.warning("STT %s failed (%s)", candidate.name, exc)
        if result is None:
            return TranscriptResult(
                "",
                0.0,
                self.name,
                language=language_hint,
                error=f"ai_stt_error:{error}",
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
            # A stalled stream falls back to the device voice instead of a long silence.
            timeout=max(2.0, float(settings.tts_timeout_s)),
        )
        if not self.tts.is_configured():
            raise ProviderNotConfigured("YARNGPT_API_KEY / YARN_API_KEY is not set")

    async def synthesize(self, text: str, voice: str = "", language: str = "en") -> AudioResult:
        start = time.perf_counter()
        try:
            result = await self.tts.synthesize(text, voice or None, language)
        except (NotConfigured, ProviderError) as exc:
            # The client falls back to the device voice; say why in the logs.
            logger.warning("tts failed: %s", exc)
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

    @property
    def last_error(self) -> str | None:
        return getattr(self.tts, "last_error", None)
