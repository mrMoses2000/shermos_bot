"""
Settings loaded from .env via pydantic-settings.
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    telegram_bot_token: str
    telegram_webhook_secret: str

    manager_bot_token: str
    manager_webhook_secret: str
    manager_chat_ids: str = ""

    webhook_host: str = "0.0.0.0"
    webhook_port: int = 88
    webhook_public_url: str = "https://3.79.24.73:88"
    webhook_path_client: str = "/webhook/client"
    webhook_path_manager: str = "/webhook/manager"
    ssl_cert_path: str = "certs/webhook.pem"
    ssl_key_path: str = "certs/webhook.key"

    renders_dir: str = "data/renders"

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

    gcal_calendar_id: str = "primary"
    gcal_credentials_path: str = "credentials.json"
    timezone: str = "Asia/Bishkek"

    bot_language: str = "ru"
    send_typing_indicator: bool = True
    max_context_messages: int = 20
    render_cache_ttl_seconds: int = 3600

    mini_app_url: str = ""

    log_level: str = "INFO"
    log_format: str = "json"

    @property
    def webhook_url_client(self) -> str:
        return f"{self.webhook_public_url}{self.webhook_path_client}"

    @property
    def webhook_url_manager(self) -> str:
        return f"{self.webhook_public_url}{self.webhook_path_manager}"

    @property
    def manager_chat_ids_list(self) -> list[int]:
        if not self.manager_chat_ids:
            return []
        return [int(x.strip()) for x in self.manager_chat_ids.split(",") if x.strip()]

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
    )


settings = Settings()
