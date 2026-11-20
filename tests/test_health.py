"""The health endpoint is served by the FastAPI app and never needs a model.

M4: it also reports the Prompt Version and the number of FAQ Entries.
"""

import hashlib
import re
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.main import app
from backend.model_client import get_model_client

client = TestClient(app)

PROMPT_DIR = Path(__file__).resolve().parent.parent / "backend" / "prompt_files"


def computed_prompt_version() -> str:
    data = (PROMPT_DIR / "system.md").read_bytes() + (
        PROMPT_DIR / "faq.md"
    ).read_bytes()
    return hashlib.sha256(data).hexdigest()[:12]


def test_app_is_a_fastapi_instance():
    assert isinstance(app, FastAPI)


def test_health_returns_200_with_status_prompt_version_and_faq_entries():
    response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "prompt_version": computed_prompt_version(),
        "faq_entries": 52,
    }


def test_health_prompt_version_is_12_hex_chars():
    body = client.get("/api/health").json()

    assert re.fullmatch(r"[0-9a-f]{12}", body["prompt_version"])


def test_health_reports_52_faq_entries():
    assert client.get("/api/health").json()["faq_entries"] == 52


def test_health_is_json():
    response = client.get("/api/health")

    assert response.headers["content-type"].startswith("application/json")


def test_health_works_without_any_model_configuration(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("OPENROUTER_MODEL", raising=False)

    response = TestClient(app).get("/api/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["prompt_version"] == computed_prompt_version()
    assert body["faq_entries"] == 52


def test_health_never_calls_the_model():
    class ExplodingClient:
        calls = 0

        async def complete(self, *args, **kwargs):
            ExplodingClient.calls += 1
            raise AssertionError("health must not call the model")

    app.dependency_overrides[get_model_client] = lambda: ExplodingClient()
    try:
        with TestClient(app) as test_client:
            response = test_client.get("/api/health")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert ExplodingClient.calls == 0


def test_health_only_allows_get():
    response = client.post("/api/health")

    assert response.status_code == 405


def test_unknown_api_route_is_not_found():
    response = client.get("/api/does-not-exist")

    assert response.status_code == 404
