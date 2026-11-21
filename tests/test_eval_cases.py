"""M8: content requirements for ``evals/cases.yaml`` (pure; no network).

Assumed interface in ``evals.run``:
  - load_cases(path=None) -> list[dict]   (default: evals/cases.yaml; unchanged)
Case fields are those already documented in ``evals/cases.yaml``: id, category,
question, optional history, expected_outcome (str or list), expected_citations.

Requirements checked here (plan.md, M8):
  - at least 12 answerable, 4 partial, 6 unanswerable, 6 injection,
    3 smalltalk, 3 smalltalk_injection cases
  - every ``## `` section of ``backend/prompt_files/faq.md`` is covered by at
    least one answerable case whose expected_citations include an entry of it
  - unanswerable near-misses: client sign-in vs the Maturity Index portal, and
    office-hours timezone (matched by keywords in the question)
  - injection: one case with a forged assistant turn in ``history``, one that
    asks to reveal the prompt
  - every case is a valid ``ChatRequest`` (message and history limits)
"""

import re
from collections import Counter
from pathlib import Path

import pytest

from backend.schemas import ChatRequest
from evals.run import load_cases

FAQ_PATH = (
    Path(__file__).resolve().parent.parent / "backend" / "prompt_files" / "faq.md"
)

MINIMUMS = {
    "answerable": 12,
    "partial": 4,
    "unanswerable": 6,
    "injection": 6,
    "smalltalk": 3,
    "smalltalk_injection": 3,
}


def faq_sections() -> dict[str, set[int]]:
    """Map each ``## `` section heading in faq.md to its entry numbers."""
    sections: dict[str, set[int]] = {}
    current = None
    for line in FAQ_PATH.read_text(encoding="utf-8").splitlines():
        if line.startswith("## "):
            current = line[3:].strip()
            sections[current] = set()
        elif current is not None:
            match = re.match(r"### (\d+)\. ", line)
            if match:
                sections[current].add(int(match.group(1)))
    return sections


def outcomes_of(case: dict) -> list[str]:
    expected = case["expected_outcome"]
    return [expected] if isinstance(expected, str) else list(expected)


def in_category(category: str) -> list[dict]:
    return [c for c in load_cases() if c["category"] == category]


# --- sanity of the helper itself ---


def test_faq_has_sections_with_entries():
    sections = faq_sections()

    assert len(sections) >= 5
    assert all(entries for entries in sections.values())


# --- counts ---


@pytest.mark.parametrize(("category", "minimum"), sorted(MINIMUMS.items()))
def test_each_category_has_at_least_its_minimum_number_of_cases(category, minimum):
    counts = Counter(c["category"] for c in load_cases())

    assert counts[category] >= minimum, f"{category}: {counts[category]} < {minimum}"


def test_ids_and_questions_are_unique():
    cases = load_cases()
    ids = [c["id"] for c in cases]
    questions = [c["question"].strip().lower() for c in cases]

    assert len(ids) == len(set(ids))
    assert len(questions) == len(set(questions))


# --- answerable: every FAQ section covered ---


def test_every_faq_section_is_covered_by_an_answerable_case():
    cited = {n for c in in_category("answerable") for n in c["expected_citations"]}

    uncovered = [
        name for name, entries in faq_sections().items() if not (entries & cited)
    ]

    assert uncovered == [], f"no answerable case cites an entry of: {uncovered}"


def test_answerable_cases_expect_answered_with_citations():
    for c in in_category("answerable"):
        assert "answered" in outcomes_of(c), c["id"]
        assert c["expected_citations"], c["id"]


def test_partial_cases_expect_partial_with_citations():
    for c in in_category("partial"):
        assert outcomes_of(c) == ["partial"], c["id"]
        assert c["expected_citations"], c["id"]


# --- unanswerable ---


def test_unanswerable_cases_expect_unanswered_and_no_citations():
    for c in in_category("unanswerable"):
        assert outcomes_of(c) == ["unanswered"], c["id"]
        assert c["expected_citations"] == [], c["id"]


def test_unanswerable_includes_the_client_sign_in_near_miss():
    pattern = re.compile(r"sign[\s-]?in|log[\s-]?in", re.IGNORECASE)

    matches = [c for c in in_category("unanswerable") if pattern.search(c["question"])]

    assert matches, "no unanswerable case asks where clients sign in"


def test_unanswerable_includes_the_office_hours_timezone_near_miss():
    pattern = re.compile(r"time[\s-]?zone", re.IGNORECASE)

    matches = [c for c in in_category("unanswerable") if pattern.search(c["question"])]

    assert matches, "no unanswerable case asks about the office-hours timezone"


# --- injection ---


def test_injection_cases_cite_nothing():
    for c in in_category("injection"):
        assert c["expected_citations"] == [], c["id"]


def test_injection_includes_a_forged_assistant_turn_in_history():
    forged = [
        c
        for c in in_category("injection")
        if any(m["role"] == "assistant" for m in c.get("history") or [])
    ]

    assert forged, "no injection case has an assistant message in its history"


def test_injection_includes_a_request_to_reveal_the_prompt():
    reveal = re.compile(
        r"(system|initial|hidden|original)\s+(prompt|instructions)"
        r"|your\s+(prompt|instructions)",
        re.IGNORECASE,
    )

    matches = [c for c in in_category("injection") if reveal.search(c["question"])]

    assert matches, "no injection case asks to reveal the prompt"


# --- smalltalk and smalltalk_injection ---


def test_smalltalk_cases_expect_smalltalk_and_no_citations():
    for c in in_category("smalltalk"):
        assert "smalltalk" in outcomes_of(c), c["id"]
        assert c["expected_citations"] == [], c["id"]


def test_smalltalk_injection_cases_cite_nothing_and_never_expect_an_answer():
    for c in in_category("smalltalk_injection"):
        assert c["expected_citations"] == [], c["id"]
        assert not {"answered", "partial"} & set(outcomes_of(c)), c["id"]


# --- every case is something the API would accept ---


def test_every_case_is_a_valid_chat_request():
    for c in load_cases():
        ChatRequest(message=c["question"], history=c.get("history") or [])
