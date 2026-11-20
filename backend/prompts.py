"""System prompt construction and the Prompt Version.

The system prompt is `prompt_files/system.md` with `faq.md` inserted at the
`{{FAQ}}` placeholder. Both paths are read at call time.
"""

import hashlib
from pathlib import Path

from backend import faq

SYSTEM_PROMPT_PATH = Path(__file__).parent / "prompt_files" / "system.md"
FAQ_PLACEHOLDER = "{{FAQ}}"


def load_prompt() -> str:
    system = SYSTEM_PROMPT_PATH.read_text(encoding="utf-8").strip()
    faq_text = faq.FAQ_PATH.read_text(encoding="utf-8").strip()
    return system.replace(FAQ_PLACEHOLDER, faq_text)


def version_of(system_bytes: bytes, faq_bytes: bytes) -> str:
    """First 12 hex chars of sha256 over `system.md` bytes + `faq.md` bytes."""
    return hashlib.sha256(system_bytes + faq_bytes).hexdigest()[:12]


def prompt_version() -> str:
    return version_of(SYSTEM_PROMPT_PATH.read_bytes(), faq.FAQ_PATH.read_bytes())
