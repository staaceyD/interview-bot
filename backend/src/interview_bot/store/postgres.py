import json

import psycopg
from psycopg.rows import TupleRow
from psycopg_pool import AsyncConnectionPool

from interview_bot.domain import Difficulty, Explanation, Grade, Question, Topic
from interview_bot.store.base import DEFAULT_MODEL_PROVIDER, Session, new_session_id

# The same shape as the SQLite schema, so the two stores read alike.
SCHEMA = f"""
CREATE TABLE IF NOT EXISTS sessions (
    id             TEXT PRIMARY KEY,
    -- A JSON array: an interview can draw on several topics at once.
    topics         TEXT NOT NULL,
    difficulty     TEXT NOT NULL,
    model_provider TEXT NOT NULL DEFAULT '{DEFAULT_MODEL_PROVIDER}'
);

CREATE TABLE IF NOT EXISTS questions (
    seq        BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    id         TEXT NOT NULL UNIQUE,
    session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    topic      TEXT NOT NULL,
    difficulty TEXT NOT NULL,
    prompt     TEXT NOT NULL,
    key_points TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS questions_by_session ON questions(session_id, seq);

CREATE TABLE IF NOT EXISTS grades (
    question_id TEXT PRIMARY KEY REFERENCES questions(id) ON DELETE CASCADE,
    session_id  TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    payload     TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS grades_by_session ON grades(session_id);

CREATE TABLE IF NOT EXISTS explanations (
    question_id TEXT PRIMARY KEY REFERENCES questions(id) ON DELETE CASCADE,
    session_id  TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    payload     TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS explanations_by_session ON explanations(session_id);
"""


class PostgresSessionStore:
    """Keeps sessions in Postgres, for a host whose own disk does not last."""

    def __init__(self, conninfo: str, *, schema_conninfo: str | None = None) -> None:
        """`conninfo` serves every query; `schema_conninfo`, if given, creates the schema.

        On Neon the first is the pooled string and the second the direct one:
        the pooler runs in transaction mode, which is for queries, not DDL.
        """
        self._schema_conninfo = schema_conninfo or conninfo
        # Opened in initialize(), inside the running event loop.
        self._pool = AsyncConnectionPool(
            conninfo,
            min_size=1,
            max_size=5,
            open=False,
            # psycopg prepares a statement it has run a few times, and a
            # transaction-mode pooler can hand the next query to a server that
            # never saw it prepared. Off, every statement is sent as it is.
            kwargs={"prepare_threshold": None},
        )

    async def initialize(self) -> None:
        async with await psycopg.AsyncConnection.connect(
            self._schema_conninfo, autocommit=True
        ) as conn:
            await conn.execute(SCHEMA)
        await self._pool.open(wait=True)

    async def create(
        self,
        *,
        topics: list[Topic],
        difficulty: Difficulty,
        model_provider: str = DEFAULT_MODEL_PROVIDER,
    ) -> Session:
        session = Session(
            id=new_session_id(),
            topics=list(topics),
            difficulty=difficulty,
            model_provider=model_provider,
        )
        async with self._pool.connection() as conn:
            await conn.execute(
                "INSERT INTO sessions (id, topics, difficulty, model_provider)"
                " VALUES (%s, %s, %s, %s)",
                (
                    session.id,
                    json.dumps([topic.value for topic in session.topics]),
                    session.difficulty.value,
                    session.model_provider,
                ),
            )
        return session

    async def set_model_provider(self, session_id: str, model_provider: str) -> None:
        async with self._pool.connection() as conn:
            await conn.execute(
                "UPDATE sessions SET model_provider = %s WHERE id = %s",
                (model_provider, session_id),
            )

    async def get(self, session_id: str) -> Session | None:
        async with self._pool.connection() as conn:
            cursor = await conn.execute(
                "SELECT topics, difficulty, model_provider FROM sessions WHERE id = %s",
                (session_id,),
            )
            row = await cursor.fetchone()
            if row is None:
                return None

            session = Session(
                id=session_id,
                topics=[Topic(topic) for topic in json.loads(row[0])],
                difficulty=Difficulty(row[1]),
                model_provider=row[2],
            )
            cursor = await conn.execute(
                "SELECT id, topic, difficulty, prompt, key_points"
                " FROM questions WHERE session_id = %s ORDER BY seq",
                (session_id,),
            )
            session.questions = {row[0]: _to_question(row) for row in await cursor.fetchall()}

            cursor = await conn.execute(
                "SELECT question_id, payload FROM grades WHERE session_id = %s", (session_id,)
            )
            session.grades = {
                row[0]: Grade.model_validate_json(row[1]) for row in await cursor.fetchall()
            }

            cursor = await conn.execute(
                "SELECT question_id, payload FROM explanations WHERE session_id = %s",
                (session_id,),
            )
            session.explanations = {
                row[0]: Explanation.model_validate_json(row[1]) for row in await cursor.fetchall()
            }
        return session

    async def add_question(self, session_id: str, question: Question) -> None:
        async with self._pool.connection() as conn:
            await conn.execute(
                "INSERT INTO questions (id, session_id, topic, difficulty, prompt, key_points)"
                " VALUES (%s, %s, %s, %s, %s, %s)",
                (
                    question.id,
                    session_id,
                    question.topic.value,
                    question.difficulty.value,
                    question.prompt,
                    json.dumps(question.key_points),
                ),
            )

    async def record_grade(self, session_id: str, question_id: str, grade: Grade) -> None:
        async with self._pool.connection() as conn:
            await conn.execute(
                "INSERT INTO grades (question_id, session_id, payload) VALUES (%s, %s, %s)"
                " ON CONFLICT (question_id) DO UPDATE SET payload = excluded.payload",
                (question_id, session_id, grade.model_dump_json()),
            )

    async def record_explanation(
        self, session_id: str, question_id: str, explanation: Explanation
    ) -> None:
        async with self._pool.connection() as conn:
            await conn.execute(
                "INSERT INTO explanations (question_id, session_id, payload) VALUES (%s, %s, %s)"
                " ON CONFLICT (question_id) DO UPDATE SET payload = excluded.payload",
                (question_id, session_id, explanation.model_dump_json()),
            )

    async def aclose(self) -> None:
        await self._pool.close()


def _to_question(row: TupleRow) -> Question:
    question_id, topic, difficulty, prompt, key_points = row
    return Question(
        id=question_id,
        topic=Topic(topic),
        difficulty=Difficulty(difficulty),
        prompt=prompt,
        key_points=json.loads(key_points),
    )
