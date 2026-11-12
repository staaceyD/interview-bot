from functools import lru_cache
from pathlib import Path
from typing import Literal, get_args

from pydantic import AliasChoices, Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

ModelProvider = Literal["ollama", "anthropic", "echo"]
StoreBackend = Literal["sqlite", "memory", "postgres"]
SignInProvider = Literal["google", "github"]
Environment = Literal["development", "production"]

# Where `neon deploy` writes the Neon branch's variables: the repository root.
NEON_ENV_FILE = Path(__file__).resolve().parents[3] / ".env.local"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="INTERVIEW_BOT_",
        env_file=(NEON_ENV_FILE, ".env.local", ".env"),
        extra="ignore",
        populate_by_name=True,
    )

    environment: Environment = "development"

    default_model_provider: ModelProvider = "ollama"
    llm_timeout_seconds: float = 120.0
    llm_explain_timeout_seconds: float = 300.0
    prefetch_explanations: bool = True

    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "qwen3:4b-instruct"

    anthropic_model: str = "claude-haiku-4-5"
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
    database_url_unpooled: SecretStr | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "INTERVIEW_BOT_DATABASE_URL_UNPOOLED", "DATABASE_URL_UNPOOLED"
        ),
    )

    session_secret: SecretStr | None = None
    session_max_age_seconds: int = 14 * 24 * 60 * 60
    google_client_id: str | None = None
    google_client_secret: SecretStr | None = None
    github_client_id: str | None = None
    github_client_secret: SecretStr | None = None

    sign_in_required: bool = False
    daily_question_limit: int = 5
    daily_question_limit_total: int = 20
    unlimited_emails: list[str] = []

    cors_origins: list[str] = ["http://localhost:5173"]
    static_dir: Path | None = None

    @model_validator(mode="after")
    def _production(self) -> "Settings":
        if self.environment == "production":
            self.default_model_provider = "anthropic"
            # Forced rather than defaulted: a public deployment that forgot the
            # flag would spend the owner's key on anyone.
            self.sign_in_required = True
        if self.sign_in_required and self.session_secret is None:
            # A made-up secret would sign everyone out on every restart, and a
            # fixed default would let anyone forge a session.
            raise ValueError("INTERVIEW_BOT_SESSION_SECRET is required when sign-in is")
        return self

    @property
    def sign_in_providers(self) -> list[SignInProvider]:
        """The providers with both an id and a secret, in the order they are offered."""
        configured: list[SignInProvider] = []
        if self.google_client_id and self.google_client_secret:
            configured.append("google")
        if self.github_client_id and self.github_client_secret:
            configured.append("github")
        return configured

    @property
    def model_providers(self) -> tuple[ModelProvider, ...]:
        """Every provider an interview can run on in this environment."""
        if self.environment == "production":
            return ("anthropic",)
        return get_args(ModelProvider)


@lru_cache
def get_settings() -> Settings:
    return Settings()
