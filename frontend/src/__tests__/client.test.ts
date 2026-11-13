import { afterEach, describe, expect, it, vi } from "vitest";

import { api, ApiError } from "../api/client";

function mockFetch(response: Partial<Response> & { json?: () => Promise<unknown> }) {
  const spy = vi.fn().mockResolvedValue({ ok: true, status: 200, ...response });
  vi.stubGlobal("fetch", spy);
  return spy;
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("startSession", () => {
  it("posts the topics and difficulty", async () => {
    const fetchSpy = mockFetch({
      json: async () => ({ session_id: "s1", topics: ["python", "databases"], difficulty: "mid" }),
    });

    const session = await api.startSession(["python", "databases"], "mid", "ollama");

    expect(session.session_id).toBe("s1");
    const [url, init] = fetchSpy.mock.calls[0];
    expect(url).toBe("http://localhost:8000/sessions");
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body)).toEqual({
      topics: ["python", "databases"],
      difficulty: "mid",
      model_provider: "ollama",
    });
  });
});

describe("switchModel", () => {
  it("patches the session with the chosen provider", async () => {
    const fetchSpy = mockFetch({
      json: async () => ({
        session_id: "s1",
        topics: ["python"],
        difficulty: "mid",
        model_provider: "anthropic",
      }),
    });

    const session = await api.switchModel("s1", "anthropic");

    expect(session.model_provider).toBe("anthropic");
    const [url, init] = fetchSpy.mock.calls[0];
    expect(url).toBe("http://localhost:8000/sessions/s1");
    expect(init.method).toBe("PATCH");
    expect(JSON.parse(init.body)).toEqual({ model_provider: "anthropic" });
  });
});

describe("submitAnswer", () => {
  it("sends the question id and answer in snake_case", async () => {
    const fetchSpy = mockFetch({
      json: async () => ({ score: 3, verdict: "ok", covered: [], missed: [] }),
    });

    await api.submitAnswer("s1", "q1", "my answer");

    const [url, init] = fetchSpy.mock.calls[0];
    expect(url).toBe("http://localhost:8000/sessions/s1/answers");
    expect(JSON.parse(init.body)).toEqual({ question_id: "q1", answer: "my answer" });
  });
});

describe("explainQuestion", () => {
  it("posts to the question's explanation endpoint", async () => {
    const fetchSpy = mockFetch({
      json: async () => ({ answer: "Because.", points: [], pitfalls: [] }),
    });

    const explanation = await api.explainQuestion("s1", "q1");

    expect(explanation.answer).toBe("Because.");
    const [url, init] = fetchSpy.mock.calls[0];
    expect(url).toBe("http://localhost:8000/sessions/s1/questions/q1/explanation");
    expect(init.method).toBe("POST");
  });
});

describe("resumeSession", () => {
  it("bounds the request with a timeout, so a hung backend cannot block the app", async () => {
    const fetchSpy = mockFetch({
      json: async () => ({
        session_id: "s1",
        topics: ["python"],
        difficulty: "mid",
        current_question: null,
        current_grade: null,
      }),
    });

    await api.resumeSession("s1");

    const [url, init] = fetchSpy.mock.calls[0];
    expect(url).toBe("http://localhost:8000/sessions/s1");
    expect(init.signal).toBeInstanceOf(AbortSignal);
    expect(init.signal.aborted).toBe(false);
  });

  it("reports a timed-out resume as an unreachable server", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockRejectedValue(new DOMException("signal timed out", "TimeoutError")),
    );

    await expect(api.resumeSession("s1")).rejects.toThrow("Cannot reach the server");
  });
});

describe("error handling", () => {
  it("surfaces the detail string from the backend", async () => {
    mockFetch({
      ok: false,
      status: 502,
      json: async () => ({ detail: "The model is unavailable: boom" }),
    });

    await expect(api.nextQuestion("s1")).rejects.toThrow(ApiError);
    await expect(api.nextQuestion("s1")).rejects.toThrow("The model is unavailable: boom");
  });

  it("falls back to the status when detail is not a string", async () => {
    mockFetch({
      ok: false,
      status: 422,
      json: async () => ({ detail: [{ msg: "must not be blank" }] }),
    });

    await expect(api.nextQuestion("s1")).rejects.toThrow("status 422");
  });

  it("falls back to the status when the body is not json", async () => {
    mockFetch({
      ok: false,
      status: 500,
      json: async () => {
        throw new Error("not json");
      },
    });

    await expect(api.nextQuestion("s1")).rejects.toThrow("status 500");
  });

  it("explains a connection failure", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockRejectedValue(new TypeError("Failed to fetch")),
    );

    await expect(api.startSession(["react"], "mid", "ollama")).rejects.toThrow(
      "Cannot reach the server",
    );
  });
});

describe("account", () => {
  it("reads who is signed in", async () => {
    const fetchSpy = mockFetch({ json: async () => ({ user: null }) });

    await api.account();

    expect(fetchSpy.mock.calls[0][0]).toBe("http://localhost:8000/auth/me");
  });

  it("signs out with a POST that has nothing to return", async () => {
    const fetchSpy = mockFetch({ status: 204, json: async () => Promise.reject(new Error()) });

    await expect(api.signOut()).resolves.toBeUndefined();

    const [url, init] = fetchSpy.mock.calls[0];
    expect(url).toBe("http://localhost:8000/auth/logout");
    expect(init.method).toBe("POST");
  });
});
