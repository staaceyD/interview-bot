import { useState } from "react";

import { TOPIC_LABELS } from "../api/types";
import type { Question } from "../api/types";

type Props = {
  question: Question;
  disabled: boolean;
  onSubmit: (answer: string) => void;
  onSkip: () => void;
};

export function QuestionCard({ question, disabled, onSubmit, onSkip }: Props) {
  const [answer, setAnswer] = useState("");

  return (
    <section className="card">
      <p className="tag">
        {TOPIC_LABELS[question.topic]} · {question.difficulty}
      </p>
      <h2>{question.prompt}</h2>

      <label htmlFor="answer">Your answer</label>
      <textarea
        id="answer"
        rows={8}
        value={answer}
        disabled={disabled}
        placeholder="Answer in a few sentences, as you would out loud. One line of code is fine."
        onChange={(event) => setAnswer(event.target.value)}
      />

      <div className="actions">
        <button
          type="button"
          onClick={() => onSubmit(answer)}
          disabled={disabled || answer.trim() === ""}
        >
          Submit answer
        </button>
        {/* For a question you already know. Enabled whatever is in the
            textarea: there is nothing to type if you are not answering. */}
        <button type="button" className="secondary" onClick={onSkip} disabled={disabled}>
          Skip
        </button>
      </div>
    </section>
  );
}
