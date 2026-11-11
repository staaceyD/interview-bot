from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from interview_bot.api import router
from interview_bot.config import Settings, get_settings
from interview_bot.explainer import Explainer
from interview_bot.interviewer import Interviewer
from interview_bot.llm import LLMClient, LLMError, build_llm_clients
from interview_bot.store import SessionStore, build_session_store


def create_app(
    settings: Settings | None = None,
    llm_client: LLMClient | None = None,
    session_store: SessionStore | None = None,
) -> FastAPI:
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        # An injected client stands in for every provider, so a test can pick
        # any of them and still be talking to the one it set up.
        app.state.llm_clients = (
            {provider: llm_client for provider in settings.model_providers}
            if llm_client
            else build_llm_clients(settings)
        )
        app.state.interviewers = {
            provider: Interviewer(
                client, explain_timeout_seconds=settings.llm_explain_timeout_seconds
            )
            for provider, client in app.state.llm_clients.items()
        }
        app.state.session_store = session_store or build_session_store(settings)
        await app.state.session_store.initialize()
        app.state.explainer = Explainer(
            app.state.session_store,
            prefetch=settings.prefetch_explanations,
        )
        try:
            yield
        finally:
            await app.state.explainer.aclose()
            # dict.fromkeys drops the duplicates an injected client leaves behind.
            for client in dict.fromkeys(app.state.llm_clients.values()):
                await client.aclose()
            await app.state.session_store.aclose()

    app = FastAPI(title="Interview Bot", version="0.1.0", lifespan=lifespan)
    # Read back by the request handlers, so they see the settings this app was
    # built with rather than the process-wide ones.
    app.state.settings = settings
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.exception_handler(LLMError)
    async def handle_llm_error(request: Request, exc: LLMError) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_502_BAD_GATEWAY,
            content={"detail": f"The model is unavailable: {exc}"},
        )

    app.include_router(router)
    if settings.static_dir is not None:
        # Mounted last, so the API routes are matched before the catch-all.
        app.mount("/", StaticFiles(directory=settings.static_dir, html=True), name="frontend")
    return app


app = create_app()
