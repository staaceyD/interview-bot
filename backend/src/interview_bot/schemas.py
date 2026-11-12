from typing import Annotated

from pydantic import AfterValidator, BaseModel, Field

from interview_bot.config import ModelProvider, SignInProvider
from interview_bot.domain import Difficulty, Explanation, Grade, Topic


def _non_blank(value: str) -> str:
    stripped = value.strip()
    if not stripped:
        raise ValueError("must not be blank")
    return stripped


Answer = Annotated[str, Field(max_length=5000), AfterValidator(_non_blank)]


def _deduplicated(topics: list[Topic]) -> list[Topic]:
    """The same topic twice would only weight the rotation towards it."""
    return list(dict.fromkeys(topics))


# One topic is an interview about it; several make a mixed interview, with the
# questions rotating over them.
Topics = Annotated[list[Topic], Field(min_length=1), AfterValidator(_deduplicated)]


class StartSessionRequest(BaseModel):
    topics: Topics
    difficulty: Difficulty = Difficulty.MID
    model_provider: ModelProvider | None = None


class SwitchModelRequest(BaseModel):
    model_provider: ModelProvider


class SessionResponse(BaseModel):
    session_id: str
    topics: list[Topic]
    difficulty: Difficulty
    model_provider: str


class QuestionResponse(BaseModel):
    """Deliberately without key_points, so the client cannot read the answer."""

    question_id: str
    prompt: str
    topic: Topic
    difficulty: Difficulty


class SessionStateResponse(BaseModel):
    session_id: str
    topics: list[Topic]
    difficulty: Difficulty
    model_provider: str
    current_question: QuestionResponse | None
    # Set when the current question was already answered, so a resume shows the
    # grade the candidate has already seen instead of asking again.
    current_grade: Grade | None
    # Set once the worked answer has been read, so a refresh does not spend
    # another wait on the model to show it again.
    current_explanation: Explanation | None


class AnswerRequest(BaseModel):
    question_id: str
    answer: Answer


class LLMInfo(BaseModel):
    model_provider: str
    model: str


class HealthResponse(BaseModel):
    status: str
    llm: LLMInfo
    available: list[LLMInfo]


class UserResponse(BaseModel):
    name: str
    email: str | None


class AccountResponse(BaseModel):
    sign_in_required: bool
    # The providers to offer buttons for, in order.
    providers: list[SignInProvider]
    user: UserResponse | None
    # None when the visitor is not counted: signed out, unlimited, or running
    # somewhere sign-in is not required.
    questions_left: int | None
