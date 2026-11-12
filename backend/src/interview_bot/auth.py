"""Signing in with Google or GitHub, over OAuth 2.0 with PKCE.

Nothing here stores a password or a provider's access token. The token is used
once, during the callback, to learn who signed in, and only that identity is
kept: in a signed, httpOnly cookie the browser cannot read or alter.
"""

from dataclasses import asdict, dataclass
from typing import Any, Protocol

import httpx2
from authlib.integrations.starlette_client import OAuth, OAuthError
from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import RedirectResponse
from starlette.responses import Response

from interview_bot.config import Settings, SignInProvider

SESSION_USER = "user"

# A provider that cannot be reached is a sign-in that did not finish, not a 500.
_SIGN_IN_ERRORS = (OAuthError, httpx2.HTTPError)


@dataclass(frozen=True)
class User:
    # Namespaced by provider, so a Google and a GitHub account never collide.
    id: str
    name: str
    email: str | None


class SignInFailed(Exception):
    """The provider sent the visitor back without a usable identity."""


class IdentityProvider(Protocol):
    name: SignInProvider

    async def login_redirect(self, request: Request, redirect_uri: str) -> Response: ...

    async def identify(self, request: Request) -> User:
        """The visitor the provider has just sent back, from the callback request."""
        ...


class GoogleProvider:
    name: SignInProvider = "google"

    def __init__(self, oauth: OAuth, *, client_id: str, client_secret: str) -> None:
        self._client = oauth.register(
            name="google",
            client_id=client_id,
            client_secret=client_secret,
            server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
            client_kwargs={"scope": "openid email profile", "code_challenge_method": "S256"},
        )

    async def login_redirect(self, request: Request, redirect_uri: str) -> Response:
        return await self._client.authorize_redirect(request, redirect_uri)

    async def identify(self, request: Request) -> User:
        try:
            token = await self._client.authorize_access_token(request)
        except _SIGN_IN_ERRORS as exc:
            raise SignInFailed(str(exc)) from exc
        claims = token.get("userinfo") or {}
        if "sub" not in claims:
            raise SignInFailed("Google sent no account id")
        return User(
            id=f"google:{claims['sub']}",
            name=claims.get("name") or claims.get("email") or "Google user",
            email=claims.get("email") if claims.get("email_verified") else None,
        )


class GitHubProvider:
    name: SignInProvider = "github"

    def __init__(self, oauth: OAuth, *, client_id: str, client_secret: str) -> None:
        self._client = oauth.register(
            name="github",
            client_id=client_id,
            client_secret=client_secret,
            authorize_url="https://github.com/login/oauth/authorize",
            access_token_url="https://github.com/login/oauth/access_token",
            api_base_url="https://api.github.com/",
            client_kwargs={"scope": "read:user user:email", "code_challenge_method": "S256"},
        )

    async def login_redirect(self, request: Request, redirect_uri: str) -> Response:
        return await self._client.authorize_redirect(request, redirect_uri)

    async def identify(self, request: Request) -> User:
        try:
            token = await self._client.authorize_access_token(request)
            profile = (await self._client.get("user", token=token)).json()
            emails = (await self._client.get("user/emails", token=token)).json()
        except _SIGN_IN_ERRORS as exc:
            raise SignInFailed(str(exc)) from exc
        if "id" not in profile:
            raise SignInFailed("GitHub sent no account id")
        return User(
            id=f"github:{profile['id']}",
            name=profile.get("name") or profile.get("login") or "GitHub user",
            email=primary_verified_email(emails),
        )


def primary_verified_email(emails: Any) -> str | None:
    """The address GitHub calls primary, if GitHub has verified it."""
    if not isinstance(emails, list):
        return None
    for entry in emails:
        if isinstance(entry, dict) and entry.get("primary") and entry.get("verified"):
            return entry.get("email")
    return None


def build_identity_providers(settings: Settings) -> dict[str, IdentityProvider]:
    oauth = OAuth()
    providers: dict[str, IdentityProvider] = {}
    for name in settings.sign_in_providers:
        if name == "google":
            assert settings.google_client_id and settings.google_client_secret
            providers[name] = GoogleProvider(
                oauth,
                client_id=settings.google_client_id,
                client_secret=settings.google_client_secret.get_secret_value(),
            )
        elif name == "github":
            assert settings.github_client_id and settings.github_client_secret
            providers[name] = GitHubProvider(
                oauth,
                client_id=settings.github_client_id,
                client_secret=settings.github_client_secret.get_secret_value(),
            )
    return providers


def current_user(request: Request) -> User | None:
    stored = request.session.get(SESSION_USER)
    if not isinstance(stored, dict):
        return None
    try:
        return User(**stored)
    except TypeError:
        return None


router = APIRouter(prefix="/auth")


def _provider(request: Request, name: str) -> IdentityProvider:
    provider = request.app.state.identity_providers.get(name)
    if provider is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown sign-in provider")
    return provider


@router.get("/{provider}/login")
async def login(provider: str, request: Request) -> Response:
    chosen = _provider(request, provider)
    redirect_uri = str(request.url_for("auth_callback", provider=chosen.name))
    return await chosen.login_redirect(request, redirect_uri)


@router.get("/{provider}/callback", name="auth_callback")
async def callback(provider: str, request: Request) -> Response:
    chosen = _provider(request, provider)
    try:
        user = await chosen.identify(request)
    except SignInFailed:
        return RedirectResponse("/?sign_in=failed", status_code=status.HTTP_303_SEE_OTHER)
    request.session.clear()
    request.session[SESSION_USER] = asdict(user)
    return RedirectResponse("/", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(request: Request) -> None:
    request.session.clear()
