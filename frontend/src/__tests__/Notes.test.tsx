import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { App } from "../App";
import type { Api } from "../api/client";
import type { Grade, Question, Session, SessionState } from "../api/types";

const session: Session = {
  session_id: "s1",
  topics: ["databases"],
  difficulty: "mid",
  model_provider: "ollama",
};

const question: Question = {
  question_id: "q1",
  prompt: "What does an index cost on write?",
  topic: "databases",
  difficulty: "mid",
};

const grade: Grade = { score: 3, verdict: "Partly.", covered: [], missed: [] };

const sessionState: SessionState = {
  ...session,
  current_question: question,
  current_grade: null,
  current_explanation: null,
};

function fakeApi(overrides: Partial<Api> = {}): Api {
  return {
    resumeSession: vi.fn().mockResolvedValue(sessionState),
    startSession: vi.fn().mockResolvedValue(session),
    switchModel: vi.fn().mockResolvedValue(session),
    nextQuestion: vi.fn().mockResolvedValue(question),
    submitAnswer: vi.fn().mockResolvedValue(grade),
    explainQuestion: vi.fn().mockRejectedValue(new Error("not used here")),
    ...overrides,
  };
}

const NOTES_KEY = "interview-bot.notes";
const SESSION_KEY = "interview-bot.session-id";

const notesTab = () => screen.getByRole("tab", { name: /notes/i });
const interviewTab = () => screen.getByRole("tab", { name: /interview/i });

async function startInterview(api: Api = fakeApi()) {
  const user = userEvent.setup();
  render(<App api={api} />);
  await user.click(screen.getByRole("button", { name: /start interview/i }));
  await screen.findByText(question.prompt);
  return user;
}

async function writeNote(user: ReturnType<typeof userEvent.setup>, text: string) {
  await user.click(screen.getByRole("button", { name: /note to self/i }));
  await user.type(await screen.findByLabelText(/your note/i), text);
  await user.click(screen.getByRole("button", { name: /save note/i }));
}

function stored() {
  return JSON.parse(localStorage.getItem(NOTES_KEY) ?? "[]");
}

beforeEach(() => {
  vi.clearAllMocks();
  localStorage.clear();
});

describe("writing a note", () => {
  it("opens a modal from the interview and saves what was typed", async () => {
    const user = await startInterview();

    expect(screen.queryByLabelText(/your note/i)).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /note to self/i }));

    const dialog = await screen.findByRole("dialog");
    expect(dialog).toBeInTheDocument();
    await user.type(screen.getByLabelText(/your note/i), "Read up on partial indexes.");
    await user.click(screen.getByRole("button", { name: /save note/i }));

    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    await user.click(notesTab());
    expect(screen.getByText("Read up on partial indexes.")).toBeInTheDocument();
  });

  it("keeps save disabled until something is typed", async () => {
    const user = await startInterview();

    await user.click(screen.getByRole("button", { name: /note to self/i }));
    const save = await screen.findByRole("button", { name: /save note/i });

    expect(save).toBeDisabled();

    await user.type(screen.getByLabelText(/your note/i), "   ");
    expect(save).toBeDisabled();

    await user.type(screen.getByLabelText(/your note/i), "a real note");
    expect(save).toBeEnabled();
  });

  it("tags the note with the topic of the question on screen", async () => {
    const user = await startInterview();

    await writeNote(user, "Indexes.");

    expect(stored()[0].topic).toBe("databases");
    await user.click(notesTab());
    expect(screen.getByText(/databases and sql/i)).toBeInTheDocument();
  });

  it("takes a note before an interview has started, with no topic", async () => {
    const user = userEvent.setup();
    render(<App api={fakeApi()} />);

    await writeNote(user, "Look into event loops.");

    expect(stored()[0].topic).toBeNull();
    await user.click(notesTab());
    expect(screen.getByText("Look into event loops.")).toBeInTheDocument();
  });

  it("throws the note away on cancel", async () => {
    const user = await startInterview();

    await user.click(screen.getByRole("button", { name: /note to self/i }));
    await user.type(await screen.findByLabelText(/your note/i), "Never mind.");
    await user.click(screen.getByRole("button", { name: /cancel/i }));

    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(localStorage.getItem(NOTES_KEY)).toBeNull();
    await user.click(notesTab());
    expect(screen.queryByText("Never mind.")).not.toBeInTheDocument();
  });

  it("starts the next note empty", async () => {
    const user = await startInterview();
    await writeNote(user, "The first note.");

    await user.click(screen.getByRole("button", { name: /note to self/i }));

    expect(await screen.findByLabelText(/your note/i)).toHaveValue("");
  });

  it("can be written while the model is thinking", async () => {
    const api = fakeApi({
      nextQuestion: vi.fn().mockResolvedValueOnce(question).mockReturnValueOnce(
        new Promise<Question>(() => {}),
      ),
    });
    const user = await startInterview(api);
    await user.type(screen.getByLabelText(/your answer/i), "It slows them down.");
    await user.click(screen.getByRole("button", { name: /submit answer/i }));
    await screen.findByTestId("score");
    await user.click(screen.getByRole("button", { name: /next question/i }));

    expect(screen.getByRole("button", { name: /note to self/i })).toBeEnabled();
    await writeNote(user, "Written while waiting.");

    await user.click(notesTab());
    expect(screen.getByText("Written while waiting.")).toBeInTheDocument();
  });
});

describe("the notes tab", () => {
  it("is empty until a note is written", async () => {
    const user = userEvent.setup();
    render(<App api={fakeApi()} />);

    await user.click(notesTab());

    expect(screen.getByText(/nothing here yet/i)).toBeInTheDocument();
  });

  it("shows the newest note first", async () => {
    const user = await startInterview();
    await writeNote(user, "The older note.");
    await writeNote(user, "The newer note.");

    await user.click(notesTab());

    const shown = screen.getAllByRole("listitem").map((item) => item.textContent);
    expect(shown[0]).toContain("The newer note.");
    expect(shown[1]).toContain("The older note.");
  });

  it("swaps the interview out for the notes and back", async () => {
    const user = await startInterview();

    await user.click(notesTab());

    expect(screen.queryByText(question.prompt)).not.toBeInTheDocument();
    expect(notesTab()).toHaveAttribute("aria-selected", "true");

    await user.click(interviewTab());

    expect(screen.getByText(question.prompt)).toBeInTheDocument();
    expect(interviewTab()).toHaveAttribute("aria-selected", "true");
  });

  it("deletes one note and leaves the rest", async () => {
    const user = await startInterview();
    await writeNote(user, "Keep this one.");
    await writeNote(user, "Delete this one.");
    await user.click(notesTab());

    await user.click(screen.getByRole("button", { name: /delete note: delete this one/i }));

    expect(screen.queryByText("Delete this one.")).not.toBeInTheDocument();
    expect(screen.getByText("Keep this one.")).toBeInTheDocument();
    expect(stored()).toHaveLength(1);
  });
});

describe("notes outliving the interview", () => {
  it("comes back after a reload", async () => {
    const user = await startInterview();
    await writeNote(user, "Survives a refresh.");

    // Unmount and mount again: the same thing a refresh does, without
    // leaving the first copy on screen to be found instead.
    cleanup();
    render(<App api={fakeApi()} />);
    // The remembered interview is restored first, as it would be on a refresh.
    await screen.findByText(question.prompt);
    await user.click(notesTab());

    expect(screen.getByText("Survives a refresh.")).toBeInTheDocument();
  });

  it("keeps the notes when the interview is started over", async () => {
    const user = await startInterview();
    await writeNote(user, "Kept across a start over.");

    await user.click(screen.getByRole("button", { name: /start over/i }));
    await user.click(notesTab());

    expect(screen.getByText("Kept across a start over.")).toBeInTheDocument();
  });

  it("ignores a stored note it cannot make sense of", async () => {
    localStorage.setItem(
      NOTES_KEY,
      JSON.stringify([
        { id: "1", text: "A good note.", topic: "python", writtenAt: "2026-10-03T09:00:00Z" },
        { id: "2", topic: "python" },
        "not a note at all",
      ]),
    );
    const user = userEvent.setup();
    render(<App api={fakeApi()} />);

    await user.click(notesTab());

    expect(screen.getByText("A good note.")).toBeInTheDocument();
    expect(screen.getAllByRole("listitem")).toHaveLength(1);
  });

  it("is reachable while a remembered interview is still being restored", async () => {
    localStorage.setItem(SESSION_KEY, "s1");
    const user = userEvent.setup();
    render(<App api={fakeApi()} />);
    await screen.findByText(question.prompt);

    await writeNote(user, "Taken after a resume.");

    expect(stored()[0].topic).toBe("databases");
  });
});
