import { useEffect, useRef, useState } from "react";

import { api as defaultApi, ApiError } from "./api/client";
import type { Api } from "./api/client";
import type { Difficulty, Explanation, Grade, Question, Topic } from "./api/types";
import { GradeCard } from "./components/GradeCard";
import { ModelPicker } from "./components/ModelPicker";
import { NoteDialog } from "./components/NoteDialog";
import { NotesTab } from "./components/NotesTab";
import { QuestionCard } from "./components/QuestionCard";
import { TopicPicker } from "./components/TopicPicker";
import { recallNotes, rememberNotes, writeNote } from "./notes";
import type { Note } from "./notes";
import { forgetSession, recallSession, rememberSession } from "./storage";

const TABS = [
  { value: "interview", label: "Interview" },
  { value: "notes", label: "Notes" },
] as const;

type Tab = (typeof TABS)[number]["value"];

export function App({ api = defaultApi }: { api?: Api }) {
  const [topics, setTopics] = useState<Topic[]>(["python"]);
  const [difficulty, setDifficulty] = useState<Difficulty>("mid");
  // The local model to begin with: nothing is spent until this is changed.
  const [modelProvider, setModelProvider] = useState<string>("ollama");
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [question, setQuestion] = useState<Question | null>(null);
  const [grade, setGrade] = useState<Grade | null>(null);
  const [explanation, setExplanation] = useState<Explanation | null>(null);
  const [busy, setBusy] = useState(false);
  // Read storage during the first render, so a visitor with nothing stored
  // never sees a flash of the restoring splash.
  const [resuming, setResuming] = useState(() => recallSession() !== null);
  const [error, setError] = useState<string | null>(null);
  const [tab, setTab] = useState<Tab>("interview");
  // Notes outlive the interview they were written during, so they are read
  // from storage once and never cleared by starting over.
  const [notes, setNotes] = useState<Note[]>(recallNotes);
  const [noting, setNoting] = useState(false);

  const resumed = useRef(false);

  useEffect(() => {
    if (resumed.current) return;
    resumed.current = true;

    const stored = recallSession();
    if (stored === null) {
      setResuming(false);
      return;
    }

    void (async () => {
      try {
        const state = await api.resumeSession(stored);
        // A session with no question yet has nothing to return to.
        if (state.current_question === null) {
          forgetSession();
          return;
        }
        setSessionId(state.session_id);
        setTopics(state.topics);
        setDifficulty(state.difficulty);
        setModelProvider(state.model_provider);
        setQuestion(state.current_question);
        // Restored alongside the question, so answering it again is never the
        // only way forward after a refresh.
        setGrade(state.current_grade);
        setExplanation(state.current_explanation);
      } catch (caught) {
        // Only a 404 proves the session is gone. Forgetting the id on a passing
        // failure would strand an interview the backend still has.
        if (caught instanceof ApiError && caught.status === 404) {
          forgetSession();
        } else {
          setError("Could not restore your last interview. Refresh to try again.");
        }
      } finally {
        setResuming(false);
      }
    })();
  }, [api]);

  async function run(action: () => Promise<void>) {
    setBusy(true);
    setError(null);
    try {
      await action();
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : "Something went wrong.");
    } finally {
      setBusy(false);
    }
  }

  // Each step commits its state only once every request has resolved, so the
  // screen never blanks out while the model is thinking.
  const start = () =>
    run(async () => {
      const session = await api.startSession(topics, difficulty, modelProvider);
      const first = await api.nextQuestion(session.session_id);
      rememberSession(session.session_id);
      setSessionId(session.session_id);
      setQuestion(first);
      setGrade(null);
      setExplanation(null);
    });

  const next = () =>
    run(async () => {
      if (!sessionId) return;
      const following = await api.nextQuestion(sessionId);
      setQuestion(following);
      setGrade(null);
      setExplanation(null);
    });

  const answer = (text: string) =>
    run(async () => {
      if (!sessionId || !question) return;
      setGrade(await api.submitAnswer(sessionId, question.question_id, text));
    });

  // Before an interview starts this only picks what to start on. Once one is
  // running it moves that interview across, from the next question onwards.
  const chooseModel = (chosen: string) => {
    if (chosen === modelProvider) return;
    if (sessionId === null) {
      setModelProvider(chosen);
      return;
    }
    void run(async () => {
      setModelProvider((await api.switchModel(sessionId, chosen)).model_provider);
    });
  };

  const learnMore = () =>
    run(async () => {
      if (!sessionId || !question) return;
      setExplanation(await api.explainQuestion(sessionId, question.question_id));
    });

  // Written straight to storage rather than on unload: a note is a single
  // sentence somebody expects to still be there after they close the tab.
  function keep(kept: Note[]) {
    setNotes(kept);
    rememberNotes(kept);
  }

  const addNote = (text: string) => {
    // Newest first, the order the Notes tab reads in.
    keep([writeNote(text, question?.topic ?? null), ...notes]);
    setNoting(false);
  };

  const deleteNote = (id: string) => keep(notes.filter((note) => note.id !== id));

  function startOver() {
    forgetSession();
    setSessionId(null);
    setQuestion(null);
    setGrade(null);
    setExplanation(null);
    setError(null);
  }

  if (resuming) {
    return (
      <main>
        <h1>Interview Bot</h1>
        <p role="status">Restoring your interview…</p>
      </main>
    );
  }

  return (
    <main>
      <h1>Interview Bot</h1>

      <div className="tabs" role="tablist">
        {TABS.map(({ value, label }) => (
          <button
            key={value}
            type="button"
            role="tab"
            id={`tab-${value}`}
            aria-controls={`panel-${value}`}
            aria-selected={tab === value}
            onClick={() => setTab(value)}
          >
            {label}
          </button>
        ))}
      </div>

      {tab === "notes" ? (
        <div role="tabpanel" id="panel-notes" aria-labelledby="tab-notes">
          <NotesTab notes={notes} onDelete={deleteNote} />
        </div>
      ) : (
        <div role="tabpanel" id="panel-interview" aria-labelledby="tab-interview">
          <ModelPicker modelProvider={modelProvider} disabled={busy} onChange={chooseModel} />

          {sessionId === null ? (
            <TopicPicker
              topics={topics}
              difficulty={difficulty}
              disabled={busy}
              onTopicsChange={setTopics}
              onDifficultyChange={setDifficulty}
              onStart={start}
            />
          ) : (
            <>
              {question && !grade && (
                <QuestionCard
                  // Remount on a new question so the textarea starts empty.
                  key={question.question_id}
                  question={question}
                  disabled={busy}
                  onSubmit={answer}
                  onSkip={next}
                />
              )}
              {grade && question && (
                <GradeCard
                  // Remount on a new question so the details start folded away.
                  key={question.question_id}
                  grade={grade}
                  explanation={explanation}
                  disabled={busy}
                  onLearnMore={learnMore}
                  onNext={next}
                />
              )}
            </>
          )}

          <div className="actions">
            {/* Never disabled by `busy`: jotting a note touches nothing the
                model is holding, and waiting is when it comes to mind. */}
            <button type="button" className="secondary" onClick={() => setNoting(true)}>
              Note to self
            </button>
            {sessionId !== null && (
              <button
                type="button"
                className="secondary"
                onClick={startOver}
                disabled={busy}
              >
                Start over
              </button>
            )}
          </div>

          {busy && <p role="status">Thinking…</p>}
          {error && <p role="alert">{error}</p>}
        </div>
      )}

      {noting && (
        <NoteDialog
          topic={question?.topic ?? null}
          onSave={addNote}
          onClose={() => setNoting(false)}
        />
      )}
    </main>
  );
}
