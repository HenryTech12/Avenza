from __future__ import annotations

import asyncio
import base64
import logging
import time
from collections import OrderedDict
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Awaitable, Callable

from .bank import BANK_NAMES, BankAccountRestricted, BankAdapter, BankNotFound, BankUnavailable
from .config import Settings
from .intent import Intent, IntentClassifier, language_request
from .langdetect import detect_language
from .latency import LatencyLog, Turn
from .money import format_naira
from .parser import ParseError, extract_transfer_fields, normalize, parse_history_query
from .prompts import PROMPTS, PromptLibrary
from .services import DraftActive, SessionService, TransferLocked, TransferService
from .state_machine import TransferState, display_state
from .timeutil import utcnow

if TYPE_CHECKING:
    from .ai.workflow import AIWorkflow

logger = logging.getLogger("avenza.orchestrator")

# The turn being processed by the current asyncio task (one per WebSocket), so
# concurrent sessions never write timings into each other's records.
_CURRENT_TURN: ContextVar["Turn | None"] = ContextVar("avenza_current_turn", default=None)

SendEvents = Callable[[list[dict]], Awaitable[None]]


@dataclass
class SessionContext:
    session_id: str
    user_id: str
    device_id: str
    language: str
    display_name: str = ""
    active_transfer_id: str | None = None
    accumulator: dict = field(default_factory=dict)
    collecting: bool = False
    unclear_count: int = 0
    approval_failures: int = 0
    # Payments this session has spoken about, so a later bank change (settled
    # after pending, or a reversal) is announced exactly once.
    watching: set = field(default_factory=set)
    announced: dict = field(default_factory=dict)
    last_status_check: float = 0.0
    send: SendEvents | None = None
    hold_task: asyncio.Task | None = None
    closed: bool = False
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    turn: Turn | None = None


class TurnOrchestrator:
    def __init__(
        self,
        settings: Settings,
        prompts: PromptLibrary,
        stt,
        tts,
        intent: IntentClassifier,
        bank: BankAdapter,
        transfers: TransferService,
        sessions: SessionService,
        ai: "AIWorkflow | None" = None,
    ):
        self.settings = settings
        self.prompts = prompts
        self.stt = stt
        self.tts = tts
        self.intent = intent
        self.bank = bank
        self.transfers = transfers
        self.sessions = sessions
        self.ai = ai
        self.latency = LatencyLog(settings.latency_log or None)
        self._tts_cache: OrderedDict[tuple[str, str], tuple[str, int]] = OrderedDict()
        # Fixed prompts synthesised at startup; never evicted by read-backs.
        self._tts_fixed: dict[tuple[str, str], tuple[str, int]] = {}

    # ------------------------------------------------------------------
    # Speech output
    # ------------------------------------------------------------------
    async def render_audio(self, ctx: SessionContext, events: list[dict]) -> list[dict]:
        """Attach provider TTS audio to spoken prompts.

        Prompts with a recorded clip (``audio_url``) keep it. Every other
        prompt, including the read-back with the bank-verified name, is
        synthesised by the configured TTS provider and sent inside the same
        ``prompt.play`` event, so playback order is preserved. Fixed prompts
        are cached. If TTS is simulated or fails, the client speaks the text
        with its local engine.
        """
        if getattr(self.tts, "simulated", True):
            return events
        for event in events:
            if (
                event.get("type") != "prompt.play"
                or event.get("audio_url")
                or event.get("audio")
                or not event.get("text")
            ):
                continue
            key = (event.get("language") or ctx.language, event["text"])
            cached = self._tts_fixed.get(key) or self._tts_cache.get(key)
            if cached is None:
                started = time.perf_counter()
                try:
                    result = await asyncio.wait_for(
                        self.tts.synthesize(event["text"], language=key[0]),
                        self.settings.tts_timeout_s,
                    )
                except Exception as exc:  # noqa: BLE001 - client falls back to local speech
                    logger.warning("tts failed: %s", type(exc).__name__)
                    event["tts_error"] = type(exc).__name__
                    continue
                if result.is_empty:
                    event["tts_error"] = "empty_audio"
                    continue
                ttfa = result.ttfa_ms or int((time.perf_counter() - started) * 1000)
                if ctx.turn is not None and "tts_ttfa_ms" not in ctx.turn.stages:
                    ctx.turn.mark("tts_ttfa_ms", ttfa)
                cached = (base64.b64encode(result.pcm).decode("ascii"), int(result.sample_rate))
                self._tts_cache[key] = cached
                while len(self._tts_cache) > max(1, self.settings.tts_cache_size):
                    self._tts_cache.popitem(last=False)
            elif key in self._tts_cache:
                self._tts_cache.move_to_end(key)
            event["audio"] = {"encoding": "pcm_s16le", "sample_rate": cached[1], "data": cached[0]}
        return events

    def fixed_prompts(self, languages: list[str]) -> list[tuple[str, str]]:
        """(language, text) of every prompt with no variable part and no recorded clip."""
        out: list[tuple[str, str]] = []
        for language in languages:
            for prompt_id in self.prompts.all_ids():
                if not self.prompts.is_fixed(prompt_id, language):
                    continue
                prompt = self.prompts.render(prompt_id, language=language)
                key = (prompt.language, prompt.text)
                if prompt.audio_url or key in out:
                    continue
                out.append(key)
        return out

    async def prewarm_tts(self) -> int:
        """Synthesise every fixed prompt once, so a turn only waits for its read-back.

        YarnGPT takes 3.5-4.6 s to deliver a clip (10 Nov 2026), so without this
        "Thank you. Place your finger on the sensor..." would wait that long on
        every first use after a deploy. Runs in the background at startup; a
        prompt that is needed before it is ready is synthesised live as before.
        Every call spends YarnGPT credits: about one per English prompt per start.
        """
        if getattr(self.tts, "simulated", True) or not self.settings.tts_prewarm:
            logger.info(
                "tts prewarm: skipped (tts=%s simulated=%s TTS_PREWARM=%s)",
                getattr(self.tts, "name", "?"), getattr(self.tts, "simulated", True), self.settings.tts_prewarm,
            )
            return 0
        languages = [x.strip() for x in self.settings.tts_prewarm_languages.split(",") if x.strip()]
        todo = [k for k in self.fixed_prompts(languages) if k not in self._tts_fixed]
        if todo:
            logger.info(
                "tts prewarm: starting %d fixed prompts (%s), %d at a time",
                len(todo), ",".join(languages), max(1, self.settings.tts_prewarm_concurrency),
            )
        gate = asyncio.Semaphore(max(1, self.settings.tts_prewarm_concurrency))
        started = time.perf_counter()

        out_of_credit = asyncio.Event()

        async def one(key: tuple[str, str]) -> bool:
            async with gate:
                if out_of_credit.is_set():
                    return False
                try:
                    result = await asyncio.wait_for(
                        self.tts.synthesize(key[1], language=key[0]),
                        # a self-hosted model may need a minute to wake up on the first call
                        max(self.settings.tts_prewarm_timeout_s, getattr(self.tts, "prewarm_timeout_s", 0)),
                    )
                except Exception as exc:  # noqa: BLE001 - the live path still works
                    logger.warning("tts prewarm failed for %r: %s", key[1][:40], type(exc).__name__)
                    return False
                if result.is_empty:  # under the provider minimum, or no audio
                    # Out of credits (402, 10 Nov 2026): stop, keep what is left for read-backs.
                    if "QUOTA_EXCEEDED" in str(getattr(self.tts, "last_error", "") or ""):
                        if not out_of_credit.is_set():
                            logger.warning("tts prewarm: stopped, the TTS provider is out of credits")
                        out_of_credit.set()
                    return False
                self._tts_fixed[key] = (base64.b64encode(result.pcm).decode("ascii"), int(result.sample_rate))
                return True

        done = sum(await asyncio.gather(*(one(k) for k in todo)))
        logger.info(
            "tts prewarm: %d of %d fixed prompts cached in %.1f s",
            done, len(todo), time.perf_counter() - started,
        )
        return done

    # ------------------------------------------------------------------
    # Failure safety
    # ------------------------------------------------------------------
    def safe_error_events(self, ctx: SessionContext, code: str = "internal_error") -> list[dict]:
        """What to say after an unexpected error, without lying about money.

        "The money has not moved" is only said when it is true. If a payment
        is with the bank, the customer is told to wait for the status instead.
        """
        try:
            active = self.transfers.active_for_user(ctx.user_id)
        except Exception:  # noqa: BLE001
            active = None
        if active is not None and active.state in {
            TransferState.APPROVED.value,
            TransferState.SUBMITTED.value,
            TransferState.PENDING_UNKNOWN.value,
        }:
            return [
                self._error(code, "error_after_submit", "internal error after approval"),
                self._state(active),
                self._prompt(ctx, "error_after_submit"),
                self._listening(),
            ]
        try:
            latest = self.transfers.latest_for_user(ctx.user_id)
        except Exception:  # noqa: BLE001
            latest = None
        if (
            latest is not None
            and latest.state == TransferState.SETTLED.value
            and latest.settled_at is not None
            and (utcnow() - latest.settled_at).total_seconds() < 120
        ):
            return [
                self._error(code, "settled", "internal error after settlement"),
                self._state(latest),
                self._result_prompt(ctx, latest),
                self._listening(),
            ]
        return [
            self._error(code, "error_generic", "internal error"),
            self._prompt(ctx, "error_generic"),
            self._listening(),
        ]

    # ------------------------------------------------------------------
    # Event helpers
    # ------------------------------------------------------------------
    def _prompt(self, ctx: SessionContext, prompt_id: str, **kwargs) -> dict:
        prompt = self.prompts.render(prompt_id, language=ctx.language, **kwargs)
        return {
            "type": "prompt.play",
            "id": prompt.id,
            "text": prompt.text,
            "language": prompt.language,
            "audio_url": prompt.audio_url,
        }

    async def _classify(self, text: str, state: str | None = None, language: str = "en"):
        """Use the AI-augmented classifier when wired, else the backend one.

        The AI layer is advisory: it is only consulted for genuinely unclear
        requests, and confirmations never come from it.
        """
        started = time.perf_counter()
        try:
            if self.ai is not None:
                return await self.ai.classify(text, state=state, language=language)
            return await self.intent.classify(text, state=state, language=language)
        finally:
            turn = _CURRENT_TURN.get()
            if turn is not None and "intent_ms" not in turn.stages:
                turn.mark("intent_ms", (time.perf_counter() - started) * 1000)

    def _readback_prompt(self, ctx: SessionContext, transfer, *, prefix: str = "") -> dict:
        """Read-back prompt, optionally rendered by the AI template.

        The bank-verified name is always used. If the AI template cannot render
        (missing name/amount), the backend prompt is used unchanged. Risk
        warnings (duplicate payment, large amount to a new recipient, a name
        that differs from the bank's) are always spoken first.
        """
        event = self._prompt(ctx, "readback", **_readback_fields(transfer))
        if self.ai is not None:
            text = self.ai.readback(
                transfer.amount_kobo,
                transfer.verified_recipient_name,
                bank_name=BANK_NAMES.get(transfer.bank_code, transfer.bank_code),
                language=ctx.language,
            )
            if text:
                event["text"] = text
        warnings = self.transfers.warnings_for(transfer, ctx.language)
        parts = [p for p in [prefix, *warnings, event["text"]] if p]
        event["text"] = " ".join(parts)
        event["warnings"] = list(transfer.risk_flags or [])
        if warnings or prefix:
            event["audio_url"] = None
        return event

    @staticmethod
    def _state(transfer) -> dict:
        return {
            "type": "state.changed",
            "transfer_id": transfer.id,
            "state": transfer.state,
            "display": display_state(transfer.state),
            "amount_display": format_naira(transfer.amount_kobo),
            "recipient": transfer.verified_recipient_name,
            "reference": transfer.bank_reference,
        }

    @staticmethod
    def _listening() -> dict:
        return {"type": "listening", "tone": True}

    @staticmethod
    def _error(code: str, prompt_id: str, message: str) -> dict:
        return {"type": "error", "code": code, "prompt_id": prompt_id, "message": message}

    def _watch(self, ctx: SessionContext, transfer) -> None:
        """Remember what the customer was told about this payment."""
        ctx.announced[transfer.id] = transfer.state
        if transfer.state in {
            TransferState.SUBMITTED.value,
            TransferState.PENDING_UNKNOWN.value,
            TransferState.APPROVED.value,
        } or (transfer.state == TransferState.SETTLED.value and not getattr(self.bank, "simulated", True)):
            ctx.watching.add(transfer.id)

    def _result_prompt(self, ctx: SessionContext, transfer) -> dict:
        self._watch(ctx, transfer)
        if transfer.state == TransferState.SETTLED.value:
            event = self._prompt(
                ctx,
                "settled",
                amount_display=format_naira(transfer.amount_kobo),
                recipient=transfer.verified_recipient_name,
                reference=transfer.bank_reference or "",
            )
            charges = _charges_kobo(transfer.bank_status)
            if charges:
                # Charges are read from the bank's response, never hard-coded.
                event["text"] += " " + self.prompts.render(
                    "charges", language=ctx.language, charges=format_naira(charges)
                ).text
                event["charges_kobo"] = charges
                event["audio_url"] = None
            return event
        if transfer.state == TransferState.REVERSED.value:
            return self._prompt(
                ctx,
                "reversed",
                amount_display=format_naira(transfer.amount_kobo),
                recipient=transfer.verified_recipient_name,
            )
        if transfer.state == TransferState.FAILED.value:
            reason = FAILURE_REASONS.get(transfer.failure_reason or "", "The bank reported a failure.")
            return self._prompt(ctx, "failed", reason=reason)
        if transfer.state == TransferState.PENDING_UNKNOWN.value:
            return self._prompt(ctx, "pending")
        if transfer.state == TransferState.CANCELLED.value:
            return self._prompt(ctx, "cancelled")
        if transfer.state == TransferState.EXPIRED.value:
            return self._prompt(ctx, "expired")
        return self._prompt(ctx, "wait_status")

    def _clear_active(self, ctx: SessionContext, transfer_id: str | None = None) -> None:
        if transfer_id is None or ctx.active_transfer_id == transfer_id:
            ctx.active_transfer_id = None
        ctx.accumulator = {}
        ctx.collecting = False
        ctx.unclear_count = 0
        ctx.approval_failures = 0

    def _expire_events(self, ctx: SessionContext) -> list[dict]:
        events: list[dict] = []
        for transfer in self.transfers.expire_due(user_id=ctx.user_id):
            events.append(self._state(transfer))
            events.append(self._prompt(ctx, "expired"))
            if ctx.active_transfer_id == transfer.id:
                self._clear_active(ctx, transfer.id)
        return events

    # ------------------------------------------------------------------
    # Session start
    # ------------------------------------------------------------------
    async def start_events(self, ctx: SessionContext) -> list[dict]:
        """First events of a session, resuming any transfer still in flight.

        Transfers are looked up per customer, not per connection: a phone that
        drops and reconnects picks up the same draft, approval or bank status.
        """
        async with ctx.lock:
            events = self._expire_events(ctx)
            active = self.transfers.active_for_user(ctx.user_id)
            if active is None:
                return events + [self._prompt(ctx, "session_ready"), self._listening()]
            ctx.active_transfer_id = active.id
            if active.state == TransferState.DRAFTED.value:
                active = self.transfers.mark_readback(active.id)
            if active.state == TransferState.READBACK_PLAYED.value:
                return events + [
                    self._state(active),
                    self._readback_prompt(ctx, active, prefix=self.prompts.render("resume_draft", language=ctx.language).text),
                    self._listening(),
                ]
            if active.state == TransferState.CONFIRMED_BY_VOICE.value:
                return events + await self._begin_approval(ctx, active.id)
            if active.state == TransferState.AWAITING_BIOMETRIC.value:
                return events + await self._resume_approval(ctx, active.id)
            if active.state in {
                TransferState.APPROVED.value,
                TransferState.SUBMITTED.value,
                TransferState.PENDING_UNKNOWN.value,
            }:
                ctx.last_status_check = time.monotonic()
                updated = await self.transfers.check_status(active.id)
                if updated.state in {TransferState.SETTLED.value, TransferState.FAILED.value}:
                    self._clear_active(ctx, updated.id)
                    return events + [self._state(updated), self._result_prompt(ctx, updated), self._listening()]
                return events + [self._state(updated), self._prompt(ctx, "resume_pending"), self._listening()]
            return events + [self._prompt(ctx, "session_ready"), self._listening()]

    async def _resume_approval(self, ctx: SessionContext, transfer_id: str) -> list[dict]:
        try:
            options = self.transfers.reissue_approval(transfer_id, ctx.device_id)
        except Exception:
            return [self._prompt(ctx, "approval_required"), self._listening()]
        transfer = self.transfers.get(transfer_id)
        return [
            self._state(transfer),
            self._prompt(ctx, "confirm_voice"),
            {
                "type": "approval.request",
                "transfer_id": transfer.id,
                "options": options,
                "transfer": TransferService.summary(transfer),
                "expires_in_s": self.settings.approval_ttl_s,
            },
        ]

    # ------------------------------------------------------------------
    # Audio / text
    # ------------------------------------------------------------------
    async def process_audio(
        self,
        ctx: SessionContext,
        pcm: bytes,
        sample_rate: int,
        provided_text: str | None = None,
        *,
        transcript=None,
        vad_ms: int | None = None,
        stt_wait_ms: int | None = None,
    ) -> list[dict]:
        """Handle one customer turn and log its per-stage latency.

        ``transcript`` is a finished result from a live STT stream; without it
        the audio (or provided text) is transcribed here.
        """
        turn = Turn(ctx.session_id)
        ctx.turn = turn
        token = _CURRENT_TURN.set(turn)
        turn.mark("vad_ms", vad_ms)
        try:
            events = await self._process_audio(
                ctx, pcm, sample_rate, provided_text, transcript=transcript, turn=turn, stt_wait_ms=stt_wait_ms
            )
        finally:
            _CURRENT_TURN.reset(token)
        return events

    def finish_turn(self, ctx: SessionContext, events: list[dict]) -> list[dict]:
        """Close the turn's latency record once its reply is ready to send."""
        turn = ctx.turn
        if turn is None:
            return events
        ctx.turn = None
        # Live STT finished before this turn object existed, so its wait is
        # added; batch STT ran inside the turn and is already counted.
        turn.mark("reply_ms", turn.since_start_ms() + turn.external_wait_ms)
        # Logged server-side (JSON lines) for the report; not sent to the
        # client, so the event sequence stays exactly as documented.
        self.latency.write(turn)
        return events

    async def _process_audio(
        self,
        ctx: SessionContext,
        pcm: bytes,
        sample_rate: int,
        provided_text: str | None,
        *,
        transcript,
        turn: Turn,
        stt_wait_ms: int | None,
    ) -> list[dict]:
        if provided_text and not self.settings.allow_text_utterance:
            return [
                self._error("text_not_allowed", "error_stt", "text utterances are disabled"),
                self._prompt(ctx, "error_stt"),
                self._listening(),
            ]
        if transcript is not None:
            result = transcript
            turn.mark("stt_wait_ms", stt_wait_ms)
            turn.external_wait_ms = int(stt_wait_ms or 0)
        else:
            started = time.perf_counter()
            try:
                result = await asyncio.wait_for(
                    self.stt.transcribe(pcm, sample_rate, language_hint=ctx.language, provided_text=provided_text),
                    max(1.0, float(self.settings.ai_stt_timeout_s)),
                )
            except Exception as exc:  # noqa: BLE001 - every step has a timeout
                logger.warning("stt failed: %s", type(exc).__name__)
                return [
                    self._error("stt_unavailable", "error_stt", f"speech-to-text failed: {type(exc).__name__}"),
                    self._prompt(ctx, "error_stt"),
                    self._listening(),
                ]
            turn.mark("stt_wait_ms", (time.perf_counter() - started) * 1000)
        turn.meta["provider"] = result.provider
        turn.meta["language"] = result.language
        turn.meta["simulated_stt"] = bool(result.simulated) or None
        turn.mark("stt_ttfp_ms", result.ttfp_ms or None)
        turn.mark("stt_final_ms", result.final_ms or None)
        events: list[dict] = [
            {
                "type": "transcript.final",
                "text": result.text,
                "confidence": result.confidence,
                "provider": result.provider,
                "simulated": result.simulated,
                "timings": {"ttfp_ms": result.ttfp_ms, "final_ms": result.final_ms},
            }
        ]
        if result.is_empty and result.error and result.error != "no_speech":
            # A provider failure is not silence: say speech is unavailable.
            events.append(self._error("stt_unavailable", "error_stt", result.error))
            events.append(self._prompt(ctx, "error_stt"))
            events.append(self._listening())
            return events
        if result.is_empty:
            events.append(self._error("no_speech", "no_speech", "no speech detected"))
            events.append(self._prompt(ctx, "no_speech"))
            events.append(self._listening())
            return events
        if result.confidence and result.confidence < 0.45 and not result.simulated:
            events.append(self._error("low_confidence", "unclear", "low confidence transcript"))
            events.append(self._prompt(ctx, "unclear"))
            events.append(self._listening())
            return events
        logger.info(
            "stt provider=%s final_ms=%s ttfp_ms=%s chars=%s",
            result.provider,
            result.final_ms,
            result.ttfp_ms,
            len(result.text),
        )
        events.extend(await self.process_text(ctx, result.text))
        return events

    async def process_text(self, ctx: SessionContext, text: str) -> list[dict]:
        async with ctx.lock:
            ctx.unclear_count = max(0, ctx.unclear_count)
            events = self._expire_events(ctx)
            active = self.transfers.active_for_user(ctx.user_id)
            # Answer in the language the customer speaks: an explicit "speak Yoruba",
            # or (beta) the language detected in what they just said.
            requested = language_request(text)
            if requested and active is None:
                events.extend(self._switch_language(ctx, requested, explicit=True))
                events.append(self._listening())
                return events
            if self.settings.language_detection and active is None:
                detected = detect_language(text, ctx.language)
                if detected and detected != ctx.language and self._language_allowed(detected):
                    events.extend(self._switch_language(ctx, detected, explicit=False))
            if active is not None:
                ctx.active_transfer_id = active.id
            else:
                # Keep any partial field collection alive across turns; only
                # drop the pointer to a transfer that no longer exists.
                ctx.active_transfer_id = None

            if active is None:
                events.extend(await self._handle_no_active(ctx, text))
                return events

            state = active.state
            if state in {
                TransferState.DRAFTED.value,
                TransferState.READBACK_PLAYED.value,
            }:
                events.extend(await self._handle_readback_reply(ctx, active, text))
                return events

            if state == TransferState.CONFIRMED_BY_VOICE.value:
                result = await self._classify(text, state=state, language=ctx.language)
                if result.intent in {Intent.NO, Intent.CANCEL}:
                    transfer = self.transfers.cancel(active.id, reason="voice_cancel")
                    events.append(self._state(transfer))
                    events.append(self._prompt(ctx, "cancelled"))
                    self._clear_active(ctx, active.id)
                    events.append(self._listening())
                    return events
                events.extend(await self._begin_approval(ctx, active.id))
                return events

            if state == TransferState.AWAITING_BIOMETRIC.value:
                result = await self._classify(text, state=state, language=ctx.language)
                if result.intent in {Intent.NO, Intent.CANCEL}:
                    transfer = self.transfers.cancel(active.id, reason="voice_cancel")
                    events.append(self._state(transfer))
                    events.append(self._prompt(ctx, "cancelled"))
                    self._clear_active(ctx, active.id)
                    events.append(self._listening())
                    return events
                events.append(self._error("approval_required", "approval_required", "voice cannot approve"))
                events.append(self._prompt(ctx, "approval_required"))
                events.append(self._listening())
                return events

            if state in {
                TransferState.APPROVED.value,
                TransferState.SUBMITTED.value,
                TransferState.PENDING_UNKNOWN.value,
            }:
                now = time.monotonic()
                if now - ctx.last_status_check > 3:
                    ctx.last_status_check = now
                    updated = await self.transfers.check_status(active.id)
                    events.append(self._state(updated))
                    events.append(self._result_prompt(ctx, updated))
                    if updated.state in {
                        TransferState.SETTLED.value,
                        TransferState.FAILED.value,
                    }:
                        self._clear_active(ctx, updated.id)
                else:
                    events.append(self._prompt(ctx, "payment_in_progress"))
                events.append(self._listening())
                return events

            events.append(self._prompt(ctx, "payment_in_progress"))
            events.append(self._listening())
            return events

    # ------------------------------------------------------------------
    # Language
    # ------------------------------------------------------------------
    def _language_allowed(self, language: str) -> bool:
        allowed = {x.strip() for x in self.settings.switch_languages.split(",") if x.strip()}
        return language in allowed and self.prompts.language_supported(language)

    def _switch_language(self, ctx: SessionContext, language: str, *, explicit: bool) -> list[dict]:
        """Switch replies (and the next turn's speech-to-text) to ``language``."""
        if language == ctx.language:
            return [self._prompt(ctx, "language_switched")] if explicit else []
        if not self._language_allowed(language):
            return [self._prompt(ctx, "unsupported_language")] if explicit else []
        previous, ctx.language = ctx.language, language
        beta = language in {x.strip() for x in self.settings.beta_languages.split(",") if x.strip()}
        logger.info("language %s -> %s (%s)", previous, language, "asked" if explicit else "detected")
        events: list[dict] = [
            {"type": "language.changed", "language": language, "previous": previous,
             "beta": beta, "reason": "asked" if explicit else "detected"},
            self._prompt(ctx, "language_switched"),
        ]
        if beta:
            events.append(self._prompt(ctx, "language_beta"))
        return events

    # ------------------------------------------------------------------
    # No active transfer
    # ------------------------------------------------------------------
    async def _handle_no_active(self, ctx: SessionContext, text: str) -> list[dict]:
        result = await self._classify(text, state=None, language=ctx.language)
        events: list[dict] = []

        if result.intent == Intent.BALANCE:
            self._clear_active(ctx)
            return await self._balance_events(ctx)

        if result.intent == Intent.NAVIGATE:
            self._clear_active(ctx)
            screen = result.reason.removeprefix("screen:") or "home"
            events.append({"type": "navigate", "screen": screen})
            if screen == "history":
                return events + await self._history_events(ctx, text)
            events.append(self._prompt(ctx, "nav_settings" if screen == "settings" else "nav_home"))
            events.append(self._listening())
            return events

        if result.intent == Intent.LOCK:
            self.transfers.engage_lock(ctx.user_id, reason="voice_request")
            self._clear_active(ctx)
            events.append({"type": "lock.changed", "locked": True, "reason": "voice_request"})
            events.append(self._prompt(ctx, "locked"))
            events.append(self._listening())
            return events

        if result.intent == Intent.HISTORY:
            self._clear_active(ctx)
            return [{"type": "navigate", "screen": "history"}, *await self._history_events(ctx, text)]

        if result.intent == Intent.HELP:
            self._clear_active(ctx)
            events.append(self._prompt(ctx, "help"))
            events.append(self._listening())
            return events

        if result.intent == Intent.TRANSFER:
            return await self._handle_transfer_request(ctx, text)

        # Multi-turn field collection: if we already have part of a draft, a
        # bare answer such as "GTBank" or "0123456789" is a field, not noise.
        if (ctx.accumulator or ctx.collecting) and result.intent == Intent.UNCLEAR:
            return await self._handle_transfer_request(ctx, text)

        if result.intent in {Intent.YES, Intent.NO, Intent.REPEAT, Intent.CANCEL}:
            events.append(self._prompt(ctx, "no_draft"))
            events.append(self._listening())
            return events

        events.append(self._prompt(ctx, "unclear"))
        events.append(self._listening())
        return events

    # ------------------------------------------------------------------
    # Draft creation
    # ------------------------------------------------------------------
    async def _handle_transfer_request(self, ctx: SessionContext, text: str) -> list[dict]:
        events: list[dict] = []
        fields = extract_transfer_fields(text, max_kobo=self.settings.max_amount_kobo)
        if fields.amount is not None and self.ai is not None:
            issue = self.ai.crosscheck_amount(text, fields.amount.kobo)
            if issue:
                # The AI cross-check can only force a clarification; it never
                # supplies or replaces the amount.
                fields.amount = None
                fields.amount_error = issue
        acc = ctx.accumulator

        if fields.amount is not None:
            acc["amount"] = fields.amount
            acc.pop("amount_error", None)
        elif fields.amount_error in {
            "ambiguous_amount",
            "invalid_amount",
            "amount_too_large",
            "unsupported_currency",
        } or (fields.amount_error or "").startswith("ai_"):
            acc.pop("amount", None)
            acc["amount_error"] = fields.amount_error

        if fields.account is not None:
            acc["account"] = fields.account
            acc.pop("account_error", None)
        elif fields.account_error == "ambiguous_account":
            acc.pop("account", None)
            acc["account_error"] = "ambiguous_account"

        if fields.bank is not None:
            acc["bank"] = fields.bank
        if fields.recipient_hint:
            acc["hint"] = fields.recipient_hint

        if acc.get("amount_error") == "amount_too_large":
            acc.pop("amount_error", None)
            events.append(
                self._error("amount_too_large", "amount_too_large", "amount above configured limit")
            )
            events.append(self._prompt(ctx, "amount_too_large", limit=format_naira(self.settings.max_amount_kobo)))
            events.append(self._listening())
            return events
        if acc.get("amount_error") in {"ambiguous_amount", "invalid_amount", "unsupported_currency"} or str(
            acc.get("amount_error") or ""
        ).startswith("ai_"):
            acc.pop("amount_error", None)
            events.append(self._error("ambiguous_amount", "clarify_amount", "unclear amount"))
            events.append(self._prompt(ctx, "clarify_amount"))
            events.append(self._listening())
            return events
        if acc.get("account_error") == "ambiguous_account":
            acc.pop("account_error", None)
            events.append(self._error("ambiguous_account", "clarify_account", "unclear account number"))
            events.append(self._prompt(ctx, "clarify_account"))
            events.append(self._listening())
            return events

        missing = [key for key in ("amount", "account", "bank") if key not in acc]
        if missing:
            ctx.collecting = True
            if len(missing) == 3:
                events.append(self._prompt(ctx, "ask_all"))
            elif missing[0] == "amount":
                events.append(self._prompt(ctx, "ask_amount"))
            elif missing[0] == "account":
                events.append(self._prompt(ctx, "ask_account"))
            else:
                events.append(self._prompt(ctx, "ask_bank"))
            events.append(self._listening())
            return events

        amount = acc["amount"]
        account = acc["account"]
        bank = acc["bank"]
        hint = acc.get("hint")

        started = time.perf_counter()
        try:
            info = await self.bank.name_enquiry(bank.code, account.value)
        except BankNotFound:
            acc.pop("account", None)
            self.transfers.audit.record_standalone(
                "name.not_found",
                details={"bank_code": bank.code, "account_last4": account.value[-4:]},
            )
            events.append(self._error("account_not_found", "name_not_found", "account not found"))
            events.append(self._prompt(ctx, "name_not_found", bank=bank.name))
            events.append(self._listening())
            return events
        except BankAccountRestricted:
            acc.pop("account", None)
            events.append(self._error("account_restricted", "name_cannot_receive", "beneficiary cannot receive"))
            events.append(self._prompt(ctx, "name_cannot_receive"))
            events.append(self._listening())
            return events
        except BankUnavailable:
            events.append(self._error("bank_unavailable", "error_bank", "name enquiry unavailable"))
            events.append(self._prompt(ctx, "error_bank"))
            events.append(self._listening())
            return events
        except Exception:
            logger.exception("name enquiry failed")
            events.append(self._error("bank_error", "error_bank", "name enquiry failed"))
            events.append(self._prompt(ctx, "error_bank"))
            events.append(self._listening())
            return events

        name_ms = int((time.perf_counter() - started) * 1000)
        if ctx.turn is not None:
            ctx.turn.mark("name_enquiry_ms", name_ms)
        try:
            transfer = self.transfers.create_draft(
                user_id=ctx.user_id,
                session_id=ctx.session_id,
                amount_kobo=amount.kobo,
                bank_code=bank.code,
                account_number=account.value,
                verified_name=info.account_name,
                hint=hint,
                language=ctx.language,
            )
        except TransferLocked:
            events.append(self._error("transfers_locked", "locked", "transfers locked"))
            events.append(self._prompt(ctx, "locked"))
            events.append(self._listening())
            return events
        except DraftActive:
            events.append(self._error("draft_active", "draft_active", "a transfer is already in flight"))
            events.append(self._prompt(ctx, "payment_in_progress"))
            events.append(self._listening())
            return events

        transfer = self.transfers.mark_readback(transfer.id)
        self.transfers.audit.record_standalone(
            "name.verified",
            transfer_id=transfer.id,
            session_id=ctx.session_id,
            details={
                "bank_code": bank.code,
                "account_last4": account.value[-4:],
                "verified_name": info.account_name,
                "name_enquiry_ms": name_ms,
            },
        )
        logger.info(
            "latency name_enquiry_ms=%s amount_kobo=%s state=%s",
            name_ms,
            transfer.amount_kobo,
            transfer.state,
        )

        ctx.active_transfer_id = transfer.id
        ctx.accumulator = {}
        ctx.collecting = False
        ctx.unclear_count = 0
        events.append(self._state(transfer))
        events.append(self._readback_prompt(ctx, transfer))
        events.append(self._listening())
        return events

    # ------------------------------------------------------------------
    # Read-back reply
    # ------------------------------------------------------------------
    async def _handle_readback_reply(self, ctx: SessionContext, transfer, text: str) -> list[dict]:
        events: list[dict] = []
        result = await self._classify(text, state=transfer.state, language=ctx.language)

        if result.intent in {Intent.NO, Intent.CANCEL}:
            cancelled = self.transfers.cancel(transfer.id, reason="voice_no")
            events.append(self._state(cancelled))
            events.append(self._prompt(ctx, "cancelled"))
            self._clear_active(ctx, transfer.id)
            events.append(self._listening())
            return events

        if result.intent == Intent.REPEAT:
            events.append(self._state(transfer))
            events.append(self._readback_prompt(ctx, transfer))
            events.append(self._listening())
            ctx.unclear_count = 0
            return events

        if result.intent == Intent.YES:
            ctx.unclear_count = 0
            outcome = self.transfers.record_confirmation(transfer.id, Intent.YES)
            if outcome.outcome == "more_confirmation":
                events.append(self._state(outcome.transfer))
                events.append(
                    self._readback_prompt(
                        ctx,
                        outcome.transfer,
                        prefix=self.prompts.render("confirm_again", language=ctx.language).text,
                    )
                )
                events.append(self._listening())
                return events
            return await self._begin_approval(ctx, transfer.id)

        # A new transfer request while a draft is active must never create a
        # second draft. Repeat the existing read-back instead.
        if result.intent == Intent.TRANSFER:
            events.append(self._error("draft_active", "draft_active", "a draft is already active"))
            events.append(self._prompt(ctx, "draft_active"))
            events.append(self._listening())
            return events

        ctx.unclear_count += 1
        if ctx.unclear_count >= 2:
            cancelled = self.transfers.cancel(transfer.id, reason="two_unclear_replies")
            events.append(self._state(cancelled))
            events.append(self._prompt(ctx, "too_many_attempts"))
            self._clear_active(ctx, transfer.id)
        else:
            events.append(self._error("unclear", "unclear", "unclear confirmation"))
            events.append(self._prompt(ctx, "unclear"))
        events.append(self._listening())
        return events

    # ------------------------------------------------------------------
    # Approval
    # ------------------------------------------------------------------
    async def _begin_approval(self, ctx: SessionContext, transfer_id: str) -> list[dict]:
        events: list[dict] = []
        try:
            options, hold_seconds, transfer = self.transfers.issue_approval(transfer_id, ctx.device_id)
        except TransferLocked:
            events.append(self._error("transfers_locked", "locked", "transfers locked"))
            events.append(self._prompt(ctx, "locked"))
            events.append(self._listening())
            return events
        except Exception as exc:
            logger.warning("approval issue failed: %s", exc)
            events.append(self._error("approval_error", "fingerprint_retry", "approval could not start"))
            events.append(self._prompt(ctx, "fingerprint_retry"))
            events.append(self._listening())
            return events

        if options is None and hold_seconds > 0:
            events.append(self._state(transfer))
            events.append(self._prompt(ctx, "risk_hold", seconds=hold_seconds))
            if ctx.send and not ctx.closed:
                if ctx.hold_task and not ctx.hold_task.done():
                    ctx.hold_task.cancel()
                ctx.hold_task = asyncio.create_task(self._delayed_approval(ctx, transfer_id, hold_seconds))
            events.append(self._listening())
            return events

        events.append(self._state(transfer))
        events.append(self._prompt(ctx, "confirm_voice"))
        events.append(
            {
                "type": "approval.request",
                "transfer_id": transfer.id,
                "options": options,
                "transfer": TransferService.summary(transfer),
                "expires_in_s": self.settings.approval_ttl_s,
            }
        )
        return events

    async def _delayed_approval(self, ctx: SessionContext, transfer_id: str, seconds: int) -> None:
        try:
            await asyncio.sleep(max(0, seconds))
            if ctx.closed:
                return
            async with ctx.lock:
                current = self.transfers.get(transfer_id)
                if current.state != TransferState.CONFIRMED_BY_VOICE.value:
                    return  # cancelled or expired during the hold
                events = await self._begin_approval(ctx, transfer_id)
            if ctx.send:
                await ctx.send(events)
        except asyncio.CancelledError:
            return
        except Exception:
            logger.exception("delayed approval failed")

    async def handle_approval(
        self, ctx: SessionContext, credential: dict | None, *, dev: bool = False
    ) -> list[dict]:
        # A real bank can take several seconds (interbank settles in about 5).
        # The customer must never hear silence, so a short notice is spoken if
        # the answer is slow. Only sent on a live socket.
        notice = asyncio.create_task(self._slow_bank_notice(ctx)) if ctx.send is not None else None
        try:
            return await self._handle_approval(ctx, credential, dev=dev)
        finally:
            if notice is not None and not notice.done():
                notice.cancel()

    async def _slow_bank_notice(self, ctx: SessionContext, after_s: float = 1.5) -> None:
        try:
            await asyncio.sleep(after_s)
            if ctx.send is not None and not ctx.closed:
                await ctx.send([self._prompt(ctx, "sending")])
        except asyncio.CancelledError:
            return
        except Exception:  # noqa: BLE001 - a notice must never break approval
            logger.debug("slow bank notice failed", exc_info=True)

    async def _handle_approval(
        self, ctx: SessionContext, credential: dict | None, *, dev: bool = False
    ) -> list[dict]:
        async with ctx.lock:
            active = self.transfers.active_for_user(ctx.user_id)
            if active is None:
                return [self._prompt(ctx, "no_draft"), self._listening()]
            if active.state != TransferState.AWAITING_BIOMETRIC.value:
                return [self._prompt(ctx, "approval_required"), self._listening()]

            try:
                transfer = await self.transfers.approve_and_submit(
                    active.id,
                    ctx.device_id,
                    credential,
                    dev_approval=dev,
                )
            except TransferLocked:
                return [
                    self._error("transfers_locked", "locked", "transfers locked"),
                    self._prompt(ctx, "locked"),
                    self._listening(),
                ]
            except Exception as exc:
                logger.info("approval rejected: %s", exc)
                transfer = self.transfers.get(active.id)
                if transfer.state in {
                    TransferState.APPROVED.value,
                    TransferState.SUBMITTED.value,
                    TransferState.PENDING_UNKNOWN.value,
                    TransferState.SETTLED.value,
                    TransferState.FAILED.value,
                }:
                    # The approval went through and something failed later.
                    # Never ask for the fingerprint again: report the payment.
                    logger.exception("failure after approval")
                    if transfer.state in {TransferState.SETTLED.value, TransferState.FAILED.value}:
                        self._clear_active(ctx, transfer.id)
                        return [self._state(transfer), self._result_prompt(ctx, transfer), self._listening()]
                    return [
                        self._error("after_approval", "error_after_submit", "error after approval"),
                        self._state(transfer),
                        self._prompt(ctx, "error_after_submit"),
                        self._listening(),
                    ]
                if transfer.state == TransferState.EXPIRED.value or (
                    transfer.approval_expires_at is not None and transfer.approval_expires_at < utcnow()
                ):
                    if transfer.state != TransferState.EXPIRED.value:
                        transfer = self.transfers.expire_now(transfer.id, reason="approval_expired")
                    self._clear_active(ctx, transfer.id)
                    return [
                        self._state(transfer),
                        self._prompt(ctx, "approval_expired"),
                        self._listening(),
                    ]
                # Counted from the audit log, so a reconnect cannot reset it.
                ctx.approval_failures = self.transfers.approval_failures(transfer.id)
                if ctx.approval_failures >= 3:
                    cancelled = self.transfers.cancel(transfer.id, reason="too_many_failed_reads")
                    self._clear_active(ctx, transfer.id)
                    return [
                        self._state(cancelled),
                        self._prompt(ctx, "too_many_attempts"),
                        self._listening(),
                    ]
                # Fresh challenge; the client prompts the fingerprint again.
                try:
                    options = self.transfers.reissue_approval(transfer.id, ctx.device_id)
                except Exception:
                    return [
                        self._state(transfer),
                        self._prompt(ctx, "fingerprint_retry"),
                        self._listening(),
                    ]
                return [
                    self._state(transfer),
                    self._prompt(ctx, "fingerprint_retry"),
                    {
                        "type": "approval.request",
                        "transfer_id": transfer.id,
                        "options": options,
                        "transfer": TransferService.summary(transfer),
                        "expires_in_s": self.settings.approval_ttl_s,
                    },
                ]

            events = [
                self._state(transfer),
                self._result_prompt(ctx, transfer),
            ]
            if transfer.state in {
                TransferState.SETTLED.value,
                TransferState.FAILED.value,
                TransferState.PENDING_UNKNOWN.value,
                TransferState.REVERSED.value,
            }:
                self._clear_active(ctx, transfer.id)
            events.append(self._listening())
            return events

    # ------------------------------------------------------------------
    # History
    # ------------------------------------------------------------------
    async def _balance_events(self, ctx: SessionContext) -> list[dict]:
        """"What is my balance?": the bank's figure, spoken. Never a made-up number."""
        events: list[dict] = []
        get_balance = getattr(self.bank, "get_balance", None)
        data = None
        if get_balance is not None:
            try:
                data = await asyncio.wait_for(get_balance(self.transfers.customer_ref_for(ctx.user_id)), 8.0)
            except Exception as exc:  # noqa: BLE001 - say we could not get it
                logger.info("balance unavailable: %s", type(exc).__name__)
        available = (data or {}).get("available_kobo")
        if available is None:
            events.append(self._prompt(ctx, "balance_unavailable"))
        else:
            events.append({"type": "balance", "available_kobo": available, "available_display": format_naira(available)})
            events.append(self._prompt(ctx, "balance", amount=format_naira(available)))
        events.append(self._listening())
        return events

    async def _history_events(self, ctx: SessionContext, text: str) -> list[dict]:
        """Spoken history from Avenza's own records plus the bank's ledger.

        Avenza only knows the payments it drafted. The bank adapter's
        ``list_transactions`` adds anything else on the customer's account,
        and receipts come from ``get_receipt``. If the bank cannot answer,
        Avenza's own records are read and the event says so.
        """
        query = None
        # The AI time-phrase parser understands more phrases ("in October",
        # "5 days ago", "this year"); the backend parser is the fallback.
        if self.ai is not None:
            query = self.ai.history_query(text, limit=parse_history_query(text).limit)
        if query is None:
            query = parse_history_query(text)
        rows = self.transfers.history(ctx.user_id, query.start, query.end, query.limit)
        items: list[dict] = [{**TransferService.summary(r), "source": "avenza"} for r in rows]

        bank_ok = True
        known_refs = {r.bank_reference for r in rows if r.bank_reference}
        try:
            bank_rows = await asyncio.wait_for(
                self.bank.list_transactions(ctx.user_id, query.start, query.end, query.limit), 5.0
            )
        except Exception as exc:  # noqa: BLE001 - history still works from local records
            logger.info("bank history unavailable: %s", type(exc).__name__)
            bank_rows = []
            bank_ok = False
        for row in bank_rows:
            if row.reference and row.reference in known_refs:
                continue
            items.append(
                {
                    "id": None,
                    "state": row.status,
                    "display": row.status.title(),
                    "amount_kobo": row.amount_kobo,
                    "amount_display": format_naira(row.amount_kobo),
                    "account_last4": (row.account_number or "")[-4:],
                    "recipient": row.recipient_name,
                    "reference": row.reference,
                    "created_at": row.created_at.isoformat() + "Z" if row.created_at else None,
                    "source": "bank",
                }
            )
        items.sort(key=lambda i: i.get("created_at") or "", reverse=True)
        items = items[: query.limit]

        events: list[dict] = [
            {
                "type": "history.data",
                "period": query.label,
                "transactions": items,
                "bank_history": bank_ok,
            }
        ]
        if not items:
            events.append(self._prompt(ctx, "history_empty", period=query.label))
            events.append(self._listening())
            return events

        if "receipt" in normalize(text):
            latest = items[0]
            receipt = None
            if latest.get("reference"):
                try:
                    receipt = await asyncio.wait_for(self.bank.get_receipt(latest["reference"]), 5.0)
                except Exception:  # noqa: BLE001
                    receipt = None
            if receipt:
                amount = int(receipt.get("amount_kobo") or latest["amount_kobo"])
                recipient = receipt.get("recipient_name") or latest["recipient"]
                status = str(receipt.get("status") or latest["state"])
                status_text = display_state(status) if status in TransferState.__members__ else status.title()
            else:
                amount, recipient = latest["amount_kobo"], latest["recipient"]
                status_text = latest.get("display") or latest["state"]
            events.append(
                self._prompt(
                    ctx,
                    "receipt",
                    amount_display=format_naira(amount),
                    recipient=recipient,
                    status=status_text,
                    reference=latest.get("reference") or "not available",
                )
            )
            events.append(self._listening())
            return events

        settled_total = sum(i["amount_kobo"] for i in items if i["state"] == TransferState.SETTLED.value)
        latest = items[0]
        summary = (
            f"{format_naira(settled_total)} settled. Latest: {latest['recipient']} "
            f"{format_naira(latest['amount_kobo'])}."
        )
        events.append(
            self._prompt(
                ctx,
                "history_summary",
                count=len(items),
                period=query.label,
                summary=summary,
            )
        )
        events.append(self._listening())
        return events

    # ------------------------------------------------------------------
    # Periodic tick
    # ------------------------------------------------------------------
    async def tick(self, ctx: SessionContext) -> list[dict]:
        """Periodic work: expiry, bank status, and late changes.

        A payment the customer heard about is watched until it is final, so
        a result reached by the background reconciler or a bank webhook (or a
        later reversal) is still spoken, once.
        """
        events = self._expire_events(ctx)
        active = self.transfers.active_for_user(ctx.user_id)
        if active is not None and active.state in {
            TransferState.SUBMITTED.value,
            TransferState.PENDING_UNKNOWN.value,
        }:
            ctx.watching.add(active.id)
            ctx.announced.setdefault(active.id, active.state)
        now = time.monotonic()
        for transfer_id in list(ctx.watching):
            try:
                transfer = self.transfers.get(transfer_id)
            except Exception:  # noqa: BLE001
                ctx.watching.discard(transfer_id)
                continue
            if transfer.state in {TransferState.SUBMITTED.value, TransferState.PENDING_UNKNOWN.value}:
                if now - ctx.last_status_check > 5:
                    ctx.last_status_check = now
                    transfer = await self.transfers.check_status(transfer_id)
            announced = ctx.announced.get(transfer_id)
            if announced is not None and transfer.state != announced:
                events.append(self._state(transfer))
                events.append(self._result_prompt(ctx, transfer))
                if transfer.state in {
                    TransferState.SETTLED.value,
                    TransferState.FAILED.value,
                    TransferState.REVERSED.value,
                }:
                    self._clear_active(ctx, transfer.id)
            ctx.announced[transfer_id] = transfer.state
            settled_long_ago = (
                transfer.state == TransferState.SETTLED.value
                and (
                    getattr(self.bank, "simulated", True)
                    or transfer.settled_at is None
                    or (utcnow() - transfer.settled_at).total_seconds() > 180
                )
            )
            if transfer.state in {
                TransferState.FAILED.value,
                TransferState.REVERSED.value,
                TransferState.CANCELLED.value,
                TransferState.EXPIRED.value,
            } or settled_long_ago:
                ctx.watching.discard(transfer_id)
        return events


FAILURE_REASONS = {
    "insufficient_funds": "You do not have enough money for this amount plus charges.",
    "limit_exceeded": "It is above your account's transfer limit.",
    "source_restricted": "Your account is restricted from sending money.",
    "beneficiary_restricted": "The recipient's account cannot receive payments.",
    "account_not_found": "The bank could not find that account.",
    "name_check_expired": "The name check expired. Please start again.",
    "recipient_changed": "The bank now shows a different name for that account, so I stopped.",
    "bank_unavailable": "The bank could not be reached.",
    "bank_busy": "The bank is busy. Please try again in a minute.",
    "bank_not_supported": "That bank is not available here.",
    "duplicate_request": "The bank rejected it as a duplicate.",
    "reversed": "The bank reversed it.",
    "not_received_by_bank": "The bank never received it.",
    "bank_declined": "The bank declined it.",
}


def _charges_kobo(bank_status: dict | None) -> int:
    """Fee + VAT + stamp duty from the bank's transfer response, in kobo."""
    if not isinstance(bank_status, dict):
        return 0
    total = 0
    for key in ("fee", "vat", "stamp_duty"):
        try:
            total += int(round(float(bank_status.get(key) or 0) * 100))
        except (TypeError, ValueError):
            continue
    return max(total, 0)


def _readback_fields(transfer) -> dict:
    return {
        "amount_words": _amount_words(transfer.amount_kobo),
        "amount_display": format_naira(transfer.amount_kobo),
        "recipient": transfer.verified_recipient_name,
        "last4": transfer.account_number[-4:],
        "bank": BANK_NAMES.get(transfer.bank_code, transfer.bank_code),
    }


def _amount_words(kobo: int) -> str:
    from .money import amount_to_words

    return amount_to_words(kobo)
