"""Self-hosted YarnGPT on Modal (10 Nov 2026): {text, lang, speaker} -> wav, with fallbacks."""
from __future__ import annotations

import json

import httpx
import pytest

from avenza.config import Settings
from avenza.providers.ai_speech import AIModalYarnTTS
from avenza.providers.base import AudioResult
from avenza.providers.stt import build_tts
from avenza_ai.providers.audio import pcm_to_wav_bytes, tone_pcm
from avenza_ai.providers.yarngpt_modal import ModalYarnGPTTTS, parse_speakers
from avenza_ai.types import ProviderError

URL = "https://team--yarngpt-yarngpt-tts.us-east.modal.run"


def modal_with(handler, **kw):
    return ModalYarnGPTTTS(url=URL, client=httpx.AsyncClient(transport=httpx.MockTransport(handler)), **kw)


async def test_sends_text_language_and_speaker_and_decodes_the_wav():
    seen = []

    def handler(req):
        seen.append(json.loads(req.content))
        return httpx.Response(200, content=pcm_to_wav_bytes(tone_pcm(0.2, 24000), 24000), headers={"content-type": "audio/wav"})

    tts = modal_with(handler)
    res = await tts.synthesize("Good morning, Lagos!", None, "en")
    assert seen[0] == {"text": "Good morning, Lagos!", "lang": "english", "speaker": "idera"}
    assert res.sample_rate == 24000 and len(res.pcm) == 9600
    await tts.synthesize("Ẹ káàárọ̀", None, "yo")
    assert seen[1]["lang"] == "yoruba" and seen[1]["speaker"] == "yoruba_female2"  # a Yoruba voice, never an English one


async def test_speakers_can_be_overridden_and_an_explicit_voice_wins():
    seen = []

    def handler(req):
        seen.append(json.loads(req.content))
        return httpx.Response(200, content=pcm_to_wav_bytes(tone_pcm(0.05, 24000), 24000), headers={"content-type": "audio/wav"})

    tts = modal_with(handler, speakers=parse_speakers("en=jude, ha=hausa_male2"))
    await tts.synthesize("Hello there", None, "en")
    await tts.synthesize("Sannu", None, "ha")
    await tts.synthesize("Hello there", "zainab", "en")
    assert [s["speaker"] for s in seen] == ["jude", "hausa_male2", "zainab"]


async def test_json_base64_responses_are_accepted():
    import base64

    wav = pcm_to_wav_bytes(tone_pcm(0.05, 16000), 16000)
    tts = modal_with(lambda r: httpx.Response(200, json={"audio": base64.b64encode(wav).decode()}))
    res = await tts.synthesize("Hello there", None, "en")
    assert res.sample_rate == 16000


@pytest.mark.parametrize("response", [
    httpx.Response(500, text="CUDA out of memory"),
    httpx.Response(422, json={"detail": [{"msg": "field required"}]}),
    httpx.Response(200, content=b""),
])
async def test_errors_are_reported(response):
    tts = modal_with(lambda r: response)
    with pytest.raises(ProviderError):
        await tts.synthesize("Hello there", None, "en")
    assert tts.last_error


def test_not_configured_without_a_url(monkeypatch):
    monkeypatch.delenv("YARNGPT_MODAL_URL", raising=False)
    assert not ModalYarnGPTTTS(url="").is_configured()
    s = Settings().for_test(tts_provider="yarngpt-modal", yarngpt_modal_url="")
    assert build_tts(s).name == "mock"  # no URL: the device voice, never a crash


class FakeHosted:
    name = "ai:yarngpt"
    simulated = False

    def __init__(self):
        self.calls = 0

    async def synthesize(self, text, voice="", language="en"):
        self.calls += 1
        return AudioResult(b"\x01\x00" * 8, 24000, self.name, text=text)


async def test_wrapper_falls_back_to_the_hosted_api_when_modal_fails():
    tts = AIModalYarnTTS(Settings().for_test(tts_provider="yarngpt-modal", yarngpt_modal_url=URL, yarngpt_modal_mode="all"))
    tts.modal = modal_with(lambda r: httpx.Response(503, text="no capacity"))
    tts.fallback = FakeHosted()
    res = await tts.synthesize("Hello there", language="en")
    assert res.provider == "ai:yarngpt" and tts.fallback.calls == 1


async def test_wrapper_uses_modal_audio_when_it_works():
    tts = AIModalYarnTTS(Settings().for_test(tts_provider="yarngpt-modal", yarngpt_modal_url=URL, yarngpt_modal_mode="all"))
    tts.modal = modal_with(lambda r: httpx.Response(200, content=pcm_to_wav_bytes(tone_pcm(0.1, 24000), 24000)))
    tts.fallback = FakeHosted()
    res = await tts.synthesize("Hello there", language="en")
    assert res.provider == "ai:yarngpt-modal" and not res.is_empty and tts.fallback.calls == 0
    assert build_tts(Settings().for_test(tts_provider="yarngpt-modal", yarngpt_modal_url=URL)).name == "ai:yarngpt-modal"


async def test_no_fallback_configured_gives_empty_audio_so_the_phone_speaks():
    tts = AIModalYarnTTS(Settings().for_test(tts_provider="yarngpt-modal", yarngpt_modal_url=URL, yarngpt_api_key="", yarn_api_key="", yarngpt_modal_mode="all"))
    tts.modal = modal_with(lambda r: httpx.Response(500))
    tts.fallback = None
    assert (await tts.synthesize("Hello there", language="en")).is_empty


async def test_prewarm_mode_modal_voices_cached_prompts_and_live_replies_never_wait_for_it():
    """Measured 10 Nov: ~21 s warm for 4.8 s of speech, far over the 6 s a live reply may wait."""
    calls = []

    def handler(req):
        calls.append(json.loads(req.content)["text"])
        return httpx.Response(200, content=pcm_to_wav_bytes(tone_pcm(0.1, 24000), 24000))

    tts = AIModalYarnTTS(Settings().for_test(tts_provider="yarngpt-modal", yarngpt_modal_url=URL))  # default mode
    tts.modal = modal_with(handler)
    tts.fallback = FakeHosted()
    cached = await tts.synthesize_for_cache("Cancelled. No money moved.", language="en")
    assert cached.provider == "ai:yarngpt-modal" and calls == ["Cancelled. No money moved."]
    live = await tts.synthesize("You are about to send five thousand naira.", language="en")
    assert live.provider == "ai:yarngpt" and calls == ["Cancelled. No money moved."]  # Modal not called live
    tts.fallback = None
    assert (await tts.synthesize("Reply text here", language="en")).is_empty  # no hosted key: the phone speaks at once


async def test_orchestrator_prewarm_uses_the_cache_path(services):
    o = services["orchestrator"]
    used = []

    class Split:
        name, simulated = "split", False

        async def synthesize(self, text, voice="", language="en"):
            used.append("live")
            return AudioResult(b"\x01\x00" * 4, 24000, self.name, text=text)

        async def synthesize_for_cache(self, text, voice="", language="en"):
            used.append("cache")
            return AudioResult(b"\x01\x00" * 4, 24000, self.name, text=text)

    o.tts = Split()
    await o.prewarm_tts()
    assert used and set(used) == {"cache"}


async def test_a_long_cold_start_303_is_followed_to_the_result():
    """Probe 10 Nov: the first call on a new L4 container ran past 150 s and Modal answered 303."""
    calls = []

    def handler(req):
        calls.append((req.method, req.url.path))
        if req.method == "POST":
            return httpx.Response(303, headers={"location": "https://team--yarngpt-yarngpt-tts.us-east.modal.run/__result/fc-1"})
        return httpx.Response(200, content=pcm_to_wav_bytes(tone_pcm(0.1, 24000), 24000), headers={"content-type": "audio/wav"})

    res = await modal_with(handler).synthesize("Hello there", None, "en")
    assert calls == [("POST", "/"), ("GET", "/__result/fc-1")]
    assert res.sample_rate == 24000 and res.pcm
