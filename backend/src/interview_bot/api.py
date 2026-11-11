from collections.abc import Mapping

from fastapi import APIRouter, HTTPException, status

from interview_bot.deps import (
    ExplainerDep,
    InterviewersDep,
    LLMClientsDep,
    SessionStoreDep,
    SettingsDep,
)
from interview_bot.domain import Explanation, Grade, Question
from interview_bot.interviewer import Interviewer
from interview_bot.rotation import next_topic
from interview_bot.schemas import (
    AnswerRequest,
    HealthResponse,
    LLMInfo,
    QuestionResponse,
    SessionResponse,
    SessionStateResponse,
    StartSessionRequest,
    SwitchModelRequest,
)
from interview_bot.store import Session, SessionStore

router = APIRouter()


async def _require_session(store: SessionStore, session_id: str) -> Session:
    session = await store.get(session_id)
    if session is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown session")
    return session


def _require_question(session: Session, question_id: str) -> Question:
    question = session.questions.get(question_id)
    if question is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown question for this session")
    return question


def _interviewer_for(model_provider: str, interviewers: Mapping[str, Interviewer]) -> Interviewer:
    """The interviewer running one named model."""
    interviewer = interviewers.get(model_provider)
    if interviewer is None:
        # A provider this environment does not run, or one a stored session
        # was on before it was removed.
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            f"The {model_provider} model is not configured",
        )
    return interviewer


def _as_response(question: Question) -> QuestionResponse:
    return QuestionResponse(
        question_id=question.id,
        prompt=question.prompt,
        topic=question.topic,
        difficulty=question.difficulty,
    )


def _as_session(session: Session) -> SessionResponse:
    return SessionResponse(
        session_id=session.id,
        topics=session.topics,
        difficulty=session.difficulty,
        model_provider=session.model_provider,
    )


@router.get("/health")
async def health(clients: LLMClientsDep, settings: SettingsDep) -> HealthResponse:
    default = clients[settings.default_model_provider]
    return HealthResponse(
        status="ok",
        llm=LLMInfo(model_provider=default.name, model=default.model),
        available=[
            LLMInfo(model_provider=model_provider, model=client.model)
            for model_provider, client in clients.items()
        ],
    )


@router.post("/sessions", status_code=status.HTTP_201_CREATED)
async def start_session(
    body: StartSessionRequest,
    store: SessionStoreDep,
    interviewers: InterviewersDep,
    settings: SettingsDep,
) -> SessionResponse:
    model_provider = body.model_provider or settings.default_model_provider
    # Refused up front, so an interview never starts on a model this deployment
    # does not run.
    _interviewer_for(model_provider, interviewers)
    session = await store.create(
        topics=body.topics,
        difficulty=body.difficulty,
        model_provider=model_provider,
    )
    return _as_session(session)


@router.get("/sessions/{session_id}")
async def resume_session(session_id: str, store: SessionStoreDep) -> SessionStateResponse:
    session = await _require_session(store, session_id)
    current = session.latest_question
    return SessionStateResponse(
        session_id=session.id,
        topics=session.topics,
        difficulty=session.difficulty,
        model_provider=session.model_provider,
        current_question=_as_response(current) if current else None,
        current_grade=session.latest_grade,
        current_explanation=session.latest_explanation,
    )


@router.patch("/sessions/{session_id}")
async def switch_model(
    session_id: str,
    body: SwitchModelRequest,
    store: SessionStoreDep,
    interviewers: InterviewersDep,
    explainer: ExplainerDep,
) -> SessionResponse:
    """Move an interview onto another model, from the next question onwards."""
    session = await _require_session(store, session_id)
    if body.model_provider == session.model_provider:
        return _as_session(session)

    # Checked before anything is stored, so a session is never left pointing at
    # a model that cannot answer it.
    _interviewer_for(body.model_provider, interviewers)

    await store.set_model_provider(session.id, body.model_provider)
    # The worked answer being written ahead is the old model's, and nobody has
    # asked for it yet, so it is dropped rather than served as the new one's.
    await explainer.forget(session.id)

    session.model_provider = body.model_provider
    return _as_session(session)


@router.post("/sessions/{session_id}/questions", status_code=status.HTTP_201_CREATED)
async def next_question(
    session_id: str,
    store: SessionStoreDep,
    interviewers: InterviewersDep,
    explainer: ExplainerDep,
) -> QuestionResponse:
    session = await _require_session(store, session_id)
    interviewer = _interviewer_for(session.model_provider, interviewers)

    async with explainer.foreground():
        question = await interviewer.generate_question(
            # Shuffled across the session's topics, so a mixed interview jumps
            # between them instead of working through one at a time.
            topic=next_topic(session.topics, session.asked_topics),
            difficulty=session.difficulty,
            avoid=session.asked_prompts,
        )
    await store.add_question(session.id, question)

    # The model is free now and stays free while the question is answered
    explainer.prefetch(session.id, question, interviewer)
    return _as_response(question)


@router.post("/sessions/{session_id}/answers")
async def submit_answer(
    session_id: str,
    body: AnswerRequest,
    store: SessionStoreDep,
    interviewers: InterviewersDep,
    explainer: ExplainerDep,
) -> Grade:
    session = await _require_session(store, session_id)
    question = _require_question(session, body.question_id)
    interviewer = _interviewer_for(session.model_provider, interviewers)

    async with explainer.foreground():
        grade = await interviewer.grade(question=question, answer=body.answer)
    await store.record_grade(session.id, question.id, grade)

    # Picked up again in case answering interrupted it, or the API restarted
    # between the question and the answer.
    explainer.prefetch(session.id, question, interviewer)
    return grade


@router.post("/sessions/{session_id}/questions/{question_id}/explanation")
async def explain_question(
    session_id: str,
    question_id: str,
    store: SessionStoreDep,
    interviewers: InterviewersDep,
    explainer: ExplainerDep,
) -> Explanation:
    session = await _require_session(store, session_id)
    question = _require_question(session, question_id)

    if question_id not in session.grades:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "Answer the question before reading the explanation"
        )

    explained = session.explanations.get(question_id)
    if explained is not None:
        return explained

    # Written ahead while the question was being answered, in which case this
    # returns as fast as the store can hand it over.
    return await explainer.explain(
        session.id, question, _interviewer_for(session.model_provider, interviewers)
    )
