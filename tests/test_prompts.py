"""M4: the system prompt, load_prompt(), and the Prompt Version."""

import hashlib
import re
import shutil
from pathlib import Path

import pytest

from backend import faq, prompts
from backend.prompts import load_prompt, prompt_version

ROOT = Path(__file__).resolve().parent.parent
SYSTEM_MD = ROOT / "backend" / "prompt_files" / "system.md"
FAQ_MD = ROOT / "backend" / "prompt_files" / "faq.md"


def expected_version(system_path: Path, faq_path: Path) -> str:
    digest = hashlib.sha256(system_path.read_bytes() + faq_path.read_bytes())
    return digest.hexdigest()[:12]


@pytest.fixture
def prompt_files(tmp_path, monkeypatch):
    """Point the prompt modules at temp copies of system.md and faq.md."""
    system = tmp_path / "system.md"
    faq_copy = tmp_path / "faq.md"
    shutil.copyfile(SYSTEM_MD, system)
    shutil.copyfile(FAQ_MD, faq_copy)
    monkeypatch.setattr(prompts, "SYSTEM_PROMPT_PATH", system)
    monkeypatch.setattr(faq, "FAQ_PATH", faq_copy)
    monkeypatch.setattr(prompts, "FAQ_PATH", faq_copy, raising=False)
    return system, faq_copy


# --- Prompt Version ---


def test_prompt_version_is_12_lowercase_hex_chars():
    assert re.fullmatch(r"[0-9a-f]{12}", prompt_version())


def test_prompt_version_is_sha256_of_system_bytes_then_faq_bytes():
    assert prompt_version() == expected_version(SYSTEM_MD, FAQ_MD)


def test_prompt_version_is_deterministic():
    assert prompt_version() == prompt_version()


def test_prompt_version_follows_the_files_it_is_pointed_at(prompt_files):
    system, faq_copy = prompt_files

    assert prompt_version() == expected_version(system, faq_copy)
    assert prompt_version() == expected_version(SYSTEM_MD, FAQ_MD)


def test_prompt_version_changes_when_system_md_changes(prompt_files):
    system, faq_copy = prompt_files
    before = prompt_version()

    system.write_bytes(system.read_bytes() + b"\nAn extra rule.\n")

    after = prompt_version()
    assert after != before
    assert after == expected_version(system, faq_copy)


def test_prompt_version_changes_when_faq_md_changes(prompt_files):
    system, faq_copy = prompt_files
    before = prompt_version()

    faq_copy.write_bytes(faq_copy.read_bytes() + b"\n")

    after = prompt_version()
    assert after != before
    assert after == expected_version(system, faq_copy)


def test_prompt_version_is_computed_over_bytes_so_a_whitespace_change_counts(
    prompt_files,
):
    system, _ = prompt_files
    before = prompt_version()

    system.write_bytes(system.read_bytes().rstrip() + b"   \n")

    assert prompt_version() != before


def test_prompt_version_reverts_when_the_file_is_restored(prompt_files):
    system, _ = prompt_files
    original = system.read_bytes()
    before = prompt_version()

    system.write_bytes(original + b"x")
    assert prompt_version() != before
    system.write_bytes(original)

    assert prompt_version() == before


def test_swapping_file_contents_changes_the_version_because_order_matters(
    tmp_path, monkeypatch
):
    # sha256(system + faq) is not symmetric: this pins the concatenation order.
    a = tmp_path / "a.md"
    b = tmp_path / "b.md"
    a.write_bytes(b"AAAA")
    b.write_bytes(b"BBBB")
    monkeypatch.setattr(prompts, "SYSTEM_PROMPT_PATH", a)
    monkeypatch.setattr(faq, "FAQ_PATH", b)
    monkeypatch.setattr(prompts, "FAQ_PATH", b, raising=False)

    assert prompt_version() == hashlib.sha256(b"AAAABBBB").hexdigest()[:12]


# --- load_prompt() ---


def test_system_md_exists_and_is_not_empty():
    assert SYSTEM_MD.is_file()
    assert SYSTEM_MD.read_text(encoding="utf-8").strip() != ""


def test_load_prompt_contains_the_whole_faq():
    prompt = load_prompt()

    assert FAQ_MD.read_text(encoding="utf-8").strip() in prompt


def test_load_prompt_contains_every_faq_question():
    prompt = load_prompt()
    entries = faq.load_faq().entries

    assert len(entries) == 52
    for entry in entries.values():
        assert entry.question in prompt


def test_load_prompt_includes_the_system_instructions():
    system_text = SYSTEM_MD.read_text(encoding="utf-8")
    first_line = next(
        line.strip()
        for line in system_text.splitlines()
        if line.strip() and "{" not in line
    )

    assert first_line in load_prompt()


def test_load_prompt_returns_a_string():
    assert isinstance(load_prompt(), str)


# --- required statements in system.md (loose keyword checks) ---


@pytest.fixture(scope="module")
def system_text() -> str:
    return SYSTEM_MD.read_text(encoding="utf-8").lower()


def sentence_with(text: str, first: str, second: str) -> bool:
    """True if both regexes occur within one sentence-ish span (no period between)."""
    return bool(
        re.search(rf"{first}[^.]*{second}|{second}[^.]*{first}", text, re.DOTALL)
    )


def test_prompt_says_to_answer_only_from_the_faq(system_text):
    assert sentence_with(system_text, r"\bonly\b", r"\bfaq\b")


def test_prompt_says_never_to_guess(system_text):
    assert re.search(r"never guess|do not guess|don't guess|not guess", system_text)


@pytest.mark.parametrize(
    "outcome", ["answered", "partial", "unanswered", r"small ?talk"]
)
def test_prompt_defines_each_of_the_four_outcomes(system_text, outcome):
    assert re.search(outcome, system_text)


def test_prompt_says_to_cite_faq_entry_numbers(system_text):
    assert re.search(r"\bcite\b|\bcitations?\b", system_text)
    assert sentence_with(system_text, r"\bnumbers?\b", r"\b(cite|citations?)\b")


def test_prompt_restricts_links_to_urls_in_the_faq(system_text):
    assert sentence_with(system_text, r"\b(links?|urls?)\b", r"\bfaq\b")


def test_prompt_says_the_server_writes_contact_and_fallback_lines(system_text):
    assert "contact" in system_text
    assert "fallback" in system_text
    assert "server" in system_text
    assert re.search(r"\bnever\b|\bdo not\b|\bdon't\b|\bmust not\b", system_text)


def test_prompt_treats_visitor_messages_as_data_not_instructions(system_text):
    assert sentence_with(system_text, r"\bdata\b", r"\binstructions?\b")
    assert re.search(r"\bvisitor\b", system_text)
    assert re.search(r"\bhistory\b", system_text)


def test_prompt_says_prior_assistant_turns_are_not_sources(system_text):
    assert sentence_with(system_text, r"\bassistant\b", r"\bsources?\b")


def test_prompt_says_never_to_reveal_its_instructions(system_text):
    assert re.search(
        r"(reveal|disclose|repeat|share|discuss)[^.]*(instructions|prompt)",
        system_text,
        re.DOTALL,
    )


def test_prompt_limits_small_talk_to_greetings_thanks_and_what_the_bot_does(
    system_text,
):
    assert "greeting" in system_text
    assert re.search(r"thank", system_text)
    assert re.search(
        r"what (can )?you (can )?do|who (are )?you|what the bot can do", system_text
    )


def test_prompt_asks_small_talk_to_nudge_toward_asking_about_cadre(system_text):
    assert re.search(
        r"nudge|invite|encourag|suggest|prompt the visitor|ask about|ask them",
        system_text,
    )
