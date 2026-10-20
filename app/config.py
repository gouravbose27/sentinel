from functools import lru_cache

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", env_parse_none_str="none")

    openai_api_key: SecretStr = SecretStr("")
    openai_model: str = "gpt-4o"
    openai_base_url: str | None = None
    openai_temperature: float | None = 0.1

    ado_org: str = ""
    ado_pat: SecretStr = SecretStr("")

    max_files: int = 40
    max_file_chars: int = 200_000
    max_chunk_chars: int = 12_000
    llm_concurrency: int = 4
    min_confidence: float = 0.4
    job_ttl_seconds: int = 3600


@lru_cache
def get_settings() -> Settings:
    return Settings()
