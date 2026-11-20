"""Map Prompt Versions (hashes) to the git commits that produced them.

    uv run python -m evals.prompt_versions            # table, newest first
    uv run python -m evals.prompt_versions --show HASH  # print that version's prompt

Derived from git history of `system.md` and `faq.md`, so nothing extra is
stored. A version only appears here once its files are committed; uncommitted
edits show up as `working tree`.
"""

import argparse
import subprocess
from dataclasses import dataclass
from pathlib import Path

from backend.prompts import version_of

ROOT = Path(__file__).resolve().parent.parent
SYSTEM_REL = "backend/prompt_files/system.md"
FAQ_REL = "backend/prompt_files/faq.md"


@dataclass(frozen=True)
class VersionRow:
    version: str
    commit: str  # short sha, or "working tree"
    date: str
    subject: str


def _git(root: Path, *args: str) -> bytes | None:
    done = subprocess.run(["git", *args], cwd=root, capture_output=True)
    return done.stdout if done.returncode == 0 else None


def _blob(root: Path, commit: str, rel: str) -> bytes | None:
    return _git(root, "show", f"{commit}:{rel}")


def history(root: Path = ROOT) -> list[VersionRow]:
    """Prompt Versions for the working tree and every commit touching the files.

    Newest first. Commits where either file doesn't exist yet are skipped. A
    version that several commits share (e.g. a revert) appears once per commit.
    """
    rows: list[VersionRow] = []
    system_now, faq_now = root / SYSTEM_REL, root / FAQ_REL
    if system_now.is_file() and faq_now.is_file():
        rows.append(
            VersionRow(
                version_of(system_now.read_bytes(), faq_now.read_bytes()),
                "working tree",
                "",
                "uncommitted state of the prompt files",
            )
        )
    log = _git(root, "log", "--format=%h%x09%cs%x09%s", "--", SYSTEM_REL, FAQ_REL)
    for line in (log or b"").decode("utf-8", "replace").splitlines():
        commit, date, subject = line.split("\t", 2)
        system, faq = _blob(root, commit, SYSTEM_REL), _blob(root, commit, FAQ_REL)
        if system is None or faq is None:
            continue
        rows.append(VersionRow(version_of(system, faq), commit, date, subject))
    return rows


def prompt_text_for(version: str, root: Path = ROOT) -> str | None:
    """system.md + faq.md of the first commit (or working tree) with this version."""
    for row in history(root):
        if row.version != version:
            continue
        if row.commit == "working tree":
            return (
                (root / SYSTEM_REL).read_text(encoding="utf-8")
                + "\n\n=== faq.md ===\n\n"
                + (root / FAQ_REL).read_text(encoding="utf-8")
            )
        system, faq = (
            _blob(root, row.commit, SYSTEM_REL),
            _blob(root, row.commit, FAQ_REL),
        )
        assert system is not None and faq is not None
        return system.decode("utf-8") + "\n\n=== faq.md ===\n\n" + faq.decode("utf-8")
    return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m evals.prompt_versions")
    parser.add_argument("--show", metavar="HASH", help="print this version's text")
    args = parser.parse_args(argv)

    if args.show:
        text = prompt_text_for(args.show)
        if text is None:
            print(f"No committed or working-tree version matches {args.show}")
            return 1
        print(text)
        return 0

    rows = history()
    print(f"{'version':<14}{'commit':<14}{'date':<12}subject")
    for row in rows:
        print(f"{row.version:<14}{row.commit:<14}{row.date:<12}{row.subject}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
