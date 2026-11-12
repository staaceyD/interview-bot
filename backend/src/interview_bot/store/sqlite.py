import json
from datetime import date
from pathlib import Path

import aiosqlite

from interview_bot.domain import Difficulty, Explanation, Grade, Question, Topic
from interview_bot.store.base import DEFAULT_MODEL_PROVIDER, Session, new_session_id

SCHEMA = f"""
CREATE TABLE IF NOT EXISTS sessions (
    id         TEXT PRIMARY KEY,
    -- A JSON array: an interview can draw on several topics at once.
    topics     TEXT NOT NULL,
    difficulty TEXT NOT NULL,
    model_provider    TEXT NOT NULL DEFAULT '{DEFAULT_MODEL_PROVIDER}',
    owner_id   TEXT
);

CREATE TABLE IF NOT EXISTS questions (
    seq        INTEGER PRIMARY KEY AUTOINCREMENT,
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

-- Questions asked per user per day, for the daily limits.
CREATE TABLE IF NOT EXISTS usage (
    user_id   TEXT NOT NULL,
    day       TEXT NOT NULL,
    questions INTEGER NOT NULL,
    PRIMARY KEY (user_id, day)
);
"""


class SQLiteSessionStore:
    """Keeps sessions in a SQLite file so they outlive the process."""

    def __init__(self, path: Path | str) -> None:
        self._path = Path(path)
        self._db: aiosqlite.Connection | None = None

    async def initialize(self) -> None:
        if self._path.parent != Path():
            self._path.parent.mkdir(parents=True, exist_ok=True)
        self._db = await aiosqlite.connect(self._path)
        await self._db.execute("PRAGMA foreign_keys = ON")
        # WAL lets the API keep reading while a question is being written.
        await self._db.execute("PRAGMA journal_mode = WAL")
        await self._db.executescript(SCHEMA)
        await self._migrate()
        await self._db.commit()

    async def _migrate(self) -> None:
        """Bring a file written by an older version up to the current schema.

        CREATE TABLE IF NOT EXISTS leaves an existing table alone, so a column
        added or changed later has to be brought to the file as well, or every
        read of it fails.
        """
        db = self._connection()
        async with db.execute("PRAGMA table_info(sessions)") as cursor:
            columns = {row[1] for row in await cursor.fetchall()}

        await self._migrate_model_provider(columns)
        await self._migrate_topics(columns)
        if "owner_id" not in columns:
            await db.execute("ALTER TABLE sessions ADD COLUMN owner_id TEXT")

    async def _migrate_model_provider(self, columns: set[str]) -> None:
        db = self._connection()
        if "model_provider" in columns:
            return
        if "backend" in columns:
            # What this column was called while it was being built.
            await db.execute("ALTER TABLE sessions RENAME COLUMN backend TO model_provider")
            return
        await db.execute(
            "ALTER TABLE sessions ADD COLUMN model_provider TEXT NOT NULL"
            f" DEFAULT '{DEFAULT_MODEL_PROVIDER}'"
        )

    async def _migrate_topics(self, columns: set[str]) -> None:
        """A file from when a session had one topic rather than a list of them."""
        if "topics" in columns:
            return
        db = self._connection()
        # Renamed rather than replaced, so an interview started before mixed
        # topics existed keeps the one it was on — as a list of that one.
        await db.execute("ALTER TABLE sessions RENAME COLUMN topic TO topics")
        await db.execute("UPDATE sessions SET topics = json_array(topics)")

    async def create(
        self,
        *,
        topics: list[Topic],
        difficulty: Difficulty,
        model_provider: str = DEFAULT_MODEL_PROVIDER,
        owner_id: str | None = None,
    ) -> Session:
        session = Session(
            id=new_session_id(),
            topics=list(topics),
            difficulty=difficulty,
            model_provider=model_provider,
            owner_id=owner_id,
        )
        await self._connection().execute(
            "INSERT INTO sessions (id, topics, difficulty, model_provider, owner_id)"
            " VALUES (?, ?, ?, ?, ?)",
            (
                session.id,
                json.dumps([topic.value for topic in session.topics]),
                session.difficulty.value,
                session.model_provider,
                session.owner_id,
            ),
        )
        await self._connection().commit()
        return session

    async def set_model_provider(self, session_id: str, model_provider: str) -> None:
        await self._connection().execute(
            "UPDATE sessions SET model_provider = ? WHERE id = ?", (model_provider, session_id)
        )
        await self._connection().commit()

    async def get(self, session_id: str) -> Session | None:
        db = self._connection()
        async with db.execute(
            "SELECT topics, difficulty, model_provider, owner_id FROM sessions WHERE id = ?",
            (session_id,),
        ) as cursor:
            row = await cursor.fetchone()
        if row is None:
            return None

        session = Session(
            id=session_id,
            topics=[Topic(topic) for topic in json.loads(row[0])],
            difficulty=Difficulty(row[1]),
            model_provider=row[2],
            owner_id=row[3],
        )
        async with db.execute(
            "SELECT id, topic, difficulty, prompt, key_points"
            " FROM questions WHERE session_id = ? ORDER BY seq",
            (session_id,),
        ) as cursor:
            rows = await cursor.fetchall()

        session.questions = {row[0]: _to_question(row) for row in rows}

        async with db.execute(
            "SELECT question_id, payload FROM grades WHERE session_id = ?", (session_id,)
        ) as cursor:
            rows = await cursor.fetchall()

        session.grades = {row[0]: Grade.model_validate_json(row[1]) for row in rows}

        async with db.execute(
            "SELECT question_id, payload FROM explanations WHERE session_id = ?", (session_id,)
        ) as cursor:
            rows = await cursor.fetchall()

        session.explanations = {row[0]: Explanation.model_validate_json(row[1]) for row in rows}
        return session

    async def add_question(self, session_id: str, question: Question) -> None:
        await self._connection().execute(
            "INSERT INTO questions (id, session_id, topic, difficulty, prompt, key_points)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (
                question.id,
                session_id,
                question.topic.value,
                question.difficulty.value,
                question.prompt,
                json.dumps(question.key_points),
            ),
        )
        await self._connection().commit()

    async def record_grade(self, session_id: str, question_id: str, grade: Grade) -> None:
        # Re-answering a question replaces its grade rather than piling up rows.
        await self._connection().execute(
            "INSERT INTO grades (question_id, session_id, payload) VALUES (?, ?, ?)"
            " ON CONFLICT(question_id) DO UPDATE SET payload = excluded.payload",
            (question_id, session_id, grade.model_dump_json()),
        )
        await self._connection().commit()

    async def record_explanation(
        self, session_id: str, question_id: str, explanation: Explanation
    ) -> None:
        # Written once and read back on every "Learn more", so generating it again
        # never costs the reader another wait on the model.
        await self._connection().execute(
            "INSERT INTO explanations (question_id, session_id, payload) VALUES (?, ?, ?)"
            " ON CONFLICT(question_id) DO UPDATE SET payload = excluded.payload",
            (question_id, session_id, explanation.model_dump_json()),
        )
        await self._connection().commit()

    async def take_question(self, *, user_id: str, day: date, limit: int) -> bool:
        if limit <= 0:
            return False
        db = self._connection()
        # The upsert only counts while under the limit, and returns no row when
        # it does not, so the check and the count are one statement.
        async with db.execute(
            "INSERT INTO usage (user_id, day, questions) VALUES (?, ?, 1)"
            " ON CONFLICT (user_id, day) DO UPDATE SET questions = questions + 1"
            " WHERE usage.questions < ?"
            " RETURNING questions",
            (user_id, day.isoformat(), limit),
        ) as cursor:
            counted = await cursor.fetchone()
        await db.commit()
        return counted is not None

    async def give_back_question(self, *, user_id: str, day: date) -> None:
        await self._connection().execute(
            "UPDATE usage SET questions = questions - 1"
            " WHERE user_id = ? AND day = ? AND questions > 0",
            (user_id, day.isoformat()),
        )
        await self._connection().commit()

    async def questions_taken(self, *, user_id: str, day: date) -> int:
        async with self._connection().execute(
            "SELECT questions FROM usage WHERE user_id = ? AND day = ?",
            (user_id, day.isoformat()),
        ) as cursor:
            row = await cursor.fetchone()
        return row[0] if row else 0

    async def aclose(self) -> None:
        if self._db is not None:
            await self._db.close()
            self._db = None

    def _connection(self) -> aiosqlite.Connection:
        if self._db is None:
            raise RuntimeError("Store used before initialize()")
        return self._db


def _to_question(row: aiosqlite.Row) -> Question:
    question_id, topic, difficulty, prompt, key_points = row
    return Question(
        id=question_id,
        topic=Topic(topic),
        difficulty=Difficulty(difficulty),
        prompt=prompt,
        key_points=json.loads(key_points),
    )
