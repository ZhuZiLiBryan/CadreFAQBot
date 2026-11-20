"""The chat code path shared by `POST /api/chat` and the eval runner."""

from backend.faq import get_faq
from backend.model_client import ModelClient, ModelResult
from backend.prompts import load_prompt
from backend.reply import assemble_reply
from backend.schemas import ChatRequest, ChatResponse


async def handle_chat(
    request: ChatRequest, client: ModelClient
) -> tuple[ChatResponse, ModelResult]:
    """Call the model and assemble the Reply; also returns the raw model result."""
    result = await client.complete(
        load_prompt(), [m.model_dump() for m in request.history], request.message
    )
    return assemble_reply(result, get_faq()), result
