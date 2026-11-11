from functools import lru_cache
from pathlib import Path
from typing import Literal, get_args

from pydantic import AliasChoices, Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

ModelProvider = Literal["ollama", "anthropic", "echo"]
StoreBackend = Literal["sqlite", "memory", "postgres"]
Environment = Literal["development", "production"]

# Where `neon deploy` writes the Neon branch's variables: the repository root.
NEON_ENV_FILE = Path(__file__).resolve().parents[3] / ".env.local"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="INTERVIEW_BOT_",
        # Later files win: a .env of your own overrides what Neon wrote.
        env_file=(NEON_ENV_FILE, ".env.local", ".env"),
        # The Neon file carries variables this app has no use for.
        extra="ignore",
        # So a test can still pass database_url=... by name.
        populate_by_name=True,
    )

    # Production is the hosted deployment, where there is no Ollama next to the
    # server: it runs on Claude alone and offers nothing to switch to.
    environment: Environment = "development"

    # The provider a session runs on when it does not choose one itself.
    default_model_provider: ModelProvider = "ollama"
    llm_timeout_seconds: float = 120.0
    # A worked answer is several times longer than a question or a grade, so it
    # gets its own budget rather than making a hung model take five minutes to
    # fail on every call.
    llm_explain_timeout_seconds: float = 300.0
    prefetch_explanations: bool = True

    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "qwen3:4b-instruct"

    # The cheapest Claude model, and still several times faster than a 4B model
    # on a laptop. The key comes from the environment: ANTHROPIC_API_KEY, or a
    # profile left by `ant auth login`.
    anthropic_model: str = "claude-haiku-4-5"
    # A worked answer is the longest reply and runs to about 1,300 tokens.
    anthropic_max_tokens: int = 4096

    store_backend: StoreBackend = "sqlite"
    sqlite_path: Path = Path("interview_bot.db")
    # Neon's own names, as `neon deploy` writes them, so nothing has to be
    # renamed by hand. Only read with the postgres backend, so a local run stays
    # on SQLite even with Neon's file in place.
    # Pooled, through Neon's PgBouncer: every query the app makes.
    database_url: SecretStr | None = Field(
        default=None,
        validation_alias=AliasChoices("INTERVIEW_BOT_DATABASE_URL", "DATABASE_URL"),
    )
    # Direct: creating the schema, which the pooler is not for.
    database_url_unpooled: SecretStr | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "INTERVIEW_BOT_DATABASE_URL_UNPOOLED", "DATABASE_URL_UNPOOLED"
        ),
    )

    cors_origins: list[str] = ["http://localhost:5173"]
    # The built frontend, served by the API itself when set, so a deployment is
    # one service on one origin.
    static_dir: Path | None = None

    @model_validator(mode="after")
    def _claude_in_production(self) -> "Settings":
        if self.environment == "production":
            self.default_model_provider = "anthropic"
        return self

    @property
    def model_providers(self) -> tuple[ModelProvider, ...]:
        """Every provider an interview can run on in this environment."""
        if self.environment == "production":
            return ("anthropic",)
        return get_args(ModelProvider)


@lru_cache
def get_settings() -> Settings:
    return Settings()
