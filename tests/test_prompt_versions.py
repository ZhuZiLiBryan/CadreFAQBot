"""Prompt Version history derived from git, against a throwaway repo."""

import subprocess
from pathlib import Path

import pytest

from backend.prompts import version_of
from evals.prompt_versions import FAQ_REL, SYSTEM_REL, history, prompt_text_for


def git(root: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@t", *args],
        cwd=root,
        check=True,
        capture_output=True,
    )


def write(root: Path, rel: str, text: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.encode())


@pytest.fixture
def repo(tmp_path):
    git(tmp_path, "init", "-q")
    git(tmp_path, "config", "core.autocrlf", "false")
    write(tmp_path, FAQ_REL, "faq v1\n")
    git(tmp_path, "add", ".")
    git(tmp_path, "commit", "-q", "-m", "faq only")
    write(tmp_path, SYSTEM_REL, "system v1\n")
    git(tmp_path, "add", ".")
    git(tmp_path, "commit", "-q", "-m", "add system prompt")
    write(tmp_path, SYSTEM_REL, "system v2\n")
    git(tmp_path, "add", ".")
    git(tmp_path, "commit", "-q", "-m", "tighten system prompt")
    return tmp_path


def test_each_commit_maps_to_its_hash_and_older_commits_without_both_files_skip(repo):
    rows = history(repo)

    committed = [r for r in rows if r.commit != "working tree"]
    assert [r.subject for r in committed] == [
        "tighten system prompt",
        "add system prompt",
    ]
    assert committed[0].version == version_of(b"system v2\n", b"faq v1\n")
    assert committed[1].version == version_of(b"system v1\n", b"faq v1\n")


def test_uncommitted_edit_shows_as_working_tree(repo):
    write(repo, SYSTEM_REL, "system draft\n")

    rows = history(repo)

    assert rows[0].commit == "working tree"
    assert rows[0].version == version_of(b"system draft\n", b"faq v1\n")


def test_prompt_text_for_an_old_version(repo):
    old = version_of(b"system v1\n", b"faq v1\n")

    text = prompt_text_for(old, repo)

    assert text is not None and "system v1" in text and "faq v1" in text


def test_unknown_version_returns_none(repo):
    assert prompt_text_for("000000000000", repo) is None
