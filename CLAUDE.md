# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Status
M1 (Backend scaffold + CI), M2 (Frontend scaffold + CI), M3 (Chat contract without model), M4 (Model integration, system prompt, Prompt Version, minimal evals) and M6 (Output guardrails: `backend/guardrails.py`, `apply_guardrails()` returns the reasons applied, `handle_chat` returns `(reply, result, reasons)`; frontend renders allowlisted `[text](https://...)` links as anchors) done: uv project, FastAPI `GET /api/health` (with `prompt_version`, `faq_entries`) and `POST /api/chat` against an injectable `ModelClient` (`backend/model_client.py`: real `OpenRouterClient`, one retry on invalid model output, SDK errors become `UpstreamError`), `backend/prompts.py` (`load_prompt()`, `prompt_version()`) with `prompt_files/system.md`, shared chat path `backend/chat.py`, FAQ parser (`backend/faq.py`), startup refusal without `OPENROUTER_API_KEY`/`OPENROUTER_MODEL`, error envelope on every `/api/*` error, backend CI; React + Vite + TS chat UI wired to `/api/chat`, ESLint, Vitest, frontend CI; `evals/run.py` (scoring, `--case`/`--category`, saves each run to `evals/results/<UTC timestamp>/` as `results.jsonl`, `report.md`, `prompt.txt`), `evals/prompt_versions.py` (maps Prompt Version hashes to git commits). The starter-case eval run passed 12/12 (`google/gemini-2.5-flash-lite`, Prompt Version `4a5ca6cb94b4`). M5 (Docker + Railway deploy) is implemented and verified locally (Dockerfile, `.dockerignore`, `railway.toml`, SPA static serving, CI Docker job); the Railway deploy itself is pending my manual step. Next: M7 (Rate limiting) in `plan.md`. Existing files: `backend/prompt_files/faq.md` (the FAQ, in its parsed format), `evals/cases.yaml` (starter eval cases), `GLOSSARY.md`, `docs/adr/`.

## What the project is

A small public customer-support chatbot for Cadre AI, an AI strategy and implementation consultancy. It answers only from `backend/prompt_files/faq.md`, cites the FAQ Entries it relied on with links to their Sources, and when the FAQ doesn't cover a question it says so and points the Visitor to Cadre's contact form and email. Deployed as one Docker service on Railway serving the React build and the API on the same domain.

## Where things are specified

- `plan.md`: the milestones, and the **Shared spec** (FAQ file format, API contract, model reply schema, env vars). It is the single source of truth for behavior and numbers (limits, caps, retry policy).
- `GLOSSARY.md`: canonical domain terms (Visitor, Reply, Outcome, Citation, Source, Contact Line, Fallback Line, Prompt Version). Use them in code, tests, and docs.
- `docs/adr/`: decisions that look surprising without context. Read `0001-server-resolved-citations.md` before touching citations, links, or the FAQ format.

## Architecture
- `backend/`: FastAPI. `POST /api/chat`, `GET /api/health`, `GET /api/metrics` (token-protected).
  - `backend/prompts.py` `load_prompt()` builds the system message from `backend/prompt_files/system.md` + `faq.md`. The whole FAQ goes in the system prompt (no RAG).
  - The model is called through OpenRouter with the `openai` SDK and returns structured JSON `{outcome, answer, citations}`, where `citations` are FAQ Entry numbers. `OPENROUTER_MODEL` is `openrouter/free` for end-to-end testing; a cheap paid model is swapped in later through the env var alone.
  - The server owns trust: it resolves citation numbers to Sources, applies output guardrails, and writes every Contact Line and Fallback Line. Model text never supplies contact details or unbacked links.
  - `backend/observability.py`: JSON logging, metrics, request-ID middleware.
- `frontend/`: React + Vite + TypeScript. Renders answers as plain text plus allowlisted links only. In dev, Vite proxies `/api` to FastAPI; in production FastAPI serves the built files, so there is no CORS.
- `evals/`: `cases.yaml` + `run.py` (`uv run python -m evals.run`). Scores Outcome and cited IDs against expectations, never exact wording, and writes reports to `evals/results/` (git-ignored) for manual grading of groundedness and faithfulness. Kept out of `pytest` because it costs quota and is non-deterministic.
- `Dockerfile`: multi-stage; Node builds the frontend, then the Python stage installs with uv and serves everything.

## Development commands
Backend commands below were verified in M1, frontend commands in M2, eval commands in M4 and Docker commands in M5. Each milestone verifies the commands it introduces and updates this section to match.

This is a uv project: one root `pyproject.toml`, committed `uv.lock` and `.python-version` (3.12); `backend/` and `evals/` are packages in it. Always go through uv; don't use `pip`, `requirements.txt` or a hand-made venv.

### Backend (repository root)
- Install locked dependencies: `uv sync --locked`
- Start API: `uv run uvicorn backend.main:app --reload --env-file .env` (copy `.env.example` to `.env` and set `OPENROUTER_API_KEY` first; the app refuses to start without it and `OPENROUTER_MODEL`. The backend does not read `.env` itself, only uvicorn's `--env-file` and `evals/run.py` do)
- Run tests: `uv run pytest`
- Run a single test: `uv run pytest tests/test_chat.py -k <test_name>`
- Lint: `uv run ruff check .`
- Format check: `uv run ruff format --check .`
- Format: `uv run ruff format .`

### Frontend (Node 22)
- Install from lockfile: `cd frontend && npm ci`
- Start Vite: `cd frontend && npm run dev` (proxies `/api` to `http://localhost:8000`, so start the backend too)
- Lint: `cd frontend && npm run lint`
- Type-check and build: `cd frontend && npm run build`
- Run frontend tests: `cd frontend && npm test`

### Docker and Railway
- Build: `docker build -t cadre-faq-bot .` (Node 22 stage builds the frontend; Python 3.12 stage installs with `uv sync --locked --no-dev`, runs as non-root user `app`, one uvicorn worker)
- Run: `docker run --rm -p 8000:8000 --env-file .env cadre-faq-bot`, then check `http://localhost:8000/api/health` and `/`. Secrets come from `--env-file` at run time only; `.dockerignore` keeps `.env` out of the build context.
- Static serving: `backend/main.py` serves `frontend/dist` (override with `FRONTEND_DIST`) through the router's no-match handler, so real `/api` routes and the JSON 404 win. With no build present (local dev, CI backend job) the API runs alone.
- Railway setup (one-time, by me): create a project from this GitHub repo; `railway.toml` supplies the Dockerfile builder, health check `/api/health` and one replica. In the service's Variables tab set `OPENROUTER_API_KEY` and `OPENROUTER_MODEL`; Railway injects `PORT`. Generate a public domain under Settings > Networking, then check `/api/health` and send one chat. Never add replicas or workers.

### Evals (only with my permission)
- Run all: `uv run python -m evals.run`
- Filter: `--case <id>`, `--category <name>`. Each run writes `results.jsonl`, `report.md` and `prompt.txt` to `evals/results/<UTC timestamp>/` (git-ignored). `--repeat N`, latency/token stats and the exit-code rule come in M8.
- Map Prompt Version hashes to commits (no model call, free): `uv run python -m evals.prompt_versions`; print one version's text with `--show <hash>`. Commit prompt changes before evaluating them, since uncommitted versions are only recoverable from a run's `prompt.txt`.

## Verification

After making changes, run the checks relevant to the files changed:

- Backend: `uv run pytest`, `uv run ruff check .`, and `uv run ruff format --check .`
- Frontend: `cd frontend && npm run lint`, `npm test`, and `npm run build`
- Docker or deployment changes: build the image and verify `/api/health` responds from the running container.

CI (GitHub Actions) runs these on every PR to `main`. Evals and deploys are never run in CI.

## Rules
- **The API key stays server-side.** `OPENROUTER_API_KEY` and `OPENROUTER_MODEL` come from environment variables (`.env` locally, git-ignored; `.env.example` is committed). Never expose them to the frontend or bake them into the Docker image.
- **Privacy by default in logs.** One JSON log line per chat request with metadata only (request ID, latency, tokens, model, served model, `prompt_version`, outcome, guardrail reasons). No message text, except truncated unanswered questions when `LOG_UNANSWERED_TEXT=true`.
- **FAQ-only answers.** Don't let prompt changes loosen the "answer only from the FAQ, never guess" rule. Run the evals (with permission) after any change to `faq.md`, the system prompt or the model, and confirm the `unanswerable`, `injection`, and `smalltalk_injection` categories stay at 100%.
- **The FAQ format is load-bearing.** The server parses `faq.md` at startup and refuses to start if it is malformed. Append new FAQ Entries; never renumber existing ones, because eval expectations and citations reference the numbers.
- **Single process only.** One uvicorn worker, one Railway replica: rate limiting and metrics are in-memory. Don't add workers or replicas without first replacing that state.
- **Tests must not call external model APIs.** Mock the client in `pytest`; only `evals/` hits the real API.
- **Do not run evals without my permission.** They spend money or free-tier quota.

## Milestone Workflow
Each milestone in `plan.md` is done as one PR, in this order:
1. **Test writing by subagent.** Spawn a fresh test-writer subagent and give it `plan.md`'s Shared spec, the milestone section, and `GLOSSARY.md`. Don't give it the implementation or your reasoning; it writes the tests independently.
2. **Red check.** Run the tests. They should fail because the milestone's behavior is missing, not because of syntax or import errors.
3. **Implement.** Implement just enough to pass the tests. If a test seems wrong, leave it unedited, explain why it seems wrong, and wait for me to confirm.
4. **Verify with a fresh subagent.** Give a verifier agent the Shared spec, the milestone section, and the diff. It runs every verification command and checks each acceptance box.
5. **Update docs.** Tick the milestone in `plan.md` Progress, update this file's Status line and any changed commands, and update `GLOSSARY.md` if a term changed.
6. **User reviews.** I review the changes, then commit and merge the branch myself.

## Out of scope
Per-user accounts, saved chat history, admin UI, live human handoff, contact-form backend, multi-language, hosted tracing, RAG, custom domain, Redis/shared state, multiple workers/replicas, fake model mode, load testing, browser E2E tests.
