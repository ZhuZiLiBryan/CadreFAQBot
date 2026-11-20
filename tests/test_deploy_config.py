"""M5: deployment files (Dockerfile, .dockerignore, railway.toml, CI job).

Text-based checks only: no Docker, no network.
"""

import re
import tomllib
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent


def read(relative: str) -> str:
    path = REPO_ROOT / relative
    assert path.is_file(), f"{relative} is missing"
    return path.read_text(encoding="utf-8")


def instructions(dockerfile: str) -> list[str]:
    """Dockerfile instructions with comments dropped and continuations joined."""
    lines = []
    for raw in dockerfile.replace("\\\r\n", " ").replace("\\\n", " ").splitlines():
        line = raw.strip()
        if line and not line.startswith("#"):
            lines.append(line)
    return lines


@pytest.fixture(scope="module")
def dockerfile() -> str:
    return read("Dockerfile")


# --- Dockerfile ---------------------------------------------------------------


def test_dockerfile_is_multi_stage(dockerfile):
    froms = [i for i in instructions(dockerfile) if i.upper().startswith("FROM ")]

    assert len(froms) >= 2


def test_dockerfile_uses_a_node_22_stage(dockerfile):
    froms = [i for i in instructions(dockerfile) if i.upper().startswith("FROM ")]

    assert any(re.search(r"node:22", f, re.IGNORECASE) for f in froms)


def test_dockerfile_uses_a_python_3_12_stage(dockerfile):
    froms = [i for i in instructions(dockerfile) if i.upper().startswith("FROM ")]

    assert any(re.search(r"python:3\.12", f, re.IGNORECASE) for f in froms)


@pytest.mark.parametrize(
    "fragment",
    ["npm ci", "npm run build", "uv sync --locked --no-dev"],
)
def test_dockerfile_runs_the_locked_install_and_build_steps(dockerfile, fragment):
    assert fragment in dockerfile


def test_dockerfile_runs_as_a_non_root_user(dockerfile):
    users = [
        i.split(None, 1)[1].strip()
        for i in instructions(dockerfile)
        if i.upper().startswith("USER ")
    ]

    assert users, "no USER directive"
    final = users[-1].split(":")[0]
    assert final not in {"root", "0"}


def test_dockerfile_starts_one_uvicorn_worker_on_the_port_env_var(dockerfile):
    assert "uvicorn" in dockerfile
    assert "backend.main:app" in dockerfile
    assert "--workers 1" in dockerfile
    assert "--host 0.0.0.0" in dockerfile
    assert "${PORT:-8000}" in dockerfile


def test_dockerfile_does_not_copy_the_env_file(dockerfile):
    for line in instructions(dockerfile):
        if line.upper().startswith(("COPY ", "ADD ")):
            args = line.split()[1:]
            assert not any(
                a in {".env", "./.env"} or a.endswith("/.env") for a in args
            ), line


@pytest.mark.parametrize("name", ["OPENROUTER_API_KEY", "OPENROUTER_MODEL"])
def test_dockerfile_does_not_bake_in_model_configuration(dockerfile, name):
    for line in instructions(dockerfile):
        if line.upper().startswith(("ENV ", "ARG ")):
            assert name not in line, line


# --- .dockerignore ------------------------------------------------------------


@pytest.mark.parametrize(
    "entry",
    [".env", ".git", ".venv", "node_modules", "frontend/dist", "evals/results"],
)
def test_dockerignore_excludes(entry):
    entries = {
        line.strip().strip("/")
        for line in read(".dockerignore").splitlines()
        if line.strip() and not line.strip().startswith("#")
    }

    assert any(e == entry or e == f"**/{entry}" for e in entries), entry


# --- railway.toml -------------------------------------------------------------


@pytest.fixture(scope="module")
def railway() -> dict:
    return tomllib.loads(read("railway.toml"))


def test_railway_builds_with_the_dockerfile(railway):
    assert railway["build"]["builder"].upper() == "DOCKERFILE"


def test_railway_health_check_is_the_api_health_endpoint(railway):
    assert railway["deploy"]["healthcheckPath"] == "/api/health"


def test_railway_runs_exactly_one_replica(railway):
    assert railway["deploy"]["numReplicas"] == 1


def test_railway_config_contains_no_secret_values():
    text = read("railway.toml")

    assert "sk-" not in text
    assert not re.search(r"OPENROUTER_API_KEY\s*=", text)


# --- CI -----------------------------------------------------------------------


def test_ci_has_a_job_that_builds_the_docker_image():
    workflow = yaml.safe_load(read(".github/workflows/ci.yml"))
    jobs = workflow["jobs"]

    other_jobs = {
        name: job for name, job in jobs.items() if name not in {"backend", "frontend"}
    }
    assert other_jobs, "expected a third job besides backend and frontend"
    assert any(
        "docker build" in step.get("run", "")
        for job in other_jobs.values()
        for step in job["steps"]
    )


def test_ci_keeps_the_backend_and_frontend_jobs():
    workflow = yaml.safe_load(read(".github/workflows/ci.yml"))

    assert {"backend", "frontend"} <= set(workflow["jobs"])
