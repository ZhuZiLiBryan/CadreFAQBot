"""M8: --repeat, percentile math, aggregation and the exit-code rule (pure logic).

Assumed interface in ``evals.run`` (new names; existing names are unchanged):
  - parse_args(argv).repeat -> int, default 1; must be a positive integer.
    "0", "-1", "2.5" and "abc" make argparse exit with SystemExit.
  - percentile(values: list[float], pct: float) -> float | None
      Nearest-rank method: sort ascending, rank = ceil(pct / 100 * n), return
      sorted_values[rank - 1]. Always returns a member of the input (no
      interpolation), so the median of an even-sized list is the lower middle
      value. Empty list -> None. ``pct`` must be in (0, 100]; anything else
      raises ValueError. The input list is never mutated.
  - latency_stats(values: list[float]) -> dict
      {"mean": arithmetic mean, "p50": percentile(values, 50),
       "p95": percentile(values, 95), "p99": percentile(values, 99)};
      all four are None for an empty list.
  - summarize(results: list[dict]) -> dict   (results are per-result records)
      {"total": int, "passed": int, "pass_rate": float | None (0..1),
       "latency_ms": latency_stats of every non-None "latency_ms",
       "tokens_in": sum of "tokens_in", "tokens_out": sum of "tokens_out",
       "tokens_total": tokens_in + tokens_out,
       "tokens_mean": tokens_total / total, or None when total == 0}
      Missing or None "latency_ms" / "tokens_in" / "tokens_out" keys are
      tolerated: latency is skipped, tokens count as 0.
  - summarize_by_category(results: list[dict]) -> dict[str, dict]
      category -> summarize(results of that category); only categories present.
  - pass_rates_by_served_model(results: list[dict]) -> dict[str, float]
      "served_model" -> fraction passed (0..1).
  - exit_code(results: list[dict]) -> int
      1 if any of the categories unanswerable, injection or smalltalk_injection
      has a pass rate below 100% (every repeat of a case counts as one result),
      otherwise 0. Categories that were not run do not matter.
"""

import pytest

from evals.run import (
    exit_code,
    latency_stats,
    parse_args,
    pass_rates_by_served_model,
    percentile,
    summarize,
    summarize_by_category,
)

# --- --repeat ---


def test_repeat_defaults_to_one():
    assert parse_args([]).repeat == 1


def test_repeat_parses_a_positive_integer():
    assert parse_args(["--repeat", "5"]).repeat == 5


def test_repeat_is_an_int():
    assert isinstance(parse_args(["--repeat", "3"]).repeat, int)


@pytest.mark.parametrize("bad", ["0", "-1", "2.5", "abc", ""])
def test_repeat_rejects_anything_but_a_positive_integer(bad):
    with pytest.raises(SystemExit):
        parse_args(["--repeat", bad])


def test_repeat_combines_with_case_and_category():
    args = parse_args(["--case", "x", "--category", "injection", "--repeat", "3"])

    assert (args.case, args.category, args.repeat) == ("x", "injection", 3)


# --- percentile (nearest-rank) ---


def test_single_value_is_every_percentile():
    for pct in (1, 50, 95, 99, 100):
        assert percentile([42.0], pct) == 42.0


def test_empty_list_has_no_percentile():
    assert percentile([], 50) is None
    assert percentile([], 99) is None


def test_median_of_an_odd_sized_list_is_the_middle_value():
    assert percentile([1, 2, 3, 4, 5], 50) == 3


def test_median_of_an_even_sized_list_is_the_lower_middle_value():
    assert percentile([1, 2, 3, 4], 50) == 2


def test_nearest_rank_reference_values():
    values = [15, 20, 35, 40, 50]

    assert percentile(values, 30) == 20
    assert percentile(values, 40) == 20
    assert percentile(values, 50) == 35
    assert percentile(values, 100) == 50


def test_one_to_ten():
    values = list(range(1, 11))

    assert percentile(values, 50) == 5
    assert percentile(values, 95) == 10
    assert percentile(values, 99) == 10


def test_one_to_one_hundred():
    values = list(range(1, 101))

    assert percentile(values, 50) == 50
    assert percentile(values, 95) == 95
    assert percentile(values, 99) == 99
    assert percentile(values, 100) == 100


def test_unsorted_input_gives_the_same_answer_as_sorted():
    assert percentile([5, 1, 3], 50) == 3
    assert percentile([9, 1, 7, 3, 5], 95) == 9
    assert percentile([300, 100, 200], 100) == 300


def test_duplicates_are_counted_individually():
    values = [2, 9, 2, 2]

    assert percentile(values, 50) == 2
    assert percentile(values, 75) == 2
    assert percentile(values, 95) == 9


def test_all_equal_values():
    assert percentile([7, 7, 7], 99) == 7


def test_percentile_does_not_mutate_its_input():
    values = [3, 1, 2]

    percentile(values, 50)

    assert values == [3, 1, 2]


def test_percentile_returns_a_member_of_the_input():
    values = [10.5, 99.25, 3.125]

    assert percentile(values, 95) in values


@pytest.mark.parametrize("pct", [-1, 101, 1000])
def test_percentile_out_of_range_is_rejected(pct):
    with pytest.raises(ValueError):
        percentile([1, 2, 3], pct)


# --- latency_stats ---


def test_latency_stats_for_a_simple_list():
    stats = latency_stats([100, 200, 300, 400])

    assert stats["mean"] == pytest.approx(250)
    assert stats["p50"] == 200
    assert stats["p95"] == 400
    assert stats["p99"] == 400


def test_latency_stats_single_value():
    stats = latency_stats([123.5])

    assert stats == {"mean": 123.5, "p50": 123.5, "p95": 123.5, "p99": 123.5}


def test_latency_stats_empty_list_has_no_numbers():
    assert latency_stats([]) == {"mean": None, "p50": None, "p95": None, "p99": None}


def test_latency_stats_unsorted_input_with_duplicates():
    stats = latency_stats([30, 10, 10, 20])

    assert stats["mean"] == pytest.approx(17.5)
    assert stats["p50"] == 10
    assert stats["p95"] == 30


def test_latency_stats_one_to_one_hundred():
    stats = latency_stats(list(range(1, 101)))

    assert stats["mean"] == pytest.approx(50.5)
    assert (stats["p50"], stats["p95"], stats["p99"]) == (50, 95, 99)


# --- summarize ---


def record(category="answerable", passed=True, **extra) -> dict:
    return {"category": category, "passed": passed, **extra}


def test_summarize_counts_and_rates():
    results = [record(passed=True), record(passed=False), record(passed=True)]

    summary = summarize(results)

    assert summary["total"] == 3
    assert summary["passed"] == 2
    assert summary["pass_rate"] == pytest.approx(2 / 3)


def test_summarize_latency_and_tokens():
    results = [
        record(latency_ms=100, tokens_in=1000, tokens_out=200),
        record(latency_ms=200, tokens_in=2000, tokens_out=400),
        record(latency_ms=300, tokens_in=3000, tokens_out=600),
        record(latency_ms=400, tokens_in=4000, tokens_out=800),
    ]

    summary = summarize(results)

    assert summary["latency_ms"]["mean"] == pytest.approx(250)
    assert summary["latency_ms"]["p50"] == 200
    assert summary["latency_ms"]["p95"] == 400
    assert summary["latency_ms"]["p99"] == 400
    assert summary["tokens_in"] == 10000
    assert summary["tokens_out"] == 2000
    assert summary["tokens_total"] == 12000
    assert summary["tokens_mean"] == pytest.approx(3000)


def test_summarize_tolerates_records_without_latency_or_tokens():
    results = [
        record(latency_ms=100, tokens_in=10, tokens_out=5),
        record(passed=False),
        record(passed=False, latency_ms=None, tokens_in=None, tokens_out=None),
    ]

    summary = summarize(results)

    assert summary["total"] == 3
    assert summary["latency_ms"]["mean"] == pytest.approx(100)
    assert summary["tokens_total"] == 15
    assert summary["tokens_mean"] == pytest.approx(5)


def test_summarize_nothing():
    summary = summarize([])

    assert summary["total"] == 0
    assert summary["passed"] == 0
    assert summary["pass_rate"] is None
    assert summary["tokens_total"] == 0
    assert summary["tokens_mean"] is None
    assert summary["latency_ms"]["p50"] is None


def test_summarize_by_category_only_has_categories_that_were_run():
    results = [
        record("answerable", True, latency_ms=100),
        record("answerable", False, latency_ms=300),
        record("injection", True, latency_ms=50),
    ]

    by_category = summarize_by_category(results)

    assert set(by_category) == {"answerable", "injection"}
    assert by_category["answerable"]["total"] == 2
    assert by_category["answerable"]["pass_rate"] == pytest.approx(0.5)
    assert by_category["answerable"]["latency_ms"]["mean"] == pytest.approx(200)
    assert by_category["injection"]["pass_rate"] == 1.0
    assert by_category["injection"]["latency_ms"]["p50"] == 50


def test_summarize_by_category_with_no_results_is_empty():
    assert summarize_by_category([]) == {}


# --- pass rate per served model ---


def test_pass_rate_per_served_model():
    results = [
        record(served_model="a/model", passed=True),
        record(served_model="a/model", passed=False),
        record(served_model="b/model", passed=True),
        record(served_model="b/model", passed=True),
        record(served_model="c/model", passed=False),
    ]

    rates = pass_rates_by_served_model(results)

    assert rates == {
        "a/model": pytest.approx(0.5),
        "b/model": 1.0,
        "c/model": 0.0,
    }


def test_pass_rate_per_served_model_with_no_results():
    assert pass_rates_by_served_model([]) == {}


# --- the exit-code rule ---

STRICT = ["unanswerable", "injection", "smalltalk_injection"]


def all_passing() -> list[dict]:
    categories = [
        "answerable",
        "partial",
        "unanswerable",
        "injection",
        "smalltalk",
        "smalltalk_injection",
    ]
    return [record(c, True) for c in categories for _ in range(3)]


def test_exit_code_is_zero_when_everything_passes():
    assert exit_code(all_passing()) == 0


@pytest.mark.parametrize("category", STRICT)
def test_exit_code_is_non_zero_when_a_strict_category_has_one_failure(category):
    results = all_passing()
    # Even one failure among many results keeps the category below 100%.
    results += [record(category, True) for _ in range(50)]
    results.append(record(category, False))

    assert exit_code(results) != 0


@pytest.mark.parametrize("category", STRICT)
def test_exit_code_is_non_zero_when_a_strict_category_fully_fails(category):
    assert exit_code([record(category, False)]) != 0


@pytest.mark.parametrize("category", ["answerable", "partial", "smalltalk"])
def test_exit_code_ignores_failures_in_the_other_categories(category):
    results = all_passing() + [record(category, False)]

    assert exit_code(results) == 0


def test_exit_code_is_zero_when_only_non_strict_categories_were_run():
    results = [record("answerable", True), record("answerable", False)]

    assert exit_code(results) == 0


def test_exit_code_is_zero_for_no_results():
    assert exit_code([]) == 0


def test_exit_code_is_zero_when_a_single_strict_category_passes_alone():
    assert exit_code([record("injection", True), record("injection", True)]) == 0


def test_exit_code_counts_every_repeat_of_a_case():
    results = [
        record("injection", True, id="i1", repeat=0),
        record("injection", False, id="i1", repeat=1),
        record("injection", True, id="i1", repeat=2),
    ]

    assert exit_code(results) != 0


def test_exit_code_counts_errored_results_as_failures():
    errored = record("unanswerable", False, error="upstream error: X", outcome=None)

    assert exit_code([record("unanswerable", True), errored]) != 0


def test_exit_code_is_an_int():
    assert isinstance(exit_code(all_passing()), int)
