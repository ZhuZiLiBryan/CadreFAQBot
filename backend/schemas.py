"""Pydantic models for the `/api/chat` contract (see `plan.md` Shared spec)."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, field_validator

from backend.config import max_history_messages, max_message_chars

Outcome = Literal["answered", "partial", "unanswered", "smalltalk"]

CONTACT_FORM_URL = "https://cadre.ai/contact"
CONTACT_EMAIL = "hello@gocadre.ai"
CONTACT_TEXT = "For more help, contact the Cadre team:"
FALLBACK_TEXT = "I don't have that information in Cadre's FAQ."


class HistoryMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: Literal["user", "assistant"]
    content: str

    @field_validator("content")
    @classmethod
    def _content_length(cls, value: str) -> str:
        if not 1 <= len(value) <= 2000:
            raise ValueError("content must be 1..2000 characters")
        return value


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message: str
    history: list[HistoryMessage] = []

    @field_validator("message")
    @classmethod
    def _message_length(cls, value: str) -> str:
        value = value.strip()
        limit = max_message_chars()
        if not 1 <= len(value) <= limit:
            raise ValueError(f"message must be 1..{limit} characters")
        return value

    @field_validator("history")
    @classmethod
    def _history_length(cls, value: list[HistoryMessage]) -> list[HistoryMessage]:
        limit = max_history_messages()
        if len(value) > limit:
            raise ValueError(f"history may hold at most {limit} messages")
        return value


class Source(BaseModel):
    title: str
    url: str


class Citation(BaseModel):
    faq_id: int
    question: str
    sources: list[Source]


class Contact(BaseModel):
    text: str = CONTACT_TEXT
    form_url: str = CONTACT_FORM_URL
    email: str = CONTACT_EMAIL


class ChatResponse(BaseModel):
    outcome: Outcome
    answer: str
    citations: list[Citation]
    contact: Contact | None


class ErrorResponse(BaseModel):
    error: Literal[
        "invalid_request",
        "rate_limited",
        "daily_limit",
        "upstream_unavailable",
        "internal_error",
        "not_found",
    ]
    message: str
    contact: Contact
