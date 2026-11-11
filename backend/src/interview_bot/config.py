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
        # Later files win: a .env of your own overrides what Neon wrote.
        env_file=(NEON_ENV_FILE, ".env.local", ".env"),
        # The Neon file carries variables this app has no use for.
        extra="ignore",
        # So a test can still pass database_url=... by name.
        populate_by_name=True,
    )

    # Production is the hosted deployment, where there is no Ollama next to the
    # server: it runs on Claude alone and offers nothing to switch to, and an
    # interview needs a signed-in visitor with questions left for the day.
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

    # Signs the cookie a visitor stays signed in with. Required in production:
    # without it nobody could sign in, and a default would let anyone forge one.
    session_secret: SecretStr | None = None
    session_max_age_seconds: int = 14 * 24 * 60 * 60
    # A provider is offered on the sign-in screen once both halves are set.
    google_client_id: str | None = None
    google_client_secret: SecretStr | None = None
    github_client_id: str | None = None
    github_client_secret: SecretStr | None = None

    # Questions are what cost money, so they are what is counted: a grade and a
    # worked answer come with the question they are for. Each signed-in visitor
    # gets this many a day (UTC)...
    daily_question_limit: int = 20
    # ...and all of them together this many, so no number of accounts can run
    # up more than a fixed bill.
    daily_question_limit_total: int = 200
    # Verified emails that are never counted: the owner's.
    unlimited_emails: list[str] = []

    cors_origins: list[str] = ["http://localhost:5173"]
    # The built frontend, served by the API itself when set, so a deployment is
    # one service on one origin.
    static_dir: Path | None = None

    @model_validator(mode="after")
    def _production(self) -> "Settings":
        if self.environment == "production":
            self.default_model_provider = "anthropic"
            if self.session_secret is None:
                raise ValueError("INTERVIEW_BOT_SESSION_SECRET is required in production")
        return self

    @property
    def sign_in_required(self) -> bool:
        """Whether an interview needs a signed-in visitor, and is counted against them."""
        return self.environment == "production"

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
