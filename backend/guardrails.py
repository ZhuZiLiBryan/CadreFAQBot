"""Output guardrails: applied to the model's reply before Reply assembly.

The server is the only place the FAQ URL allowlist is enforced (see `plan.md` M6).
"""

import re
from dataclasses import replace

from backend.faq import Faq, normalize_url
from backend.model_client import ModelResult
from backend.reply import resolve_citations

MAX_ANSWER_CHARS = 1200
SMALLTALK_MAX_CHARS = 300
SMALLTALK_GREETING = (
    "Hi! I can answer questions about Cadre AI's services, the AI Maturity Index, "
    "industries, and how to get in touch. What would you like to know?"
)

_MD_LINK = re.compile(r"\[([^\]]*)\]\(([^)\s]*)\)")
_BARE_URL = re.compile(r"https?://[^\s)\]>]+", re.IGNORECASE)
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
_PHONE = re.compile(r"(?<![\w/.@-])\+?\(?\d[\d\s().-]{5,}\d(?!\w)")
_TRAILING_PUNCT = ".,;:!?"


def _faq_text(faq: Faq) -> str:
    parts: list[str] = []
    for entry in faq.entries.values():
        parts.append(entry.question)
        parts.append(entry.body)
        parts.extend(f"{s.title} {s.url}" for s in entry.sources)
    return "\n".join(parts)


def _allowed(url: str, faq: Faq) -> bool:
    return normalize_url(url) in faq.allowlist


def _strip_links(text: str, faq: Faq, reasons: list[str]) -> str:
    def repl(match: re.Match[str]) -> str:
        # Link text that itself shows a URL could mislead, so drop the link.
        if _allowed(match.group(2), faq) and not _BARE_URL.search(match.group(1)):
            return match.group(0)
        _add(reasons, "link_not_allowed")
        return match.group(1)

    return _MD_LINK.sub(repl, text)


def _strip_bare_urls(text: str, faq: Faq, reasons: list[str]) -> str:
    def repl(match: re.Match[str]) -> str:
        raw = match.group(0)
        url = raw.rstrip(_TRAILING_PUNCT)
        if _allowed(url, faq):
            return raw
        _add(reasons, "url_not_allowed")
        return raw[len(url) :]

    # Skip URLs inside kept markdown links: only scan the text between links.
    out: list[str] = []
    last = 0
    for link in _MD_LINK.finditer(text):
        out.append(_BARE_URL.sub(repl, text[last : link.start()]))
        out.append(link.group(0))
        last = link.end()
    out.append(_BARE_URL.sub(repl, text[last:]))
    return "".join(out)


# Known limitation: removing an email from link text can leave an empty link.
# Take [hello@evil.com](https://cadre.ai). The link is allowlisted, so it is
# kept. The email step then strips the address from the text, leaving
# [](https://cadre.ai). The frontend only turns a link with non-empty text into
# an anchor, so the Visitor sees the literal characters [](https://cadre.ai):
# ugly but safe, because nothing unbacked gets through.
def _strip_contacts(text: str, faq_text: str, reasons: list[str]) -> str:
    def email_repl(match: re.Match[str]) -> str:
        if match.group(0) in faq_text:
            return match.group(0)
        _add(reasons, "contact_not_allowed")
        return ""

    def phone_repl(match: re.Match[str]) -> str:
        value = match.group(0)
        if sum(c.isdigit() for c in value) < 10 or value in faq_text:
            return value
        _add(reasons, "contact_not_allowed")
        return ""

    return _PHONE.sub(phone_repl, _EMAIL.sub(email_repl, text))


def _truncate(text: str, reasons: list[str]) -> str:
    if len(text) <= MAX_ANSWER_CHARS:
        return text
    _add(reasons, "answer_truncated")
    room = MAX_ANSWER_CHARS - 1
    cut = text[:room]
    if not text[room].isspace():
        boundary = max(cut.rfind(" "), cut.rfind("\n"), cut.rfind("\t"))
        if boundary > 0:
            cut = cut[:boundary]
    return cut.rstrip() + "…"


def _smalltalk_is_risky(text: str) -> bool:
    return (
        len(text) > SMALLTALK_MAX_CHARS
        or bool(_BARE_URL.search(text))
        or bool(_MD_LINK.search(text))
        or bool(_EMAIL.search(text))
        or any(c.isdigit() for c in text)
        or "$" in text
    )


def _add(reasons: list[str], reason: str) -> None:
    if reason not in reasons:
        reasons.append(reason)


def apply_guardrails(result: ModelResult, faq: Faq) -> tuple[ModelResult, list[str]]:
    """Return the (possibly modified) model result and the reasons applied."""
    reasons: list[str] = []

    if result.outcome == "smalltalk":
        answer = result.answer
        if _smalltalk_is_risky(answer):
            answer = SMALLTALK_GREETING
            reasons.append("smalltalk_replaced")
        return replace(result, answer=answer, citations=[]), reasons

    if result.outcome == "unanswered":
        return result, reasons

    outcome = result.outcome
    if not resolve_citations(result.citations, faq):
        outcome = "unanswered"
        reasons.append("no_valid_citations")

    cleaned = _strip_links(result.answer, faq, reasons)
    cleaned = _strip_bare_urls(cleaned, faq, reasons)
    cleaned = _strip_contacts(cleaned, _faq_text(faq), reasons)
    if cleaned != result.answer:
        # Removals can leave doubled or trailing spaces.
        cleaned = re.sub(r"[ \t]{2,}", " ", cleaned)
        cleaned = re.sub(r"[ \t]+$", "", cleaned, flags=re.MULTILINE)
    answer = _truncate(cleaned, reasons)

    return replace(result, outcome=outcome, answer=answer), reasons
