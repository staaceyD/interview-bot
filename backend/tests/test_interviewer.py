import json

import pytest

from interview_bot.domain import Difficulty, Question, Topic
from interview_bot.interviewer import Interviewer
from interview_bot.llm import LLMError
from interview_bot.llm.echo import EchoClient, FailingClient

QUESTION = Question(
    id="q1",
    topic=Topic.PYTHON,
    difficulty=Difficulty.MID,
    prompt="What is the GIL?",
    key_points=["a mutex", "one thread at a time"],
)


def interviewer_replying(*replies: str) -> Interviewer:
    llm = EchoClient()
    llm.queue(*replies)
    return Interviewer(llm)


async def test_generates_a_question_with_key_points() -> None:
    reply = json.dumps({"question": "Explain closures", "key_points": ["scope"]})

    question = await interviewer_replying(reply).generate_question(
        topic=Topic.JAVASCRIPT, difficulty=Difficulty.JUNIOR
    )

    assert question.prompt == "Explain closures"
    assert question.key_points == ["scope"]
    assert question.topic == Topic.JAVASCRIPT
    assert question.difficulty == Difficulty.JUNIOR
    assert question.id


async def test_generated_questions_get_distinct_ids() -> None:
    reply = json.dumps({"question": "q", "key_points": ["k"]})
    interviewer = interviewer_replying(reply, reply)

    first = await interviewer.generate_question(topic=Topic.PYTHON, difficulty=Difficulty.MID)
    second = await interviewer.generate_question(topic=Topic.PYTHON, difficulty=Difficulty.MID)

    assert first.id != second.id


async def test_generation_asks_the_model_for_json_and_passes_previous_questions() -> None:
    llm = EchoClient()
    llm.queue(json.dumps({"question": "q", "key_points": ["k"]}))

    await Interviewer(llm).generate_question(
        topic=Topic.REACT,
        difficulty=Difficulty.SENIOR,
        avoid=["What is the virtual DOM?"],
    )

    call = llm.calls[0]
    assert call["json_mode"] is True
    assert "React" in call["prompt"]
    assert "What is the virtual DOM?" in call["prompt"]


async def test_grades_an_answer_against_the_key_points() -> None:
    llm = EchoClient()
    llm.queue(
        json.dumps(
            {"score": 4, "verdict": "Good.", "covered": ["a mutex"], "missed": ["one thread"]}
        )
    )

    grade = await Interviewer(llm).grade(question=QUESTION, answer="It is a mutex.")

    assert grade.score == 4
    assert grade.verdict == "Good."
    assert grade.covered == ["a mutex"]
    assert grade.missed == ["one thread"]
    assert "a mutex" in llm.calls[0]["prompt"]
    assert "It is a mutex." in llm.calls[0]["prompt"]


@pytest.mark.parametrize(
    "fenced",
    [
        '```json\n{"score": 2, "verdict": "ok"}\n```',
        '```\n{"score": 2, "verdict": "ok"}\n```',
        '  ```json\n{"score": 2, "verdict": "ok"}\n```  ',
    ],
)
async def test_strips_markdown_fences_local_models_add(fenced: str) -> None:
    grade = await interviewer_replying(fenced).grade(question=QUESTION, answer="a")

    assert grade.score == 2


async def test_non_json_reply_becomes_llm_error() -> None:
    with pytest.raises(LLMError, match="did not return JSON"):
        await interviewer_replying("Sure! Here is a question.").grade(question=QUESTION, answer="a")


async def test_json_missing_required_fields_becomes_llm_error() -> None:
    with pytest.raises(LLMError, match="unusable Grade"):
        await interviewer_replying('{"verdict": "no score"}').grade(question=QUESTION, answer="a")


async def test_out_of_range_score_becomes_llm_error() -> None:
    with pytest.raises(LLMError, match="unusable Grade"):
        await interviewer_replying('{"score": 9, "verdict": "x"}').grade(
            question=QUESTION, answer="a"
        )


async def test_question_without_key_points_becomes_llm_error() -> None:
    with pytest.raises(LLMError, match="unusable GeneratedQuestion"):
        await interviewer_replying('{"question": "q", "key_points": []}').generate_question(
            topic=Topic.PYTHON, difficulty=Difficulty.MID
        )


async def test_model_provider_failure_propagates() -> None:
    with pytest.raises(LLMError, match="model provider unavailable"):
        await Interviewer(FailingClient()).generate_question(
            topic=Topic.PYTHON, difficulty=Difficulty.MID
        )


async def test_explains_the_answer_from_the_key_points() -> None:
    llm = EchoClient()
    llm.queue(
        json.dumps(
            {
                "answer": "It is a mutex around the interpreter.",
                "points": [{"point": "a mutex", "detail": "It guards interpreter state."}],
                "pitfalls": ["Reaching for threads on CPU-bound work"],
            }
        )
    )

    explanation = await Interviewer(llm).explain(question=QUESTION)

    assert explanation.answer == "It is a mutex around the interpreter."
    assert explanation.points[0].point == "a mutex"
    assert explanation.pitfalls == ["Reaching for threads on CPU-bound work"]
    assert "a mutex" in llm.calls[0]["prompt"]
    assert "What is the GIL?" in llm.calls[0]["prompt"]
    assert llm.calls[0]["json_mode"] is True


async def test_explanation_survives_a_model_that_skips_the_optional_parts() -> None:
    explanation = await interviewer_replying('{"answer": "Just the prose."}').explain(
        question=QUESTION
    )

    assert explanation.answer == "Just the prose."
    assert explanation.points == []
    assert explanation.pitfalls == []


async def test_explanation_without_an_answer_becomes_llm_error() -> None:
    with pytest.raises(LLMError, match="unusable Explanation"):
        await interviewer_replying('{"points": []}').explain(question=QUESTION)


async def test_worked_answer_survives_a_model_that_escapes_its_json_twice() -> None:
    # The two characters \ and n, as a doubly-escaped model writes them, rather
    # than a newline.
    doubly_escaped = "Paragraph one.\\n\\n```ts\\nconst x = 1;\\n```\\n\\nParagraph two."

    explanation = await interviewer_replying(json.dumps({"answer": doubly_escaped})).explain(
        question=QUESTION
    )

    assert explanation.answer == "Paragraph one.\n\n```ts\nconst x = 1;\n```\n\nParagraph two."
    assert "\\n" not in explanation.answer


async def test_a_correctly_escaped_worked_answer_is_left_alone() -> None:
    answer = "Paragraph one.\n\nParagraph two."

    explanation = await interviewer_replying(json.dumps({"answer": answer})).explain(
        question=QUESTION
    )

    assert explanation.answer == answer


async def test_an_answer_about_escape_sequences_keeps_them() -> None:
    # The model means the characters \ and n here, and is right to escape them;
    # the real newlines around it are what say the JSON was written correctly.
    answer = "In Python, `\\n` is a newline.\n\nUse `\\t` for a tab."

    explanation = await interviewer_replying(json.dumps({"answer": answer})).explain(
        question=QUESTION
    )

    assert explanation.answer == answer
    assert "`\\n`" in explanation.answer
