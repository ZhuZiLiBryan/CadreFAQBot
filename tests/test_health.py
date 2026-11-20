"""M1: the health endpoint is served by the FastAPI app and never needs a model."""

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.main import app

client = TestClient(app)


def test_app_is_a_fastapi_instance():
    assert isinstance(app, FastAPI)


def test_health_returns_200_with_exact_body():
    response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_health_is_json():
    response = client.get("/api/health")

    assert response.headers["content-type"].startswith("application/json")


def test_health_works_without_any_model_configuration(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("OPENROUTER_MODEL", raising=False)

    response = TestClient(app).get("/api/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_health_only_allows_get():
    response = client.post("/api/health")

    assert response.status_code == 405


def test_unknown_api_route_is_not_found():
    response = client.get("/api/does-not-exist")

    assert response.status_code == 404
