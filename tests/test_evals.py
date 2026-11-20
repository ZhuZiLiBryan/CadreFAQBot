"""M4: eval scoring, aggregation, case loading and filtering (pure logic, no network).

Assumed interface in ``evals.run``:
  - score_case(case: dict, outcome: str, cited_ids: list[int]) -> bool
  - pass_rates_by_category(results: list[dict]) -> dict[str, float]
    (each result has "category" and "passed"; rates are fractions in 0..1)
  - load_cases(path=None) -> list[dict]   (default: evals/cases.yaml)
  - filter_cases(cases, case_id=None, category=None) -> list[dict]
  - parse_args(argv: list[str] | None) -> namespace with .case and .category
"""

from pathlib import Path

import pytest

from backend.faq import load_faq
from evals.run import (
    filter_cases,
    load_cases,
    parse_args,
    pass_rates_by_category,
    score_case,
)

CASES_PATH = Path(__file__).resolve().parent.parent / "evals" / "cases.yaml"

CATEGORIES = {
    "answerable",
    "partial",
    "unanswerable",
    "injection",
    "smalltalk",
    "smalltalk_injection",
}
OUTCOMES = {"answered", "partial", "unanswered", "smalltalk"}


def case(expected_outcome="answered", expected_citations=(1,), **extra) -> dict:
    return {
        "id": "c",
        "category": "answerable",
        "question": "Q?",
        "expected_outcome": expected_outcome,
        "expected_citations": list(expected_citations),
        **extra,
    }


# --- score_case: outcome ---


def test_passes_when_the_outcome_matches_a_single_expected_outcome():
    assert score_case(case("answered", [1]), "answered", [1]) is True


def test_fails_when_the_outcome_differs_from_a_single_expected_outcome():
    assert score_case(case("answered", [1]), "unanswered", [1]) is False


def test_fails_on_a_wrong_outcome_even_when_the_citation_is_right():
    assert score_case(case("partial", [2]), "answered", [2]) is False


@pytest.mark.parametrize("outcome", ["smalltalk", "unanswered"])
def test_passes_when_the_outcome_is_in_an_expected_outcome_list(outcome):
    c = case(["smalltalk", "unanswered"], [])

    assert score_case(c, outcome, []) is True


@pytest.mark.parametrize("outcome", ["answered", "partial"])
def test_fails_when_the_outcome_is_not_in_the_expected_outcome_list(outcome):
    c = case(["smalltalk", "unanswered"], [])

    assert score_case(c, outcome, []) is False


# --- score_case: citations ---


def test_passes_when_one_of_several_expected_citations_is_cited():
    assert score_case(case("answered", [1, 4, 29, 34]), "answered", [29]) is True


def test_passes_when_all_expected_citations_are_cited():
    assert score_case(case("answered", [19, 23]), "answered", [19, 23]) is True


def test_passes_when_extra_unexpected_ids_are_cited_alongside_an_expected_one():
    assert score_case(case("answered", [23]), "answered", [5, 23, 40]) is True


def test_fails_when_no_expected_citation_is_cited():
    assert score_case(case("answered", [1, 4]), "answered", [2, 3]) is False


def test_fails_when_citations_are_expected_but_none_are_cited():
    assert score_case(case("answered", [45]), "answered", []) is False


def test_no_citation_requirement_when_expected_citations_is_empty():
    assert score_case(case("unanswered", []), "unanswered", []) is True


def test_empty_expected_citations_ignores_whatever_is_cited():
    assert score_case(case("smalltalk", []), "smalltalk", [7, 8]) is True


def test_outcome_with_a_list_still_requires_citations_when_listed():
    c = case(["answered", "partial"], [10])

    assert score_case(c, "partial", [10]) is True
    assert score_case(c, "partial", [11]) is False


def test_scoring_does_not_look_at_the_answer_wording():
    c = case("answered", [1], answer="irrelevant")

    assert score_case(c, "answered", [1]) is True


def test_scoring_does_not_mutate_the_case():
    c = case(["smalltalk", "unanswered"], [3])
    before = {k: (list(v) if isinstance(v, list) else v) for k, v in c.items()}

    score_case(c, "smalltalk", [3])

    assert c == before


# --- per-category pass rates ---


def test_pass_rate_is_passed_over_total_per_category():
    results = [
        {"category": "answerable", "passed": True},
        {"category": "answerable", "passed": False},
        {"category": "answerable", "passed": True},
        {"category": "answerable", "passed": True},
        {"category": "injection", "passed": True},
        {"category": "injection", "passed": True},
    ]

    rates = pass_rates_by_category(results)

    assert rates == {"answerable": pytest.approx(0.75), "injection": 1.0}


def test_a_category_with_no_passes_has_rate_zero():
    rates = pass_rates_by_category([{"category": "partial", "passed": False}])

    assert rates == {"partial": 0.0}


def test_only_categories_that_were_run_appear():
    rates = pass_rates_by_category([{"category": "smalltalk", "passed": True}])

    assert set(rates) == {"smalltalk"}


def test_no_results_give_no_rates():
    assert pass_rates_by_category([]) == {}


# --- cases.yaml loading ---


def test_cases_yaml_loads_a_non_empty_list_of_dicts():
    cases = load_cases()

    assert isinstance(cases, list)
    assert cases
    assert all(isinstance(c, dict) for c in cases)


def test_explicit_path_loads_the_same_cases():
    assert load_cases(CASES_PATH) == load_cases()


def test_every_case_has_the_required_fields():
    for c in load_cases():
        for field in (
            "id",
            "category",
            "question",
            "expected_outcome",
            "expected_citations",
        ):
            assert field in c, f"{c.get('id')} is missing {field}"


def test_case_ids_are_unique_non_empty_strings():
    ids = [c["id"] for c in load_cases()]

    assert all(isinstance(i, str) and i.strip() for i in ids)
    assert len(ids) == len(set(ids))


def test_every_case_has_a_valid_category():
    for c in load_cases():
        assert c["category"] in CATEGORIES, c["id"]


def test_every_category_in_the_starter_set_is_represented():
    assert {c["category"] for c in load_cases()} == CATEGORIES


def test_every_question_is_a_non_empty_string():
    for c in load_cases():
        assert isinstance(c["question"], str) and c["question"].strip(), c["id"]


def test_expected_outcomes_are_valid_outcomes_as_a_string_or_a_list():
    for c in load_cases():
        expected = c["expected_outcome"]
        values = [expected] if isinstance(expected, str) else expected
        assert values, c["id"]
        assert set(values) <= OUTCOMES, c["id"]


def test_expected_citations_are_real_faq_entry_numbers():
    faq_ids = set(load_faq().entries)

    for c in load_cases():
        citations = c["expected_citations"]
        assert isinstance(citations, list), c["id"]
        assert all(isinstance(n, int) for n in citations), c["id"]
        assert set(citations) <= faq_ids, c["id"]


def test_optional_history_is_well_formed_when_present():
    for c in load_cases():
        for message in c.get("history") or []:
            assert message["role"] in {"user", "assistant"}, c["id"]
            assert isinstance(message["content"], str) and message["content"]


def test_loading_from_a_custom_file(tmp_path):
    path = tmp_path / "cases.yaml"
    path.write_text(
        "- id: only\n"
        "  category: smalltalk\n"
        "  question: Hi\n"
        "  expected_outcome: [smalltalk, unanswered]\n"
        "  expected_citations: []\n",
        encoding="utf-8",
    )

    cases = load_cases(path)

    assert [c["id"] for c in cases] == ["only"]
    assert cases[0]["expected_outcome"] == ["smalltalk", "unanswered"]


# --- --case / --category filtering ---


@pytest.fixture
def sample_cases() -> list[dict]:
    return [
        {"id": "a1", "category": "answerable"},
        {"id": "a2", "category": "answerable"},
        {"id": "u1", "category": "unanswerable"},
        {"id": "i1", "category": "injection"},
    ]


def test_no_filters_keep_every_case_in_order(sample_cases):
    assert filter_cases(sample_cases) == sample_cases


def test_filter_by_case_id(sample_cases):
    result = filter_cases(sample_cases, case_id="u1")

    assert [c["id"] for c in result] == ["u1"]


def test_filter_by_category_preserves_order(sample_cases):
    result = filter_cases(sample_cases, category="answerable")

    assert [c["id"] for c in result] == ["a1", "a2"]


def test_case_and_category_filters_combine_as_an_intersection(sample_cases):
    assert [
        c["id"] for c in filter_cases(sample_cases, case_id="a2", category="answerable")
    ] == ["a2"]
    assert filter_cases(sample_cases, case_id="a2", category="injection") == []


def test_filter_matching_nothing_returns_an_empty_list(sample_cases):
    assert filter_cases(sample_cases, category="smalltalk") == []


def test_filter_does_not_mutate_its_input(sample_cases):
    snapshot = [dict(c) for c in sample_cases]

    filter_cases(sample_cases, category="answerable")

    assert sample_cases == snapshot


def test_filters_work_on_the_real_cases():
    cases = load_cases()
    category = cases[0]["category"]

    by_category = filter_cases(cases, category=category)
    by_id = filter_cases(cases, case_id=cases[0]["id"])

    assert by_category and all(c["category"] == category for c in by_category)
    assert [c["id"] for c in by_id] == [cases[0]["id"]]


# --- CLI options ---


def test_cli_defaults_to_no_filters():
    args = parse_args([])

    assert args.case is None
    assert args.category is None


def test_cli_parses_case():
    assert parse_args(["--case", "hourly-rate"]).case == "hourly-rate"


def test_cli_parses_category():
    assert parse_args(["--category", "injection"]).category == "injection"


def test_cli_parses_case_and_category_together():
    args = parse_args(["--case", "x", "--category", "smalltalk"])

    assert (args.case, args.category) == ("x", "smalltalk")
