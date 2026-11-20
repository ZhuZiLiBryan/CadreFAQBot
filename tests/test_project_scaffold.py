"""M1: the repository is an installable uv project with lint config, ignore
rules, an env template, and a backend CI workflow."""

import importlib
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def _gitignore_entries() -> set[str]:
    text = (ROOT / ".gitignore").read_text(encoding="utf-8")
    entries = set()
    for line in text.splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            entries.add(line.lstrip("/"))
    return entries


def _pyproject() -> dict:
    with (ROOT / "pyproject.toml").open("rb") as f:
        return tomllib.load(f)


@pytest.mark.parametrize("name", ["backend", "evals"])
def test_top_level_packages_are_importable(name):
    assert importlib.import_module(name) is not None


def test_uv_project_files_exist():
    assert (ROOT / "pyproject.toml").is_file()
    assert (ROOT / "uv.lock").is_file()
    assert (ROOT / ".python-version").is_file()


def test_python_version_is_3_12():
    version = (ROOT / ".python-version").read_text(encoding="utf-8").strip()

    assert version.startswith("3.12")


def test_dev_dependencies_include_pytest_httpx_and_ruff():
    config = _pyproject()
    groups = config.get("dependency-groups", {})
    legacy = config.get("tool", {}).get("uv", {}).get("dev-dependencies", [])
    declared = " ".join(str(item) for items in groups.values() for item in items)
    declared += " " + " ".join(str(item) for item in legacy)

    for package in ("pytest", "httpx", "ruff"):
        assert package in declared


def test_runtime_dependencies_include_fastapi():
    dependencies = _pyproject().get("project", {}).get("dependencies", [])

    assert any(str(dep).lower().startswith("fastapi") for dep in dependencies)


def test_ruff_is_configured_in_pyproject():
    assert "ruff" in _pyproject().get("tool", {})


@pytest.mark.parametrize(
    "variants",
    [
        {".env"},
        {".venv/", ".venv"},
        {"node_modules/", "node_modules"},
        {"frontend/dist/", "frontend/dist"},
        {"evals/results/", "evals/results"},
        {"__pycache__/", "__pycache__", "__pycache__/*", "**/__pycache__/"},
    ],
    ids=[".env", ".venv", "node_modules", "frontend/dist", "evals/results", "pycache"],
)
def test_gitignore_covers_required_paths(variants):
    assert _gitignore_entries() & variants


def test_env_example_is_committed_and_not_ignored():
    assert (ROOT / ".env.example").is_file()
    assert ".env.example" not in _gitignore_entries()


def test_env_example_has_no_real_secret_values():
    text = (ROOT / ".env.example").read_text(encoding="utf-8")

    assert "sk-" not in text


def test_ci_workflow_runs_backend_checks():
    workflow = ROOT / ".github" / "workflows" / "ci.yml"

    assert workflow.is_file()
    text = workflow.read_text(encoding="utf-8")
    assert "pull_request" in text
    assert "push" in text
    assert "main" in text
    assert "uv sync --locked" in text
    assert "uv run ruff check ." in text
    assert "uv run ruff format --check ." in text
    assert "uv run pytest" in text
