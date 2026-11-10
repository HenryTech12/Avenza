"""YarnGPT findings from the cluster probe (10 Nov 2026).

1. YarnGPT rejects text under 20 characters (422 INPUT_TOO_SHORT): such text is
   never sent, and no English prompt is that short.
2. A clip takes 3.5-4.6 s to arrive, so fixed prompts are synthesised once at
   startup and only read-backs wait for TTS.
"""
from __future__ import annotations

import asyncio
import dataclasses
from collections import defaultdict

import httpx

from avenza.prompts import PROMPTS, PromptLibrary
from avenza.providers.base import AudioResult
from avenza_ai.providers.yarngpt_tts import MIN_CHARS, YarnGPTTTS
from tests.conftest import make_customer

REQUEST = "Send five thousand naira to GTBank account 0123456789"


def test_no_english_prompt_is_under_the_yarngpt_minimum():
    short = {}
    for prompt_id, template in PROMPTS["en"].items():
        # Placeholders rendered empty: the shortest the prompt can ever be.
        text = template.format_map(defaultdict(str)).strip()
        if len(text) < MIN_CHARS:
            short[prompt_id] = text
    assert short == {}


def test_yarngpt_is_not_called_for_text_under_20_characters():
    calls = []

    def handler(req):
        calls.append(req)
        return httpx.Response(422, json={"error": {"code": "INPUT_TOO_SHORT"}})

    tts = YarnGPTTTS(api_key="k", default_voice="V", client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    result = asyncio.run(tts.synthesize("Payment settled.", None, "en"))
    assert calls == [] and result.pcm == b"" and tts.last_error is None


class CountingTTS:
    name = "counting"
    simulated = False

    def __init__(self, fail_on: str = ""):
        self.texts: list[str] = []
        self.fail_on = fail_on

    async def synthesize(self, text, voice="", language="en"):
        self.texts.append(text)
        if self.fail_on and self.fail_on in text:
            raise RuntimeError("provider down")
        return AudioResult(b"\x01\x00" * 10, 24000, self.name, ttfa_ms=4000, text=text)


async def test_prewarm_caches_every_fixed_prompt_once(services):
    o = services["orchestrator"]
    o.tts = CountingTTS()
    fixed = o.fixed_prompts(["en"])
    lib = PromptLibrary()
    assert ("en", lib.render("confirm_voice").text) in fixed
    assert all("{" not in PROMPTS["en"][pid] for pid in PROMPTS["en"] if ("en", PROMPTS["en"][pid]) in fixed)
    assert not any(t == lib.render("readback").text for _, t in fixed)  # variable prompts are not cached

    assert await o.prewarm_tts() == len(fixed)
    assert sorted(o.tts.texts) == sorted(t for _, t in fixed)
    assert await o.prewarm_tts() == 0  # nothing left to do, no extra credits


async def test_after_prewarm_only_the_readback_calls_tts(services):
    o = services["orchestrator"]
    o.tts = CountingTTS()
    o.settings = dataclasses.replace(o.settings, tts_cache_size=1)  # read-backs cannot evict the fixed prompts
    await o.prewarm_tts()
    o.tts.texts.clear()
    c = make_customer(services)
    events = await o.render_audio(c.ctx, await o.process_text(c.ctx, REQUEST))
    spoken = [e for e in events if e.get("type") == "prompt.play"]
    assert all(e.get("audio") for e in spoken)
    readback = next(e for e in spoken if e["id"] == "readback")
    assert o.tts.texts == [readback["text"]]

    o.tts.texts.clear()
    cancel = await o.render_audio(c.ctx, await o.process_text(c.ctx, "no"))
    assert [e["id"] for e in cancel if e.get("type") == "prompt.play"] == ["cancelled"]
    assert o.tts.texts == []  # "Cancelled. No money moved." came from the startup cache


async def test_prewarm_survives_a_failing_prompt_and_skips_simulated_tts(services):
    o = services["orchestrator"]
    assert await o.prewarm_tts() == 0  # the mock TTS is simulated: no calls at all
    o.tts = CountingTTS(fail_on="Cancelled")
    total = len(o.fixed_prompts(["en"]))
    assert await o.prewarm_tts() == total - 1
    o.settings = dataclasses.replace(o.settings, tts_prewarm=False)
    o._tts_fixed.clear()
    assert await o.prewarm_tts() == 0


async def test_prewarm_logs_when_it_starts_and_when_it_is_skipped(services, caplog):
    """An empty `grep "tts prewarm"` must mean old code, not a silent skip (10 Nov)."""
    import logging

    o = services["orchestrator"]
    with caplog.at_level(logging.INFO, logger="avenza.orchestrator"):
        await o.prewarm_tts()  # mock TTS: simulated
        o.tts = CountingTTS()
        await o.prewarm_tts()
    lines = [r.getMessage() for r in caplog.records if "tts prewarm" in r.getMessage()]
    assert lines[0].startswith("tts prewarm: skipped (tts=")
    assert lines[1].startswith("tts prewarm: starting ")
    assert " fixed prompts cached in " in lines[2]


class QuotaTTS(CountingTTS):
    """Like AIYarnTTS: a 402 comes back as empty audio, with the reason in last_error."""

    def __init__(self, credits_for: int):
        super().__init__()
        self.credits_for = credits_for
        self.last_error = None

    async def synthesize(self, text, voice="", language="en"):
        self.texts.append(text)
        if len(self.texts) > self.credits_for:
            self.last_error = "HTTP 402 QUOTA_EXCEEDED insufficient credits"
            return AudioResult(b"", 24000, self.name, text=text)
        return AudioResult(b"\x01\x00" * 10, 24000, self.name, text=text)


async def test_prewarm_stops_when_the_provider_is_out_of_credits(services, caplog):
    """Cluster, 10 Nov: 18 of 50 cached, then 32 more calls each answered 402."""
    import logging

    o = services["orchestrator"]
    o.tts = QuotaTTS(credits_for=5)
    o.settings = dataclasses.replace(o.settings, tts_prewarm_concurrency=1)
    with caplog.at_level(logging.WARNING, logger="avenza.orchestrator"):
        assert await o.prewarm_tts() == 5
    assert len(o.tts.texts) == 6  # five cached, one refused, then it stops
    assert sum("out of credits" in r.getMessage() for r in caplog.records) == 1


async def test_restart_replays_fixed_prompts_from_disk_with_no_tts_calls(services, tmp_path):
    """10 Nov: every start re-generated ~50 lines (credits, minutes on Modal). Now they are saved once."""
    o = services["orchestrator"]
    o.settings = dataclasses.replace(o.settings, tts_cache_dir=str(tmp_path))
    o.tts = CountingTTS()
    first = await o.prewarm_tts()
    assert first == len(o.fixed_prompts(["en"])) and len(o.tts.texts) == first
    assert len(list(tmp_path.glob("*.pcm"))) == first

    # a "restart": empty memory caches, a fresh TTS provider
    o._tts_fixed.clear()
    o._tts_cache.clear()
    o.tts = CountingTTS()
    assert await o.prewarm_tts() == first
    assert o.tts.texts == []  # nothing synthesised again


async def test_readbacks_never_reach_the_disk_cache(services, tmp_path):
    o = services["orchestrator"]
    o.settings = dataclasses.replace(o.settings, tts_cache_dir=str(tmp_path), tts_prewarm=False)
    o.tts = CountingTTS()
    c = make_customer(services)
    events = await o.render_audio(c.ctx, await o.process_text(c.ctx, REQUEST))
    readback = next(e for e in events if e.get("id") == "readback")
    assert readback.get("audio")
    saved = {p.read_bytes() for p in tmp_path.glob("*.pcm")}
    # only fixed prompts may be written; the read-back (name, amount) stays in memory
    assert len(list(tmp_path.glob("*.pcm"))) == sum(
        1 for e in events if e.get("type") == "prompt.play" and o.prompts.is_fixed(e["id"], "en")
    )
    assert saved is not None


async def test_changing_the_voice_does_not_replay_the_old_one(services, tmp_path):
    o = services["orchestrator"]
    o.settings = dataclasses.replace(o.settings, tts_cache_dir=str(tmp_path), yarngpt_default_voice="adaora")
    o.tts = CountingTTS()
    await o.prewarm_tts()
    o._tts_fixed.clear()
    o.settings = dataclasses.replace(o.settings, yarngpt_default_voice="umar")
    o.tts = CountingTTS()
    await o.prewarm_tts()
    assert len(o.tts.texts) == len(o.fixed_prompts(["en"]))  # new voice: generated again



async def test_prewarm_prepares_the_app_lines_in_each_chosen_language(services, tmp_path):
    """Phone test, 10 Nov: the first Yoruba onboarding paused before every line while it was generated."""
    from avenza.client_lines import CLIENT_LINES

    o = services["orchestrator"]
    o.settings = dataclasses.replace(o.settings, tts_cache_dir=str(tmp_path), tts_prewarm_languages="en,yo")
    o.tts = CountingTTS()
    await o.prewarm_tts()
    said = set(o.tts.texts)
    assert set(CLIENT_LINES["yo"].values()) <= said and CLIENT_LINES["en"]["ob_greeting"] in said
    assert o._disk_get("yo", CLIENT_LINES["yo"]["ob_consent"]) is not None  # what GET /voice/yo/... serves
