"""The hosted deployment: Claude alone, behind sign-in and a daily question limit."""

import asyncio
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient
from starlette.requests import Request
from starlette.responses import RedirectResponse, Response

from interview_bot.auth import SignInFailed, User, primary_verified_email
from interview_bot.config import Settings
from interview_bot.llm import LLMError
from interview_bot.llm.echo import EchoClient
from interview_bot.main import create_app
from interview_bot.prompts import GENERATE_SYSTEM
from interview_bot.store import InMemorySessionStore
from replies import grade_reply, question_reply

OWNER_EMAIL = "owner@example.com"


class FakeProvider:
    """Signs in as whoever the login link names, so a test can be anyone."""

    name = "github"

    async def login_redirect(self, request: Request, redirect_uri: str) -> Response:
        return RedirectResponse(f"{redirect_uri}?{request.url.query}")

    async def identify(self, request: Request) -> User:
        who = request.query_params.get("as")
        if not who:
            raise SignInFailed("no account")
        email = request.query_params.get("email")
        return User(id=f"github:{who}", name=who, email=email)


class Interviews(EchoClient):
    """A model that always writes a fresh question, and grades whatever it is sent."""

    def __init__(self) -> None:
        super().__init__(model="claude-haiku-4-5")
        self.asked = 0
        self.fail = False

    async def complete(self, *, system: str, prompt: str, **kwargs: object) -> str:
        if self.fail:
            raise LLMError("down")
        if system == GENERATE_SYSTEM:
            self.asked += 1
            return question_reply(f"Question {self.asked}?")
        return grade_reply()


@pytest.fixture
def settings() -> Settings:
    return Settings(
        environment="production",
        session_secret="test-secret",
        github_client_id="id",
        github_client_secret="secret",
        daily_question_limit=3,
        daily_question_limit_total=5,
        unlimited_emails=[OWNER_EMAIL],
        prefetch_explanations=False,
    )


@pytest.fixture
def model() -> Interviews:
    return Interviews()


@pytest.fixture
def app(settings: Settings, model: Interviews):
    return create_app(
        settings=settings,
        llm_client=model,
        session_store=InMemorySessionStore(),
        identity_providers={"github": FakeProvider()},
    )


@pytest.fixture
async def visitor(app):
    """A browser: it keeps its cookies, over https, as the real one would."""
    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=ASGITransport(app=app), base_url="https://test") as client,
    ):
        yield client


async def browser(app) -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="https://test")


async def sign_in(client: AsyncClient, who: str = "ada", email: str | None = None) -> None:
    query = f"as={who}" + (f"&email={email}" if email else "")
    response = await client.get(f"/auth/github/login?{query}", follow_redirects=True)
    assert response.url.path == "/"


async def start(client: AsyncClient) -> str:
    response = await client.post("/sessions", json={"topics": ["python"]})
    assert response.status_code == 201, response.text
    return response.json()["session_id"]


# Settings


def test_production_runs_on_claude_whatever_the_default_says() -> None:
    settings = Settings(
        environment="production", session_secret="s", default_model_provider="ollama"
    )

    assert settings.default_model_provider == "anthropic"
    assert settings.model_providers == ("anthropic",)
    assert settings.sign_in_required


def test_production_will_not_start_without_a_session_secret() -> None:
    with pytest.raises(ValueError, match="SESSION_SECRET"):
        Settings(environment="production")


def test_only_providers_with_both_halves_are_offered() -> None:
    settings = Settings(google_client_id="id", github_client_id="id", github_client_secret="s")

    assert settings.sign_in_providers == ["github"]


def test_development_needs_no_sign_in() -> None:
    assert not Settings().sign_in_required


# Signing in


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


async def test_the_cookie_is_httponly_secure_and_lax(visitor: AsyncClient) -> None:
    response = await visitor.get("/auth/github/login?as=ada", follow_redirects=False)
    callback = await visitor.get(response.headers["location"], follow_redirects=False)

    cookie = callback.headers["set-cookie"].lower()
    assert "httponly" in cookie
    assert "secure" in cookie
    assert "samesite=lax" in cookie


async def test_a_failed_sign_in_comes_back_signed_out(visitor: AsyncClient) -> None:
    response = await visitor.get("/auth/github/login", follow_redirects=True)

    assert response.url.query == b"sign_in=failed"
    assert (await visitor.get("/auth/me")).json()["user"] is None


async def test_an_unknown_provider_is_a_404(visitor: AsyncClient) -> None:
    response = await visitor.get("/auth/myspace/login")

    assert response.status_code == 404


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


# Interviews need a signed-in visitor, and belong to them


async def test_an_interview_cannot_start_signed_out(
    visitor: AsyncClient, model: Interviews
) -> None:
    response = await visitor.post("/sessions", json={"topics": ["python"]})

    assert response.status_code == 401
    assert response.json()["detail"] == "Sign in to start an interview"
    assert model.asked == 0


async def test_a_signed_in_visitor_runs_an_interview_on_claude(visitor: AsyncClient) -> None:
    await sign_in(visitor)
    session_id = await start(visitor)

    question = await visitor.post(f"/sessions/{session_id}/questions")
    answer = await visitor.post(
        f"/sessions/{session_id}/answers",
        json={"question_id": question.json()["question_id"], "answer": "A mutex."},
    )

    assert question.status_code == 201
    assert answer.status_code == 200
    assert (await visitor.get(f"/sessions/{session_id}")).json()["model_provider"] == "anthropic"


async def test_someone_elses_interview_does_not_exist(app, visitor: AsyncClient) -> None:
    await sign_in(visitor, "ada")
    session_id = await start(visitor)
    question_id = (await visitor.post(f"/sessions/{session_id}/questions")).json()["question_id"]

    async with await browser(app) as other:
        await sign_in(other, "grace")
        resumed = await other.get(f"/sessions/{session_id}")
        asked = await other.post(f"/sessions/{session_id}/questions")
        answered = await other.post(
            f"/sessions/{session_id}/answers", json={"question_id": question_id, "answer": "x"}
        )

    assert [resumed.status_code, asked.status_code, answered.status_code] == [404, 404, 404]


async def test_a_question_is_graded_once(visitor: AsyncClient, model: Interviews) -> None:
    await sign_in(visitor)
    session_id = await start(visitor)
    question_id = (await visitor.post(f"/sessions/{session_id}/questions")).json()["question_id"]
    body = {"question_id": question_id, "answer": "A mutex."}

    first = await visitor.post(f"/sessions/{session_id}/answers", json=body)
    again = await visitor.post(f"/sessions/{session_id}/answers", json=body)

    assert first.status_code == 200
    assert again.status_code == 409


async def test_a_session_cannot_start_on_ollama(visitor: AsyncClient) -> None:
    await sign_in(visitor)

    response = await visitor.post(
        "/sessions", json={"topics": ["python"], "model_provider": "ollama"}
    )

    assert response.status_code == 503


async def test_health_offers_nothing_to_switch_to(visitor: AsyncClient) -> None:
    offered = [
        entry["model_provider"] for entry in (await visitor.get("/health")).json()["available"]
    ]

    assert offered == ["anthropic"]


# The daily limits


async def ask(client: AsyncClient, session_id: str) -> int:
    return (await client.post(f"/sessions/{session_id}/questions")).status_code


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

    async with await browser(app) as other:
        await sign_in(other, "grace")
        grace = await start(other)
        statuses = [await ask(other, grace) for _ in range(3)]
        refused = await other.post(f"/sessions/{grace}/questions")

    # Five between them, though Grace had three of her own.
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


async def test_the_owner_is_never_counted(visitor: AsyncClient, model: Interviews) -> None:
    await sign_in(visitor, "owner", email=OWNER_EMAIL)
    session_id = await start(visitor)

    statuses = [await ask(visitor, session_id) for _ in range(8)]

    assert statuses == [201] * 8
    assert (await visitor.get("/auth/me")).json()["questions_left"] is None


async def test_the_owner_needs_a_verified_email(visitor: AsyncClient) -> None:
    # The provider withheld the address because it is unverified.
    await sign_in(visitor, "owner")

    assert (await visitor.get("/auth/me")).json()["questions_left"] == 3


# Serving


async def test_serves_the_frontend_next_to_the_api(tmp_path: Path) -> None:
    (tmp_path / "index.html").write_text("<h1>Interview Bot</h1>")
    settings = Settings(environment="production", session_secret="s", static_dir=tmp_path)
    app = create_app(
        settings=settings, llm_client=EchoClient(), session_store=InMemorySessionStore()
    )

    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=ASGITransport(app=app), base_url="https://test") as client,
    ):
        page = await client.get("/")
        health = await client.get("/health")

    assert "Interview Bot" in page.text
    assert health.json()["status"] == "ok"
