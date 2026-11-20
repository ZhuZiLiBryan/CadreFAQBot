# Citations are FAQ Entry IDs resolved by the server

The model cites FAQ Entries by number only; the server looks up each entry's question and Source URL and drops IDs that don't exist, and a Reply that claims to answer but has no valid Citation is downgraded to Unanswered. Links the model writes inside answer text are kept only when the URL appears in the FAQ, and emails and phone numbers only when they match the FAQ verbatim. We chose this over letting the model emit URLs (checked against an allowlist) because a public bot facing prompt injection must never show a link, price, or contact detail the FAQ doesn't back, and because ID-based Citations make eval scoring a set comparison instead of fuzzy URL matching.

## Consequences

- `faq.md` must stay in its strict machine-parsed format (numbered `###` entries, one `Sources:` line each); the server refuses to start otherwise.
- Renumbering FAQ Entries silently invalidates `expected_citations` in `evals/cases.yaml`; append new entries instead of renumbering.
