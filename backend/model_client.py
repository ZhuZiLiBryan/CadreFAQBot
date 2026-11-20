"""The model seam: an async interface the chat route depends on.

M3 has no real implementation; tests override `get_model_client`. M4 adds the
OpenRouter client.
"""

from dataclasses import dataclass
from typing import Protocol


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


class _UnconfiguredClient:
    async def complete(
        self, system_prompt: str, history: list[dict], message: str
    ) -> ModelResult:
        raise RuntimeError("No model client is configured")


def get_model_client() -> ModelClient:
    """FastAPI dependency. No real client until M4.

    Returns a client that fails when used (-> 500) rather than raising here, so
    request validation (422) still runs before the model is ever needed.
    """
    return _UnconfiguredClient()
