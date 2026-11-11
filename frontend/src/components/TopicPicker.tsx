import { DIFFICULTIES, TOPIC_GROUPS, TOPICS } from "../api/types";
import type { Difficulty, Topic } from "../api/types";

type Props = {
  topics: Topic[];
  difficulty: Difficulty;
  disabled: boolean;
  // Why the interview cannot start yet, if there is something to do first.
  blocked?: string;
  onTopicsChange: (topics: Topic[]) => void;
  onDifficultyChange: (difficulty: Difficulty) => void;
  onStart: () => void;
};

export function TopicPicker({
  topics,
  difficulty,
  disabled,
  blocked,
  onTopicsChange,
  onDifficultyChange,
  onStart,
}: Props) {
  // Rebuilt from the full list rather than appended to, so the selection stays
  // in the order the groups below show it whatever order it was clicked in.
  const toggle = (topic: Topic, chosen: boolean) =>
    onTopicsChange(
      TOPICS.filter((value) => (value === topic ? chosen : topics.includes(value))),
    );

  return (
    <section className="card">
      <h2>Pick your topics</h2>
      <p className="hint">
        Pick as many as you like. Several, and the questions jump between them, shuffled —
        as they would in a real interview.
      </p>

      {TOPIC_GROUPS.map((group) => (
        <fieldset key={group.label} className="topics">
          <legend>{group.label}</legend>
          <div className="options">
            {group.topics.map((option) => (
              <label key={option.value}>
                <input
                  type="checkbox"
                  value={option.value}
                  checked={topics.includes(option.value)}
                  disabled={disabled}
                  onChange={(event) => toggle(option.value, event.target.checked)}
                />
                {option.label}
              </label>
            ))}
          </div>
        </fieldset>
      ))}

      <label htmlFor="difficulty">Difficulty</label>
      <select
        id="difficulty"
        value={difficulty}
        disabled={disabled}
        onChange={(event) => onDifficultyChange(event.target.value as Difficulty)}
      >
        {DIFFICULTIES.map((value) => (
          <option key={value} value={value}>
            {value}
          </option>
        ))}
      </select>

      <button
        type="button"
        onClick={onStart}
        disabled={disabled || blocked !== undefined || topics.length === 0}
      >
        Start interview
      </button>
      {topics.length === 0 && <p className="hint">Choose at least one topic to begin.</p>}
      {blocked && <p className="hint">{blocked}</p>}
    </section>
  );
}
