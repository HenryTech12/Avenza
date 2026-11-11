from __future__ import annotations

from datetime import timedelta

import pytest

from avenza.money import amount_to_words, format_naira, kobo_to_naira, naira_to_kobo
from avenza.parser import (
    AmbiguousAccount,
    AmbiguousAmount,
    AmountTooLarge,
    InvalidAmount,
    MissingAmount,
    UnsupportedCurrency,
    detect_bank,
    extract_recipient_hint,
    extract_transfer_fields,
    normalize,
    parse_account_number,
    parse_amount,
    parse_history_query,
)


def kobo(naira: float) -> int:
    return int(round(naira * 100))


# ---------------------------------------------------------------------------
# Digits
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text,expected",
    [
        ("send 5000 naira", kobo(5000)),
        ("send 5,000 naira", kobo(5000)),
        ("send 5000", kobo(5000)),
        ("send 20k", kobo(20000)),
        ("send 2.5k", kobo(2500)),
        ("send 1,250.50 naira", kobo(1250.50)),
        ("transfer 100000 naira", kobo(100000)),
        ("pay 250 naira", kobo(250)),
    ],
)
def test_digit_amounts(text, expected):
    assert parse_amount(text, max_kobo=10**12).kobo == expected


def test_digit_amount_with_kobo_remainder():
    parsed = parse_amount("send 1,250 naira and 50 kobo")
    assert parsed.kobo == kobo(1250.50)


def test_digit_amount_with_only_kobo():
    # 500 kobo is five naira; the parser must not reject a whole kobo amount.
    assert parse_amount("send 500 kobo").kobo == 500


# ---------------------------------------------------------------------------
# Spoken English
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text,expected",
    [
        ("send five thousand naira", kobo(5000)),
        ("send one thousand two hundred naira", kobo(1200)),
        ("send twenty five thousand naira", kobo(25000)),
        ("send one hundred and fifty naira", kobo(150)),
        ("send two million naira", kobo(2_000_000)),
        ("send a thousand naira", kobo(1000)),
    ],
)
def test_spoken_amounts(text, expected):
    assert parse_amount(text, max_kobo=10**12).kobo == expected


def test_fifteen_and_fifty_are_distinct():
    fifteen = parse_amount("send fifteen thousand naira")
    fifty = parse_amount("send fifty thousand naira")
    assert fifteen.kobo == kobo(15000)
    assert fifty.kobo == kobo(50000)
    assert fifteen.kobo != fifty.kobo


def test_fifteen_and_fifty_without_scale_word():
    assert parse_amount("send fifteen naira").kobo == kobo(15)
    assert parse_amount("send fifty naira").kobo == kobo(50)


def test_spoken_number_requires_currency_or_scale():
    # A bare number word is not enough to draft a payment.
    with pytest.raises(MissingAmount):
        parse_amount("send five")


def test_separate_digits_are_rejected_as_ambiguous():
    # "one five" could be a misheard 15; refuse rather than guess.
    with pytest.raises(AmbiguousAmount):
        parse_amount("send one five naira")


# ---------------------------------------------------------------------------
# Mixed language
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text,expected",
    [
        ("send dubu biyar naira", kobo(5000)),  # Hausa: thousand five
        ("send dubu goma naira", kobo(10000)),
        ("send puku ise naira", kobo(5000)),  # Igbo: thousand five
        ("send egberun marun naira", kobo(5000)),  # Yoruba: thousand five
    ],
)
def test_mixed_language_amounts(text, expected):
    assert parse_amount(text, max_kobo=10**12).kobo == expected


def test_pidgin_digits():
    assert parse_amount("send wan thousand naira").kobo == kobo(1000)


# ---------------------------------------------------------------------------
# Rejections
# ---------------------------------------------------------------------------


def test_missing_amount():
    with pytest.raises(MissingAmount):
        parse_amount("send money to my friend")


def test_unsupported_currency():
    with pytest.raises(UnsupportedCurrency):
        parse_amount("send 5000 dollars")


def test_amount_above_limit():
    with pytest.raises(AmountTooLarge):
        parse_amount("send two million naira", max_kobo=kobo(1_000_000))


def test_zero_amount_rejected():
    with pytest.raises((InvalidAmount, MissingAmount)):
        parse_amount("send zero naira")


def test_two_different_amounts_rejected():
    with pytest.raises(AmbiguousAmount):
        parse_amount("send 5000 naira and 7000 naira")


# ---------------------------------------------------------------------------
# Accounts and banks
# ---------------------------------------------------------------------------


def test_account_number_is_not_an_amount():
    fields = extract_transfer_fields("send 5000 naira to GTBank account 0123456789")
    assert fields.amount is not None and fields.amount.kobo == kobo(5000)
    assert fields.account is not None and fields.account.value == "0123456789"


def test_spoken_account_number():
    account = parse_account_number(
        "send to account zero one two three four five six seven eight nine"
    )
    assert account is not None
    assert account.value == "0123456789"


def test_two_account_numbers_rejected():
    with pytest.raises(AmbiguousAccount):
        parse_account_number("0123456789 or 0987654321")


@pytest.mark.parametrize(
    "text,code",
    [
        ("GTBank", "058"),
        ("gtb", "058"),
        ("Access Bank", "044"),
        ("Zenith", "057"),
        ("First Bank", "011"),
        ("Kuda", "50211"),
        ("OPay", "999992"),
        ("Moniepoint", "50515"),
    ],
)
def test_detect_bank(text, code):
    bank = detect_bank(text)
    assert bank is not None
    assert bank.code == code


def test_detect_bank_unknown():
    assert detect_bank("send to my cousin") is None


def test_recipient_hint():
    hint = extract_recipient_hint("send five thousand naira to Aisha in GTBank 0123456789")
    assert hint is not None
    assert "aisha" in hint
    assert "0123456789" not in hint


def test_full_field_extraction():
    fields = extract_transfer_fields("Send fifty thousand naira to Access Bank account 1111222333")
    assert fields.missing == []
    assert fields.amount is not None and fields.amount.kobo == kobo(50000)
    assert fields.account is not None and fields.account.value == "1111222333"
    assert fields.bank is not None and fields.bank.code == "044"


# ---------------------------------------------------------------------------
# Normalisation and history
# ---------------------------------------------------------------------------


def test_normalize_handles_naira_sign_and_accents():
    assert "naira" in normalize("send ₦5000")
    assert normalize("Ọ̀rẹ́") == "ore"


def test_history_today():
    from avenza.timeutil import utcnow

    now = utcnow()
    query = parse_history_query("show me my transactions today", now=now)
    assert query.label == "today"
    # "Today" starts at Lagos midnight, which is 23:00 UTC the day before.
    lagos_now = now + timedelta(hours=1)
    assert (query.start + timedelta(hours=1)).date() == lagos_now.date()
    assert (query.start + timedelta(hours=1)).hour == 0


def test_history_uses_lagos_midnight():
    from datetime import datetime

    # 23:30 UTC on 8 Nov is 00:30 on 9 Nov in Lagos.
    now = datetime(2026, 11, 8, 23, 30)
    today = parse_history_query("history today", now=now)
    assert today.start == datetime(2026, 11, 8, 23, 0)
    yesterday = parse_history_query("history yesterday", now=now)
    assert yesterday.start == datetime(2026, 11, 7, 23, 0)
    assert yesterday.end == datetime(2026, 11, 8, 23, 0)


def test_history_last_n():
    from avenza.timeutil import utcnow

    query = parse_history_query("show my last three transactions", now=utcnow())
    assert query.limit == 3


# ---------------------------------------------------------------------------
# Money formatting
# ---------------------------------------------------------------------------


def test_money_round_trip():
    assert naira_to_kobo(12.34) == 1234
    assert kobo_to_naira(1234) == 12.34
    assert format_naira(1234) == "₦12.34"
    assert format_naira(500000) == "₦5,000.00"


def test_amount_to_words():
    assert amount_to_words(500000) == "five thousand naira"
    assert amount_to_words(150000) == "one thousand five hundred naira"
    assert amount_to_words(50) == "fifty kobo"
    assert amount_to_words(1234) == "twelve naira and thirty-four kobo"


@pytest.mark.parametrize(
    "spoken",
    [
        "zero one two three nine eight seven zero zero one.",
        "Zero, one, two, three, nine, eight, seven, zero, zero, one.",
        "0 1 2 3 9 8 7 0 0 1",
        "0123 987 001",
        "oh one two three nine eight seven oh oh one",
    ],
)
def test_account_number_spoken_with_punctuation_or_grouped_digits(spoken):
    account = parse_account_number(spoken)
    assert account is not None and account.value == "0123987001"
    # the digits are an account, never an amount
    assert extract_transfer_fields(spoken).amount is None
    assert extract_transfer_fields(spoken).amount_error == "missing_amount"


def test_a_spaced_out_amount_is_not_an_account_number():
    assert parse_account_number("send 5 000 000 000 naira") is None


@pytest.mark.parametrize(
    "heard",
    [
        "di amount is 5000 naira to gtbank 012398701",  # nine of ten digits heard
        "di amount is 5000 naira to gtbank 012398701 \u130b\u12da\u12eb",  # plus stray characters
        "send 5000 naira to gtbank 01239870",
        "send 5000 naira to gtbank 123987001",  # the leading zero dropped
    ],
)
def test_a_partial_account_number_is_not_a_second_amount(heard):
    fields = extract_transfer_fields(heard)
    assert fields.amount is not None and fields.amount.kobo == 500_000
    assert fields.amount_error is None
    assert fields.account is None
    assert fields.bank is not None
