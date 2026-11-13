"""Signing in, and interviews that belong to whoever started them."""

from contextlib import asynccontextmanager

import httpx2
import pytest
from httpx import AsyncClient

from accounts import Interviews, browser, build_app, sign_in, sign_in_settings, start
from interview_bot.auth import GitHubProvider, GoogleProvider, SignInFailed, primary_verified_email
from interview_bot.config import Settings


@pytest.fixture
def model() -> Interviews:
    return Interviews()


@pytest.fixture
def app(model: Interviews):
    return build_app(sign_in_settings(), model)


@pytest.fixture
async def visitor(app):
    async with app.router.lifespan_context(app):
        async for client in browser(app):
            yield client


@asynccontextmanager
async def another_visitor(app):
    async for client in browser(app):
        yield client


def test_sign_in_needs_a_session_secret() -> None:
    with pytest.raises(ValueError, match="SESSION_SECRET"):
        Settings(sign_in_required=True)


def test_a_production_deployment_always_requires_sign_in() -> None:
    settings = Settings(environment="production", session_secret="s", sign_in_required=False)

    assert settings.sign_in_required


def test_only_providers_with_both_halves_are_offered() -> None:
    settings = Settings(google_client_id="id", github_client_id="id", github_client_secret="s")

    assert settings.sign_in_providers == ["github"]


async def test_a_visitor_starts_signed_out(visitor: AsyncClient) -> None:
    response = await visitor.get("/auth/me")

    assert response.json() == {
        "sign_in_required": True,
        "providers": ["github"],
        "user": None,
        "questions_left": None,
    }


async def test_signing_in_keeps_the_visitor_signed_in(visitor: AsyncClient) -> None:
    await sign_in(visitor, "ada", email="ada@example.com")

    me = (await visitor.get("/auth/me")).json()

    assert me["user"] == {"name": "ada", "email": "ada@example.com"}
    assert me["questions_left"] == 3


async def test_the_cookie_is_httponly_and_lax(visitor: AsyncClient) -> None:
    login = await visitor.get("/auth/github/login?as=ada", follow_redirects=False)
    callback = await visitor.get(login.headers["location"], follow_redirects=False)

    cookie = callback.headers["set-cookie"].lower()
    assert "httponly" in cookie
    assert "samesite=lax" in cookie


async def test_a_failed_sign_in_comes_back_signed_out(visitor: AsyncClient) -> None:
    response = await visitor.get("/auth/github/login", follow_redirects=True)

    assert response.url.query == b"sign_in=failed"
    assert (await visitor.get("/auth/me")).json()["user"] is None


async def test_an_unknown_provider_is_a_404(visitor: AsyncClient) -> None:
    assert (await visitor.get("/auth/myspace/login")).status_code == 404


async def test_signing_out_ends_it(visitor: AsyncClient) -> None:
    await sign_in(visitor)

    assert (await visitor.post("/auth/logout")).status_code == 204

    assert (await visitor.get("/auth/me")).json()["user"] is None
    assert (await visitor.post("/sessions", json={"topics": ["python"]})).status_code == 401


async def test_a_forged_cookie_is_signed_out(visitor: AsyncClient) -> None:
    visitor.cookies.set("interview_bot_session", "eyJ1c2VyIjogeyJpZCI6ICJ4In19.forged")

    assert (await visitor.get("/auth/me")).json()["user"] is None


def test_github_email_is_the_primary_verified_one() -> None:
    emails = [
        {"email": "old@example.com", "primary": False, "verified": True},
        {"email": "main@example.com", "primary": True, "verified": True},
    ]

    assert primary_verified_email(emails) == "main@example.com"


def test_an_unverified_github_email_is_none() -> None:
    emails = [{"email": "owner@example.com", "primary": True, "verified": False}]

    assert primary_verified_email(emails) is None


class Unreachable:
    """An OAuth client whose provider cannot be reached."""

    async def authorize_access_token(self, request: object) -> dict:
        raise httpx2.ConnectError("provider unreachable")


@pytest.mark.parametrize("provider_class", [GoogleProvider, GitHubProvider])
async def test_a_provider_that_cannot_be_reached_is_a_failed_sign_in(provider_class) -> None:
    provider = provider_class.__new__(provider_class)
    provider._client = Unreachable()

    with pytest.raises(SignInFailed):
        await provider.identify(request=None)


async def test_an_interview_cannot_start_signed_out(
    visitor: AsyncClient, model: Interviews
) -> None:
    response = await visitor.post("/sessions", json={"topics": ["python"]})

    assert response.status_code == 401
    assert model.asked == 0


async def test_someone_elses_interview_does_not_exist(app, visitor: AsyncClient) -> None:
    await sign_in(visitor, "ada")
    session_id = await start(visitor)
    question_id = (await visitor.post(f"/sessions/{session_id}/questions")).json()["question_id"]

    async with another_visitor(app) as other:
        await sign_in(other, "grace")
        statuses = [
            (await other.get(f"/sessions/{session_id}")).status_code,
            (await other.post(f"/sessions/{session_id}/questions")).status_code,
            (
                await other.post(
                    f"/sessions/{session_id}/answers",
                    json={"question_id": question_id, "answer": "x"},
                )
            ).status_code,
        ]

    assert statuses == [404, 404, 404]
