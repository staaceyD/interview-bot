"""The contract every SessionStore must satisfy, run against each implementation."""

import asyncio
from collections.abc import AsyncIterator
from datetime import date

import pytest

from interview_bot.domain import Difficulty, Explanation, Grade, Question, Topic
from interview_bot.store import InMemorySessionStore, PostgresSessionStore, SessionStore
from postgres_db import empty_database, needs_postgres


@pytest.fixture(params=["memory", pytest.param("postgres", marks=needs_postgres)])
async def store(request: pytest.FixtureRequest) -> AsyncIterator[SessionStore]:
    built: SessionStore = (
        InMemorySessionStore()
        if request.param == "memory"
        else PostgresSessionStore(await empty_database())
    )
    await built.initialize()
    yield built
    await built.aclose()


def a_question(
    prompt: str, key_points: list[str] | None = None, topic: Topic = Topic.PYTHON
) -> Question:
    return Question(
        id=prompt,
        topic=topic,
        difficulty=Difficulty.MID,
        prompt=prompt,
        key_points=key_points or ["point"],
    )


async def test_created_session_can_be_read_back(store: SessionStore) -> None:
    session = await store.create(topics=[Topic.REACT], difficulty=Difficulty.SENIOR)

    loaded = await store.get(session.id)

    assert loaded is not None
    assert loaded.id == session.id
    assert loaded.topics == [Topic.REACT]
    assert loaded.difficulty == Difficulty.SENIOR


async def test_a_session_keeps_every_topic_in_the_order_picked(store: SessionStore) -> None:
    session = await store.create(
        topics=[Topic.SECURITY, Topic.PYTHON, Topic.DATABASES], difficulty=Difficulty.MID
    )

    loaded = await store.get(session.id)

    assert loaded is not None
    assert loaded.topics == [Topic.SECURITY, Topic.PYTHON, Topic.DATABASES]


async def test_asked_topics_follow_the_questions_asked(store: SessionStore) -> None:
    """What the rotation reads to decide which topic is due next."""
    session = await store.create(topics=[Topic.PYTHON, Topic.SECURITY], difficulty=Difficulty.MID)

    await store.add_question(session.id, a_question("first", topic=Topic.SECURITY))
    await store.add_question(session.id, a_question("second", topic=Topic.PYTHON))

    assert (await store.get(session.id)).asked_topics == [Topic.SECURITY, Topic.PYTHON]


async def test_unknown_session_is_none(store: SessionStore) -> None:
    assert await store.get("nope") is None


async def test_sessions_get_distinct_ids(store: SessionStore) -> None:
    first = await store.create(topics=[Topic.PYTHON], difficulty=Difficulty.MID)
    second = await store.create(topics=[Topic.PYTHON], difficulty=Difficulty.MID)

    assert first.id != second.id


async def test_sessions_are_isolated(store: SessionStore) -> None:
    first = await store.create(topics=[Topic.PYTHON], difficulty=Difficulty.MID)
    second = await store.create(topics=[Topic.PYTHON], difficulty=Difficulty.MID)

    await store.add_question(first.id, a_question("only in first"))

    assert (await store.get(second.id)).questions == {}


async def test_asked_prompts_keep_insertion_order(store: SessionStore) -> None:
    session = await store.create(topics=[Topic.PYTHON], difficulty=Difficulty.MID)

    for prompt in ["first", "second", "third"]:
        await store.add_question(session.id, a_question(prompt))

    assert (await store.get(session.id)).asked_prompts == ["first", "second", "third"]


async def test_question_round_trips_intact(store: SessionStore) -> None:
    session = await store.create(topics=[Topic.JAVASCRIPT], difficulty=Difficulty.JUNIOR)
    question = Question(
        id="q1",
        topic=Topic.JAVASCRIPT,
        difficulty=Difficulty.JUNIOR,
        prompt="What is a closure?",
        key_points=["captured scope", "lives past the call", "used for privacy"],
    )

    await store.add_question(session.id, question)

    assert (await store.get(session.id)).questions["q1"] == question


async def test_grade_round_trips_with_its_question(store: SessionStore) -> None:
    session = await store.create(topics=[Topic.PYTHON], difficulty=Difficulty.MID)
    await store.add_question(session.id, a_question("What is the GIL?"))
    grade = Grade(score=4, verdict="Good answer.", covered=["a mutex"], missed=["I/O"])

    await store.record_grade(session.id, "What is the GIL?", grade)

    loaded = await store.get(session.id)
    assert loaded.grades == {"What is the GIL?": grade}
    assert loaded.latest_grade == grade


async def test_regrading_replaces_the_previous_grade(store: SessionStore) -> None:
    session = await store.create(topics=[Topic.PYTHON], difficulty=Difficulty.MID)
    await store.add_question(session.id, a_question("q"))

    await store.record_grade(session.id, "q", Grade(score=1, verdict="Thin."))
    await store.record_grade(session.id, "q", Grade(score=5, verdict="Much better."))

    assert (await store.get(session.id)).latest_grade.score == 5


async def test_an_unanswered_latest_question_has_no_grade(store: SessionStore) -> None:
    session = await store.create(topics=[Topic.PYTHON], difficulty=Difficulty.MID)
    await store.add_question(session.id, a_question("first"))
    await store.record_grade(session.id, "first", Grade(score=3, verdict="Fine."))
    await store.add_question(session.id, a_question("second"))

    assert (await store.get(session.id)).latest_grade is None


async def test_explanation_round_trips_with_its_question(store: SessionStore) -> None:
    session = await store.create(topics=[Topic.PYTHON], difficulty=Difficulty.MID)
    await store.add_question(session.id, a_question("What is the GIL?"))
    explanation = Explanation(
        answer="A mutex around the interpreter.",
        points=[{"point": "a mutex", "detail": "It guards interpreter state."}],
        pitfalls=["Reaching for threads on CPU-bound work"],
    )

    await store.record_explanation(session.id, "What is the GIL?", explanation)
    await store.record_grade(session.id, "What is the GIL?", Grade(score=3, verdict="Fine."))

    loaded = await store.get(session.id)
    assert loaded.explanations == {"What is the GIL?": explanation}
    assert loaded.latest_explanation == explanation


async def test_an_ungraded_question_keeps_its_explanation_back(store: SessionStore) -> None:
    """An answer written ahead is in the store before the candidate attempts anything."""
    session = await store.create(topics=[Topic.PYTHON], difficulty=Difficulty.MID)
    await store.add_question(session.id, a_question("What is the GIL?"))
    await store.record_explanation(session.id, "What is the GIL?", Explanation(answer="A mutex."))

    loaded = await store.get(session.id)
    assert loaded.explanations["What is the GIL?"].answer == "A mutex."
    assert loaded.latest_explanation is None


async def test_an_unexplained_latest_question_has_no_explanation(store: SessionStore) -> None:
    session = await store.create(topics=[Topic.PYTHON], difficulty=Difficulty.MID)
    await store.add_question(session.id, a_question("first"))
    await store.record_explanation(session.id, "first", Explanation(answer="Because."))
    await store.add_question(session.id, a_question("second"))

    assert (await store.get(session.id)).latest_explanation is None


async def test_a_session_remembers_which_model_it_runs_on(store: SessionStore) -> None:
    session = await store.create(
        topics=[Topic.PYTHON], difficulty=Difficulty.MID, model_provider="anthropic"
    )

    loaded = await store.get(session.id)

    assert loaded is not None
    assert loaded.model_provider == "anthropic"


async def test_a_session_defaults_to_the_local_model(store: SessionStore) -> None:
    session = await store.create(topics=[Topic.PYTHON], difficulty=Difficulty.MID)

    assert (await store.get(session.id)).model_provider == "ollama"


async def test_switching_model_is_stored(store: SessionStore) -> None:
    session = await store.create(topics=[Topic.PYTHON], difficulty=Difficulty.MID)

    await store.set_model_provider(session.id, "anthropic")

    assert (await store.get(session.id)).model_provider == "anthropic"


async def test_a_session_remembers_who_it_belongs_to(store: SessionStore) -> None:
    mine = await store.create(topics=[Topic.PYTHON], difficulty=Difficulty.MID, owner_id="github:1")
    nobodys = await store.create(topics=[Topic.PYTHON], difficulty=Difficulty.MID)

    loaded_mine = await store.get(mine.id)
    loaded_nobodys = await store.get(nobodys.id)

    assert loaded_mine is not None and loaded_mine.owner_id == "github:1"
    assert loaded_nobodys is not None and loaded_nobodys.owner_id is None


TODAY = date(2026, 11, 11)


async def test_questions_are_counted_up_to_the_limit(store: SessionStore) -> None:
    taken = [await store.take_question(user_id="u", day=TODAY, limit=2) for _ in range(3)]

    assert taken == [True, True, False]
    assert await store.questions_taken(user_id="u", day=TODAY) == 2


async def test_questions_are_counted_per_user_and_per_day(store: SessionStore) -> None:
    await store.take_question(user_id="u", day=TODAY, limit=1)

    assert await store.take_question(user_id="v", day=TODAY, limit=1)
    assert await store.take_question(user_id="u", day=date(2026, 11, 12), limit=1)
    assert await store.questions_taken(user_id="nobody", day=TODAY) == 0


async def test_a_limit_of_nothing_counts_nothing(store: SessionStore) -> None:
    assert not await store.take_question(user_id="u", day=TODAY, limit=0)
    assert await store.questions_taken(user_id="u", day=TODAY) == 0


async def test_a_question_given_back_can_be_taken_again(store: SessionStore) -> None:
    await store.take_question(user_id="u", day=TODAY, limit=1)

    await store.give_back_question(user_id="u", day=TODAY)

    assert await store.take_question(user_id="u", day=TODAY, limit=1)


async def test_giving_back_never_goes_below_nothing(store: SessionStore) -> None:
    await store.give_back_question(user_id="u", day=TODAY)

    assert await store.questions_taken(user_id="u", day=TODAY) == 0


async def test_concurrent_takes_never_pass_the_limit(store: SessionStore) -> None:
    taken = await asyncio.gather(
        *(store.take_question(user_id="u", day=TODAY, limit=3) for _ in range(20))
    )

    assert taken.count(True) == 3
    assert await store.questions_taken(user_id="u", day=TODAY) == 3
