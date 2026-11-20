"""Parser for `prompt_files/faq.md`, the FAQ's strict machine-read format.

The server refuses to start when the file is malformed (see `plan.md` Shared spec
and `docs/adr/0001-server-resolved-citations.md`).
"""

import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlsplit

FAQ_PATH = Path(__file__).parent / "prompt_files" / "faq.md"

_ENTRY_HEADING = re.compile(r"^###\s+(\d+)\.\s+(\S.*?)\s*$")
_LINK = r"\[[^\]]+\]\([^)\s]+\)"
_SOURCES_LINE = re.compile(rf"^Sources:\s*{_LINK}(?:\s*,\s*{_LINK})*\s*$")
_LINK_PARTS = re.compile(r"\[([^\]]+)\]\(([^)\s]+)\)")
_ANY_URL = re.compile(r"https?://[^\s)\]>]+", re.IGNORECASE)


class FaqParseError(ValueError):
    """The FAQ file violates the format; the message names the line number."""


@dataclass(frozen=True)
class FaqSource:
    title: str
    url: str


@dataclass(frozen=True)
class FaqEntry:
    number: int
    question: str
    body: str
    sources: tuple[FaqSource, ...]


@dataclass(frozen=True)
class Faq:
    entries: dict[int, FaqEntry] = field(default_factory=dict)
    allowlist: frozenset[str] = frozenset()


def normalize_url(url: str) -> str:
    """Lowercase host, strip `www.` and trailing slash: the allowlist's key form."""
    parts = urlsplit(url.strip())
    host = (parts.hostname or "").lower().removeprefix("www.")
    port = f":{parts.port}" if parts.port else ""
    query = f"?{parts.query}" if parts.query else ""
    return f"{parts.scheme.lower()}://{host}{port}{parts.path.rstrip('/')}{query}"


@dataclass
class _Draft:
    line: int
    number: int
    question: str
    body: list[str] = field(default_factory=list)
    sources: list[FaqSource] | None = None


def parse_faq(text: str) -> Faq:
    entries: dict[int, FaqEntry] = {}
    allowlist: set[str] = set()
    draft: _Draft | None = None
    last_number = 0

    def check_urls(line: str, lineno: int) -> None:
        for _, target in _LINK_PARTS.findall(line):
            if not target.lower().startswith("https://"):
                raise FaqParseError(f"line {lineno}: URL must be https: {target}")
        for raw in _ANY_URL.findall(line):
            url = raw.rstrip(".,;:")
            if not url.lower().startswith("https://"):
                raise FaqParseError(f"line {lineno}: URL must be https: {url}")
            allowlist.add(normalize_url(url))

    def finish() -> None:
        nonlocal draft
        if draft is None:
            return
        if not draft.body:
            raise FaqParseError(f"line {draft.line}: entry {draft.number} has no body")
        if draft.sources is None:
            raise FaqParseError(
                f"line {draft.line}: entry {draft.number} has no Sources line"
            )
        entries[draft.number] = FaqEntry(
            number=draft.number,
            question=draft.question,
            body="\n".join(draft.body),
            sources=tuple(draft.sources),
        )
        draft = None

    for lineno, raw_line in enumerate(text.splitlines(), start=1):
        line = raw_line.strip()

        if line.startswith("### "):
            finish()
            match = _ENTRY_HEADING.match(line)
            if not match:
                raise FaqParseError(f"line {lineno}: malformed entry heading")
            number = int(match.group(1))
            if number < 1:
                raise FaqParseError(f"line {lineno}: entry number must be positive")
            if number in entries:
                raise FaqParseError(f"line {lineno}: duplicate entry number {number}")
            if number <= last_number:
                raise FaqParseError(
                    f"line {lineno}: entry number {number} is out of order"
                )
            check_urls(match.group(2), lineno)
            last_number = number
            draft = _Draft(line=lineno, number=number, question=match.group(2))
            continue

        if line.startswith("# ") or line.startswith("## "):
            finish()
            continue

        if draft is None or not line:
            continue

        if draft.sources is not None:
            raise FaqParseError(
                f"line {lineno}: Sources must be the last line of entry {draft.number}"
            )

        if line.startswith("Sources:"):
            check_urls(line, lineno)
            if not _SOURCES_LINE.match(line):
                raise FaqParseError(
                    f"line {lineno}: Sources must be comma-separated "
                    "[Title](https://...) links"
                )
            draft.sources = [
                FaqSource(title=title, url=url)
                for title, url in _LINK_PARTS.findall(line)
            ]
        else:
            check_urls(line, lineno)
            draft.body.append(line)

    finish()
    return Faq(entries=entries, allowlist=frozenset(allowlist))


def load_faq(path: Path | None = None) -> Faq:
    return parse_faq((path or FAQ_PATH).read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def get_faq() -> Faq:
    """The parsed FAQ, loaded once; called at startup so a bad file stops the app."""
    return load_faq()
