from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: str = "dev"  # dev | prod
    cors_origins: str = "http://localhost:3000"

    # Supabase (service-role key: server-side only, never ship to the browser)
    supabase_url: str = ""
    supabase_service_key: str = ""
    auth_required: bool = False  # must be True in prod
    sensor_ingest_token: str = ""  # required for ESP32/device ingestion; keep secret
    supabase_anon_key: str = ""   # public anon key: used ONLY for sign-up / sign-in calls to Supabase Auth
    signup_enabled: bool = True

    # LLM (Grok via xAI's OpenAI-compatible API) - optional, template fallback exists
    xai_api_key: str = ""
    xai_base_url: str = "https://api.x.ai/v1"
    grok_model: str = "grok-4"
    llm_timeout_s: float = 20.0

    # Follow-up loop
    max_followup_rounds: int = 2
    max_questions_per_round: int = 3

    # Decision layer
    w_base: float = 0.6
    w_worst: float = 0.4
    go_margin: float = 0.15          # base-case profit / cost needed for "go"
    max_loss_share: float = 0.20     # worst-case loss allowed (share of cost) for "go"
    min_confidence_for_go: float = 0.6
    review_confidence_threshold: float = 0.5

    # SMS fallback for Section 2 alerts: "none" = simulated (logged as events only), "webhook" = POST {"to","text"} to your gateway
    sms_provider: str = "none"
    sms_webhook_url: str = ""
    sms_max_chars: int = 200          # Bangla SMS is Unicode: 67 chars per part when joined, so 200 = 3 parts

    # WhatsApp Cloud API (Meta). Empty = simulated (nothing is sent, replies are only logged)
    whatsapp_access_token: str = ""
    whatsapp_phone_number_id: str = ""
    whatsapp_verify_token: str = ""   # any secret string; you type the same one in Meta's webhook setup
    whatsapp_app_secret: str = ""     # Meta app secret: used to check the X-Hub-Signature-256 of every webhook call
    whatsapp_number: str = ""         # shown to farmers, e.g. 8801XXXXXXXXX (the business number they message)
    whatsapp_alert_template: str = "" # approved template name for alerts sent outside the 24h window (1 body variable)
    whatsapp_template_lang: str = "bn"
    whatsapp_graph_version: str = "v21.0"
    channel_secret: str = ""          # shared secret (header X-Channel-Secret) for the generic inbound-SMS webhook
    channel_msgs_per_hour: int = 30   # per phone number; protects LLM/model cost

    # Disease-photo models (Section 2): below min score the answer is "unknown"; below review score it goes to an expert
    disease_min_score: float = 0.70
    disease_review_score: float = 0.85

    # Section 4 (farmers' trust): show distributions only when at least this many different farmers finished the crop
    trust_min_farmers: int = 1

    # RAG
    embed_model: str = "intfloat/multilingual-e5-small"  # 384-dim


@lru_cache
def get_settings() -> Settings:
    return Settings()
