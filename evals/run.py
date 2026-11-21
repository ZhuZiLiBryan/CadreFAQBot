"""Eval runner: `uv run python -m evals.run [--case ID] [--category NAME] [--repeat N]`.

Runs each case in `evals/cases.yaml` through the same in-process code path as
`POST /api/chat` (so server-side assembly applies) against the real model, and
scores the Outcome and cited FAQ Entry IDs, never the wording. This spends API
quota, so it is not part of `pytest`; only the pure helpers are tested there.

The exit code is non-zero when `unanswerable`, `injection` or
`smalltalk_injection` is below 100%.
"""

import argparse
import asyncio
import json
import math
import os
import time
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path

import yaml

CASES_PATH = Path(__file__).parent / "cases.yaml"
RESULTS_DIR = Path(__file__).parent / "results"  # git-ignored

# Categories that must stay at 100%: refusing, resisting injection, and not being
# talked into unbacked claims through small talk.
STRICT_CATEGORIES = ("unanswerable", "injection", "smalltalk_injection")


def score_case(case: dict, outcome: str, cited_ids: list[int]) -> bool:
    """Pass when the Outcome is expected and, if citations are expected, at least
    one expected FAQ Entry ID is cited."""
    expected = case["expected_outcome"]
    allowed = [expected] if isinstance(expected, str) else list(expected)
    if outcome not in allowed:
        return False
    expected_citations = case.get("expected_citations") or []
    # No citations needed for this case
    if not expected_citations:
        return True
    # Check at least one expected citation is in the result
    return any(n in cited_ids for n in expected_citations)


def fail_reason(case: dict, outcome: str, cited_ids: list[int]) -> str:
    """Why `score_case` failed, for the report; empty string when it passed."""
    if score_case(case, outcome, cited_ids):
        return ""
    expected = case["expected_outcome"]
    allowed = [expected] if isinstance(expected, str) else list(expected)
    if outcome not in allowed:
        return f"outcome {outcome} not in expected {allowed}"
    return (
        f"cited {cited_ids} but expected at least one of {case['expected_citations']}"
    )


def pass_rates_by_category(results: list[dict]) -> dict[str, float]:
    """Fraction of passed results per category, for the categories that were run."""
    totals: dict[str, int] = defaultdict(int)
    passes: dict[str, int] = defaultdict(int)
    for result in results:
        totals[result["category"]] += 1
        passes[result["category"]] += bool(result["passed"])
    return {category: passes[category] / total for category, total in totals.items()}


def pass_rates_by_served_model(results: list[dict]) -> dict[str, float]:
    """Fraction of passed results per served model."""
    totals: dict[str, int] = defaultdict(int)
    passes: dict[str, int] = defaultdict(int)
    for result in results:
        model = _served_model(result)
        totals[model] += 1
        passes[model] += bool(result["passed"])
    return {model: passes[model] / total for model, total in totals.items()}


def percentile(values: list[float], pct: float) -> float | None:
    """Nearest-rank percentile: the value at rank ceil(pct/100 * n) of the sorted
    values. Always a member of the input; None for an empty list."""
    if not 0 < pct <= 100:
        raise ValueError(f"pct must be in (0, 100], got {pct}")
    if not values:
        return None
    ordered = sorted(values)
    rank = math.ceil(pct / 100 * len(ordered))
    return ordered[rank - 1]


def latency_stats(values: list[float]) -> dict[str, float | None]:
    if not values:
        return {"mean": None, "p50": None, "p95": None, "p99": None}
    return {
        "mean": sum(values) / len(values),
        "p50": percentile(values, 50),
        "p95": percentile(values, 95),
        "p99": percentile(values, 99),
    }


def summarize(results: list[dict]) -> dict:
    """Pass rate, latency stats and token totals for a group of results."""
    total = len(results)
    passed = sum(bool(r["passed"]) for r in results)
    latencies = [r["latency_ms"] for r in results if r.get("latency_ms") is not None]
    tokens_in = sum(r.get("tokens_in") or 0 for r in results)
    tokens_out = sum(r.get("tokens_out") or 0 for r in results)
    tokens_total = tokens_in + tokens_out
    return {
        "total": total,
        "passed": passed,
        "pass_rate": passed / total if total else None,
        "latency_ms": latency_stats(latencies),
        "tokens_in": tokens_in,
        "tokens_out": tokens_out,
        "tokens_total": tokens_total,
        "tokens_mean": tokens_total / total if total else None,
    }


def summarize_by_category(results: list[dict]) -> dict[str, dict]:
    groups: dict[str, list[dict]] = defaultdict(list)
    for result in results:
        groups[result["category"]].append(result)
    return {category: summarize(rows) for category, rows in groups.items()}


def exit_code(results: list[dict]) -> int:
    """1 if any strict category is below 100% (every repeat counts), else 0."""
    rates = pass_rates_by_category(results)
    return int(any(rates.get(category, 1.0) < 1.0 for category in STRICT_CATEGORIES))


def load_cases(path: Path | None = None) -> list[dict]:
    with open(path or CASES_PATH, encoding="utf-8") as f:
        return yaml.safe_load(f) or []


def filter_cases(
    cases: list[dict], case_id: str | None = None, category: str | None = None
) -> list[dict]:
    return [
        c
        for c in cases
        if (case_id is None or c["id"] == case_id)
        and (category is None or c["category"] == category)
    ]


def _positive_int(text: str) -> int:
    try:
        value = int(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"not an integer: {text!r}") from None
    if value < 1:
        raise argparse.ArgumentTypeError(f"must be at least 1, got {value}")
    return value


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="python -m evals.run", description=__doc__)
    parser.add_argument("--case", default=None, help="run only the case with this id")
    parser.add_argument("--category", default=None, help="run only this category")
    parser.add_argument(
        "--repeat",
        type=_positive_int,
        default=1,
        help="run each case this many times (default 1)",
    )
    return parser.parse_args(argv)


async def run_case(case: dict, client, repeat: int = 0, model: str = "") -> dict:
    from backend.chat import handle_chat
    from backend.model_client import UpstreamError
    from backend.prompts import prompt_version
    from backend.schemas import ChatRequest

    request = ChatRequest(message=case["question"], history=case.get("history") or [])
    started = time.perf_counter()
    try:
        reply, result, reasons = await handle_chat(request, client)
    except UpstreamError as exc:
        error = f"upstream error: {exc}"
        return _result(
            case,
            repeat=repeat,
            passed=False,
            reason=error,
            error=error,
            latency_ms=_elapsed_ms(started),
            model=model,
            prompt_version=prompt_version(),
        )
    cited = [c.faq_id for c in reply.citations]
    return _result(
        case,
        repeat=repeat,
        passed=score_case(case, reply.outcome, cited),
        reason=fail_reason(case, reply.outcome, cited),
        outcome=reply.outcome,
        answer=reply.answer,
        cited=cited,
        guardrail_reasons=list(reasons),
        raw_outcome=result.outcome,
        raw_answer=result.answer,
        raw_citations=list(result.citations),
        served_model=result.served_model,
        tokens_in=result.tokens_in,
        tokens_out=result.tokens_out,
        latency_ms=_elapsed_ms(started),
        model=model,
        prompt_version=prompt_version(),
    )


async def run_cases(
    cases: list[dict], client, repeat: int = 1, model: str = ""
) -> list[dict]:
    """Run every case `repeat` times, sequentially (free-tier models are rate
    limited): all repeats of the first case, then the next case."""
    results = []
    for case in cases:
        for index in range(repeat):
            result = await run_case(case, client, repeat=index, model=model)
            print_result(result)
            results.append(result)
    return results


def _elapsed_ms(started: float) -> float:
    return round((time.perf_counter() - started) * 1000, 1)


def _result(case: dict, **fields) -> dict:
    return {
        "id": case["id"],
        "category": case["category"],
        "repeat": 0,
        "question": case["question"],
        "history": case.get("history") or [],
        "expected_outcome": case["expected_outcome"],
        "expected_citations": case.get("expected_citations") or [],
        "raw_outcome": None,
        "raw_answer": None,
        "raw_citations": [],
        "outcome": None,
        "answer": "",
        "cited": [],
        "guardrail_reasons": [],
        "passed": False,
        "reason": "",
        "error": None,
        "latency_ms": None,
        "tokens_in": None,
        "tokens_out": None,
        "model": "",
        "served_model": "-",
        "prompt_version": "",
        **fields,
    }


def _served_model(result: dict) -> str:
    return str(result.get("served_model") or "-")


def _num(value: float | None) -> str:
    """A plain whole number (no thousands separators), or `-` when unknown."""
    return "-" if value is None else f"{value:.0f}"


def _rate(rate: float | None) -> str:
    return "-" if rate is None else f"{rate:.0%}"


def _summary_row(name: str, summary: dict) -> str:
    latency = summary["latency_ms"]
    cells = [
        name,
        f"{summary['passed']}/{summary['total']}",
        _rate(summary["pass_rate"]),
        _num(latency["mean"]),
        _num(latency["p50"]),
        _num(latency["p95"]),
        _num(latency["p99"]),
        _num(summary["tokens_total"]),
        _num(summary["tokens_mean"]),
    ]
    return "| " + " | ".join(cells) + " |"


def render_report(results: list[dict], meta: dict) -> str:
    """Markdown report: summary tables, then every case for manual grading of
    groundedness and faithfulness."""
    lines = [
        "# Eval report",
        "",
        f"- Run (UTC): {meta['timestamp']}",
        f"- Prompt Version: `{meta['prompt_version']}`",
        f"- Configured model: `{meta['model']}`",
        f"- Results: {len(results)}",
        "",
        "## Pass rate, latency (ms) and tokens",
        "",
        "| group | passed | rate | latency mean | p50 | p95 | p99 "
        "| tokens total | tokens mean |",
        "|---|---|---|---|---|---|---|---|---|",
        _summary_row("overall", summarize(results)),
    ]
    for category, summary in sorted(summarize_by_category(results).items()):
        lines.append(_summary_row(category, summary))

    lines += [
        "",
        "## Pass rate by served model",
        "",
        "| served model | passed | rate |",
        "|---|---|---|",
    ]
    by_model: dict[str, list[dict]] = defaultdict(list)
    for r in results:
        by_model[_served_model(r)].append(r)
    for model, rows in sorted(by_model.items()):
        passed = sum(bool(r["passed"]) for r in rows)
        lines.append(f"| {model} | {passed}/{len(rows)} | {passed / len(rows):.0%} |")

    lines += ["", "## Cases", ""]
    for r in results:
        repeat = r.get("repeat", 0)
        lines += [
            f"### {'PASS' if r['passed'] else 'FAIL'} `{r['id']}` "
            f"({r['category']}, repeat {repeat})",
            "",
            f"- **Question:** {r['question']}",
        ]
        if r.get("history"):
            lines.append(f"- **History:** {r['history']}")
        lines += [
            f"- **Expected:** outcome {r['expected_outcome']}, "
            f"cites any of {r['expected_citations'] or 'none'}",
            f"- **Got:** outcome {r['outcome']}, cited {r['cited']}, "
            f"model `{_served_model(r)}`",
        ]
        if r.get("guardrail_reasons"):
            lines.append(f"- **Guardrails applied:** {r['guardrail_reasons']}")
        if r.get("reason"):
            lines.append(f"- **Why it failed:** {r['reason']}")
        if r.get("error"):
            lines.append(f"- **Error:** {r['error']}")
        if r.get("raw_answer") is not None and r["outcome"] is not None:
            lines.append(
                f"- **Raw model output:** outcome {r.get('raw_outcome')}, "
                f"citations {r.get('raw_citations')}"
            )
        lines += ["", "> " + (r["answer"] or "(no answer)").replace("\n", "\n> "), ""]
    return "\n".join(lines)


def write_results(
    results: list[dict], meta: dict, out_root: Path | None = None
) -> Path:
    """Write results.jsonl and report.md under `<out_root>/<UTC timestamp>/`."""
    folder = (out_root or RESULTS_DIR) / meta["timestamp"]
    folder.mkdir(parents=True, exist_ok=True)
    defaults = {
        "timestamp": meta["timestamp"],
        "prompt_version": meta["prompt_version"],
        "model": meta["model"],
    }
    with open(folder / "results.jsonl", "w", encoding="utf-8") as f:
        for r in results:
            f.write(json.dumps({**defaults, **r}, ensure_ascii=False) + "\n")
    (folder / "report.md").write_text(render_report(results, meta), encoding="utf-8")
    return folder


def print_result(result: dict) -> None:
    status = "PASS" if result["passed"] else "FAIL"
    print(
        f"[{status}] {result['id']} ({result['category']}, repeat {result['repeat']})"
    )
    print(f"  question: {result['question']}")
    if result["error"]:
        print(f"  error:    {result['error']}")
        return
    print(f"  outcome:  {result['outcome']}")
    print(f"  answer:   {result['answer']}")
    print(f"  cited:    {result['cited']}")
    print(f"  model:    {result['served_model']}")
    if result["reason"]:
        print(f"  why:      {result['reason']}")


def print_summary(results: list[dict]) -> None:
    groups = {"overall": summarize(results)}
    groups.update(sorted(summarize_by_category(results).items()))
    width = max(len(name) for name in groups)
    print(
        f"\n{'group'.ljust(width)}  passed  rate  "
        "mean_ms  p50_ms  p95_ms  p99_ms  tokens  tokens/req"
    )
    for name, s in groups.items():
        latency = s["latency_ms"]
        print(
            f"{name.ljust(width)}  {s['passed']}/{s['total']}".ljust(width + 8)
            + f"  {_rate(s['pass_rate']):>4}  {_num(latency['mean']):>7}  "
            f"{_num(latency['p50']):>6}  {_num(latency['p95']):>6}  "
            f"{_num(latency['p99']):>6}  {_num(s['tokens_total']):>6}  "
            f"{_num(s['tokens_mean']):>10}"
        )
    print("\nPass rate by served model:")
    for model, rate in sorted(pass_rates_by_served_model(results).items()):
        print(f"  {model}: {rate:.0%}")


async def run_all(cases: list[dict], repeat: int = 1) -> list[dict]:
    from backend.faq import get_faq
    from backend.model_client import get_model_client
    from backend.prompts import prompt_version

    get_faq()
    client = get_model_client()
    print(f"Prompt Version: {prompt_version()}\n")
    return await run_cases(
        cases, client, repeat=repeat, model=os.environ.get("OPENROUTER_MODEL", "")
    )


def main(argv: list[str] | None = None) -> int:
    from dotenv import load_dotenv

    load_dotenv()
    args = parse_args(argv)
    cases = filter_cases(load_cases(), case_id=args.case, category=args.category)
    if not cases:
        print("No cases match the given filters.")
        return 2
    results = asyncio.run(run_all(cases, repeat=args.repeat))
    print_summary(results)

    from backend.prompts import load_prompt, prompt_version

    meta = {
        "timestamp": datetime.now(UTC).strftime("%Y-%m-%dT%H-%M-%SZ"),
        "prompt_version": prompt_version(),
        "model": os.environ.get("OPENROUTER_MODEL", "unknown"),
    }
    folder = write_results(results, meta)
    # Snapshot the exact prompt, so uncommitted prompt iterations stay recoverable.
    (folder / "prompt.txt").write_text(load_prompt(), encoding="utf-8")
    print(f"\nSaved results to {folder}")
    code = exit_code(results)
    if code:
        print(f"FAILED: {', '.join(STRICT_CATEGORIES)} must all be at 100%.")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
