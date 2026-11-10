"""Which language is the customer speaking? (beta, 10 Nov 2026)

Avenza answers in the language it hears. Speech-to-text has to be told a
language before the audio is sent, so this works on the transcript of the
turn just finished and switches replies (and the next turn's speech-to-text)
when the words clearly belong to Hausa, Igbo or Yoruba, or clearly to English.

Deliberately cautious: it needs several marker words, or letters only one
language uses, and never switches on a one- or two-word reply ("ee", "ok"),
because those are shared across languages and decide confirmations.
Unverified for production: the word lists come from common phrases, not a
language test with native speakers.
"""
from __future__ import annotations

import re
import unicodedata

# Letters that point to one language.
_CHARS = {
    "ha": set("ƙɗɓƘƊƁ"),
    "ig": set("ịụṅỊỤṄ"),
    "yo": set("ẹṣẸṢ"),
}
# Common words in requests to a banking assistant, without tone marks.
_WORDS = {
    "ha": {
        "ina", "son", "aika", "tura", "kudi", "zuwa", "dubu", "biyar", "goma", "ashirin", "nawa", "asusun",
        "asusuna", "don", "allah", "yanzu", "naira", "ga", "na", "da", "shi", "ne", "ka", "kai", "sannu", "eh",
        "babu", "wannan", "lambar", "banki", "ta",
    },
    "ig": {
        "biko", "ziga", "ego", "puku", "nde", "ise", "iri", "achoro", "choro", "nye", "ka", "akaunt", "akaụntụ",
        "ndewo", "kedu", "mba", "ugbu", "a", "gi", "m", "na", "ozo", "nke", "ihe", "onye", "bu", "ulo", "aku",
    },
    "yo": {
        "mo", "fe", "fi", "ranse", "owo", "egberun", "marun", "mewa", "ogun", "si", "ni", "mi", "e", "jowo",
        "bawo", "akanti", "ile", "ifowopamo", "beeni", "rara", "ati", "lati", "ki", "lo", "elo", "melo", "naira",
    },
}
_EN = {
    "the", "to", "my", "send", "transfer", "please", "account", "money", "thousand", "hundred", "show", "what",
    "is", "how", "much", "i", "want", "and", "of", "for", "me", "can", "you", "last", "transactions", "balance",
    "bank", "pay", "check", "yes", "no", "it", "that", "this",
}
# Words every language here shares in a banking request; they never count.
_SHARED = {"naira", "gtbank", "zenith", "uba", "access", "wema", "kuda", "opay", "first", "bank", "ok", "okay"}


def _plain(text: str) -> str:
    """Lower case, tone marks removed, but dot-below letters kept (they carry the signal)."""
    out = []
    for ch in unicodedata.normalize("NFD", text.lower()):
        if unicodedata.category(ch) == "Mn" and ch != "̣":
            continue
        out.append(ch)
    return unicodedata.normalize("NFC", "".join(out))


def detect_language(text: str, current: str = "en") -> str | None:
    """The language of ``text``, or None when it is not clear enough to switch.

    Returns ``current`` when the text fits the current language.
    """
    if not text or not text.strip():
        return None
    raw = text.strip()
    for lang, chars in _CHARS.items():
        if sum(1 for ch in raw if ch in chars) >= 2:
            return lang
    plain = _plain(raw)
    tokens = [t for t in re.findall(r"[a-zỊịỤụṄṅẸẹṢṣƙɗɓ']+", plain) if t not in _SHARED and not t.isdigit()]
    if len(tokens) < 3:
        return None
    scores = {lang: sum(1 for t in tokens if t in words) for lang, words in _WORDS.items()}
    scores["en"] = sum(1 for t in tokens if t in _EN)
    best = max(scores, key=lambda k: scores[k])
    ranked = sorted(scores.values(), reverse=True)
    # Clearly ahead: at least 3 marker words, 40% of the words, and 2 more than the runner-up.
    if scores[best] >= 3 and scores[best] >= 0.4 * len(tokens) and ranked[0] - ranked[1] >= 2:
        return best
    return None
