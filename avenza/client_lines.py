"""Lines the app speaks itself (onboarding and short fillers), in every language. 10 Nov 2026.

The phone's own speech engine usually has no Yoruba, Hausa or Igbo voice, and before
enrolment there is no voice session, so the app asks the server for these lines:
GET /voice/{lang}/{line_id} returns the text and YarnGPT audio (cached on disk).
Only these fixed ids exist, so the endpoint cannot be used to synthesise arbitrary text.

Hausa, Igbo and Yoruba are unverified translations (beta): have a native speaker check them.
"""
from __future__ import annotations

CLIENT_LINES: dict[str, dict[str, str]] = {
    "en": {
        "ob_greeting": "Hello, and welcome to Avenza, your voice bank. I'll get you set up in under a minute.",
        "ob_ask_name": "First, what's your name?",
        "ob_ask_name_again": "Sorry, I didn't catch that. What's your name?",
        "ob_ask_language": "Welcome to Avenza. Which language would you like to use? Say English, Hausa, Igbo or Yoruba.",
        "ob_ask_language_again": "Please say English, Hausa, Igbo or Yoruba.",
        "ob_language_set": "Great. I will speak English with you from now on.",
        "ob_consent": "One quick thing. I listen while Avenza is open, and my speech partners process your voice only to understand you. Your voice never moves money: only your fingerprint does. Do you agree?",
        "ob_consent_again": "If you agree, please say: I agree.",
        "ob_finger": "Last step. Touch the screen anywhere, then place your finger on the sensor.",
        "ob_finger_again": "Touch the screen anywhere, then place your finger on the sensor to register it.",
        "ob_mic_denied": "I need the microphone to hear you. Please allow it, then say I agree again.",
        "ob_save_failed": "I couldn't save that. Let's try once more.",
        "ob_done": "You're all set. Welcome to Avenza.",
        "checking_bank": "One moment, I am checking with your bank.",
        "no_speech_hint": "I'm still here. Tell me who to send money to.",
    },
    "yo": {
        "ob_greeting": "Ẹ kú àbọ̀ sí Avenza, báǹkì tí ẹ ń lò pẹ̀lú ohùn yín. Màá ṣètò yín kí ìṣẹ́jú kan tó kọjá.",
        "ob_ask_name": "Lákọ̀ọ́kọ́, kí ni orúkọ yín?",
        "ob_ask_name_again": "Ẹ má bínú, n kò gbọ́ dáadáa. Kí ni orúkọ yín?",
        "ob_language_set": "Ó dára. Màá máa bá yín sọ Yorùbá láti ìsinsìnyí lọ.",
        "ob_consent": "Ohun kan ṣoṣo. Mo máa ń gbọ́ ohùn yín nígbà tí Avenza bá ṣí sílẹ̀, kí n lè lóye yín. Ohùn yín kò lè gbé owó: ìka yín nìkan ló lè ṣe é. Ṣé ẹ gbà?",
        "ob_consent_again": "Tí ẹ bá gbà, ẹ sọ pé: mo gbà.",
        "ob_finger": "Ìgbésẹ̀ tó kẹ́yìn. Ẹ fọwọ́ kan ojú fóònù níbikíbi, lẹ́yìn náà ẹ fi ìka yín lé orí sensọ̀.",
        "ob_finger_again": "Ẹ fọwọ́ kan ojú fóònù níbikíbi, lẹ́yìn náà ẹ fi ìka yín lé orí sensọ̀ láti forúkọ rẹ̀ sílẹ̀.",
        "ob_mic_denied": "Mo nílò máíkírófóònù kí n lè gbọ́ yín. Ẹ gbà á láyè, lẹ́yìn náà ẹ tún sọ pé mo gbà.",
        "ob_save_failed": "N kò lè fi pamọ́. Ẹ jẹ́ ká tún gbìyànjú lẹ́ẹ̀kan sí i.",
        "ob_done": "Gbogbo rẹ̀ ti ṣetán. Ẹ kú àbọ̀ sí Avenza.",
        "checking_bank": "Ẹ dúró díẹ̀, mo ń bá báǹkì yín sọ̀rọ̀.",
        "no_speech_hint": "Mo ṣì wà níbí. Ẹ sọ fún mi ẹni tí ẹ fẹ́ fi owó ránṣẹ́ sí.",
    },
    "ha": {
        "ob_greeting": "Sannu da zuwa Avenza, bankinka na murya. Zan saita maka komai cikin minti ɗaya.",
        "ob_ask_name": "Da farko, menene sunanka?",
        "ob_ask_name_again": "Yi haƙuri, ban ji sosai ba. Menene sunanka?",
        "ob_language_set": "Madalla. Daga yanzu zan yi magana da kai da Hausa.",
        "ob_consent": "Abu ɗaya kawai. Ina sauraron muryarka idan Avenza a buɗe take, don in fahimce ka. Muryarka ba za ta iya tura kuɗi ba: sai yatsanka kawai. Ka yarda?",
        "ob_consent_again": "Idan ka yarda, ka ce: na yarda.",
        "ob_finger": "Mataki na ƙarshe. Taɓa allon wayar a ko'ina, sannan ka sa yatsanka a kan na'urar tantancewa.",
        "ob_finger_again": "Taɓa allon wayar a ko'ina, sannan ka sa yatsanka a kan na'urar tantancewa don yin rajista.",
        "ob_mic_denied": "Ina buƙatar makirufo don in ji ka. Ka ba da izini, sannan ka sake cewa na yarda.",
        "ob_save_failed": "Ban iya ajiye wannan ba. Mu sake gwadawa sau ɗaya.",
        "ob_done": "An gama komai. Barka da zuwa Avenza.",
        "checking_bank": "Ɗan jira kaɗan, ina dubawa da bankinka.",
        "no_speech_hint": "Ina nan har yanzu. Faɗa mini wanda kake so ka tura wa kuɗi.",
    },
    "ig": {
        "ob_greeting": "Nnọọ na Avenza, ụlọ akụ gị nke olu. M ga-edozi gị n'ime otu nkeji.",
        "ob_ask_name": "Nke mbụ, gịnị bụ aha gị?",
        "ob_ask_name_again": "Ndo, anụghị m nke ọma. Gịnị bụ aha gị?",
        "ob_language_set": "Ọ dị mma. Site ugbu a, m ga-asụ Igbo gị.",
        "ob_consent": "Otu ihe dị mkpa. Ana m ege olu gị mgbe Avenza mepere emepe, ka m ghọta gị. Olu gị apụghị ibuga ego: ọ bụ naanị mkpịsị aka gị nwere ike. Ị kwenyere?",
        "ob_consent_again": "Ọ bụrụ na ị kwenyere, kwuo: ekwere m.",
        "ob_finger": "Nzọụkwụ ikpeazụ. Metụ ihuenyo ekwentị ebe ọ bụla, wee tinye mkpịsị aka gị n'elu ihe nyocha.",
        "ob_finger_again": "Metụ ihuenyo ekwentị ebe ọ bụla, wee tinye mkpịsị aka gị n'elu ihe nyocha iji debanye ya aha.",
        "ob_mic_denied": "Achọrọ m igwe okwu ka m nụ gị. Kwe ka o rụọ ọrụ, wee kwuo ekwere m ọzọ.",
        "ob_save_failed": "Enweghị m ike ichekwa nke a. Ka anyị nwalee ọzọ.",
        "ob_done": "Ihe niile adịla njikere. Nnọọ na Avenza.",
        "checking_bank": "Chere ntakịrị, ana m enyocha n'ụlọ akụ gị.",
        "no_speech_hint": "Anọ m ebe a. Gwa m onye ị chọrọ iziga ego.",
    },
}


def client_line(language: str, line_id: str) -> tuple[str, str] | None:
    """(language actually used, text). Falls back to English; None for an unknown id."""
    if line_id not in CLIENT_LINES["en"]:
        return None
    lang = language if language in CLIENT_LINES and line_id in CLIENT_LINES[language] else "en"
    return lang, CLIENT_LINES[lang][line_id]

# The app's other short lines (confirm, retry, errors, warnings), so every reply follows the chosen language.
_MORE: dict[str, dict[str, str]] = {'en': {'say_yes_no_repeat': 'Say yes, no, or repeat.', 'fingerprint_retry': "I couldn't read your fingerprint. Try once more.", 'err_offline': "You're offline. I'll keep trying. Your money has not moved.", 'err_connection_lost': 'I lost the connection. Your money has not moved.', 'err_mic_denied': 'I need the microphone to hear you.', 'err_provider_down': "I can't understand speech right now. Your money has not moved.", 'err_generic': 'Something went wrong. Your money has not moved.', 'scam_pause': 'This is a new recipient and a large amount. Take a moment. Say cancel if this is not right.', 'duplicate_warning': 'You sent this same amount to this person a moment ago. Send again?'}, 'yo': {'say_yes_no_repeat': 'Ẹ sọ bẹ́ẹ̀ni, rárá, tàbí tún sọ.', 'fingerprint_retry': 'N kò lè ka ìka yín. Ẹ tún gbìyànjú lẹ́ẹ̀kan sí i.', 'err_offline': 'Ẹ kò sí lórí íńtánẹ́ẹ̀tì. Màá máa gbìyànjú. Owó yín kò tíì lọ.', 'err_connection_lost': 'Ìsopọ̀ ti já. Owó yín kò tíì lọ.', 'err_mic_denied': 'Mo nílò máíkírófóònù kí n lè gbọ́ yín.', 'err_provider_down': 'N kò lè gbọ́ ohùn yín báyìí. Owó yín kò tíì lọ.', 'err_generic': 'Nǹkan kan ṣẹlẹ̀. Owó yín kò tíì lọ.', 'scam_pause': 'Ẹni tuntun ni èyí, owó náà sì pọ̀. Ẹ dúró díẹ̀. Ẹ sọ pé fagilé tí kò bá tọ́.', 'duplicate_warning': 'Ẹ ṣẹ̀ṣẹ̀ fi iye owó yìí ránṣẹ́ sí ẹni yìí. Ṣé kí n tún fi ránṣẹ́?'}, 'ha': {'say_yes_no_repeat': "Ka ce eh, a'a, ko ka maimaita.", 'fingerprint_retry': 'Ban iya karanta yatsanka ba. Ka sake gwadawa sau ɗaya.', 'err_offline': 'Ba ka kan intanet. Zan ci gaba da gwadawa. Kuɗinka bai motsa ba.', 'err_connection_lost': 'Haɗin ya yanke. Kuɗinka bai motsa ba.', 'err_mic_denied': 'Ina buƙatar makirufo don in ji ka.', 'err_provider_down': 'Ba zan iya fahimtar magana yanzu ba. Kuɗinka bai motsa ba.', 'err_generic': 'Wani abu ya faru. Kuɗinka bai motsa ba.', 'scam_pause': 'Wannan sabon mai karɓa ne kuma kuɗi masu yawa. Ka ɗan dakata. Ka ce soke idan ba daidai ba ne.', 'duplicate_warning': 'Ka aika wa wannan mutumin wannan adadin yanzu yanzu. Ka sake aikawa?'}, 'ig': {'say_yes_no_repeat': 'Kwuo ee, mba, ma ọ bụ kwughachi ya.', 'fingerprint_retry': 'Enweghị m ike ịgụ mkpịsị aka gị. Nwalee ọzọ.', 'err_offline': "Ị nọghị n'ịntanetị. M ga-anwa ọzọ. Ego gị esighị ebe ọ nọ pụọ.", 'err_connection_lost': 'Njikọ ahụ bepụrụ. Ego gị esighị ebe ọ nọ pụọ.', 'err_mic_denied': 'Achọrọ m igwe okwu ka m nụ gị.', 'err_provider_down': 'Enweghị m ike ịghọta okwu ugbu a. Ego gị esighị ebe ọ nọ pụọ.', 'err_generic': 'Ihe na-adịghị mma mere. Ego gị esighị ebe ọ nọ pụọ.', 'scam_pause': 'Onye a bụ onye ọhụrụ, ego ahụ dịkwa ukwuu. Chere ntakịrị. Kwuo kagbuo ma ọ bụrụ na ọ dịghị mma.', 'duplicate_warning': 'Ị ziri onye a otu ego a obere oge gara aga. Zigakwa ọzọ?'}}
for _lang, _lines in _MORE.items():
    CLIENT_LINES[_lang].update(_lines)
