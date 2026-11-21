"""M8: the full report (``report.md``) and ``results.jsonl`` (pure; no network).

Assumed interface in ``evals.run`` (names already tested in test_eval_report.py
keep their signatures):
  - render_report(results: list[dict], meta: dict) -> str
  - write_results(results: list[dict], meta: dict, root: Path) -> Path
      writes ``<root>/<meta["timestamp"]>/results.jsonl`` (one JSON object per
      line, in input order) and ``report.md`` there; returns that folder.
      Each jsonl row is the result record plus ``prompt_version`` and ``model``
      taken from ``meta`` when the record does not already carry them.
  - meta = {"timestamp": "2026-11-20T12-00-00Z", "prompt_version": str,
            "model": str}

Per-result record (a dict) fields, as produced by the runner:
  id, category, repeat (0-based int), question, history,
  expected_outcome, expected_citations,
  raw_outcome, raw_answer, raw_citations      (raw model output)
  outcome, answer, cited                      (final Reply; cited = FAQ ids)
  guardrail_reasons (list[str]), passed (bool), reason (str, why it failed),
  error (str | None; model unavailable), latency_ms (float | None),
  tokens_in (int | None), tokens_out (int | None),
  model (configured), served_model, prompt_version

Report layout assumed (markdown):
  - an "overall" row and one row per category, each starting
    ``| <name> | <passed>/<total> | <rate>% |`` (rate is rounded to a whole
    percent), followed by more columns; the latency (mean, p50, p95, p99, in
    milliseconds) and token (total, mean per result) figures appear in these
    tables as plain numbers without thousands separators
  - a per-served-model table whose rows start
    ``| <served_model> | <passed>/<total> | <rate>% |``
  - then, for every result, its id in backticks, the question, the answer as a
    blockquote (``> `` prefix per line) and its cited FAQ ids
"""

import json

from evals.run import render_report, write_results

META = {
    "timestamp": "2026-11-20T12-00-00Z",
    "prompt_version": "abc123abc123",
    "model": "test/model",
}


def result(
    id: str,
    category: str = "answerable",
    passed: bool = True,
    repeat: int = 0,
    latency_ms: float | None = 100.0,
    tokens_in: int | None = 1000,
    tokens_out: int | None = 230,
    served_model: str = "served/x",
    **extra,
) -> dict:
    return {
        "id": id,
        "category": category,
        "repeat": repeat,
        "question": f"Question for {id}?",
        "history": [],
        "expected_outcome": "answered",
        "expected_citations": [1],
        "raw_outcome": "answered",
        "raw_answer": f"Raw answer for {id}.",
        "raw_citations": [1],
        "outcome": "answered",
        "answer": f"Answer for {id}.",
        "cited": [1],
        "guardrail_reasons": [],
        "passed": passed,
        "reason": "" if passed else "outcome mismatch",
        "error": None,
        "latency_ms": latency_ms,
        "tokens_in": tokens_in,
        "tokens_out": tokens_out,
        "model": "test/model",
        "served_model": served_model,
        "prompt_version": "abc123abc123",
        **extra,
    }


def four_results() -> list[dict]:
    """Latencies 100/200/300/400 ms; every request is 1000 in + 230 out tokens."""
    return [
        result("a1", "answerable", True, latency_ms=100),
        result("a2", "answerable", False, latency_ms=200),
        result("i1", "injection", True, latency_ms=300),
        result("i2", "injection", True, latency_ms=400),
    ]


# --- pass rates ---


def test_report_has_an_overall_pass_rate_row():
    report = render_report(four_results(), META)

    assert "| overall | 3/4 | 75% |" in report


def test_report_has_a_row_per_category_that_was_run():
    report = render_report(four_results(), META)

    assert "| answerable | 1/2 | 50% |" in report
    assert "| injection | 2/2 | 100% |" in report
    assert "| partial |" not in report
    assert "| smalltalk |" not in report


def test_report_has_pass_rate_per_served_model():
    results = [
        result("a", served_model="served/x", passed=True),
        result("b", served_model="served/x", passed=False),
        result("c", served_model="other/y", passed=True),
        result("d", served_model="other/y", passed=True),
    ]

    report = render_report(results, META)

    assert "| served/x | 1/2 | 50% |" in report
    assert "| other/y | 2/2 | 100% |" in report


def test_report_names_the_prompt_version_and_configured_model():
    report = render_report(four_results(), META)

    assert "abc123abc123" in report
    assert "test/model" in report


# --- latency and tokens ---


def test_report_has_latency_columns():
    report = render_report(four_results(), META)

    for heading in ("mean", "p50", "p95", "p99"):
        assert heading in report.lower()


def test_report_shows_latency_mean_and_percentiles_overall():
    # mean 250, p50 200, p95 400, p99 400 (nearest-rank), none of these appear
    # anywhere else in the fixture.
    report = render_report(four_results(), META)

    assert "250" in report
    assert "200" in report
    assert "400" in report


def test_report_shows_per_category_latency():
    results = [
        result("a1", "answerable", latency_ms=111),
        result("a2", "answerable", latency_ms=333),
        result("i1", "injection", latency_ms=777),
    ]

    report = render_report(results, META)

    # answerable mean = 222, injection (single value) = 777 for every statistic
    assert "222" in report
    assert "777" in report


def test_report_shows_total_and_mean_tokens():
    # 4 requests x (1000 + 230) = 4920 total tokens, 1230 per request.
    report = render_report(four_results(), META)

    assert "4920" in report
    assert "1230" in report


def test_report_copes_with_results_that_have_no_latency_or_tokens():
    results = [
        result("ok", latency_ms=120, tokens_in=500, tokens_out=40),
        result(
            "down",
            passed=False,
            latency_ms=None,
            tokens_in=None,
            tokens_out=None,
            outcome=None,
            answer="",
            cited=[],
            error="upstream error: X",
        ),
    ]

    report = render_report(results, META)

    assert "| overall | 1/2 | 50% |" in report
    assert "upstream error: X" in report


# --- every case, for manual grading ---


def test_report_lists_every_case_with_question_answer_and_citations():
    results = [
        result("alpha", question="What is Cadre?", answer="Cadre is X.", cited=[4242]),
        result("beta", question="Where is Cadre?", answer="San Diego.", cited=[7]),
    ]

    report = render_report(results, META)

    assert "`alpha`" in report and "`beta`" in report
    assert "What is Cadre?" in report and "Where is Cadre?" in report
    assert "> Cadre is X." in report and "> San Diego." in report
    assert "4242" in report


def test_report_answers_are_blockquoted_line_by_line():
    results = [result("a", answer="Line one.\nLine two.")]

    report = render_report(results, META)

    assert "> Line one.\n> Line two." in report


def test_report_lists_each_repeat_of_a_case():
    results = [
        result("a", repeat=0, answer="First attempt."),
        result("a", repeat=1, answer="Second attempt."),
        result("a", repeat=2, answer="Third attempt."),
    ]

    report = render_report(results, META)

    for text in ("First attempt.", "Second attempt.", "Third attempt."):
        assert text in report
    assert "| overall | 3/3 | 100% |" in report


def test_report_for_no_results_does_not_crash():
    report = render_report([], META)

    assert "abc123abc123" in report


# --- results.jsonl and folder layout ---


def test_write_results_uses_a_timestamped_folder_under_the_root(tmp_path):
    folder = write_results(four_results(), META, tmp_path)

    assert folder == tmp_path / META["timestamp"]
    assert (folder / "results.jsonl").is_file()
    assert (folder / "report.md").is_file()


def test_jsonl_has_one_json_object_per_result_in_order(tmp_path):
    results = [
        result("a", repeat=0),
        result("a", repeat=1),
        result("b", "injection", passed=False),
    ]

    folder = write_results(results, META, tmp_path)

    lines = (folder / "results.jsonl").read_text(encoding="utf-8").splitlines()
    rows = [json.loads(line) for line in lines]
    assert [(r["id"], r["repeat"]) for r in rows] == [("a", 0), ("a", 1), ("b", 0)]


def test_jsonl_rows_keep_every_recorded_field(tmp_path):
    original = result(
        "a",
        history=[{"role": "assistant", "content": "Earlier turn"}],
        raw_citations=[1, 999],
        guardrail_reasons=["unknown_citation"],
        reason="",
    )

    folder = write_results([original], META, tmp_path)

    row = json.loads((folder / "results.jsonl").read_text(encoding="utf-8"))
    for key, value in original.items():
        assert row[key] == value, key


def test_jsonl_rows_get_prompt_version_and_model_from_meta(tmp_path):
    bare = result("a")
    del bare["prompt_version"], bare["model"]

    folder = write_results([bare], META, tmp_path)

    row = json.loads((folder / "results.jsonl").read_text(encoding="utf-8"))
    assert row["prompt_version"] == "abc123abc123"
    assert row["model"] == "test/model"


def test_jsonl_keeps_non_ascii_text_intact(tmp_path):
    folder = write_results([result("a", answer="Café ‘quoted’ — dash")], META, tmp_path)

    row = json.loads((folder / "results.jsonl").read_text(encoding="utf-8"))
    assert row["answer"] == "Café ‘quoted’ — dash"


def test_report_file_equals_render_report(tmp_path):
    results = four_results()

    folder = write_results(results, META, tmp_path)

    assert (folder / "report.md").read_text(encoding="utf-8") == render_report(
        results, META
    )


def test_two_runs_with_different_timestamps_do_not_overwrite_each_other(tmp_path):
    first = write_results(four_results(), META, tmp_path)
    later = {**META, "timestamp": "2026-11-20T13-00-00Z"}

    second = write_results(four_results(), later, tmp_path)

    assert first != second
    assert first.is_dir() and second.is_dir()
