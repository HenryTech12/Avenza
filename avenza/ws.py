from __future__ import annotations

import asyncio
import json
import logging
import time

from fastapi import WebSocket, WebSocketDisconnect

from .orchestrator import SessionContext
from .prompts import PROMPTS

logger = logging.getLogger("avenza.ws")


async def websocket_endpoint(websocket: WebSocket) -> None:
    app = websocket.app
    settings = app.state.settings
    devices = app.state.devices
    sessions = app.state.sessions
    orchestrator = app.state.orchestrator

    origin = websocket.headers.get("origin")
    if origin and settings.is_production:
        allowed = [o.strip() for o in settings.webauthn_origin.split(",") if o.strip()]
        if origin not in allowed:
            await websocket.close(code=1008, reason="origin not allowed")
            return

    await websocket.accept()
    send_lock = asyncio.Lock()
    ctx: SessionContext | None = None
    tick_task: asyncio.Task | None = None
    utterance: dict | None = None
    last_touch = 0.0
    stt = app.state.stt

    async def send_events(events: list[dict]) -> None:
        if ctx is not None:
            # Provider TTS audio is attached here so every path (turns, ticks,
            # delayed approvals) speaks with the same voice.
            try:
                events = await orchestrator.render_audio(ctx, events)
            except Exception:  # noqa: BLE001 - text is still sent; the client speaks it
                logger.exception("render_audio failed")
        async with send_lock:
            for event in events:
                await websocket.send_json(event)

    async def send_partial(text: str) -> None:
        if text:
            async with send_lock:
                await websocket.send_json({"type": "transcript.partial", "text": text})

    async def abort_live(current: dict | None) -> None:
        live = (current or {}).get("live")
        if live is not None and hasattr(live, "abort"):
            try:
                await live.abort()
            except Exception:  # noqa: BLE001
                pass

    async def send_error(code: str, prompt_id: str, message: str) -> None:
        await send_events(
            [{"type": "error", "code": code, "prompt_id": prompt_id, "message": message}]
        )

    async def tick_loop(session_ctx: SessionContext) -> None:
        try:
            while not session_ctx.closed:
                await asyncio.sleep(2)
                if session_ctx.closed:
                    return
                try:
                    async with session_ctx.lock:
                        events = await orchestrator.tick(session_ctx)
                    if events:
                        await send_events(events)
                except asyncio.CancelledError:
                    raise
                except Exception:  # keep ticking: expiry and status must not stop
                    logger.exception("tick failed")
        except asyncio.CancelledError:
            return

    async def handle_binary(chunk: bytes) -> None:
        nonlocal utterance
        if ctx is None:
            await send_error("session_required", "session_expired", "start a session first")
            return
        if utterance is None:
            # Frames after an aborted utterance: drop quietly instead of
            # sending one error per audio frame.
            return
        utterance["buffer"].extend(chunk)
        max_bytes = int(utterance["rate"]) * 2 * 15
        if len(utterance["buffer"]) > max_bytes:
            await abort_live(utterance)
            utterance = None
            await send_events(
                [
                    {"type": "error", "code": "utterance_too_long", "prompt_id": "unclear", "message": "utterance exceeded 15 seconds"},
                    orchestrator._prompt(ctx, "unclear"),
                    orchestrator._listening(),
                ]
            )
            return
        live = utterance.get("live")
        if live is not None:
            try:
                await live.push(chunk)
            except Exception as exc:  # noqa: BLE001 - fall back to batch STT
                logger.warning("live STT failed, falling back to batch: %s", type(exc).__name__)
                await abort_live(utterance)
                utterance["live"] = None

    async def finish_utterance(current: dict, vad_ms: int | None) -> list[dict]:
        pcm = bytes(current["buffer"])
        rate = current["rate"]
        live = current.get("live")
        transcript = None
        stt_wait_ms = None
        if live is not None:
            started = time.perf_counter()
            transcript = await live.end()
            stt_wait_ms = int((time.perf_counter() - started) * 1000)
            if transcript.error and transcript.error != "no_speech" and pcm:
                # The live stream broke; try the whole utterance once in batch.
                logger.warning("live STT error %s, retrying in batch", transcript.error)
                transcript = None
        return await orchestrator.process_audio(
            ctx,
            pcm,
            rate,
            provided_text=current["text"],
            transcript=transcript,
            vad_ms=vad_ms,
            stt_wait_ms=stt_wait_ms,
        )

    async def handle_text(message: dict) -> bool:
        """Handle one JSON control message. Returns False to end the socket."""
        nonlocal ctx, utterance, tick_task
        raw = message.get("text")
        if raw is None:
            return True
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            await send_error("bad_json", "error_generic", "message was not valid JSON")
            return True
        if not isinstance(data, dict):
            await send_error("bad_json", "error_generic", "message must be a JSON object")
            return True

        mtype = data.get("type")
        if mtype == "session.start":
            if ctx is not None:
                await send_error("session_exists", "error_generic", "session already started")
                return True
            token = data.get("device_token")
            consent_id = data.get("consent_id")
            language = data.get("language") or "en"
            auth = devices.authenticate(token)
            if auth is None:
                await send_error("device_not_enrolled", "device_required", "device token is not valid")
                return True
            device, user = auth
            consent = devices.get_consent(consent_id or "")
            if consent is None or consent.user_id != user.id:
                await send_error("consent_required", "consent_required", "record consent first")
                return True
            language_verified = language in PROMPTS
            if not language_verified:
                language = "en"
            try:
                session = sessions.start(
                    user_id=user.id,
                    device_id=device.id,
                    consent_id=consent.id,
                    language=language,
                )
            except Exception as exc:
                await send_error("session_error", "error_generic", str(exc))
                return True

            new_ctx = SessionContext(
                session_id=session.id,
                user_id=user.id,
                device_id=device.id,
                language=language,
                display_name=user.display_name,
            )
            new_ctx.send = send_events
            ctx = new_ctx

            prompts = dict(PROMPTS["en"])
            prompts.update(PROMPTS.get(language, {}))
            await send_events(
                [
                    {
                        "type": "session.ready",
                        "session_id": session.id,
                        "user": {"id": user.id, "display_name": user.display_name},
                        "language": language,
                        "language_verified": language_verified,
                        "bank": {
                            "mode": settings.bank_mode,
                            "simulated": settings.bank_is_simulated,
                        },
                        "stt": {
                            "provider": stt.name,
                            "simulated": stt.simulated,
                            "streaming": bool(settings.stt_streaming and not stt.simulated),
                        },
                        "tts": {
                            "provider": app.state.tts.name,
                            "simulated": app.state.tts.simulated,
                        },
                        "webauthn": {
                            "rp_id": settings.webauthn_rp_id,
                            "origin": settings.webauthn_origin,
                        },
                        "dev_approval_allowed": app.state.security.dev_approval_allowed(),
                        "approval_ttl_s": settings.approval_ttl_s,
                        "session_ttl_s": settings.session_ttl_s,
                        "prompts": prompts,
                    }
                ]
            )
            if not language_verified:
                await send_events([orchestrator._prompt(ctx, "unsupported_language")])
            await send_events(await orchestrator.start_events(ctx))
            tick_task = asyncio.create_task(tick_loop(ctx))
            return True

        if ctx is None:
            await send_error("session_required", "session_expired", "start a session first")
            return True

        if mtype == "utterance.start":
            try:
                rate = int(data.get("sample_rate", 16000))
            except (TypeError, ValueError):
                rate = 16000
            if rate < 8000 or rate > 48000:
                await send_error("bad_sample_rate", "error_generic", "sample rate must be 8000-48000")
                return True
            await abort_live(utterance)
            live = None
            if settings.stt_streaming and not stt.simulated:
                try:
                    live = stt.stream(ctx.language, rate)
                    if hasattr(live, "on_partial"):
                        live.on_partial = send_partial
                except Exception as exc:  # noqa: BLE001 - batch fallback
                    logger.warning("could not open live STT: %s", type(exc).__name__)
                    live = None
            utterance = {"buffer": bytearray(), "rate": rate, "text": None, "live": live}
            return True

        if mtype == "utterance.text":
            text = str(data.get("text", "")).strip()
            final = bool(data.get("final", True))
            if not final:
                await send_events([{"type": "transcript.partial", "text": text}])
                return True
            rate = utterance["rate"] if utterance else 16000
            await abort_live(utterance)
            utterance = None
            events = await orchestrator.process_audio(ctx, b"", rate, provided_text=text)
            await send_events(orchestrator.finish_turn(ctx, events))
            return True

        if mtype == "utterance.end":
            if utterance is None:
                return True
            current = utterance
            utterance = None
            vad_ms = data.get("vad_ms")
            try:
                vad_ms = int(vad_ms) if vad_ms is not None else None
            except (TypeError, ValueError):
                vad_ms = None
            events = await finish_utterance(current, vad_ms)
            await send_events(orchestrator.finish_turn(ctx, events))
            return True

        if mtype == "approval.response":
            credential = data.get("credential")
            dev = bool(data.get("dev", False))
            events = await orchestrator.handle_approval(ctx, credential, dev=dev)
            await send_events(events)
            return True

        if mtype == "ping":
            await send_events([{"type": "pong"}])
            return True

        if mtype == "session.end":
            return False

        # Unknown message types are ignored by contract.
        logger.debug("ignored websocket message type %s", mtype)
        return True

    def session_expired() -> bool:
        try:
            return not sessions.is_active(ctx.session_id)
        except Exception:  # noqa: BLE001
            return False

    try:
        while True:
            message = await websocket.receive()
            if message["type"] == "websocket.disconnect":
                break

            if ctx is not None:
                if session_expired():
                    await send_events(
                        [
                            {"type": "error", "code": "session_expired", "prompt_id": "session_expired", "message": "session expired"},
                            orchestrator._prompt(ctx, "session_expired"),
                        ]
                    )
                    await websocket.close(code=4401, reason="session expired")
                    break
                now = time.monotonic()
                if now - last_touch > 30:
                    last_touch = now
                    try:
                        sessions.touch(ctx.session_id)
                    except Exception:  # noqa: BLE001
                        pass

            try:
                if message.get("bytes") is not None:
                    await handle_binary(message["bytes"])
                    continue
                if not await handle_text(message):
                    break
            except WebSocketDisconnect:
                raise
            except Exception:
                # One bad turn must not end the session or claim money did
                # not move when it may have.
                logger.exception("websocket message failed")
                utterance = None
                if ctx is not None:
                    try:
                        await send_events(orchestrator.safe_error_events(ctx))
                    except Exception:  # noqa: BLE001
                        pass
                else:
                    await send_error("internal_error", "error_generic", "internal error")
    except WebSocketDisconnect:
        pass
    except Exception:
        logger.exception("websocket failed")
    finally:
        await abort_live(utterance)
        if ctx is not None:
            ctx.closed = True
            if ctx.hold_task and not ctx.hold_task.done():
                ctx.hold_task.cancel()
            if tick_task and not tick_task.done():
                tick_task.cancel()
            try:
                sessions.close(ctx.session_id)
            except Exception:
                logger.exception("failed to close session")
