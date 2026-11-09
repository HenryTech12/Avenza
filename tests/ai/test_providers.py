import asyncio
import json

import httpx
import pytest

from avenza_ai.providers import (DeepgramSTTProvider, MockSTTProvider, MockTTSProvider, ProviderChoice,
                                 SaharaSTTProvider, YarnGPTSTTProvider, YarnGPTTTS)
from avenza_ai.providers.audio import (decode_audio_response, pcm_to_wav_bytes, tone_pcm, wav_bytes_to_pcm)
from avenza_ai.types import NotConfigured, ProviderError, UnsupportedLanguage

run = asyncio.run
PCM = b"\x01\x00" * 3200


def test_mock_stt_returns_text_and_timing():
    r = run(MockSTTProvider("send five thousand naira").transcribe(PCM, "en", 16000))
    assert r.text == "send five thousand naira"
    assert r.timing.time_to_first_partial_ms is not None and r.timing.time_to_final_ms is not None
    assert any(not e.is_final for e in r.events) and r.events[-1].is_final


def test_mock_stt_failure_is_raised_not_swallowed():
    p = MockSTTProvider("x", fail_with=ProviderError("boom"))
    with pytest.raises(ProviderError):
        run(p.transcribe(PCM, "en", 16000))


def test_mock_stt_unsupported_language():
    p = MockSTTProvider("x", languages={"en"})
    with pytest.raises(UnsupportedLanguage):
        p.stream("yo", 16000)


def test_mock_stt_script_list_and_callable():
    p = MockSTTProvider(["one", "two"])
    assert run(p.transcribe(PCM, "en", 16000)).text == "one"
    assert run(p.transcribe(PCM, "en", 16000)).text == "two"
    q = MockSTTProvider(lambda pcm, lang: f"{lang}:{len(pcm)}")
    assert run(q.transcribe(PCM, "ha", 16000)).text == f"ha:{len(PCM)}"


# ---- Deepgram -------------------------------------------------------------------------
def dg_result(text, final, conf=0.9):
    return json.dumps({"type": "Results", "is_final": final,
                       "channel": {"alternatives": [{"transcript": text, "confidence": conf}]}})


def test_deepgram_parse_messages():
    p = DeepgramSTTProvider(api_key="k")
    assert p.parse_message(dg_result("send five", False))[0].is_final is False
    ev = p.parse_message(dg_result("send five thousand", True))[0]
    assert ev.text == "send five thousand" and ev.is_final and ev.confidence == 0.9
    assert p.parse_message(dg_result("", True)) == []
    assert p.parse_message(json.dumps({"type": "Metadata"})) == []
    assert p.parse_message("not json") == []
    with pytest.raises(ProviderError):
        p.parse_message(json.dumps({"type": "Error", "description": "bad key"}))


def test_deepgram_url_headers_and_languages():
    p = DeepgramSTTProvider(api_key="secret", model="nova-2")
    u = p.url("en", 16000)
    assert "encoding=linear16" in u and "sample_rate=16000" in u and "interim_results=true" in u
    assert p.headers() == {"Authorization": "Token secret"}
    assert p.supports("en") and p.supports("pcm")
    assert not p.supports("yo") and not p.supports("ha") and not p.supports("ig")   # unproven: not assumed
    with pytest.raises(UnsupportedLanguage):
        p.stream("yo", 16000)
    assert json.loads(p.end_message()) == {"type": "CloseStream"}


def test_deepgram_unconfigured_fails_clearly():
    p = DeepgramSTTProvider(api_key="")
    assert not p.is_configured()
    with pytest.raises(NotConfigured):
        run(p.transcribe(PCM, "en", 16000))


def test_deepgram_streaming_against_a_local_websocket_server():
    from websockets.asyncio.server import serve

    received = {"audio": 0, "headers": None, "path": None, "closed": False}

    async def handler(ws):
        received["headers"] = ws.request.headers
        received["path"] = ws.request.path
        async for msg in ws:
            if isinstance(msg, bytes):
                if received["audio"] == 0:
                    await ws.send(dg_result("send five", False))
                received["audio"] += len(msg)
            elif json.loads(msg).get("type") == "CloseStream":
                received["closed"] = True
                await ws.send(dg_result("send five thousand naira", True, 0.93))
                await ws.close()

    async def main():
        async with serve(handler, "127.0.0.1", 0) as server:
            port = server.sockets[0].getsockname()[1]
            p = DeepgramSTTProvider(api_key="abc", base_url=f"ws://127.0.0.1:{port}/v1/listen")
            return await p.transcribe(PCM, "en", 16000, chunk_ms=50)

    res = run(main())
    assert res.text == "send five thousand naira" and res.confidence == pytest.approx(0.93)
    assert received["audio"] == len(PCM) and received["closed"]
    assert received["headers"].get("Authorization") == "Token abc" and "language=en" in received["path"]
    assert res.timing.time_to_first_partial_ms is not None


def test_deepgram_multiple_finals_are_joined():
    from websockets.asyncio.server import serve

    async def handler(ws):
        async for msg in ws:
            if isinstance(msg, str):
                await ws.send(dg_result("send five thousand", True))
                await ws.send(dg_result("naira to Aisha", True))
                await ws.close()

    async def main():
        async with serve(handler, "127.0.0.1", 0) as server:
            port = server.sockets[0].getsockname()[1]
            p = DeepgramSTTProvider(api_key="abc", base_url=f"ws://127.0.0.1:{port}/v1/listen")
            return await p.transcribe(PCM, "en", 16000)

    assert run(main()).text == "send five thousand naira to Aisha"


def test_connection_failure_is_a_provider_error():
    p = DeepgramSTTProvider(api_key="abc", base_url="ws://127.0.0.1:9/v1/listen")
    with pytest.raises(ProviderError):
        run(p.transcribe(PCM, "en", 16000, timeout=5))


# ---- YarnGPT live ASR (documented protocol) / Sahara scaffold ----------------------
def test_providers_need_url_and_key(monkeypatch):
    for k in ("YARNGPT_ASR_WS_URL", "SAHARA_ASR_WS_URL", "YARNGPT_API_KEY", "SAHARA_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    assert not SaharaSTTProvider().is_configured()
    assert not YarnGPTSTTProvider().is_configured()  # default URL, but no key
    assert YarnGPTSTTProvider(api_key="k").url("en", 16000) == "wss://api.yarngpt.ai/api/v1/asr/stream"
    assert YarnGPTSTTProvider(api_key="k").is_configured()


def test_yarngpt_asr_messages_follow_the_docs():
    p = YarnGPTSTTProvider(url="wss://x.test/api/v1/asr/stream", api_key="k")
    start = json.loads(p.start_message("en", 16000))
    assert start == {
        "type": "start",
        "audio": {"encoding": "pcm_s16le", "sample_rate": 16000, "channels": 1},
        "options": {"endpoint_silence_ms": 500, "partials": True},
    }
    assert json.loads(p.end_message()) == {"type": "finalize"}
    assert p.url("yo", 16000) == "wss://x.test/api/v1/asr/stream"  # no query parameters
    assert p.headers() == {"Authorization": "Bearer k"}
    assert p.parse_message(json.dumps({"type": "partial", "segment": 0, "text": "send five"}))[0].is_final is False
    assert p.parse_message(json.dumps({"type": "final", "segment": 0, "text": "send five thousand"}))[0].is_final
    for ignored in ("status", "started", "done", "translation", "something_new"):
        assert p.parse_message(json.dumps({"type": ignored})) == []
    with pytest.raises(ProviderError, match="RATE_LIMITED"):
        p.parse_message(json.dumps({"type": "error", "error": {"code": "RATE_LIMITED", "message": "x"}}))


def test_yarngpt_asr_stream_against_a_documented_server():
    from websockets.asyncio.server import serve

    seen = {"audio": 0}

    async def handler(ws):
        seen["auth"] = ws.request.headers.get("Authorization")
        seen["path"] = ws.request.path
        start = json.loads(await ws.recv())
        seen["start"] = start
        await ws.send(json.dumps({"type": "status", "state": "connecting"}))
        await ws.send(json.dumps({"type": "started", "stream_id": "s1", "limits": {}}))
        async for msg in ws:
            if isinstance(msg, bytes):
                seen["audio"] += len(msg)
                if seen["audio"] == 3200:
                    await ws.send(json.dumps({"type": "partial", "segment": 0, "text": "send five"}))
            elif json.loads(msg)["type"] == "finalize":
                await ws.send(json.dumps({"type": "final", "segment": 0, "text": "send five thousand naira",
                                          "start_seconds": 0, "end_seconds": 1.2}))
                await ws.send(json.dumps({"type": "final", "segment": 1, "text": "to GTBank",
                                          "start_seconds": 1.4, "end_seconds": 2.0}))
                await ws.send(json.dumps({"type": "done", "reason": "finalized", "stream_id": "s1"}))
                await ws.close(1000)
                return

    async def main():
        async with serve(handler, "127.0.0.1", 0) as server:
            port = server.sockets[0].getsockname()[1]
            p = YarnGPTSTTProvider(url=f"ws://127.0.0.1:{port}/api/v1/asr/stream", api_key="sk_test")
            return await p.transcribe(PCM, "en", 16000, chunk_ms=50)

    res = run(main())
    assert res.text == "send five thousand naira to GTBank"
    assert seen["auth"] == "Bearer sk_test" and seen["path"] == "/api/v1/asr/stream"
    assert seen["start"]["audio"]["sample_rate"] == 16000 and seen["audio"] == len(PCM)


def _intron_server(seen, *, refuse=False):
    """A fake Intron Sahara stream that enforces the documented rules."""
    import base64

    async def handler(ws):
        seen["path"] = ws.request.path
        seen["auth"] = ws.request.headers.get("Authorization")
        if refuse:
            await ws.send(json.dumps({"message_type": "RESOURCE_EXHAUSTED", "status": "CAPACITY_NOT_AVAILABLE"}))
            await ws.close(1000)
            return
        await ws.send(json.dumps({"message_type": "SESSION_CREATED", "session_id": "s1", "credit_balance": 10,
                                  "configs": {"sample_rate": 16000}}))
        seen["chunks"] = []
        async for raw in ws:
            assert isinstance(raw, str), "Intron takes JSON text frames, not binary"
            msg = json.loads(raw)
            if msg["message_type"] == "INPUT_AUDIO_CHUNK":
                size = len(base64.b64decode(msg["audio_base_64"]))
                if not 1024 <= size <= 32 * 1024:
                    await ws.send(json.dumps({"message_type": "CHUNK_SIZE_TOO_SMALL" if size < 1024 else "CHUNK_SIZE_TOO_LARGE"}))
                    await ws.close(1000)
                    return
                seen["chunks"].append(size)
                await ws.send(json.dumps({"message_type": "AUDIO_CHUNK_ACK", "chunk_id": len(seen["chunks"])}))
                if len(seen["chunks"]) == 1:
                    await ws.send(json.dumps({"message_type": "PARTIAL_TRANSCRIPT", "transcript": "send five"}))
            elif msg["message_type"] == "COMMIT":
                await ws.send(json.dumps({"message_type": "COMMITTED_TRANSCRIPT", "transcript_id": "t1",
                                          "transcript_text": "send five thousand naira abeg", "audio_len": 1.0}))
                await ws.close(1000)
                return

    return handler


def test_sahara_follows_intron_streaming_protocol():
    from websockets.asyncio.server import serve

    seen = {}

    async def main():
        async with serve(_intron_server(seen), "127.0.0.1", 0) as server:
            port = server.sockets[0].getsockname()[1]
            p = SaharaSTTProvider(url=f"ws://127.0.0.1:{port}/stt/v1/stream", api_key="ik")
            # 20 ms frames (640 bytes) are below Intron's 1 KB minimum: they must be buffered.
            return await p.transcribe(PCM * 3, "en", 16000, chunk_ms=20)

    res = run(main())
    assert res.text == "send five thousand naira abeg"
    assert seen["auth"] == "Bearer ik"
    assert "use_language_asr_input=en" in seen["path"] and "sample_rate=16000" in seen["path"]
    assert sum(seen["chunks"]) >= len(PCM) * 3 and all(1024 <= c <= 32768 for c in seen["chunks"])


def test_sahara_short_tail_is_padded_not_dropped():
    p = SaharaSTTProvider(url="wss://x/stt/v1/stream", api_key="k")
    state = {}
    assert p.frame_audio(state, b"\x01\x00" * 100) == []  # 200 bytes: buffered
    (msg,) = p.flush_audio(state)
    import base64

    assert len(base64.b64decode(json.loads(msg)["audio_base_64"])) == 1024


def test_sahara_errors_and_events():
    p = SaharaSTTProvider(url="wss://x/stt/v1/stream", api_key="k")
    assert p.parse_message(json.dumps({"message_type": "PARTIAL_TRANSCRIPT", "transcript": "hi"}))[0].is_final is False
    assert p.parse_message(json.dumps({"message_type": "COMMITTED_TRANSCRIPT", "transcript_text": "hi"}))[0].is_final
    assert p.parse_message(json.dumps({"message_type": "AUDIO_CHUNK_ACK", "chunk_id": 1})) == []
    with pytest.raises(ProviderError, match="QUOTA_EXCEEDED"):
        p.parse_message(json.dumps({"message_type": "QUOTA_EXCEEDED", "message": "no credits"}))
    assert json.loads(p.end_message()) == {"message_type": "COMMIT"}
    assert p.url("en", 16000).startswith("wss://x/stt/v1/stream?")


def test_sahara_refusal_falls_back_to_the_next_provider():
    """Intron allows 3 connections a minute: a refused turn must still be heard."""
    from websockets.asyncio.server import serve

    from avenza.config import Settings
    from avenza.providers.ai_speech import AIWebSocketSTT

    seen_sahara, seen_yarn = {}, {"audio": 0}

    async def yarn_handler(ws):
        json.loads(await ws.recv())
        await ws.send(json.dumps({"type": "started"}))
        async for msg in ws:
            if isinstance(msg, bytes):
                seen_yarn["audio"] += len(msg)
            elif json.loads(msg)["type"] == "finalize":
                await ws.send(json.dumps({"type": "final", "segment": 0, "text": "send five thousand naira"}))
                await ws.send(json.dumps({"type": "done", "reason": "finalized"}))
                await ws.close(1000)
                return

    async def main():
        async with serve(_intron_server(seen_sahara, refuse=True), "127.0.0.1", 0) as sahara, \
                serve(yarn_handler, "127.0.0.1", 0) as yarn:
            settings = Settings().for_test(
                stt_provider="ai",
                ai_stt_choice="en=sahara|yarngpt",
                sahara_api_key="ik",
                sahara_asr_url=f"ws://127.0.0.1:{sahara.sockets[0].getsockname()[1]}/stt/v1/stream",
                yarngpt_api_key="yk",
                yarngpt_asr_url=f"ws://127.0.0.1:{yarn.sockets[0].getsockname()[1]}/api/v1/asr/stream",
            )
            stt = AIWebSocketSTT(settings)
            live = stt.stream("en", 16000)
            for i in range(0, len(PCM), 640):
                await live.push(PCM[i : i + 640])
            return await live.end()

    res = run(main())
    assert res.text == "send five thousand naira" and res.provider == "ai:yarngpt"
    assert seen_yarn["audio"] == len(PCM)  # every frame, including those before the switch


# ---- audio helpers --------------------------------------------------------------------
def test_wav_roundtrip_and_decode():
    wav = pcm_to_wav_bytes(PCM, 16000)
    assert wav_bytes_to_pcm(wav) == (PCM, 16000)
    assert decode_audio_response(wav, 24000) == (PCM, 16000)
    assert decode_audio_response(PCM, 24000) == (PCM, 24000)
    with pytest.raises(ProviderError):
        decode_audio_response(b"ID3\x03\x00rest", 24000)


# ---- TTS -------------------------------------------------------------------------------
CONVERSATION = "https://api.yarngpt.ai/api/v1/streaming/conversation"


def tts_with(handler, url=CONVERSATION, **kw):
    return YarnGPTTTS(api_key="k", url=url, default_voice="V",
                      client=httpx.AsyncClient(transport=httpx.MockTransport(handler)), **kw)


def test_yarngpt_tts_uses_the_conversation_route_and_reads_the_rate_header():
    seen = {}

    def handler(req):
        seen["url"], seen["json"] = str(req.url), json.loads(req.read())
        seen["auth"], seen["idem"] = req.headers["Authorization"], req.headers.get("Idempotency-Key")
        return httpx.Response(200, content=tone_pcm(0.1, 22050),
                              headers={"Content-Type": "audio/l16; rate=22050; channels=1"})

    res = run(tts_with(handler).synthesize("Hello", None, "en"))
    assert seen["url"] == CONVERSATION
    assert seen["json"] == {"text": "Hello", "output_format": "pcm", "voice": "V"}
    assert seen["auth"] == "Bearer k" and seen["idem"]
    assert res.sample_rate == 22050 and len(res.pcm) == 4410  # rate from the header, never assumed
    assert res.timing.time_to_first_audio_ms is not None


def test_yarngpt_tts_still_decodes_wav():
    res = run(tts_with(lambda r: httpx.Response(200, content=pcm_to_wav_bytes(tone_pcm(0.1, 24000), 24000),
                                                 headers={"Content-Type": "audio/wav"})).synthesize("Hi", None, "en"))
    assert res.sample_rate == 24000 and len(res.pcm) == 4800


@pytest.mark.parametrize("configured", [
    "wss://api.yarngpt.ai/api/v1/asr/stream",   # the ASR socket pasted into the TTS setting
    "https://api.yarngpt.ai/api/v1/tts",        # the async job route: returns a job id, not audio
    "",
])
def test_yarngpt_tts_url_is_corrected_to_the_conversation_route(configured, monkeypatch):
    monkeypatch.delenv("YARNGPT_TTS_URL", raising=False)
    assert YarnGPTTTS(api_key="k", url=configured).url == CONVERSATION


def test_yarngpt_tts_reports_the_error_envelope():
    body = {"error": {"code": "QUOTA_EXCEEDED", "message": "top up", "trace_id": "tr_1"}}
    tts = tts_with(lambda r: httpx.Response(402, json=body))
    with pytest.raises(ProviderError, match="402 QUOTA_EXCEEDED"):
        run(tts.synthesize("Hi", None, "en"))
    assert "tr_1" in tts.last_error


def test_yarngpt_tts_errors():
    with pytest.raises(ProviderError):
        run(tts_with(lambda r: httpx.Response(503)).synthesize("Hi", None, "en"))
    with pytest.raises(ProviderError):
        run(tts_with(lambda r: httpx.Response(200, content=b"ID3....")).synthesize("Hi", None, "en"))
    with pytest.raises(ProviderError):
        run(tts_with(lambda r: httpx.Response(200)).synthesize("   ", None, "en"))
    with pytest.raises(NotConfigured):
        run(YarnGPTTTS(api_key="").synthesize("Hi", None, "en"))


def test_mock_tts_records_calls():
    t = MockTTSProvider()
    r = run(t.synthesize("Hi", "v", "en"))
    assert r.pcm and t.calls == [("Hi", "v", "en")]


# ---- registry ---------------------------------------------------------------------------
def test_registry_only_serves_languages_that_passed(tmp_path):
    f = tmp_path / "choice.json"
    f.write_text(json.dumps({"choice": {"en": "deepgram", "ha": "yarngpt"}, "enabled_languages": ["en"]}))
    c = ProviderChoice.load(str(f))
    assert c.stt_for("en").name == "deepgram"
    with pytest.raises(LookupError):
        c.stt_for("ha")
    default = ProviderChoice.load(str(tmp_path / "missing.json"))
    assert default.enabled_languages == ["en", "pcm"]


def test_yarngpt_tts_uses_the_catalogue_default_voice_when_none_is_set(monkeypatch):
    monkeypatch.delenv("YARNGPT_DEFAULT_VOICE", raising=False)
    calls = {"voices": 0, "bodies": []}

    def handler(req):
        if req.url.path == "/api/v1/voices":
            calls["voices"] += 1
            return httpx.Response(200, json=[{"name": "umar", "default": False}, {"name": "adaora", "default": True}])
        body = json.loads(req.read())
        calls["bodies"].append(body)
        if "voice" not in body:  # what YarnGPT really does
            return httpx.Response(422, json={"error": {"code": "INVALID_INPUT", "details": {"errors": [{"loc": ["body", "voice"]}]}}})
        return httpx.Response(200, content=tone_pcm(0.05, 24000), headers={"Content-Type": "audio/l16; rate=24000; channels=1"})

    tts = YarnGPTTTS(api_key="k", url=CONVERSATION, client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    run(tts.synthesize("Hi", None, "en"))
    run(tts.synthesize("Again", None, "en"))
    assert [b["voice"] for b in calls["bodies"]] == ["adaora", "adaora"]
    assert calls["voices"] == 1  # looked up once
