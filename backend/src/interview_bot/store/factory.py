from interview_bot.config import Settings
from interview_bot.store.base import SessionStore
from interview_bot.store.memory import InMemorySessionStore
from interview_bot.store.postgres import PostgresSessionStore


def build_session_store(settings: Settings) -> SessionStore:
    if settings.store_backend == "postgres":
        if settings.database_url is None:
            raise ValueError("The postgres store needs DATABASE_URL")
        return PostgresSessionStore(
            settings.database_url.get_secret_value(),
            schema_conninfo=(
                settings.database_url_unpooled.get_secret_value()
                if settings.database_url_unpooled
                else None
            ),
        )
    if settings.store_backend == "memory":
        return InMemorySessionStore()
    raise ValueError(f"Unknown store backend: {settings.store_backend}")
