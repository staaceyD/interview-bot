"""The Postgres the tests may wipe, where one is given, as in CI."""

import os

import psycopg
import pytest

TEST_DATABASE_URL = os.environ.get("INTERVIEW_BOT_TEST_DATABASE_URL")

needs_postgres = pytest.mark.skipif(
    TEST_DATABASE_URL is None, reason="INTERVIEW_BOT_TEST_DATABASE_URL is not set"
)


async def empty_database() -> str:
    """The test database's URL, with every table of the app dropped."""
    assert TEST_DATABASE_URL is not None
    async with await psycopg.AsyncConnection.connect(TEST_DATABASE_URL, autocommit=True) as conn:
        await conn.execute(
            "DROP TABLE IF EXISTS usage, explanations, grades, questions, sessions CASCADE"
        )
    return TEST_DATABASE_URL
