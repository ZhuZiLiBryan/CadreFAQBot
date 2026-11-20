"""Environment-driven limits, read at call time."""

import os


def _int_env(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except ValueError:
        return default


def max_message_chars() -> int:
    return _int_env("MAX_MESSAGE_CHARS", 500)


def max_history_messages() -> int:
    return _int_env("MAX_HISTORY_MESSAGES", 6)
