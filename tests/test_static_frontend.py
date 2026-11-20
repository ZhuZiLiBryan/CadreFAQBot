"""M5: FastAPI serves the built frontend (with SPA fallback) next to the API.

The built frontend directory comes from ``FRONTEND_DIST`` and is resolved when
``backend.main`` builds the app, so each test sets the variable and reloads the
module. No real frontend build is needed: tests use a fake dist in ``tmp_path``.
"""

import importlib
import os
from contextlib import contextmanager
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import backend.main

REPO_ROOT = Path(__file__).resolve().parent.parent

INDEX_MARKER = "CADRE-FAKE-INDEX-MARKER-7f3a"
JS_MARKER = "console.log('CADRE-FAKE-ASSET-MARKER-91bc');"
SECRET_MARKER = "OUTSIDE-DIST-SECRET-5d2e"


@contextmanager
def app_with_dist(dist):
    """Reload ``backend.main`` with FRONTEND_DIST set, then restore the module."""
    previous = os.environ.get("FRONTEND_DIST")
    os.environ["FRONTEND_DIST"] = str(dist)
    try:
        module = importlib.reload(backend.main)
        yield module.app
    finally:
        if previous is None:
            os.environ.pop("FRONTEND_DIST", None)
        else:
            os.environ["FRONTEND_DIST"] = previous
        importlib.reload(backend.main)


@pytest.fixture
def dist(tmp_path):
    """A fake built frontend, with a secret file placed *outside* the dist dir."""
    site = tmp_path / "site"
    (site / "assets").mkdir(parents=True)
    (site / "index.html").write_text(
        f"<!doctype html><html><body><div id='root'>{INDEX_MARKER}</div></body></html>",
        encoding="utf-8",
    )
    (site / "assets" / "app.js").write_text(JS_MARKER, encoding="utf-8")
    (tmp_path / "secret.txt").write_text(SECRET_MARKER, encoding="utf-8")
    return site


@pytest.fixture
def client(dist):
    with app_with_dist(dist) as app:
        with TestClient(app) as test_client:
            yield test_client


def test_root_serves_index_html(client):
    response = client.get("/")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert INDEX_MARKER in response.text


def test_assets_are_served(client):
    response = client.get("/assets/app.js")

    assert response.status_code == 200
    assert JS_MARKER in response.text
    assert INDEX_MARKER not in response.text


def test_deep_non_api_path_falls_back_to_index_html(client):
    response = client.get("/some/deep/path")

    assert response.status_code == 200
    assert INDEX_MARKER in response.text


def test_health_still_returns_the_json_body(client):
    response = client.get("/api/health")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")
    body = response.json()
    assert body["status"] == "ok"
    assert set(body) == {"status", "prompt_version", "faq_entries"}


def test_unknown_api_path_is_a_json_not_found_not_index_html(client):
    response = client.get("/api/x")

    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/json")
    assert response.json()["error"] == "not_found"
    assert INDEX_MARKER not in response.text


def test_chat_is_still_routed_to_the_api(client):
    response = client.post("/api/chat", json={})

    assert response.status_code == 422
    assert response.json()["error"] == "invalid_request"
    assert INDEX_MARKER not in response.text


@pytest.mark.parametrize(
    "path",
    [
        "/../secret.txt",
        "/..%2fsecret.txt",
        "/..%2f..%2fpyproject.toml",
        "/%2e%2e/secret.txt",
        "/%2e%2e%2f%2e%2e%2fpyproject.toml",
        "/assets/../../secret.txt",
        "/assets/..%2f..%2fsecret.txt",
        "/../pyproject.toml",
    ],
)
def test_path_traversal_never_serves_files_outside_the_dist_dir(client, path):
    response = client.get(path)

    assert SECRET_MARKER not in response.text
    assert "[project]" not in response.text
    assert "uvicorn" not in response.text


@pytest.mark.parametrize("path", ["/%00", "/a%00b", "/assets/%00.js"])
def test_encoded_null_byte_is_a_404_not_a_server_error(client, path):
    assert client.get(path).status_code == 404


def test_missing_frontend_dist_still_starts_and_serves_the_api(tmp_path):
    missing = tmp_path / "does-not-exist"

    with app_with_dist(missing) as app:
        with TestClient(app) as test_client:
            health = test_client.get("/api/health")
            unknown = test_client.get("/api/unknown")

    assert health.status_code == 200
    assert health.json()["status"] == "ok"
    assert unknown.status_code == 404
    assert unknown.headers["content-type"].startswith("application/json")
    assert unknown.json()["error"] == "not_found"


def test_missing_frontend_dist_serves_no_static_files(tmp_path):
    with app_with_dist(tmp_path / "does-not-exist") as app:
        response = TestClient(app).get("/some/deep/path")

    assert response.status_code == 404
    assert INDEX_MARKER not in response.text


def test_default_frontend_dist_is_frontend_dist_under_the_repo_root(monkeypatch):
    """Without FRONTEND_DIST the app looks in <repo>/frontend/dist.

    Works whether or not the frontend was built locally: with a build, ``/`` is
    HTML; without one, the API must still work.
    """
    monkeypatch.delenv("FRONTEND_DIST", raising=False)
    try:
        module = importlib.reload(backend.main)
        test_client = TestClient(module.app)
        assert test_client.get("/api/health").status_code == 200
        if (REPO_ROOT / "frontend" / "dist" / "index.html").is_file():
            root = test_client.get("/")
            assert root.status_code == 200
            assert root.headers["content-type"].startswith("text/html")
    finally:
        importlib.reload(backend.main)
