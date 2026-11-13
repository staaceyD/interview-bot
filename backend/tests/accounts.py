"""Signed-in visitors for the sign-in, ownership and daily-limit tests."""

import asyncio
from collections.abc import AsyncIterator

from httpx import ASGITransport, AsyncClient
from starlette.requests import Request
from starlette.responses import RedirectResponse, Response

from interview_bot.auth import SignInFailed, User
from interview_bot.config import Settings
from interview_bot.llm import LLMError
from interview_bot.llm.echo import EchoClient
from interview_bot.main import create_app
from interview_bot.prompts import GENERATE_SYSTEM
from interview_bot.store import InMemorySessionStore
from replies import grade_reply, question_reply

OWNER_EMAIL = "owner@example.com"


def sign_in_settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "sign_in_required": True,
        "session_secret": "test-secret",
        "github_client_id": "id",
        "github_client_secret": "secret",
        "daily_question_limit": 3,
        "daily_question_limit_total": 5,
        "unlimited_emails": [OWNER_EMAIL],
        "default_model_provider": "echo",
        "prefetch_explanations": False,
    }
    return Settings(**(values | overrides))


class FakeProvider:
    """Signs in as whoever the login link names, so a test can be anyone."""

    name = "github"

    async def login_redirect(self, request: Request, redirect_uri: str) -> Response:
        return RedirectResponse(f"{redirect_uri}?{request.url.query}")

    async def identify(self, request: Request) -> User:
        who = request.query_params.get("as")
        if not who:
            raise SignInFailed("no account")
        return User(id=f"github:{who}", name=who, email=request.query_params.get("email"))


class Interviews(EchoClient):
    """A model that writes a fresh question every time, and grades whatever it is sent."""

    def __init__(self) -> None:
        super().__init__()
        self.asked = 0
        self.graded = 0
        self.fail = False

    async def complete(self, *, system: str, prompt: str, **kwargs: object) -> str:
        # A real model takes seconds to answer, and other requests run meanwhile.
        await asyncio.sleep(0.01)
        if self.fail:
            raise LLMError("down")
        if system == GENERATE_SYSTEM:
            self.asked += 1
            return question_reply(f"Question {self.asked}?")
        self.graded += 1
        return grade_reply()


def build_app(settings: Settings, model: Interviews):
    return create_app(
        settings=settings,
        llm_client=model,
        session_store=InMemorySessionStore(),
        identity_providers={"github": FakeProvider()},
    )


async def browser(app) -> AsyncIterator[AsyncClient]:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client


async def sign_in(client: AsyncClient, who: str = "ada", email: str | None = None) -> None:
    query = f"as={who}" + (f"&email={email}" if email else "")
    response = await client.get(f"/auth/github/login?{query}", follow_redirects=True)
    assert response.url.path == "/"


async def start(client: AsyncClient) -> str:
    response = await client.post("/sessions", json={"topics": ["python"]})
    assert response.status_code == 201, response.text
    return response.json()["session_id"]


async def ask(client: AsyncClient, session_id: str) -> int:
    return (await client.post(f"/sessions/{session_id}/questions")).status_code
