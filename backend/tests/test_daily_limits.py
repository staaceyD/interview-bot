"""The daily question limits, per visitor and for everyone together."""

import asyncio

import pytest
from httpx import AsyncClient

from accounts import (
    OWNER_EMAIL,
    Interviews,
    ask,
    browser,
    build_app,
    sign_in,
    sign_in_settings,
    start,
)


@pytest.fixture
def model() -> Interviews:
    return Interviews()


@pytest.fixture
def app(model: Interviews):
    return build_app(sign_in_settings(daily_question_limit=3, daily_question_limit_total=5), model)


@pytest.fixture
async def visitor(app):
    async with app.router.lifespan_context(app):
        async for client in browser(app):
            yield client


async def test_a_visitor_gets_their_daily_questions_and_no_more(
    visitor: AsyncClient, model: Interviews
) -> None:
    await sign_in(visitor)
    session_id = await start(visitor)

    statuses = [await ask(visitor, session_id) for _ in range(4)]

    assert statuses == [201, 201, 201, 429]
    assert model.asked == 3
    refused = await visitor.post(f"/sessions/{session_id}/questions")
    assert "all 3 of today's questions" in refused.json()["detail"]
    assert (await visitor.get("/auth/me")).json()["questions_left"] == 0


async def test_a_new_interview_does_not_reset_the_count(visitor: AsyncClient) -> None:
    await sign_in(visitor)
    for _ in range(3):
        assert await ask(visitor, await start(visitor)) == 201

    assert await ask(visitor, await start(visitor)) == 429


async def test_everyone_together_is_capped_too(app, visitor: AsyncClient) -> None:
    await sign_in(visitor, "ada")
    ada = await start(visitor)
    for _ in range(3):
        assert await ask(visitor, ada) == 201

    async for other in browser(app):
        await sign_in(other, "grace")
        grace = await start(other)
        statuses = [await ask(other, grace) for _ in range(3)]
        refused = await other.post(f"/sessions/{grace}/questions")

    assert statuses == [201, 201, 429]
    assert "The app has used all of today's questions" in refused.json()["detail"]


async def test_a_burst_of_requests_cannot_beat_the_limit(
    visitor: AsyncClient, model: Interviews
) -> None:
    await sign_in(visitor)
    session_id = await start(visitor)

    statuses = await asyncio.gather(*(ask(visitor, session_id) for _ in range(10)))

    assert sorted(statuses) == [201] * 3 + [429] * 7
    assert model.asked == 3


async def test_a_question_the_model_failed_to_write_is_not_counted(
    visitor: AsyncClient, model: Interviews
) -> None:
    await sign_in(visitor)
    session_id = await start(visitor)
    model.fail = True

    assert await ask(visitor, session_id) == 502

    assert (await visitor.get("/auth/me")).json()["questions_left"] == 3


async def test_a_question_is_graded_once(visitor: AsyncClient, model: Interviews) -> None:
    await sign_in(visitor)
    session_id = await start(visitor)
    question_id = (await visitor.post(f"/sessions/{session_id}/questions")).json()["question_id"]
    body = {"question_id": question_id, "answer": "A mutex."}

    first = await visitor.post(f"/sessions/{session_id}/answers", json=body)
    again = await visitor.post(f"/sessions/{session_id}/answers", json=body)

    assert [first.status_code, again.status_code] == [200, 409]
    assert model.graded == 1


async def test_the_owner_is_never_counted(visitor: AsyncClient) -> None:
    await sign_in(visitor, "owner", email=OWNER_EMAIL)
    session_id = await start(visitor)

    statuses = [await ask(visitor, session_id) for _ in range(8)]

    assert statuses == [201] * 8
    assert (await visitor.get("/auth/me")).json()["questions_left"] is None


async def test_the_owner_needs_a_verified_email(visitor: AsyncClient) -> None:
    # The provider withholds an address it has not verified.
    await sign_in(visitor, "owner")

    assert (await visitor.get("/auth/me")).json()["questions_left"] == 3
