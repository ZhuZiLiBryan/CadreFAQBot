"""M3: the app refuses to start when faq.md is malformed."""

import pytest
from fastapi.testclient import TestClient

from backend import faq, main


def test_startup_fails_when_the_faq_is_malformed(tmp_path, monkeypatch):
    bad = tmp_path / "faq.md"
    bad.write_text("### 1. Q?\nBody with no sources line.\n", encoding="utf-8")
    monkeypatch.setattr(faq, "FAQ_PATH", bad)
    faq.get_faq.cache_clear()

    try:
        with pytest.raises(faq.FaqParseError, match=r"line \d+"):
            with TestClient(main.app):
                pass
    finally:
        faq.get_faq.cache_clear()
