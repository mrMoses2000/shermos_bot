"""
Settings loaded from .env via pydantic-settings.
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    webhook_host: str = "0.0.0.0"
    webhook_port: int = 88
    webhook_public_url: str = "https://3.79.24.73:88"
    ssl_cert_path: str = "certs/webhook.pem"
    ssl_key_path: str = "certs/webhook.key"

    renders_dir: str = "data/renders"
    gallery_dir: str = "data/gallery"
    gallery_photo_max_bytes: int = 8 * 1024 * 1024  # 8 MB

    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_db: str = "shermos_bot"
    postgres_user: str = "shermos"
    postgres_password: str = "change_me"

    redis_url: str = "redis://localhost:6379/0"

    gemini_model: str = "gemini-3-flash-preview"
    llm_cli_command: str = "gemini"
    llm_cli_flags: str = "-p"
    max_llm_concurrency: int = 2
    llm_timeout_seconds: int = 90

    timezone: str = "Asia/Bishkek"

    bot_language: str = "ru"
    send_typing_indicator: bool = True
    max_context_messages: int = 20
    render_cache_ttl_seconds: int = 3600

    mini_app_url: str = ""
    cms_admin_token: str = ""

    jwt_secret: str = "change_me_in_production"
    jwt_issuer: str = "shermos-api"
    jwt_ttl_days: int = 7
    jwt_refresh_ttl_days: int = 30

    otp_expiry_minutes: int = 10
    otp_max_attempts: int = 5
    otp_rate_limit_1h: int = 10

    cors_allowed_origins: str = ""  # comma-separated; empty = no CORS allowed

    bridge_shared_secret: str = ""
    whatsapp_bridge_url: str = "http://localhost:3001"
    manager_whatsapp_bridge_url: str = ""
    manager_whatsapp_numbers: str = ""

    assemblyai_api_key: str = ""
    transcription_language: str = "ru"
    transcription_timeout_seconds: int = 180

    gemini_health_check_seconds: int = 1800
    memory_summary_max_chars: int = 900

    log_level: str = "INFO"
    log_format: str = "json"

    @property
    def cors_allowed_origins_list(self) -> list[str]:
        if not self.cors_allowed_origins:
            return []
        return [o.strip() for o in self.cors_allowed_origins.split(",") if o.strip()]

    @property
    def manager_whatsapp_numbers_list(self) -> list[str]:
        if not self.manager_whatsapp_numbers:
            return []
        return [
            "".join(ch for ch in x if ch.isdigit())
            for x in self.manager_whatsapp_numbers.split(",")
            if "".join(ch for ch in x if ch.isdigit())
        ]

    @property
    def postgres_dsn(self) -> str:
        return (
            f"postgresql://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )


settings = Settings()
