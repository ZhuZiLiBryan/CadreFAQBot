# Stage 1: build the frontend.
FROM node:22-slim AS frontend-build
WORKDIR /frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# Stage 2: Python runtime serving the API and the built frontend.
FROM python:3.12-slim AS runtime
COPY --from=ghcr.io/astral-sh/uv:0.13.8 /uv /usr/local/bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/app/.venv \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app

# Dependencies first so this layer is cached until the lockfile changes.
COPY pyproject.toml uv.lock .python-version ./
RUN uv sync --locked --no-dev --no-install-project

COPY backend/ ./backend/
COPY --from=frontend-build /frontend/dist ./frontend/dist

# Secrets (OPENROUTER_API_KEY, OPENROUTER_MODEL) are supplied at run time,
# never baked into the image.
RUN useradd --system --no-create-home --uid 10001 app
USER app

ENV PORT=8000
EXPOSE 8000

# One worker only: rate limiting and metrics are in-memory.
CMD ["sh", "-c", "exec uvicorn backend.main:app --host 0.0.0.0 --port ${PORT:-8000} --workers 1"]
