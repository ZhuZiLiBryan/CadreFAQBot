"""System prompt construction. M3 placeholder; M4 adds `system.md`, Prompt Version."""

from backend.faq import FAQ_PATH


def load_prompt() -> str:
    return FAQ_PATH.read_text(encoding="utf-8")
