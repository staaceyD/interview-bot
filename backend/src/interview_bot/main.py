import secrets
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from interview_bot.api import router
from interview_bot.auth import IdentityProvider, build_identity_providers
from interview_bot.auth import router as auth_router
from interview_bot.config import Settings, get_settings
from interview_bot.explainer import Explainer
from interview_bot.interviewer import Interviewer
from interview_bot.llm import LLMClient, LLMError, build_llm_clients
from interview_bot.quota import Quota
from interview_bot.store import SessionStore, build_session_store


def create_app(
    settings: Settings | None = None,
    llm_client: LLMClient | None = None,
    session_store: SessionStore | None = None,
    identity_providers: Mapping[str, IdentityProvider] | None = None,
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
        app.state.quota = Quota(
            app.state.session_store,
            per_user=settings.daily_question_limit,
            total=settings.daily_question_limit_total,
            unlimited_emails=settings.unlimited_emails,
        )
        app.state.explainer = Explainer(
            app.state.session_store,
            prefetch=settings.prefetch_explanations,
        )
        try:
            yield
        finally:
            await app.state.explainer.aclose()
            for client in dict.fromkeys(app.state.llm_clients.values()):
                await client.aclose()
            await app.state.session_store.aclose()

    app = FastAPI(title="Interview Bot", version="0.1.0", lifespan=lifespan)
    app.state.settings = settings
    app.state.identity_providers = (
        identity_providers if identity_providers is not None else build_identity_providers(settings)
    )

    app.add_middleware(
        SessionMiddleware,
        secret_key=(
            settings.session_secret.get_secret_value()
            if settings.session_secret
            else secrets.token_urlsafe(32)
        ),
        session_cookie="interview_bot_session",
        max_age=settings.session_max_age_seconds,
        # Lax: sent when a provider redirects back here, never on a cross-site
        # POST, which is what keeps another site from acting as the visitor.
        same_site="lax",
        https_only=settings.environment == "production",
    )
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
    app.include_router(auth_router)
    if settings.static_dir is not None:
        app.mount("/", StaticFiles(directory=settings.static_dir, html=True), name="frontend")
    return app


app = create_app()
