"""The chat code path shared by `POST /api/chat` and the eval runner."""

from backend.faq import get_faq
from backend.guardrails import apply_guardrails
from backend.model_client import ModelClient, ModelResult
from backend.prompts import load_prompt
from backend.reply import assemble_reply
from backend.schemas import ChatRequest, ChatResponse


async def handle_chat(
    request: ChatRequest, client: ModelClient
) -> tuple[ChatResponse, ModelResult, list[str]]:
    """Call the model, apply output guardrails, and assemble the Reply.

    Also returns the raw model result and the guardrail reasons applied.
    """
    result = await client.complete(
        load_prompt(), [m.model_dump() for m in request.history], request.message
    )
    faq = get_faq()
    guarded, reasons = apply_guardrails(result, faq)
    return assemble_reply(guarded, faq), result, reasons
