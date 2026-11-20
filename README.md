Design summary

Knowledge
- The FAQ moves to backend/prompt_files/faq.md in a strict numbered format, and each entry gets its own Source: link(s).
- The server parses the FAQ at startup and refuses to start if the format is broken.
- Content fixes:
  - #52 now cites the homepage partner section and adds Meta; the other partners stay.
  - #4 matches #29.
  - The typo in #49 is fixed.
- system.md sits next to faq.md, and load_prompt() lives in backend/prompts.py.
- The Prompt Version is a short sha256 hash of system.md + faq.md.

Model
- The openai SDK talks to OpenRouter, with OPENROUTER_MODEL=openrouter/free for now and a cheap paid model swapped in later through the env var.
- Responses use response_format json_schema with require_parameters: true, and no streaming.
- The served model (response.model) is logged when the response includes it.

Reply contract
- The model returns {outcome: answered | partial | unanswered | smalltalk, answer, citations: [faq_id]}.
- The server turns each cited ID into {faq_id, question, url}.
- The server writes every Contact Line and Fallback Line:
  - Partial Replies get the Contact Line appended.
  - Unanswered Replies are replaced with the Fallback Line.
  - The Contact Line points to the contact form and hello@gocadre.ai.
- Follow-ups: the client sends the last 6 messages and the server keeps no state.

Output guardrails
- Unknown citation IDs are dropped. An Answered or Partial Reply left with zero valid citations becomes Unanswered.
- Links: markdown links are allowed only to URLs that appear in the FAQ, and emails or phone numbers must match the FAQ word for word.
- Length caps: 1,200 characters for answers.
- Small Talk: at most 300 characters, with no citations, links or digits.
- Failures: schema-invalid output is retried once, and every downgrade is logged with a reason.

Frontend
- Answers are plain text, except that allowlisted [text](url) links are rendered.
- Each answer shows a list of Citations, and the Contact Line appears as its own block.
- The UI has a welcome message, example question chips and the privacy notice.
- Error messages differ for 422, 429 and 503.

Limits and errors
- 10 requests per minute per IP, using X-Forwarded-For.
- A daily cap of 1,000 requests, 500 characters per message, and at most 6 history messages, all changeable through env vars.
- Retries: on 429, 5xx, timeouts and connection errors, with 3 attempts, full-jitter backoff, 15s per attempt and a 30s overall limit.
- Errors: 400, 401 and 403 are not retried and return 500. Exhausted retries return 503 with the Contact Line.

Evals
- Categories: answerable, partial, unanswerable, injection, smalltalk and smalltalk_injection.
- A case passes when its Outcome matches and its citations include an expected ID.
- --repeat N re-runs cases, with a default of 1.
- Reports include mean and p50/p95/p99 latency, token counts, and results per category and per model.
- Results are written as JSONL plus a markdown report to a git-ignored evals/results/, for grading by hand. There is no LLM judge.

Ops
- /api/health checks the FAQ parse and env vars without calling the model.
- /api/metrics requires a bearer token and is turned off if METRICS_TOKEN isn't set.
- The container runs uvicorn with 1 worker on $PORT.
- GitHub Actions runs lint, tests, build and a Docker build check on PRs. Evals don't run in CI.