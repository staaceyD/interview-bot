from collections.abc import Mapping
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status

from interview_bot.auth import User, current_user
from interview_bot.config import Settings
from interview_bot.explainer import Explainer
from interview_bot.interviewer import Interviewer
from interview_bot.llm import LLMClient
from interview_bot.quota import Quota
from interview_bot.store import SessionStore


def get_settings(request: Request) -> Settings:
    """The settings this app was built with, which a test may have replaced."""
    return request.app.state.settings


def get_llm_clients(request: Request) -> Mapping[str, LLMClient]:
    return request.app.state.llm_clients


def get_interviewers(request: Request) -> Mapping[str, Interviewer]:
    return request.app.state.interviewers


def get_session_store(request: Request) -> SessionStore:
    return request.app.state.session_store


def get_explainer(request: Request) -> Explainer:
    return request.app.state.explainer


def get_quota(request: Request) -> Quota:
    return request.app.state.quota


def get_signed_in_user(request: Request) -> User | None:
    return current_user(request)


def get_viewer(
    request: Request, user: Annotated[User | None, Depends(get_signed_in_user)]
) -> User | None:
    """Whoever is making an interview request: required where sign-in is."""
    if user is None and request.app.state.settings.sign_in_required:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Sign in to start an interview")
    return user


LLMClientsDep = Annotated[Mapping[str, LLMClient], Depends(get_llm_clients)]
InterviewersDep = Annotated[Mapping[str, Interviewer], Depends(get_interviewers)]
SessionStoreDep = Annotated[SessionStore, Depends(get_session_store)]
ExplainerDep = Annotated[Explainer, Depends(get_explainer)]
SettingsDep = Annotated[Settings, Depends(get_settings)]
QuotaDep = Annotated[Quota, Depends(get_quota)]
SignedInUserDep = Annotated[User | None, Depends(get_signed_in_user)]
ViewerDep = Annotated[User | None, Depends(get_viewer)]
