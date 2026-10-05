from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# Provider SDKs read their API keys straight from os.environ, so .env must be exported there too.
load_dotenv()


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    llm_model: str = "openai:gpt-4o-mini"
    llm_fallback_models: str = ""
    llm_temperature: float = 0.0
    llm_max_retries: int = Field(default=0, ge=0, le=3)
    llm_timeout_seconds: float = Field(default=25, gt=0, le=120)
    llm_reasoning_effort: str = "low"

    data_dir: Path = Path("data")
    max_agent_steps: int = Field(default=25, ge=3)
    log_level: str = "WARNING"

    mealdb_base_url: str = "https://www.themealdb.com/api/json/v1/1"
    recipe_cache_ttl_hours: float = Field(default=168, ge=0)
    http_timeout_seconds: float = Field(default=10, gt=0)

    @property
    def app_db_path(self) -> Path:
        return self.data_dir / "app.db"

    @property
    def checkpoint_db_path(self) -> Path:
        return self.data_dir / "checkpoints.db"

    @property
    def log_path(self) -> Path:
        return self.data_dir / "agent.log"

    @property
    def fallback_model_names(self) -> list[str]:
        return [name.strip() for name in self.llm_fallback_models.split(",") if name.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
