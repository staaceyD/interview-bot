"""Behaviour of the Postgres store beyond the shared contract."""

import psycopg
import pytest

from interview_bot.config import LOCAL_DATABASE_URL, Settings
from interview_bot.domain import Difficulty, Grade, Question, Topic
from interview_bot.store import InMemorySessionStore, PostgresSessionStore, build_session_store
from postgres_db import empty_database, needs_postgres


def a_question(prompt: str) -> Question:
    return Question(
        id=prompt, topic=Topic.PYTHON, difficulty=Difficulty.MID, prompt=prompt, key_points=["p"]
    )


async def open_store(url: str) -> PostgresSessionStore:
    store = PostgresSessionStore(url)
    await store.initialize()
    return store


@needs_postgres
async def test_sessions_and_grades_survive_a_restart() -> None:
    url = await empty_database()
    first_run = await open_store(url)
    session = await first_run.create(topics=[Topic.REACT], difficulty=Difficulty.SENIOR)
    await first_run.add_question(session.id, a_question("What is the virtual DOM?"))
    await first_run.record_grade(
        session.id, "What is the virtual DOM?", Grade(score=4, verdict="Good answer.")
    )
    await first_run.aclose()

    second_run = await open_store(url)
    loaded = await second_run.get(session.id)
    await second_run.aclose()

    assert loaded is not None
    assert loaded.topics == [Topic.REACT]
    assert loaded.asked_prompts == ["What is the virtual DOM?"]
    assert loaded.latest_grade == Grade(score=4, verdict="Good answer.")


@needs_postgres
async def test_reopening_does_not_wipe_existing_data() -> None:
    url = await empty_database()
    first_run = await open_store(url)
    session = await first_run.create(topics=[Topic.PYTHON], difficulty=Difficulty.MID)
    await first_run.add_question(session.id, a_question("first"))
    await first_run.aclose()

    second_run = await open_store(url)
    await second_run.add_question(session.id, a_question("second"))
    loaded = await second_run.get(session.id)
    await second_run.aclose()

    assert loaded is not None
    assert loaded.asked_prompts == ["first", "second"]


@needs_postgres
async def test_a_question_needs_an_existing_session() -> None:
    store = await open_store(await empty_database())

    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        await store.add_question("no-such-session", a_question("orphan"))

    await store.aclose()


@needs_postgres
async def test_a_grade_needs_an_existing_question() -> None:
    store = await open_store(await empty_database())
    session = await store.create(topics=[Topic.PYTHON], difficulty=Difficulty.MID)

    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        await store.record_grade(session.id, "no-such-question", Grade(score=1, verdict="?"))

    await store.aclose()


def test_a_local_run_uses_the_compose_database() -> None:
    settings = Settings(_env_file=None)

    assert settings.database_url is not None
    assert settings.database_url.get_secret_value() == LOCAL_DATABASE_URL


def test_production_never_falls_back_to_a_local_database() -> None:
    settings = Settings(_env_file=None, environment="production", session_secret="s")

    assert settings.database_url is None
    with pytest.raises(ValueError, match="DATABASE_URL"):
        build_session_store(settings)


def test_factory_builds_the_configured_store() -> None:
    assert isinstance(build_session_store(Settings(_env_file=None)), PostgresSessionStore)
    assert isinstance(
        build_session_store(Settings(_env_file=None, store_backend="memory")),
        InMemorySessionStore,
    )


def test_factory_rejects_an_unknown_backend() -> None:
    settings = Settings.model_construct(store_backend="sqlite")

    with pytest.raises(ValueError, match="sqlite"):
        build_session_store(settings)
