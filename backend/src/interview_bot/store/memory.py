from datetime import date

from interview_bot.domain import Difficulty, Explanation, Grade, Question, Topic
from interview_bot.store.base import DEFAULT_MODEL_PROVIDER, Session, new_session_id


class InMemorySessionStore:
    """Keeps sessions for the life of the process."""

    def __init__(self) -> None:
        self._sessions: dict[str, Session] = {}
        self._usage: dict[tuple[str, date], int] = {}

    async def initialize(self) -> None:
        return None

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
        self._sessions[session.id] = session
        return session

    async def get(self, session_id: str) -> Session | None:
        return self._sessions.get(session_id)

    async def set_model_provider(self, session_id: str, model_provider: str) -> None:
        self._sessions[session_id].model_provider = model_provider

    async def add_question(self, session_id: str, question: Question) -> None:
        self._sessions[session_id].questions[question.id] = question

    async def record_grade(self, session_id: str, question_id: str, grade: Grade) -> None:
        self._sessions[session_id].grades[question_id] = grade

    async def record_explanation(
        self, session_id: str, question_id: str, explanation: Explanation
    ) -> None:
        self._sessions[session_id].explanations[question_id] = explanation

    async def take_question(self, *, user_id: str, day: date, limit: int) -> bool:
        # Nothing awaits between the check and the count, so it is atomic.
        taken = self._usage.get((user_id, day), 0)
        if taken >= limit:
            return False
        self._usage[(user_id, day)] = taken + 1
        return True

    async def give_back_question(self, *, user_id: str, day: date) -> None:
        taken = self._usage.get((user_id, day), 0)
        if taken > 0:
            self._usage[(user_id, day)] = taken - 1

    async def questions_taken(self, *, user_id: str, day: date) -> int:
        return self._usage.get((user_id, day), 0)

    async def aclose(self) -> None:
        return None
