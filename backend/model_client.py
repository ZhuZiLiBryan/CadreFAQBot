"""The model seam: an async interface the chat route depends on.

`OpenRouterClient` calls OpenRouter through the `openai` SDK. Tests override
`get_model_client`; only `evals/` hits the real API.
"""

import json
import os
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Protocol

from openai import AsyncOpenAI, OpenAIError

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
OUTCOMES = ("answered", "partial", "unanswered", "smalltalk")

REPLY_JSON_SCHEMA: dict[str, Any] = {
    "name": "faq_reply",
    "strict": True,
    "schema": {
        "type": "object",
        "properties": {
            "outcome": {"type": "string", "enum": list(OUTCOMES)},
            "answer": {"type": "string"},
            "citations": {"type": "array", "items": {"type": "integer"}},
        },
        "required": ["outcome", "answer", "citations"],
        "additionalProperties": False,
    },
}


class UpstreamError(Exception):
    """The model was unreachable or unusable; surfaces as 503 `upstream_unavailable`."""


@dataclass(frozen=True)
class ModelResult:
    """The model reply schema plus metadata."""

    outcome: str
    answer: str
    citations: list[int]
    served_model: str
    tokens_in: int
    tokens_out: int


class ModelClient(Protocol):
    async def complete(
        self, system_prompt: str, history: list[dict], message: str
    ) -> ModelResult: ...


class InvalidModelOutput(Exception):
    """The model's text was not valid JSON for the model reply schema."""


def parse_reply(content: object) -> tuple[str, str, list[int]]:
    """Validate the model's text against the model reply schema."""
    if not isinstance(content, str) or not content.strip():
        raise InvalidModelOutput("empty content")
    try:
        data = json.loads(content)
    except ValueError as exc:
        raise InvalidModelOutput("not JSON") from exc
    if not isinstance(data, dict) or set(data) != {"outcome", "answer", "citations"}:
        raise InvalidModelOutput("wrong fields")
    outcome, answer, citations = data["outcome"], data["answer"], data["citations"]
    if outcome not in OUTCOMES or not isinstance(answer, str):
        raise InvalidModelOutput("bad outcome or answer")
    if not isinstance(citations, list) or not all(
        isinstance(n, int) and not isinstance(n, bool) for n in citations
    ):
        raise InvalidModelOutput("bad citations")
    return outcome, answer, citations


class OpenRouterClient:
    """OpenRouter via the openai SDK. SDK retries are off; M9 owns transport retries."""

    def __init__(self, api_key: str, model: str) -> None:
        self._model = model
        self._sdk = AsyncOpenAI(
            api_key=api_key, base_url=OPENROUTER_BASE_URL, max_retries=0
        )

    async def complete(
        self, system_prompt: str, history: list[dict], message: str
    ) -> ModelResult:
        messages = [
            {"role": "system", "content": system_prompt},
            *history,
            {"role": "user", "content": message},
        ]
        # Unparseable output gets exactly one more attempt.
        for attempt in range(2):
            try:
                response = await self._sdk.chat.completions.create(
                    model=self._model,
                    messages=messages,
                    response_format={
                        "type": "json_schema",
                        "json_schema": REPLY_JSON_SCHEMA,
                    },
                    extra_body={"provider": {"require_parameters": True}},
                )
            except OpenAIError as exc:
                raise UpstreamError(type(exc).__name__) from exc
            try:
                outcome, answer, citations = parse_reply(
                    response.choices[0].message.content
                )
            except (InvalidModelOutput, IndexError, AttributeError, TypeError) as exc:
                if attempt == 1:
                    raise UpstreamError("invalid model output") from exc
                continue
            usage = getattr(response, "usage", None)
            return ModelResult(
                outcome=outcome,
                answer=answer,
                citations=citations,
                served_model=getattr(response, "model", None) or "unknown",
                tokens_in=getattr(usage, "prompt_tokens", 0) or 0,
                tokens_out=getattr(usage, "completion_tokens", 0) or 0,
            )
        raise UpstreamError("invalid model output")  # unreachable; keeps types honest


def required_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"Required environment variable {name} is not set")
    return value


@lru_cache(maxsize=1)
def get_model_client() -> ModelClient:
    """FastAPI dependency: the real client, built once from the environment.

    Construction makes no network call, so validation (422) is unaffected.
    """
    return OpenRouterClient(
        api_key=required_env("OPENROUTER_API_KEY"),
        model=required_env("OPENROUTER_MODEL"),
    )
