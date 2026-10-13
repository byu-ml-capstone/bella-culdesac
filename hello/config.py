from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    app_env: str = os.getenv("APP_ENV", "local")
    app_version: str = os.getenv("APP_VERSION", "0.2.0")
    app_timezone: str = os.getenv("APP_TIMEZONE", "America/Denver")
    app_url: str = os.getenv("APP_URL", "http://localhost:8000")
    ai_provider: str = os.getenv("AI_PROVIDER", "litellm")
    litellm_base_url: str = os.getenv("LITELLM_BASE_URL", "http://ml-capstone.cs.byu.edu:4000/v1")
    litellm_api_key: str = os.getenv("LITELLM_API_KEY", "sk-noauth")
    litellm_model: str = os.getenv("LITELLM_MODEL", "classroom-chat")
    ai_timeout_seconds: float = float(os.getenv("AI_TIMEOUT_SECONDS", "30"))
    database_url: str = os.getenv(
        "DATABASE_URL", "postgresql://appuser:apppass@db:5432/appdb"
    )
    attachments_dir: Path = Path(
        os.getenv("ATTACHMENTS_DIR", "/app/storage/attachments")
    )
    allow_admin_reset: bool = os.getenv("ALLOW_ADMIN_RESET", "false").lower() in {
        "1",
        "true",
        "yes",
    }
    session_secret: str = os.getenv("SESSION_SECRET", "local-session-secret-change-me")


settings = Settings()
