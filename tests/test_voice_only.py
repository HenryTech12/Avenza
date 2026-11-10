"""Voice-only use (10 Nov 2026): balance and navigation by voice, and answering in the customer's language."""
from __future__ import annotations

import pytest

from avenza.intent import Intent, keyword_intent, language_request, navigation_target
from avenza.langdetect import detect_language
from avenza.prompts import PROMPTS
from tests.conftest import make_customer


def prompts_of(events):
    return [e for e in events if e.get("type") == "prompt.play"]


@pytest.mark.parametrize("text,intent", [
    ("check my balance", Intent.BALANCE),
    ("what is my balance", Intent.BALANCE),
    ("open settings", Intent.NAVIGATE),
    ("go home", Intent.NAVIGATE),
    ("speak Yoruba", Intent.LANGUAGE),
    ("show my last five transactions", Intent.HISTORY),
    ("send five thousand naira to my igbo friend at GTBank 0123987001", Intent.TRANSFER),
    ("yes", Intent.YES),
    ("no", Intent.NO),
])
def test_voice_commands_are_recognised(text, intent):
    assert keyword_intent(text).intent == intent


def test_navigation_and_language_targets():
    assert navigation_target("open my profile") == "settings"
    assert navigation_target("go back") == "home"
    assert navigation_target("send money") is None
    assert language_request("switch to Hausa please") == "ha"
    assert language_request("Igbo") == "ig"
    assert language_request("speak English") == "en"
    assert language_request("send money to my Yoruba friend") is None  # a name in a sentence is not a switch


@pytest.mark.parametrize("text,lang", [
    ("Send five thousand naira to GTBank account 0123987001", "en"),
    ("Mo fẹ́ fi ẹgbẹ̀rún márùn-ún náírà ránṣẹ́ sí GTBank", "yo"),
    ("mo fe fi owo ranse si akanti mi", "yo"),
    ("Ina son in aika naira dubu biyar zuwa GTBank", "ha"),
    ("Biko ziga puku naira ise na akaụntụ m", "ig"),
    ("ee", None),  # shared one-word replies never switch the language
    ("ok send it", None),
    ("yes", None),
])
def test_language_detection_is_cautious(text, lang):
    assert detect_language(text) == lang


async def test_saying_a_language_switches_replies_and_marks_beta(services):
    o = services["orchestrator"]
    c = make_customer(services)
    events = await o.process_text(c.ctx, "speak Yoruba")
    changed = next(e for e in events if e["type"] == "language.changed")
    assert changed == {"type": "language.changed", "language": "yo", "previous": "en", "beta": True, "reason": "asked"}
    assert c.ctx.language == "yo"
    spoken = [p["text"] for p in prompts_of(events)]
    assert spoken == [PROMPTS["yo"]["language_switched"], PROMPTS["yo"]["language_beta"]]
    assert events[-1]["type"] == "listening"
    back = await o.process_text(c.ctx, "speak English")
    assert c.ctx.language == "en" and next(e for e in back if e["type"] == "language.changed")["beta"] is False


async def test_detected_language_switches_then_the_request_still_runs(services):
    o = services["orchestrator"]
    c = make_customer(services)
    events = await o.process_text(c.ctx, "Ina son in aika naira dubu biyar zuwa GTBank")
    assert c.ctx.language == "ha"
    assert events[0]["type"] == "language.changed" and events[0]["reason"] == "detected"
    # the turn is still handled after the switch (here: Avenza asks for what is missing)
    assert len(prompts_of(events)) >= 3


async def test_detection_can_be_turned_off(services):
    import dataclasses

    o = services["orchestrator"]
    o.settings = dataclasses.replace(o.settings, language_detection=False)
    c = make_customer(services)
    await o.process_text(c.ctx, "Ina son in aika naira dubu biyar zuwa GTBank")
    assert c.ctx.language == "en"


async def test_navigation_by_voice(services):
    o = services["orchestrator"]
    c = make_customer(services)
    events = await o.process_text(c.ctx, "open settings")
    assert {"type": "navigate", "screen": "settings"} in events
    assert prompts_of(events)[0]["text"] == PROMPTS["en"]["nav_settings"]
    history = await o.process_text(c.ctx, "show my last five transactions")
    assert history[0] == {"type": "navigate", "screen": "history"}


async def test_balance_by_voice_reads_the_bank_figure(services):
    o = services["orchestrator"]
    c = make_customer(services)

    async def get_balance(account):
        return {"available_kobo": 18425000}

    o.bank.get_balance = get_balance
    events = await o.process_text(c.ctx, "what is my balance")
    assert {"type": "balance", "available_kobo": 18425000, "available_display": "₦184,250.00"} in events
    assert prompts_of(events)[0]["text"] == "Your available balance is ₦184,250.00."


async def test_balance_never_invents_a_number(services):
    o = services["orchestrator"]
    c = make_customer(services)

    async def broken(account):
        raise RuntimeError("bank down")

    o.bank.get_balance = broken
    events = await o.process_text(c.ctx, "check my balance")
    assert not any(e["type"] == "balance" for e in events)
    assert prompts_of(events)[0]["text"] == PROMPTS["en"]["balance_unavailable"]


def test_new_english_lines_are_long_enough_for_yarngpt():
    for key in ("balance_unavailable", "nav_home", "nav_settings", "language_switched", "language_beta"):
        assert len(PROMPTS["en"][key]) >= 20
