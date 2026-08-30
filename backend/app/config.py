"""
DisasterMesh backend — application settings.

Loaded from environment variables / .env file via pydantic-settings.
"""

from functools import lru_cache

from dotenv import load_dotenv
from pydantic_settings import BaseSettings, SettingsConfigDict

# Explicitly load .env file into os.environ
load_dotenv()


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── App ───────────────────────────────────────────────────────────────────
    app_env: str = "development"
    log_level: str = "INFO"
    api_key: str = ""  # API key for authentication (set via X-API-Key header)

    # ── Qdrant ────────────────────────────────────────────────────────────────
    qdrant_url: str = ""
    qdrant_api_key: str = ""
    qdrant_local_path: str = "./qdrant_data"

    # ── Redis ─────────────────────────────────────────────────────────────────
    redis_url: str = "redis://localhost:6379"

    # ── Database ──────────────────────────────────────────────────────────────
    database_url: str = "sqlite+aiosqlite:///./dev.db"

    # ── Mapbox ────────────────────────────────────────────────────────────────
    mapbox_token: str = ""

    # ── Vonage SMS (recommended — free tier) ─────────────────────────────────
    vonage_api_key: str = ""
    vonage_api_secret: str = ""
    vonage_from_number: str = "DisasterMesh"

    # ── Twilio (alternative) ──────────────────────────────────────────────────
    twilio_account_sid: str = ""
    twilio_auth_token: str = ""
    twilio_from_number: str = ""

    # ── Groq LLM ──────────────────────────────────────────────────────────────
    groq_api_key: str = ""
    groq_model: str = "llama-3.3-70b-versatile"
    groq_timeout_s: int = 10

    # ── Exa Social Media Monitor ───────────────────────────────────────────────
    exa_api_key: str = ""

    # ── Data paths ────────────────────────────────────────────────────────────
    sentinel_data_dir: str = "./demo_data/satellite"

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"


@lru_cache
def get_settings() -> Settings:
    """Return cached settings singleton."""
    return Settings()
