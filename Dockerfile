# The hosted deployment: the frontend is built here and served by the API, so
# the whole app is one service on one origin, running on Claude alone.

FROM node:24-slim AS frontend
WORKDIR /app/frontend
# npm 10 crashes resolving this dependency tree (arborist "edgesOut" bug).
RUN npm install -g npm@12
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
# An empty API URL makes the frontend call the origin it was served from.
ENV VITE_API_URL="" VITE_APP_ENV=production
RUN npm run build

FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:0.13 /uv /usr/local/bin/uv
WORKDIR /app/backend
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
# Dependencies first, so a code change does not reinstall them.
COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY backend/ ./
RUN uv sync --frozen --no-dev
COPY --from=frontend /app/frontend/dist /app/frontend/dist

ENV PATH="/app/backend/.venv/bin:$PATH" \
    INTERVIEW_BOT_ENVIRONMENT=production \
    INTERVIEW_BOT_STATIC_DIR=/app/frontend/dist
# The host says which port to listen on.
CMD ["sh", "-c", "uvicorn interview_bot.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
