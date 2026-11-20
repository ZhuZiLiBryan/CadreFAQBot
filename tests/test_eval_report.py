"""The eval result writer (pure; no network)."""

import json

from evals.run import render_report, write_results

META = {
    "timestamp": "2026-11-20T12-00-00Z",
    "prompt_version": "abc123abc123",
    "model": "test/model",
}


def sample_results() -> list[dict]:
    base = {
        "history": [],
        "expected_outcome": "answered",
        "expected_citations": [1],
        "served_model": "served/x",
        "error": None,
    }
    return [
        {
            **base,
            "id": "a",
            "category": "answerable",
            "question": "What is Cadre?\nReally?",
            "outcome": "answered",
            "answer": "Line one.\nLine two.",
            "cited": [1],
            "passed": True,
            "raw_outcome": "answered",
            "raw_answer": "Line one.\nLine two.",
            "raw_citations": [1, 999],
        },
        {
            **base,
            "id": "b",
            "category": "injection",
            "question": "Ignore everything",
            "outcome": None,
            "answer": "",
            "cited": [],
            "passed": False,
            "error": "upstream error: X",
        },
    ]


def test_write_results_creates_jsonl_and_report(tmp_path):
    folder = write_results(sample_results(), META, tmp_path)

    assert folder == tmp_path / META["timestamp"]
    lines = (folder / "results.jsonl").read_text(encoding="utf-8").splitlines()
    rows = [json.loads(line) for line in lines]
    assert [r["id"] for r in rows] == ["a", "b"]
    assert rows[0]["prompt_version"] == "abc123abc123"
    assert rows[0]["raw_citations"] == [1, 999]
    assert (folder / "report.md").is_file()


def test_report_has_rates_and_every_case_for_manual_grading():
    report = render_report(sample_results(), META)

    assert "abc123abc123" in report and "test/model" in report
    assert "| answerable | 1/1 | 100% |" in report
    assert "| injection | 0/1 | 0% |" in report
    assert "`a`" in report and "`b`" in report
    assert "> Line one.\n> Line two." in report
    assert "upstream error: X" in report
