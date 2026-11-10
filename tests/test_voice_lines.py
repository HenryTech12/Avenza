"""App-spoken lines in the customer's language (phone test, 10 Nov 2026): Yoruba chosen,
but onboarding and "checking with your bank" were spoken in English."""
import dataclasses

from fastapi.testclient import TestClient

from avenza.client_lines import CLIENT_LINES, client_line
from avenza.config import Settings
from avenza.main import create_app
from avenza.providers.base import AudioResult


def test_every_language_has_every_line_except_the_language_question():
    for lang in ("yo", "ha", "ig"):
        missing = set(CLIENT_LINES["en"]) - set(CLIENT_LINES[lang])
        assert missing <= {"ob_ask_language", "ob_ask_language_again"}, (lang, missing)


def test_unknown_ids_are_refused_and_missing_languages_fall_back_to_english():
    assert client_line("yo", "anything goes") is None
    assert client_line("fr", "ob_ask_name") == ("en", CLIENT_LINES["en"]["ob_ask_name"])
    assert client_line("yo", "ob_ask_language")[0] == "en"


class FakeTTS:
    name, simulated = "fake", False

    def __init__(self):
        self.calls = []

    async def synthesize(self, text, voice="", language="en"):
        self.calls.append((language, text))
        return AudioResult(b"\x01\x00" * 100, 24000, self.name, text=text)


def test_voice_endpoint_returns_text_and_audio_then_serves_it_from_disk(tmp_path, monkeypatch):
    fake = FakeTTS()
    monkeypatch.setattr("avenza.main.build_tts", lambda settings: fake)
    app = create_app(Settings().for_test(tts_cache_dir=str(tmp_path), tts_prewarm=False))
    with TestClient(app) as client:
        r = client.get("/voice/yo/checking_bank")
        assert r.status_code == 200
        body = r.json()
        assert body["language"] == "yo" and body["text"] == CLIENT_LINES["yo"]["checking_bank"]
        assert body["audio"]["sample_rate"] == 24000 and body["audio"]["data"]
        assert fake.calls == [("yo", CLIENT_LINES["yo"]["checking_bank"])]
        again = client.get("/voice/yo/checking_bank").json()
        assert again["audio"]["data"] == body["audio"]["data"] and len(fake.calls) == 1  # from disk
        assert client.get("/voice/yo/not-a-line").status_code == 404


def test_voice_endpoint_without_a_real_voice_still_gives_the_text():
    with TestClient(create_app(Settings().for_test())) as client:  # mock TTS
        body = client.get("/voice/ha/ob_ask_name").json()
        assert body["text"] == CLIENT_LINES["ha"]["ob_ask_name"] and body["audio"] is None
