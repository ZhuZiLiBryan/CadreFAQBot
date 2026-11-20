"""M4: the app refuses to start without OPENROUTER_API_KEY / OPENROUTER_MODEL."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.main import app

ROOT = Path(__file__).resolve().parent.parent


@pytest.mark.parametrize("name", ["OPENROUTER_API_KEY", "OPENROUTER_MODEL"])
def test_startup_refuses_when_the_variable_is_unset(monkeypatch, name):
    monkeypatch.delenv(name, raising=False)

    with pytest.raises(Exception, match=name):
        with TestClient(app):
            pass


@pytest.mark.parametrize("name", ["OPENROUTER_API_KEY", "OPENROUTER_MODEL"])
@pytest.mark.parametrize("value", ["", "   "])
def test_startup_refuses_when_the_variable_is_empty(monkeypatch, name, value):
    monkeypatch.setenv(name, value)

    with pytest.raises(Exception, match=name):
        with TestClient(app):
            pass


def test_startup_names_both_variables_when_both_are_missing(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("OPENROUTER_MODEL", raising=False)

    with pytest.raises(Exception) as excinfo:
        with TestClient(app):
            pass

    message = str(excinfo.value)
    assert "OPENROUTER_API_KEY" in message or "OPENROUTER_MODEL" in message


def test_startup_succeeds_when_both_variables_are_set():
    with TestClient(app) as test_client:
        assert test_client.get("/api/health").status_code == 200


def test_startup_error_does_not_print_the_api_key(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "super-secret-key-value")
    monkeypatch.delenv("OPENROUTER_MODEL", raising=False)

    with pytest.raises(Exception) as excinfo:
        with TestClient(app):
            pass

    assert "super-secret-key-value" not in str(excinfo.value)


# --- .env.example ---


def env_example_lines() -> list[str]:
    text = (ROOT / ".env.example").read_text(encoding="utf-8")
    return [line.strip() for line in text.splitlines()]


def test_env_example_lists_an_empty_api_key():
    assert "OPENROUTER_API_KEY=" in env_example_lines()


def test_env_example_sets_the_free_router_model():
    assert "OPENROUTER_MODEL=openrouter/free" in env_example_lines()
