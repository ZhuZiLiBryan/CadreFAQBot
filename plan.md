## Status
The exact milestones need to be fleshed out and the project needs to be scaffolded accordingly.

Cursory draft of a plan is:
Backend scaffolding + CI
Frontend scaffolding + CI
Chat contract (POST /api/chat schemas) without model with basic handling of errors (display error)
Light evaluation of model + System prompt with FAQ, prompt versioning
Docker + Railway deploy (MVP)
Rate limiting
Error handling based on error types (e.g. data errors with 422, rate limit errors 429, concurrency test)
Retry handling (exponential backoff with jitter for transient errors)
Evals on model + prompt


For each milestone, include a checklist of criteria that are to be checked off as a milestone finishes.

