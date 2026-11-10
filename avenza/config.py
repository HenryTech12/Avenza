from __future__ import annotations

import os
from dataclasses import dataclass, field, replace
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")


def _bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return float(raw)
    except ValueError:
        return default


@dataclass(frozen=True)
class Settings:
    app_name: str = "Avenza"
    version: str = "0.2.0"
    env: str = "development"
    log_level: str = "INFO"

    database_url: str = "sqlite:///./avenza.db"
    bank_mode: str = "mock"

    # Forge 2026 platform (Xtradot Bank sandbox + Huawei MaaS). The team key is
    # injected by Kubernetes as GATEWAY_KEY from the huawei-gateway secret.
    gateway_key: str = ""
    sandbox_base_url: str = "http://bank-api.ingress-apisix.svc.cluster.local/v1"
    sandbox_source_account: str = "0123456790"
    sandbox_timeout_s: float = 12.0
    sandbox_settle_wait_s: float = 6.0
    sandbox_test_outcome: str = ""
    forge_webhook_secret: str = ""
    gateway_requests_per_min: int = 55

    stt_provider: str = "mock"
    tts_provider: str = "mock"
    allow_text_utterance: bool = True

    yarn_api_key: str = ""
    yarn_asr_url: str = ""
    yarn_tts_url: str = ""
    yarn_tts_voice: str = ""
    deepgram_api_key: str = ""
    deepgram_model: str = "nova-2"
    sahara_api_key: str = ""
    sahara_asr_url: str = ""

    llm_enabled: bool = False
    llm_provider: str = "openai"  # openai (any compatible API) | huawei-maas
    llm_base_url: str = "https://api.groq.com/openai/v1"
    llm_api_key: str = ""
    llm_model: str = "llama-3.1-8b-instant"
    llm_timeout_s: float = 1.5

    @property
    def llm_headers(self) -> dict:
        """Auth headers for the LLM. Huawei MaaS takes the team key as ``apikey``."""
        if self.llm_provider == "huawei-maas":
            return {"apikey": self.gateway_key}
        return {"Authorization": f"Bearer {self.llm_api_key}"} if self.llm_api_key else {}

    @property
    def llm_extra_body(self) -> dict:
        """GLM models reason by default and max_tokens does not cap it: turn it off."""
        if self.llm_provider == "huawei-maas":
            return {"chat_template_kwargs": {"thinking": False}}
        return {}

    @property
    def llm_configured(self) -> bool:
        if not self.llm_enabled:
            return False
        if self.llm_provider == "huawei-maas":
            return bool(self.gateway_key and self.llm_base_url and self.llm_model)
        return bool(self.llm_api_key)

    @property
    def sandbox_api_key(self) -> str:
        return self.gateway_key

    # AI/ML layer (vendored avenza_ai package). The backend parser remains the
    # amount authority; the AI layer is advisory and can never approve a transfer.
    ai_enabled: bool = True
    ai_intent_enabled: bool = True
    ai_amount_crosscheck: bool = True
    ai_readback: bool = False
    ai_history: bool = True
    ai_languages: str = "en"
    ai_default_language: str = "en"
    ai_provider_choice: str = "reports/provider_choice.json"
    # Per-language speech-to-text provider, e.g. "en=sahara,pcm=sahara". Overrides
    # the language-test file. Only the languages listed are offered.
    ai_stt_choice: str = ""
    ai_stt_timeout_s: float = 8.0
    stt_streaming: bool = True

    # Background reconciliation of unknown bank outcomes and expired drafts.
    reconcile_interval_s: float = 5.0
    reconcile_stale_s: int = 20
    reconcile_resubmit_s: int = 60

    # Per-stage latency log (JSON lines) for the measured-results report.
    latency_log: str = "reports/latency.jsonl"
    tts_timeout_s: float = 6.0
    tts_cache_size: int = 256
    # Answer in the language the customer speaks (beta). Languages Avenza may switch to;
    # BETA_LANGUAGES are marked beta in the app and announced as such.
    language_detection: bool = True
    switch_languages: str = "en,ha,ig,yo"
    beta_languages: str = "ha,ig,yo"
    # Synthesise every fixed prompt once at startup so only read-backs wait for TTS.
    tts_prewarm: bool = True
    tts_prewarm_languages: str = "en"
    tts_prewarm_concurrency: int = 2
    tts_prewarm_timeout_s: float = 30.0

    # YarnGPT names used by the AI package. YARN_* remains supported.
    yarngpt_api_key: str = ""
    yarngpt_asr_url: str = ""
    yarngpt_tts_url: str = ""
    yarngpt_default_voice: str = ""
    # Self-hosted open-source YarnGPT on Modal (TTS_PROVIDER=yarngpt-modal). Unauthenticated URL: keep it in .env.
    yarngpt_modal_url: str = ""
    yarngpt_modal_speakers: str = ""
    yarngpt_modal_keepwarm_s: int = 0

    webauthn_rp_id: str = "localhost"
    webauthn_rp_name: str = "Avenza"
    webauthn_origin: str = "http://localhost:8000"

    max_amount_kobo: int = 100_000_000  # NGN 1,000,000
    large_amount_threshold_kobo: int = 5_000_000  # NGN 50,000
    new_recipient_hold_s: int = 10
    duplicate_window_hours: int = 24
    draft_ttl_s: int = 120
    readback_ttl_s: int = 90
    approval_ttl_s: int = 60
    session_ttl_s: int = 1800

    dev_tools: bool = True
    allow_dev_approval: bool = False
    admin_token: str = ""

    web_dir: Path = field(default_factory=lambda: PROJECT_ROOT / "web")
    # The frontend team's built app (frontend/dist). When it exists it is served
    # at "/" on the same origin as the API; otherwise the legacy web/ PWA is.
    frontend_dist: Path = field(default_factory=lambda: PROJECT_ROOT / "frontend" / "dist")
    prompt_dir: Path = field(default_factory=lambda: PROJECT_ROOT / "web" / "prompts")

    @property
    def bank_is_simulated(self) -> bool:
        return self.bank_mode == "mock"

    @property
    def is_production(self) -> bool:
        return self.env.lower() in {"production", "prod"}

    def for_test(self, **changes) -> "Settings":
        """Return a modified copy, with test-safe defaults."""
        base = {
            "env": "test",
            "database_url": "sqlite:///:memory:",
            "bank_mode": "mock",
            "stt_provider": "mock",
            "tts_provider": "mock",
            "llm_enabled": False,
            "dev_tools": True,
            "allow_dev_approval": True,
            "new_recipient_hold_s": 0,
            "reconcile_interval_s": 0.0,
            "latency_log": "",
        }
        base.update(changes)
        return replace(self, **base)


HUAWEI_MAAS_URL = "http://huawei-maas.ingress-apisix.svc.cluster.local/openai/v1"
_LLM_DEFAULTS = {
    "openai": {"base_url": "https://api.groq.com/openai/v1", "model": "llama-3.1-8b-instant", "timeout": "1.5"},
    # Non-thinking GLM; several seconds is possible on the shared gateway.
    "huawei-maas": {"base_url": HUAWEI_MAAS_URL, "model": "glm-5.2", "timeout": "4.0"},
}


def _llm_provider() -> str:
    value = os.getenv("LLM_PROVIDER", "openai").strip().lower().replace("_", "-")
    return "huawei-maas" if value in {"huawei", "huawei-maas", "maas"} else "openai"


def _llm_default(field: str) -> str:
    return _LLM_DEFAULTS[_llm_provider()][field]


def _bank_mode() -> str:
    value = os.getenv("BANK_MODE", "mock").strip().lower()
    # "xtradot" and "forge" are names for the organisers' sandbox.
    return "sandbox" if value in {"sandbox", "xtradot", "forge"} else value


def load_settings() -> Settings:
    return Settings(
        app_name=os.getenv("APP_NAME", "Avenza"),
        env=os.getenv("APP_ENV", "development"),
        log_level=os.getenv("LOG_LEVEL", "INFO").upper(),
        database_url=os.getenv("DATABASE_URL", "sqlite:///./avenza.db"),
        bank_mode=_bank_mode(),
        gateway_key=os.getenv("GATEWAY_KEY", "") or os.getenv("SANDBOX_API_KEY", ""),
        sandbox_base_url=os.getenv(
            "SANDBOX_BASE_URL", "http://bank-api.ingress-apisix.svc.cluster.local/v1"
        ).rstrip("/"),
        sandbox_source_account=os.getenv("SANDBOX_SOURCE_ACCOUNT", "0123456790"),
        sandbox_timeout_s=_float("SANDBOX_TIMEOUT_S", 12.0),
        sandbox_settle_wait_s=_float("SANDBOX_SETTLE_WAIT_S", 6.0),
        sandbox_test_outcome=os.getenv("SANDBOX_TEST_OUTCOME", "").strip().lower(),
        forge_webhook_secret=os.getenv("FORGE_WEBHOOK_SECRET", ""),
        gateway_requests_per_min=_int("GATEWAY_REQUESTS_PER_MIN", 55),
        stt_provider=os.getenv("STT_PROVIDER", "mock").strip().lower(),
        tts_provider=os.getenv("TTS_PROVIDER", "mock").strip().lower(),
        allow_text_utterance=_bool("ALLOW_TEXT_UTTERANCE", True),
        yarn_api_key=os.getenv("YARN_API_KEY", ""),
        yarn_asr_url=os.getenv("YARN_ASR_URL", ""),
        yarn_tts_url=os.getenv("YARN_TTS_URL", ""),
        yarn_tts_voice=os.getenv("YARN_TTS_VOICE", ""),
        deepgram_api_key=os.getenv("DEEPGRAM_API_KEY", ""),
        deepgram_model=os.getenv("DEEPGRAM_MODEL", "nova-2"),
        sahara_api_key=os.getenv("SAHARA_API_KEY", ""),
        sahara_asr_url=os.getenv("SAHARA_ASR_URL", ""),
        llm_enabled=_bool("LLM_ENABLED", False),
        llm_provider=_llm_provider(),
        llm_base_url=os.getenv("LLM_BASE_URL", _llm_default("base_url")).rstrip("/"),
        llm_api_key=os.getenv("LLM_API_KEY", ""),
        llm_model=os.getenv("LLM_MODEL", _llm_default("model")),
        llm_timeout_s=_float("LLM_TIMEOUT_S", float(_llm_default("timeout"))),
        ai_enabled=_bool("AI_ENABLED", True),
        ai_intent_enabled=_bool("AI_INTENT_ENABLED", True),
        ai_amount_crosscheck=_bool("AI_AMOUNT_CROSSCHECK", True),
        ai_readback=_bool("AI_READBACK", False),
        ai_history=_bool("AI_HISTORY", True),
        ai_languages=os.getenv("AI_LANGUAGES", "en"),
        ai_default_language=os.getenv("AI_DEFAULT_LANGUAGE", "en"),
        ai_provider_choice=os.getenv("AI_PROVIDER_CHOICE", "reports/provider_choice.json"),
        ai_stt_choice=os.getenv("AI_STT_CHOICE", "").strip(),
        ai_stt_timeout_s=_float("AI_STT_TIMEOUT_S", 8.0),
        stt_streaming=_bool("STT_STREAMING", True),
        reconcile_interval_s=_float("RECONCILE_INTERVAL_S", 5.0),
        reconcile_stale_s=_int("RECONCILE_STALE_S", 20),
        reconcile_resubmit_s=_int("RECONCILE_RESUBMIT_S", 60),
        latency_log=os.getenv("LATENCY_LOG", "reports/latency.jsonl"),
        tts_timeout_s=_float("TTS_TIMEOUT_S", 6.0),
        tts_cache_size=_int("TTS_CACHE_SIZE", 256),
        language_detection=_bool("LANGUAGE_DETECTION", True),
        switch_languages=os.getenv("SWITCH_LANGUAGES", "en,ha,ig,yo"),
        beta_languages=os.getenv("BETA_LANGUAGES", "ha,ig,yo"),
        tts_prewarm=_bool("TTS_PREWARM", True),
        tts_prewarm_languages=os.getenv("TTS_PREWARM_LANGUAGES", "en"),
        tts_prewarm_concurrency=_int("TTS_PREWARM_CONCURRENCY", 2),
        tts_prewarm_timeout_s=_float("TTS_PREWARM_TIMEOUT_S", 30.0),
        yarngpt_api_key=os.getenv("YARNGPT_API_KEY", os.getenv("YARN_API_KEY", "")),
        yarngpt_asr_url=os.getenv("YARNGPT_ASR_WS_URL", os.getenv("YARN_ASR_URL", "")),
        yarngpt_tts_url=os.getenv("YARNGPT_TTS_URL", os.getenv("YARN_TTS_URL", "")),
        yarngpt_default_voice=os.getenv("YARNGPT_DEFAULT_VOICE", os.getenv("YARN_TTS_VOICE", "")),
        yarngpt_modal_url=os.getenv("YARNGPT_MODAL_URL", ""),
        yarngpt_modal_speakers=os.getenv("YARNGPT_MODAL_SPEAKERS", ""),
        yarngpt_modal_keepwarm_s=_int("YARNGPT_MODAL_KEEPWARM_S", 0),
        webauthn_rp_id=os.getenv("WEBAUTHN_RP_ID", "localhost"),
        webauthn_rp_name=os.getenv("WEBAUTHN_RP_NAME", "Avenza"),
        webauthn_origin=os.getenv("WEBAUTHN_ORIGIN", "http://localhost:8000"),
        max_amount_kobo=_int("MAX_AMOUNT_KOBO", 100_000_000),
        large_amount_threshold_kobo=_int("LARGE_AMOUNT_THRESHOLD_KOBO", 5_000_000),
        new_recipient_hold_s=_int("NEW_RECIPIENT_HOLD_S", 10),
        duplicate_window_hours=_int("DUPLICATE_WINDOW_HOURS", 24),
        draft_ttl_s=_int("DRAFT_TTL_S", 120),
        readback_ttl_s=_int("READBACK_TTL_S", 90),
        approval_ttl_s=_int("APPROVAL_TTL_S", 60),
        session_ttl_s=_int("SESSION_TTL_S", 1800),
        dev_tools=_bool("DEV_TOOLS", True),
        allow_dev_approval=_bool("ALLOW_DEV_APPROVAL", False),
        admin_token=os.getenv("ADMIN_TOKEN", ""),
        web_dir=PROJECT_ROOT / os.getenv("WEB_DIR", "web"),
        frontend_dist=PROJECT_ROOT / os.getenv("FRONTEND_DIST", "frontend/dist"),
        prompt_dir=PROJECT_ROOT / os.getenv("WEB_DIR", "web") / "prompts",
    )
