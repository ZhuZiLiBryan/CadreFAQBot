"""Reply assembly: the server resolves Citations and writes Contact/Fallback Lines."""

from backend.faq import Faq
from backend.model_client import ModelResult
from backend.schemas import FALLBACK_TEXT, ChatResponse, Citation, Contact, Source


def resolve_citations(numbers: list[int], faq: Faq) -> list[Citation]:
    """FAQ Entry numbers to Citations in model order; unknown/repeated ones drop."""
    citations: list[Citation] = []
    seen: set[int] = set()
    for number in numbers:
        entry = faq.entries.get(number)
        if entry is None or number in seen:
            continue
        seen.add(number)
        citations.append(
            Citation(
                faq_id=entry.number,
                question=entry.question,
                sources=[Source(title=s.title, url=s.url) for s in entry.sources],
            )
        )
    return citations


def assemble_reply(result: ModelResult, faq: Faq) -> ChatResponse:
    match result.outcome:
        case "unanswered":
            return ChatResponse(
                outcome="unanswered",
                answer=FALLBACK_TEXT,
                citations=[],
                contact=Contact(),
            )
        case "partial":
            return ChatResponse(
                outcome="partial",
                answer=result.answer,
                citations=resolve_citations(result.citations, faq),
                contact=Contact(),
            )
        case "answered" | "smalltalk" as outcome:
            return ChatResponse(
                outcome=outcome,
                answer=result.answer,
                citations=resolve_citations(result.citations, faq),
                contact=None,
            )
        case other:
            raise ValueError(f"Unknown outcome from model: {other!r}")
