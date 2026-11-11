import type {
  Account,
  Difficulty,
  Explanation,
  Grade,
  Question,
  Session,
  SessionState,
  SignInProvider,
  Topic,
} from "./types";

const BASE_URL = import.meta.env.VITE_API_URL ?? "http://localhost:8000";

// A resume gates the whole screen, so it must not hang forever on a backend
// that accepts the connection and then never answers.
const RESUME_TIMEOUT_MS = 8_000;

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status?: number,
  ) {
    super(message);
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${BASE_URL}${path}`, init);
  } catch {
    throw new ApiError("Cannot reach the server. Is the backend running?");
  }

  if (!response.ok) {
    throw new ApiError(await errorMessage(response), response.status);
  }
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

const send = <T,>(method: string, path: string, body?: unknown): Promise<T> =>
  request<T>(path, {
    method,
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body ?? {}),
  });

const post = <T,>(path: string, body?: unknown): Promise<T> =>
  send<T>("POST", path, body);

async function errorMessage(response: Response): Promise<string> {
  try {
    const { detail } = await response.json();
    // FastAPI sends validation errors as a list of objects, not a string.
    if (typeof detail === "string") return detail;
  } catch {
    /* fall through to the status-based message */
  }
  return `Request failed with status ${response.status}`;
}

// A full-page visit rather than a fetch: the provider's sign-in page has to
// open in the window, and comes back to the app when it is done.
export const signInUrl = (provider: SignInProvider) => `${BASE_URL}/auth/${provider}/login`;

export const api = {
  account: () => request<Account>("/auth/me"),

  signOut: () => post<void>("/auth/logout"),

  resumeSession: (sessionId: string) =>
    request<SessionState>(`/sessions/${sessionId}`, {
      signal: AbortSignal.timeout(RESUME_TIMEOUT_MS),
    }),

  startSession: (topics: Topic[], difficulty: Difficulty, modelProvider: string) =>
    post<Session>("/sessions", { topics, difficulty, model_provider: modelProvider }),

  switchModel: (sessionId: string, modelProvider: string) =>
    send<Session>("PATCH", `/sessions/${sessionId}`, { model_provider: modelProvider }),

  nextQuestion: (sessionId: string) =>
    post<Question>(`/sessions/${sessionId}/questions`),

  submitAnswer: (sessionId: string, questionId: string, answer: string) =>
    post<Grade>(`/sessions/${sessionId}/answers`, {
      question_id: questionId,
      answer,
    }),

  explainQuestion: (sessionId: string, questionId: string) =>
    post<Explanation>(`/sessions/${sessionId}/questions/${questionId}/explanation`),
};

export type Api = typeof api;
