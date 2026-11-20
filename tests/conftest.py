"""Shared fixtures. No test may reach a real model API or the network."""

import pytest


@pytest.fixture(autouse=True)
def model_env(monkeypatch):
    """Dummy model configuration so the app's startup check passes.

    Tests that need the variables missing call ``monkeypatch.delenv`` themselves
    (this fixture runs first).
    """
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key-not-real")
    monkeypatch.setenv("OPENROUTER_MODEL", "test/model-from-env")
