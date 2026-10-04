import { render, screen, waitFor } from "@testing-library/react";
import { renderToStaticMarkup } from "react-dom/server";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { App } from "../App";
import { ApiError } from "../api/client";
import type { Api } from "../api/client";
import type { Explanation, Grade, Question, Session, SessionState } from "../api/types";

const session: Session = {
  session_id: "s1",
  topics: ["python"],
  difficulty: "mid",
  model_provider: "ollama",
};

const question: Question = {
  question_id: "q1",
  prompt: "What is the GIL?",
  topic: "python",
  difficulty: "mid",
};

const grade: Grade = {
  score: 4,
  verdict: "Good answer.",
  covered: ["a mutex"],
  missed: ["I/O-bound work"],
};

const explanation: Explanation = {
  answer: "The GIL is one mutex.\n\nOnly one thread runs bytecode at a time.",
  points: [{ point: "a mutex", detail: "It guards the interpreter's own state." }],
  pitfalls: ["Reaching for threads on CPU-bound work"],
};

const sessionState: SessionState = {
  session_id: "s1",
  topics: ["python"],
  difficulty: "mid",
  model_provider: "ollama",
  current_question: question,
  current_grade: null,
  current_explanation: null,
};

function fakeApi(overrides: Partial<Api> = {}): Api {
  return {
    resumeSession: vi.fn().mockResolvedValue(sessionState),
    startSession: vi.fn().mockResolvedValue(session),
    switchModel: vi.fn().mockResolvedValue({ ...session, model_provider: "anthropic" }),
    nextQuestion: vi.fn().mockResolvedValue(question),
    submitAnswer: vi.fn().mockResolvedValue(grade),
    explainQuestion: vi.fn().mockResolvedValue(explanation),
    ...overrides,
  };
}

const STORAGE_KEY = "interview-bot.session-id";

async function startInterview(api: Api) {
  const user = userEvent.setup();
  render(<App api={api} />);
  await user.click(screen.getByRole("button", { name: /start interview/i }));
  await screen.findByText(question.prompt);
  return user;
}

async function answerTheQuestion(api: Api) {
  const user = await startInterview(api);
  await user.type(screen.getByLabelText(/your answer/i), "It is a mutex.");
  await user.click(screen.getByRole("button", { name: /submit answer/i }));
  await screen.findByTestId("score");
  return user;
}

beforeEach(() => {
  vi.clearAllMocks();
  localStorage.clear();
});

describe("starting an interview", () => {
  it("shows the first question for the chosen topic and difficulty", async () => {
    const api = fakeApi();
    const user = userEvent.setup();
    render(<App api={api} />);

    await user.click(screen.getByRole("checkbox", { name: "Python" }));
    await user.click(screen.getByRole("checkbox", { name: "React" }));
    await user.selectOptions(screen.getByLabelText(/difficulty/i), "senior");
    await user.click(screen.getByRole("button", { name: /start interview/i }));

    expect(await screen.findByText(question.prompt)).toBeInTheDocument();
    expect(api.startSession).toHaveBeenCalledWith(["react"], "senior", "ollama");
    expect(api.nextQuestion).toHaveBeenCalledWith("s1");
  });

  it("starts one interview over several topics at once", async () => {
    const api = fakeApi();
    const user = userEvent.setup();
    render(<App api={api} />);

    await user.click(screen.getByRole("checkbox", { name: "Databases and SQL" }));
    await user.click(screen.getByRole("checkbox", { name: "System design" }));
    await user.click(screen.getByRole("button", { name: /start interview/i }));

    await screen.findByText(question.prompt);
    expect(api.startSession).toHaveBeenCalledWith(
      ["python", "system_design", "databases"],
      "mid",
      "ollama",
    );
  });

  it("tags each question with the topic it came from", async () => {
    const second = {
      ...question,
      question_id: "q2",
      prompt: "What does an index cost on write?",
      topic: "databases" as const,
    };
    const api = fakeApi({
      nextQuestion: vi.fn().mockResolvedValueOnce(question).mockResolvedValueOnce(second),
    });
    const user = userEvent.setup();
    render(<App api={api} />);
    await user.click(screen.getByRole("button", { name: /start interview/i }));
    await screen.findByText(question.prompt);

    expect(screen.getByText(/python/i)).toBeInTheDocument();

    await user.type(screen.getByLabelText(/your answer/i), "It is a mutex.");
    await user.click(screen.getByRole("button", { name: /submit answer/i }));
    await screen.findByTestId("score");
    await user.click(screen.getByRole("button", { name: /next question/i }));

    await screen.findByText(second.prompt);
    expect(screen.getByText(/databases and sql/i)).toBeInTheDocument();
  });
});

describe("while the model is thinking", () => {
  it("keeps the picker on screen until the first question arrives", async () => {
    let release: (question: Question) => void = () => {};
    const api = fakeApi({
      nextQuestion: vi.fn().mockReturnValue(
        new Promise<Question>((resolve) => {
          release = resolve;
        }),
      ),
    });
    const user = userEvent.setup();
    render(<App api={api} />);

    await user.click(screen.getByRole("button", { name: /start interview/i }));

    expect(await screen.findByRole("status")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /start interview/i })).toBeDisabled();

    release(question);
    expect(await screen.findByText(question.prompt)).toBeInTheDocument();
  });

  it("keeps the grade on screen until the next question arrives", async () => {
    let release: (question: Question) => void = () => {};
    const second = { ...question, question_id: "q2", prompt: "What is a decorator?" };
    const api = fakeApi({
      nextQuestion: vi.fn().mockResolvedValueOnce(question).mockReturnValueOnce(
        new Promise<Question>((resolve) => {
          release = resolve;
        }),
      ),
    });
    const user = await startInterview(api);

    await user.type(screen.getByLabelText(/your answer/i), "It is a mutex.");
    await user.click(screen.getByRole("button", { name: /submit answer/i }));
    await screen.findByTestId("score");
    await user.click(screen.getByRole("button", { name: /next question/i }));

    expect(screen.getByTestId("score")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /next question/i })).toBeDisabled();

    release(second);
    expect(await screen.findByText(second.prompt)).toBeInTheDocument();
  });
});

describe("answering", () => {
  it("submits the answer and shows the grade", async () => {
    const api = fakeApi();
    const user = await startInterview(api);

    await user.type(screen.getByLabelText(/your answer/i), "It is a mutex.");
    await user.click(screen.getByRole("button", { name: /submit answer/i }));

    expect(await screen.findByTestId("score")).toHaveTextContent("4 / 5");
    expect(screen.getByText("Good answer.")).toBeInTheDocument();
    expect(screen.getByText("a mutex")).toBeInTheDocument();
    expect(screen.getByText("I/O-bound work")).toBeInTheDocument();
    expect(api.submitAnswer).toHaveBeenCalledWith("s1", "q1", "It is a mutex.");
  });

  it("keeps submit disabled until something is typed", async () => {
    const api = fakeApi();
    const user = await startInterview(api);
    const submit = screen.getByRole("button", { name: /submit answer/i });

    expect(submit).toBeDisabled();

    await user.type(screen.getByLabelText(/your answer/i), "   ");
    expect(submit).toBeDisabled();

    await user.type(screen.getByLabelText(/your answer/i), "real answer");
    expect(submit).toBeEnabled();
  });
});

describe("skipping", () => {
  it("moves straight to the next question without grading", async () => {
    const second = { ...question, question_id: "q2", prompt: "What is a decorator?" };
    const api = fakeApi({
      nextQuestion: vi.fn().mockResolvedValueOnce(question).mockResolvedValueOnce(second),
    });
    const user = await startInterview(api);

    await user.click(screen.getByRole("button", { name: /^skip$/i }));

    expect(await screen.findByText(second.prompt)).toBeInTheDocument();
    expect(api.submitAnswer).not.toHaveBeenCalled();
    expect(screen.queryByTestId("score")).not.toBeInTheDocument();
  });

  it("can be used with nothing typed, unlike submitting", async () => {
    const api = fakeApi();
    const user = await startInterview(api);

    expect(screen.getByRole("button", { name: /submit answer/i })).toBeDisabled();
    expect(screen.getByRole("button", { name: /^skip$/i })).toBeEnabled();
    expect(user).toBeDefined();
  });

  it("clears a part-written answer when the next question arrives", async () => {
    const second = { ...question, question_id: "q2", prompt: "What is a decorator?" };
    const api = fakeApi({
      nextQuestion: vi.fn().mockResolvedValueOnce(question).mockResolvedValueOnce(second),
    });
    const user = await startInterview(api);

    await user.type(screen.getByLabelText(/your answer/i), "Half an answer");
    await user.click(screen.getByRole("button", { name: /^skip$/i }));

    await screen.findByText(second.prompt);
    expect(screen.getByLabelText(/your answer/i)).toHaveValue("");
  });

  it("keeps the question on screen until the next one arrives", async () => {
    let release: (question: Question) => void = () => {};
    const api = fakeApi({
      nextQuestion: vi.fn().mockResolvedValueOnce(question).mockReturnValueOnce(
        new Promise<Question>((resolve) => {
          release = resolve;
        }),
      ),
    });
    const user = await startInterview(api);

    await user.click(screen.getByRole("button", { name: /^skip$/i }));

    expect(screen.getByText(question.prompt)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /^skip$/i })).toBeDisabled();

    release({ ...question, question_id: "q2", prompt: "What is a decorator?" });
    expect(await screen.findByText("What is a decorator?")).toBeInTheDocument();
  });

  it("reports a failure without losing the question", async () => {
    const api = fakeApi({
      nextQuestion: vi
        .fn()
        .mockResolvedValueOnce(question)
        .mockRejectedValueOnce(new ApiError("The model is unavailable: boom")),
    });
    const user = await startInterview(api);

    await user.click(screen.getByRole("button", { name: /^skip$/i }));

    expect(await screen.findByRole("alert")).toHaveTextContent("The model is unavailable: boom");
    expect(screen.getByText(question.prompt)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /^skip$/i })).toBeEnabled();
  });
});

describe("moving on", () => {
  it("clears the previous answer when the next question arrives", async () => {
    const second = { ...question, question_id: "q2", prompt: "What is a decorator?" };
    const api = fakeApi({
      nextQuestion: vi
        .fn()
        .mockResolvedValueOnce(question)
        .mockResolvedValueOnce(second),
    });
    const user = await startInterview(api);

    await user.type(screen.getByLabelText(/your answer/i), "It is a mutex.");
    await user.click(screen.getByRole("button", { name: /submit answer/i }));
    await screen.findByTestId("score");
    await user.click(screen.getByRole("button", { name: /next question/i }));

    expect(await screen.findByText(second.prompt)).toBeInTheDocument();
    expect(screen.getByLabelText(/your answer/i)).toHaveValue("");
    expect(screen.queryByTestId("score")).not.toBeInTheDocument();
  });
});

describe("errors", () => {
  it("shows the backend message when the model is unavailable", async () => {
    const api = fakeApi({
      nextQuestion: vi
        .fn()
        .mockRejectedValue(new ApiError("The model is unavailable: boom")),
    });
    const user = userEvent.setup();
    render(<App api={api} />);

    await user.click(screen.getByRole("button", { name: /start interview/i }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "The model is unavailable: boom",
    );
  });

  it("clears a previous error on the next attempt", async () => {
    const api = fakeApi({
      startSession: vi
        .fn()
        .mockRejectedValueOnce(new ApiError("Cannot reach the server."))
        .mockResolvedValue(session),
    });
    const user = userEvent.setup();
    render(<App api={api} />);

    await user.click(screen.getByRole("button", { name: /start interview/i }));
    await screen.findByRole("alert");

    await user.click(screen.getByRole("button", { name: /start interview/i }));

    await waitFor(() => expect(screen.queryByRole("alert")).not.toBeInTheDocument());
  });
});


describe("resuming", () => {
  it("restores the question in progress from a remembered session", async () => {
    localStorage.setItem(STORAGE_KEY, "s1");
    const api = fakeApi();

    render(<App api={api} />);

    expect(await screen.findByText(question.prompt)).toBeInTheDocument();
    expect(api.resumeSession).toHaveBeenCalledWith("s1");
    expect(api.startSession).not.toHaveBeenCalled();
  });

  it("shows the picker when nothing was remembered", async () => {
    const api = fakeApi();

    render(<App api={api} />);

    expect(screen.getByRole("button", { name: /start interview/i })).toBeInTheDocument();
    expect(api.resumeSession).not.toHaveBeenCalled();
  });

  it("paints the picker without a restoring flash when nothing was remembered", () => {
    // The first paint happens before effects run, so only what renderToStaticMarkup
    // produces is what a first-time visitor actually sees.
    const markup = renderToStaticMarkup(<App api={fakeApi()} />);

    expect(markup).toContain("Start interview");
    expect(markup).not.toContain("Restoring");
  });

  it("restores the grade when the question was already answered", async () => {
    localStorage.setItem(STORAGE_KEY, "s1");
    const api = fakeApi({
      resumeSession: vi.fn().mockResolvedValue({ ...sessionState, current_grade: grade }),
    });

    render(<App api={api} />);

    expect(await screen.findByTestId("score")).toHaveTextContent("4 / 5");
    expect(screen.getByRole("button", { name: /next question/i })).toBeInTheDocument();
    expect(screen.queryByLabelText(/your answer/i)).not.toBeInTheDocument();
  });

  it("brings a resumed interview's topics back to the picker", async () => {
    localStorage.setItem(STORAGE_KEY, "s1");
    const api = fakeApi({
      resumeSession: vi
        .fn()
        .mockResolvedValue({ ...sessionState, topics: ["react", "security"] }),
    });
    const user = userEvent.setup();
    render(<App api={api} />);
    await screen.findByText(question.prompt);

    await user.click(screen.getByRole("button", { name: /start over/i }));

    expect(screen.getByRole("checkbox", { name: "React" })).toBeChecked();
    expect(screen.getByRole("checkbox", { name: "Security" })).toBeChecked();
    expect(screen.getByRole("checkbox", { name: "Python" })).not.toBeChecked();
  });

  it("remembers the session id when an interview starts", async () => {
    const user = await startInterview(fakeApi());

    expect(localStorage.getItem(STORAGE_KEY)).toBe("s1");
    expect(user).toBeDefined();
  });

  it("forgets a session the backend no longer has", async () => {
    localStorage.setItem(STORAGE_KEY, "gone");
    const api = fakeApi({
      resumeSession: vi.fn().mockRejectedValue(new ApiError("Unknown session", 404)),
    });

    render(<App api={api} />);

    expect(
      await screen.findByRole("button", { name: /start interview/i }),
    ).toBeInTheDocument();
    expect(localStorage.getItem(STORAGE_KEY)).toBeNull();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("explains itself when the backend cannot be reached", async () => {
    localStorage.setItem(STORAGE_KEY, "s1");
    const api = fakeApi({
      resumeSession: vi
        .fn()
        .mockRejectedValue(new ApiError("Cannot reach the server.")),
    });

    render(<App api={api} />);

    expect(await screen.findByRole("alert")).toHaveTextContent(
      /could not restore your last interview/i,
    );
    expect(screen.getByRole("button", { name: /start interview/i })).toBeInTheDocument();
    // The backend may still have the session, so the id has to survive.
    expect(localStorage.getItem(STORAGE_KEY)).toBe("s1");
  });

  it("ignores a remembered session that never got a question", async () => {
    localStorage.setItem(STORAGE_KEY, "s1");
    const api = fakeApi({
      resumeSession: vi
        .fn()
        .mockResolvedValue({ ...sessionState, current_question: null }),
    });

    render(<App api={api} />);

    expect(
      await screen.findByRole("button", { name: /start interview/i }),
    ).toBeInTheDocument();
    expect(localStorage.getItem(STORAGE_KEY)).toBeNull();
  });
});

describe("learning the answer", () => {
  it("fetches and renders the worked answer behind Learn more", async () => {
    const api = fakeApi();
    const user = await answerTheQuestion(api);

    expect(screen.queryByTestId("explanation")).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /learn more/i }));

    expect(await screen.findByTestId("explanation")).toBeInTheDocument();
    expect(screen.getByText("The GIL is one mutex.")).toBeInTheDocument();
    expect(screen.getByText("Only one thread runs bytecode at a time.")).toBeInTheDocument();
    expect(screen.getByText("It guards the interpreter's own state.")).toBeInTheDocument();
    expect(screen.getByText("Reaching for threads on CPU-bound work")).toBeInTheDocument();
    expect(api.explainQuestion).toHaveBeenCalledWith("s1", "q1");
  });

  it("folds the answer away and back without asking the model again", async () => {
    const api = fakeApi();
    const user = await answerTheQuestion(api);

    await user.click(screen.getByRole("button", { name: /learn more/i }));
    await screen.findByTestId("explanation");
    await user.click(screen.getByRole("button", { name: /hide details/i }));

    expect(screen.queryByTestId("explanation")).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /learn more/i }));

    expect(screen.getByTestId("explanation")).toBeInTheDocument();
    expect(api.explainQuestion).toHaveBeenCalledTimes(1);
  });

  it("keeps the grade on screen while the answer is being written", async () => {
    let release: (explanation: Explanation) => void = () => {};
    const api = fakeApi({
      explainQuestion: vi.fn().mockReturnValue(
        new Promise<Explanation>((resolve) => {
          release = resolve;
        }),
      ),
    });
    const user = await answerTheQuestion(api);

    await user.click(screen.getByRole("button", { name: /learn more/i }));

    expect(screen.getByTestId("score")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /next question/i })).toBeDisabled();

    release(explanation);
    expect(await screen.findByTestId("explanation")).toBeInTheDocument();
  });

  it("reports a failure without losing the grade", async () => {
    const api = fakeApi({
      explainQuestion: vi.fn().mockRejectedValue(new ApiError("The model is unavailable: boom")),
    });
    const user = await answerTheQuestion(api);

    await user.click(screen.getByRole("button", { name: /learn more/i }));

    expect(await screen.findByRole("alert")).toHaveTextContent("The model is unavailable: boom");
    expect(screen.getByTestId("score")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /learn more/i })).toBeInTheDocument();
  });

  it("starts the next question with the details folded away", async () => {
    const second = { ...question, question_id: "q2", prompt: "What is a decorator?" };
    const api = fakeApi({
      nextQuestion: vi.fn().mockResolvedValueOnce(question).mockResolvedValueOnce(second),
    });
    const user = await answerTheQuestion(api);
    await user.click(screen.getByRole("button", { name: /learn more/i }));
    await screen.findByTestId("explanation");

    await user.click(screen.getByRole("button", { name: /next question/i }));
    await screen.findByText(second.prompt);
    await user.type(screen.getByLabelText(/your answer/i), "A wrapper.");
    await user.click(screen.getByRole("button", { name: /submit answer/i }));
    await screen.findByTestId("score");

    expect(screen.queryByTestId("explanation")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /learn more/i })).toBeInTheDocument();
  });

  it("restores an answer already read after a refresh", async () => {
    localStorage.setItem(STORAGE_KEY, "s1");
    const api = fakeApi({
      resumeSession: vi.fn().mockResolvedValue({
        ...sessionState,
        current_grade: grade,
        current_explanation: explanation,
      }),
    });
    const user = userEvent.setup();
    render(<App api={api} />);
    await screen.findByTestId("score");

    await user.click(screen.getByRole("button", { name: /learn more/i }));

    expect(screen.getByTestId("explanation")).toBeInTheDocument();
    expect(api.explainQuestion).not.toHaveBeenCalled();
  });
});

describe("starting over", () => {
  it("returns to the picker and forgets the session", async () => {
    const user = await startInterview(fakeApi());

    await user.click(screen.getByRole("button", { name: /start over/i }));

    expect(screen.getByRole("button", { name: /start interview/i })).toBeInTheDocument();
    expect(screen.queryByText(question.prompt)).not.toBeInTheDocument();
    expect(localStorage.getItem(STORAGE_KEY)).toBeNull();
  });
});


describe("the model picker", () => {
  it("starts on the local model", () => {
    render(<App api={fakeApi()} />);

    expect(screen.getByLabelText(/model/i)).toHaveValue("ollama");
  });

  it("starts the interview on the model that was picked", async () => {
    const api = fakeApi();
    const user = userEvent.setup();
    render(<App api={api} />);

    await user.selectOptions(screen.getByLabelText(/model/i), "anthropic");
    await user.click(screen.getByRole("button", { name: /start interview/i }));
    await screen.findByText(question.prompt);

    expect(api.startSession).toHaveBeenCalledWith(["python"], "mid", "anthropic");
  });

  it("says what the hosted model costs once it is chosen", async () => {
    const user = userEvent.setup();
    render(<App api={fakeApi()} />);

    expect(screen.queryByText(/a cent a question/i)).not.toBeInTheDocument();
    await user.selectOptions(screen.getByLabelText(/model/i), "anthropic");

    expect(screen.getByText(/a cent a question/i)).toBeInTheDocument();
  });

  it("moves a running interview onto the model picked", async () => {
    const api = fakeApi();
    const user = await startInterview(api);

    await user.selectOptions(screen.getByLabelText(/model/i), "anthropic");

    await waitFor(() => expect(api.switchModel).toHaveBeenCalledWith("s1", "anthropic"));
    expect(screen.getByLabelText(/model/i)).toHaveValue("anthropic");
    // The question on screen is the one already asked, not a new one.
    expect(api.nextQuestion).toHaveBeenCalledTimes(1);
  });

  it("keeps showing the old model when the switch fails", async () => {
    const api = fakeApi({
      switchModel: vi.fn().mockRejectedValue(new ApiError("The model is unavailable", 502)),
    });
    const user = await startInterview(api);

    await user.selectOptions(screen.getByLabelText(/model/i), "anthropic");

    expect(await screen.findByRole("alert")).toHaveTextContent("The model is unavailable");
    expect(screen.getByLabelText(/model/i)).toHaveValue("ollama");
  });

  it("comes back on the model a resumed interview was running on", async () => {
    localStorage.setItem(STORAGE_KEY, "s1");
    const api = fakeApi({
      resumeSession: vi.fn().mockResolvedValue({
        ...sessionState,
        model_provider: "anthropic",
      }),
    });
    render(<App api={api} />);

    await screen.findByText(question.prompt);

    expect(screen.getByLabelText(/model/i)).toHaveValue("anthropic");
  });
});
