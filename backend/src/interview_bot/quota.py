from collections.abc import Callable, Iterable
from datetime import UTC, date, datetime

from interview_bot.auth import User
from interview_bot.store import ALL_USERS, SessionStore


class QuotaExceeded(Exception):
    """No questions left today, for this visitor or for everyone."""


def _today() -> date:
    return datetime.now(UTC).date()


class Quota:
    """The daily question limits: one per visitor, and one shared by them all.

    Questions are counted before the model is asked, and given back if it then
    fails, so a burst of requests fired at once is counted request by request
    rather than all passing a check that none of them has been counted against.
    """

    def __init__(
        self,
        store: SessionStore,
        *,
        per_user: int,
        total: int,
        unlimited_emails: Iterable[str],
        today: Callable[[], date] = _today,
    ) -> None:
        self._store = store
        self._per_user = per_user
        self._total = total
        self._unlimited = {email.strip().lower() for email in unlimited_emails}
        self._today = today

    def is_unlimited(self, user: User) -> bool:
        return user.email is not None and user.email.lower() in self._unlimited

    async def take(self, user: User) -> date | None:
        """Count one question for the visitor, or raise if they have none left.

        Returns the day it was counted against, to give it back to, or None if
        the visitor is not counted at all.
        """
        if self.is_unlimited(user):
            return None
        day = self._today()
        if not await self._store.take_question(user_id=ALL_USERS, day=day, limit=self._total):
            raise QuotaExceeded(
                "The app has used all of today's questions. They reset at midnight UTC."
            )
        if not await self._store.take_question(user_id=user.id, day=day, limit=self._per_user):
            await self._store.give_back_question(user_id=ALL_USERS, day=day)
            raise QuotaExceeded(
                f"You have used all {self._per_user} of today's questions."
                " They reset at midnight UTC."
            )
        return day

    async def give_back(self, user: User, day: date | None) -> None:
        if day is None:
            return
        await self._store.give_back_question(user_id=user.id, day=day)
        await self._store.give_back_question(user_id=ALL_USERS, day=day)

    async def left(self, user: User) -> int | None:
        """Questions the visitor can still ask today, or None if they are not counted."""
        if self.is_unlimited(user):
            return None
        day = self._today()
        mine = await self._store.questions_taken(user_id=user.id, day=day)
        everyone = await self._store.questions_taken(user_id=ALL_USERS, day=day)
        return max(0, min(self._per_user - mine, self._total - everyone))
