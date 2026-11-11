"""The hosted deployment, which runs on Claude alone."""

from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from interview_bot.config import Settings
from interview_bot.llm.echo import EchoClient
from interview_bot.main import create_app
from interview_bot.store import InMemorySessionStore


@pytest.fixture
def settings() -> Settings:
    return Settings(environment="production", prefetch_explanations=False)


def test_production_runs_on_claude_whatever_the_default_says() -> None:
    settings = Settings(environment="production", default_model_provider="ollama")

    assert settings.default_model_provider == "anthropic"
    assert settings.model_providers == ("anthropic",)


def test_development_offers_every_provider() -> None:
    assert Settings().model_providers == ("ollama", "anthropic", "echo")


async def test_health_offers_nothing_to_switch_to(api: AsyncClient) -> None:
    response = await api.get("/health")

    offered = [entry["model_provider"] for entry in response.json()["available"]]

    assert offered == ["anthropic"]


async def test_a_session_starts_on_claude(api: AsyncClient) -> None:
    response = await api.post("/sessions", json={"topics": ["python"]})

    assert response.json()["model_provider"] == "anthropic"


async def test_a_session_cannot_start_on_ollama(api: AsyncClient) -> None:
    response = await api.post("/sessions", json={"topics": ["python"], "model_provider": "ollama"})

    assert response.status_code == 503


async def test_a_session_cannot_switch_to_ollama(api: AsyncClient) -> None:
    session_id = (await api.post("/sessions", json={"topics": ["python"]})).json()["session_id"]

    switched = await api.patch(f"/sessions/{session_id}", json={"model_provider": "ollama"})

    assert switched.status_code == 503
    assert (await api.get(f"/sessions/{session_id}")).json()["model_provider"] == "anthropic"


async def test_serves_the_frontend_next_to_the_api(tmp_path: Path) -> None:
    (tmp_path / "index.html").write_text("<h1>Interview Bot</h1>")
    settings = Settings(environment="production", static_dir=tmp_path)
    app = create_app(
        settings=settings, llm_client=EchoClient(), session_store=InMemorySessionStore()
    )

    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client,
    ):
        page = await client.get("/")
        health = await client.get("/health")

    assert "Interview Bot" in page.text
    assert health.json()["status"] == "ok"
