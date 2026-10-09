import json
import re
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field, ValidationError

from interview_bot.domain import Difficulty, Explanation, Grade, Question, Topic
from interview_bot.llm import LLMClient, LLMError
from interview_bot.prompts import (
    EXPLAIN_SYSTEM,
    GENERATE_SYSTEM,
    GRADE_SYSTEM,
    explain_prompt,
    generate_prompt,
    grade_prompt,
)

# Small local models often wrap JSON in a markdown fence despite being asked not to.
_FENCE = re.compile(r"^\s*```(?:json)?\s*(.*?)\s*```\s*$", re.DOTALL)


class GeneratedQuestion(BaseModel):
    question: str = Field(min_length=1)
    key_points: list[str] = Field(min_length=1)


class Interviewer:
    def __init__(self, llm: LLMClient, *, explain_timeout_seconds: float | None = None) -> None:
        self._llm = llm
        self._explain_timeout_seconds = explain_timeout_seconds

    async def generate_question(
        self,
        *,
        topic: Topic,
        difficulty: Difficulty,
        avoid: list[str] | None = None,
    ) -> Question:
        reply = await self._llm.complete(
            system=GENERATE_SYSTEM,
            prompt=generate_prompt(topic=topic, difficulty=difficulty, avoid=avoid or []),
            json_mode=True,
        )
        generated = _parse(reply, GeneratedQuestion)
        return Question(
            id=str(uuid4()),
            topic=topic,
            difficulty=difficulty,
            prompt=generated.question,
            key_points=generated.key_points,
        )

    async def grade(self, *, question: Question, answer: str) -> Grade:
        reply = await self._llm.complete(
            system=GRADE_SYSTEM,
            prompt=grade_prompt(question=question, answer=answer),
            json_mode=True,
        )
        return _parse(reply, Grade)

    async def explain(self, *, question: Question) -> Explanation:
        reply = await self._llm.complete(
            system=EXPLAIN_SYSTEM,
            prompt=explain_prompt(question=question),
            json_mode=True,
            timeout_seconds=self._explain_timeout_seconds,
        )
        explanation = _parse(reply, Explanation)
        return explanation.model_copy(update={"answer": _unescaped(explanation.answer)})


# Small local models sometimes escape their JSON a second time, so a newline
# arrives as the two characters \\ and n. The worked answer is the only field
# written as markdown — paragraphs split by blank lines, around a fenced example
# — so it is the only one that collapses into an unreadable run-on when that
# happens, and the only one repaired here.
#
# Repairing every string would be wrong: "What does \\n do in Python?" is a
# question a model is right to escape that way, and there is no telling it apart
# from a mistake. An answer that is several paragraphs long always carries real
# newlines when the model got it right, so their absence is the signal.
_ESCAPE = re.compile(r"\\(.)", re.DOTALL)
_ESCAPED = {"n": "\n", "t": "\t", "r": "\r", '"': '"', "\\": "\\"}


def _unescaped(answer: str) -> str:
    if "\n" in answer or "\\n" not in answer:
        return answer
    # An escape the model invented, such as \_, is left as the model wrote it.
    return _ESCAPE.sub(lambda match: _ESCAPED.get(match.group(1), match.group(0)), answer)


def _parse[T: BaseModel](reply: str, model: type[T]) -> T:
    fenced = _FENCE.match(reply)
    payload: Any
    try:
        payload = json.loads(fenced.group(1) if fenced else reply)
    except json.JSONDecodeError as exc:
        raise LLMError(f"Model did not return JSON: {reply[:200]}") from exc

    try:
        return model.model_validate(payload)
    except ValidationError as exc:
        raise LLMError(f"Model returned unusable {model.__name__}: {exc}") from exc
