# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Status
CLAUDE.md and empty plan.md exist alongside an FAQ.md in backend/prompts as the source of truth for the chatbot. A small intial init_eval.yaml exists for basic evals on groundedness/faithfulness.  Commands, architecture notes, and progress should be added here once the project is scaffolded (run `/init` again at that point).  

## What the Project is

A small customer-support chatbot for Cadre AI: an AI strategy and implementation consultancy. It answers only from a short FAQ (`backend/faq.md`).  The chatbot cites the source that verifies the answer and provides a link to the source when it has an answer, and if the chatbot doesn't have enough information to answer it replies that it doesn't know and points users to a contact option. It is intended to be deployed publicly as a single Docker service serving both React files and API on the same domain.

## Planned Stack/Architecture
- `backend/`: FastAPI. `POST /api/chat`, `GET /api/health`.  Calls OpenRouter via SDK with a system message from `load_prompt()` in `backend/prompts.py` (built from `backend/prompt_files/system.md` + `faq.md`). The model returns structured output `{answer, can_answer, fully_answered, citations}`.  The server should produce every fallback/contact email line.  The whole FAQ will be provided in the system prompt.
- `frontend/`: React + Vite + TypeScript chat UI. In dev, Vite proxies `/api` to FastAPI. In production FastAPI serves the built frontend, so there is no CORS setup.
- `evals/`: `cases.yaml` plus `run.py` (`uv run python -m evals.run`). Scores real-model behavior, not exact wording. Separate from `pytest` because it costs money and is non-deterministic.  Should output model output so manual grading can be used to evaluate groundedness and faithfulness. 
- `backend/observability.py`: JSON logging, metrics, request-ID middleware.
- Single multi-stage `Dockerfile` (Node builds the frontend; the Python stage installs with uv and serves everything). 

## Development commands
The project is not scaffolded yet. Establish and verify these commands during implementation, then update this section to match the actual configuration.

This is to be a uv project: one root `pyproject.toml`, committed `uv.lock` and `.python-version`; `backend/` and `evals/` are packages in it. Always go through uv; don't use `pip`, `requirements.txt` or a hand-made venv.

### Backend (repository root)
- Install locked dependencies: `uv sync --locked`
- Start API: `uv run uvicorn backend.main:app --reload`
- Run tests: `uv run pytest`
- Run a single test: `uv run pytest tests/test_chat.py -k <test_name>`
- Lint: `uv run ruff check .`
- Format check: `uv run ruff format --check .`
- Format: `uv run ruff format .`

### Frontend
- Install from lockfile: `cd frontend && npm ci`
- Start Vite: `cd frontend && npm run dev`
- Lint: `cd frontend && npm run lint`
- Type-check and build: `cd frontend && npm run build`
- Run frontend tests: `cd frontend && npm test`

## Verification

After making changes, run the checks relevant to the files changed:

- Backend: `uv run pytest`, `uv run ruff check .`,
  and `uv run ruff format --check .`
- Frontend: `cd frontend && npm run lint`,
  `npm test`, and `npm run build`
- Docker or deployment changes: build the image and verify
  `/api/health` responds from the running container.

## Rules
- **The API key stays server-side.** `OPENROUTER_API_KEY` and `OPENROUTER_MODEL` come from environment variables (`.env` locally, git-ignored; `.env.example` is committed). Never expose them to the frontend or bake them into the Docker image.
- **Privacy by default in logs.** One JSON log line per chat request with metadata only (request ID, latency, tokens, model, `prompt_version`, `can_answer`, outcome). No message text, except truncated unanswered questions when `LOG_UNANSWERED_TEXT=true`.
- **FAQ-only answers.** Don't let prompt changes loosen the "answer only from the FAQ, never guess" rule. Run the evals after any change to `faq.md`, the system prompt or the model, and confirm injection and unanswerable categories stay at 100%.
- **Single process only.** One uvicorn worker, one Railway replica: rate limiting and metrics are in-memory. Don't add workers or replicas without first replacing that state.
- **Tests must not call external model APIs.** Mock the client in `pytest`; only `evals/` hits the real API.
- **Do not run evals without my permission.** Evals cost money so do not run without explicit approval.

## Milestone Workflow
Each milestone in `plan.md` should be done as one PR in the following order:
1. **Test writing by subagent.** A fresh test-writer subagent should be spawned and given everything it needs to write the tests.  It is not provided implementation or your reasoning, letting it run independently with enough information to write the tests.
2. **Red check.** Run tests; should fail because of missing behavior not yet implemented for that milestone, not syntax errors.
3. **Implement.** Implement just enough to pass the tests.  If a test seems wrong, do not edit; explain why the test seems wrong and let me confirm.
4. **Verify with fresh subagent.** Give a verifier agent the milestone section and the diff.  It runs every verification command, checks the acceptance criteria for the milestone.
5. **Update docs.** Update the CLAUDE.md status line and any updated commands.
6. **User reviews.** I will review the changes before committing and merging the branch myself. 

## Out of scope
Per-user accounts, saved chat history, admin UI, live human handoff, contact-form backend, multi-language, hosted tracing, RAG, custom domain, Redis/shared state, multiple workers/replicas, fake model mode, load testing, browser E2E tests. 