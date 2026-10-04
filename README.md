# interview-bot

A local chatbot for practising software engineering interview questions —
languages and frameworks as well as engineering fundamentals such as system
design, databases, algorithms and data structures. Tick several topics and the
questions jump between them, shuffled, the way a real interview does. Answers
are graded by a model — either one running on your own machine, or a hosted Claude model if
you would rather have the speed.

## Requirements

- [uv](https://docs.astral.sh/uv/getting-started/installation/)
- [Ollama](https://ollama.com/download), unless you run against a hosted model
- Node 20 or newer, with npm 11 or newer

## Setup

Install the backend dependencies:

```sh
cd backend
uv sync --all-groups
```

Install the frontend dependencies:

```sh
cd frontend
npm install
```

Start Ollama and pull a model:

```sh
ollama serve
ollama pull qwen3:4b-instruct
```

Or skip Ollama and use a hosted model instead — see [Running against a hosted
model](#running-against-a-hosted-model).

## Run

The app needs both halves running, in two terminals.

Backend:

```sh
cd backend
uv run uvicorn interview_bot.main:app --reload
```

Frontend:

```sh
cd frontend
npm run dev
```

Open http://localhost:5173 and tick the topics you want. The API is on
http://localhost:8000, with interactive docs on http://localhost:8000/docs.

Ticking more than one topic makes it a mixed interview: each question comes
from one of them, shuffled, and the tag above the question says which — see
[Mixed topics](#mixed-topics).

A **Model** dropdown above the topics sits over the whole interview. It starts
on **Ollama (free)**, the model on your own machine, and switching it to
**Claude** moves the interview onto the hosted model from the next question
onwards — see [Running against a hosted model](#running-against-a-hosted-model)
for what that needs and what it costs.

**Skip**, under the answer box, passes on a question you already know without
answering it. Nothing is graded, and the question does not come round again —
each new question is asked to avoid the ones already put up.

A grade comes with a **Learn more** button. It writes the answer out in full —
a few paragraphs, every key point expanded, and the mistakes people usually
make — so you can learn the question without going off to search for it. It
only appears once you have answered, and it folds away again with **Hide
details**.

The worked answer is written in the background while you are reading the
question and typing, so by the time you click there is usually nothing left to
wait for.

**Note to self** opens a box to jot down a topic you want to learn properly
later, and the notes pile up under the **Notes** tab — see [Notes](#notes).

Refreshing the page picks the interview back up where you left it. Use
**Start over** to drop it and choose different topics.

On the local model, expect each question and each grade to take a few
seconds, and a worked answer to take longer — it is several times as much
writing. A hosted model is quicker on all three.

Check the backend came up:

```sh
curl http://localhost:8000/health
```

## Tests

Backend:

```sh
cd backend
uv run pytest
uv run ruff check .
uv run ruff format .
```

Frontend:

```sh
cd frontend
npm test
npm run lint
npm run typecheck
```

Both suites run on every pull request via GitHub Actions.
