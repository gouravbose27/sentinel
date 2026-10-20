from functools import lru_cache

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.models.schemas import Category, Severity


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", env_parse_none_str="none")

    openai_api_key: SecretStr = SecretStr("")
    openai_model: str = "gpt-4o"
    openai_base_url: str | None = None
    # Comma-separated models users may pick in the UI; the default model is always included.
    openai_models: str = "gpt-4o,gpt-4o-mini,gpt-4.1,gpt-4.1-mini"
    openai_temperature: float | None = 0.1

    ado_org: str = ""
    ado_pat: SecretStr = SecretStr("")

    max_files: int = 40
    max_file_chars: int = 200_000
    max_chunk_chars: int = 12_000
    max_segments: int = 150
    max_active_jobs: int = 5
    llm_concurrency: int = 4
    min_confidence: float = 0.4
    job_ttl_seconds: int = 3600

    # Empty disables UI protection / the webhook endpoint respectively.
    ui_password: SecretStr = SecretStr("")
    webhook_secret: SecretStr = SecretStr("")
    # Comma-separated extra hosts (e.g. "localhost:3000,example.com") allowed as POST origins.
    allowed_origins: str = ""

    # Applies to webhook-triggered reviews only.
    auto_review_categories: str = "bug,test,security,dependency,optimization"
    auto_post_comments: bool = True
    status_check_enabled: bool = False
    block_on_severity: Severity = Severity.HIGH

    @property
    def available_models(self) -> list[str]:
        extra = (m.strip() for m in self.openai_models.split(","))
        return list(dict.fromkeys([self.openai_model, *(m for m in extra if m)]))

    @property
    def auto_categories(self) -> list[Category]:
        valid = {c.value for c in Category}
        parts = (p.strip() for p in self.auto_review_categories.split(","))
        return [Category(p) for p in parts if p in valid]


@lru_cache
def get_settings() -> Settings:
    return Settings()
