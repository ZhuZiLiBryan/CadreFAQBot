"""Eval runner: `uv run python -m evals.run [--case ID] [--category NAME]`.

Runs each case in `evals/cases.yaml` through the same in-process code path as
`POST /api/chat` (so server-side assembly applies) against the real model, and
scores the Outcome and cited FAQ Entry IDs, never the wording. This spends API
quota, so it is not part of `pytest`; only the pure helpers are tested there.
"""

import argparse
import asyncio
import json
import os
import time
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path

import yaml

CASES_PATH = Path(__file__).parent / "cases.yaml"
RESULTS_DIR = Path(__file__).parent / "results"  # git-ignored


def score_case(case: dict, outcome: str, cited_ids: list[int]) -> bool:
    """Pass when the Outcome is expected and, if citations are expected, at least
    one expected FAQ Entry ID is cited."""
    expected = case["expected_outcome"]
    allowed = [expected] if isinstance(expected, str) else list(expected)
    if outcome not in allowed:
        return False
    expected_citations = case.get("expected_citations") or []
    if not expected_citations: # No citations needed for this case
        return True
    return any(n in cited_ids for n in expected_citations) # check at least one citation in result


def pass_rates_by_category(results: list[dict]) -> dict[str, float]:
    """Fraction of passed results per category, for the categories that were run."""
    totals: dict[str, int] = defaultdict(int)
    passes: dict[str, int] = defaultdict(int)
    for result in results:
        totals[result["category"]] += 1
        passes[result["category"]] += bool(result["passed"])
    return {category: passes[category] / total for category, total in totals.items()}


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


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="python -m evals.run", description=__doc__)
    parser.add_argument("--case", default=None, help="run only the case with this id")
    parser.add_argument("--category", default=None, help="run only this category")
    return parser.parse_args(argv)


async def run_case(case: dict, client) -> dict:
    from backend.chat import handle_chat
    from backend.model_client import UpstreamError
    from backend.schemas import ChatRequest

    request = ChatRequest(message=case["question"], history=case.get("history") or [])
    started = time.perf_counter()
    try:
        reply, result = await handle_chat(request, client)
    except UpstreamError as exc:
        return _result(
            case,
            passed=False,
            error=f"upstream error: {exc}",
            latency_ms=_elapsed_ms(started),
        )
    cited = [c.faq_id for c in reply.citations]
    return _result(
        case,
        passed=score_case(case, reply.outcome, cited),
        outcome=reply.outcome,
        answer=reply.answer,
        cited=cited,
        served_model=result.served_model,
        raw_outcome=result.outcome,
        raw_answer=result.answer,
        raw_citations=list(result.citations),
        tokens_in=result.tokens_in,
        tokens_out=result.tokens_out,
        latency_ms=_elapsed_ms(started),
    )


def _elapsed_ms(started: float) -> int:
    return round((time.perf_counter() - started) * 1000)


def _result(case: dict, **fields) -> dict:
    return {
        "id": case["id"],
        "category": case["category"],
        "question": case["question"],
        "history": case.get("history") or [],
        "expected_outcome": case["expected_outcome"],
        "expected_citations": case.get("expected_citations") or [],
        "outcome": None,
        "answer": "",
        "cited": [],
        "served_model": "-",
        "error": None,
        **fields,
    }


def render_report(results: list[dict], meta: dict) -> str:
    """Markdown report for manual grading of groundedness and faithfulness."""
    lines = [
        "# Eval report",
        "",
        f"- Run (UTC): {meta['timestamp']}",
        f"- Prompt Version: `{meta['prompt_version']}`",
        f"- Configured model: `{meta['model']}`",
        "",
        "## Pass rate by category",
        "",
        "| category | passed | rate |",
        "|---|---|---|",
    ]
    for category, rate in sorted(pass_rates_by_category(results).items()):
        rows = [r for r in results if r["category"] == category]
        passed = sum(bool(r["passed"]) for r in rows)
        lines.append(f"| {category} | {passed}/{len(rows)} | {rate:.0%} |")
    lines += ["", "## Cases", ""]
    for r in results:
        lines += [
            f"### {'PASS' if r['passed'] else 'FAIL'} `{r['id']}` ({r['category']})",
            "",
            f"- **Question:** {r['question']}",
        ]
        if r["history"]:
            lines.append(f"- **History:** {r['history']}")
        lines += [
            f"- **Expected:** outcome {r['expected_outcome']}, "
            f"cites any of {r['expected_citations'] or 'none'}",
            f"- **Got:** outcome {r['outcome']}, cited {r['cited']}, "
            f"model `{r['served_model']}`",
        ]
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
    with open(folder / "results.jsonl", "w", encoding="utf-8") as f:
        for r in results:
            f.write(json.dumps({**r, **meta}, ensure_ascii=False) + "\n")
    (folder / "report.md").write_text(render_report(results, meta), encoding="utf-8")
    return folder


def print_result(result: dict) -> None:
    status = "PASS" if result["passed"] else "FAIL"
    print(f"[{status}] {result['id']} ({result['category']})")
    print(f"  question: {result['question']}")
    if result["error"]:
        print(f"  error:    {result['error']}")
        return
    print(f"  outcome:  {result['outcome']}")
    print(f"  answer:   {result['answer']}")
    print(f"  cited:    {result['cited']}")
    print(f"  model:    {result['served_model']}")


def print_summary(results: list[dict]) -> None:
    rates = pass_rates_by_category(results)
    width = max((len(c) for c in rates), default=8)
    print(f"\n{'category'.ljust(width)}  passed  rate")
    for category, rate in sorted(rates.items()):
        rows = [r for r in results if r["category"] == category]
        passed = sum(r["passed"] for r in rows)
        print(f"{category.ljust(width)}  {passed}/{len(rows)}    {rate:.0%}")


async def run_all(cases: list[dict]) -> list[dict]:
    from backend.faq import get_faq
    from backend.model_client import get_model_client
    from backend.prompts import prompt_version

    get_faq()
    client = get_model_client()
    print(f"Prompt Version: {prompt_version()}\n")
    results = []
    for case in cases:  # sequential: free-tier models are rate limited
        result = await run_case(case, client)
        print_result(result)
        results.append(result)
    return results


def main(argv: list[str] | None = None) -> int:
    from dotenv import load_dotenv

    load_dotenv()
    args = parse_args(argv)
    cases = filter_cases(load_cases(), case_id=args.case, category=args.category)
    if not cases:
        print("No cases match the given filters.")
        return 2
    results = asyncio.run(run_all(cases))
    print_summary(results)

    from backend.prompts import prompt_version

    meta = {
        "timestamp": datetime.now(UTC).strftime("%Y-%m-%dT%H-%M-%SZ"),
        "prompt_version": prompt_version(),
        "model": os.environ.get("OPENROUTER_MODEL", "unknown"),
    }
    from backend.prompts import load_prompt

    folder = write_results(results, meta)
    # Snapshot the exact prompt, so uncommitted prompt iterations stay recoverable.
    (folder / "prompt.txt").write_text(load_prompt(), encoding="utf-8")
    print(f"\nSaved results to {folder}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
