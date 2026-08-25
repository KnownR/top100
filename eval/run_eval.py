"""Runs the labelled eval set through a matcher and prints a metrics table.

Phase 1: wired to a stub matcher that rejects every guess, just to prove the
harness works before matcher/ exists. Later phases swap `match_fn` for the
real pipeline (see `run_eval`) without touching this script.
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Literal

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

Outcome = Literal["match", "reject", "clarify"]

EVAL_PATH = Path(__file__).resolve().parent.parent / "data" / "eval" / "match_eval.jsonl"

BUCKETS = ("clean_positive", "hard_negative", "ambiguous", "adversarial")


@dataclass
class EvalCase:
    id: str
    list_id: str
    guess: str
    expected: Outcome
    expected_entry: str | None
    bucket: str
    note: str


@dataclass
class CaseResult:
    case: EvalCase
    outcome: Outcome
    entry_id: str | None
    resolved_by: str
    cost_usd: float


def load_eval_set(path: Path = EVAL_PATH) -> list[EvalCase]:
    cases = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            cases.append(
                EvalCase(
                    id=row["id"],
                    list_id=row["list_id"],
                    guess=row["guess"],
                    expected=row["expected"],
                    expected_entry=row["expected_entry"],
                    bucket=row["bucket"],
                    note=row["note"],
                )
            )
    return cases


def stub_reject_all(list_id: str, guess: str) -> tuple[Outcome, str | None, str, float]:
    """Dumb stub matcher: rejects every guess. Proves the harness works."""
    return "reject", None, "reject_floor", 0.0


def real_pipeline(list_id: str, guess: str) -> tuple[Outcome, str | None, str, float]:
    """Wraps app.matcher.pipeline.match_guess to the match_fn signature."""
    from app.matcher.pipeline import match_guess

    result = match_guess(guess, list_id)
    return result.outcome, result.entry_id, result.resolved_by, result.cost_usd


def run_eval(
    match_fn: Callable[[str, str], tuple[Outcome, str | None, str, float]],
    eval_path: Path = EVAL_PATH,
) -> list[CaseResult]:
    cases = load_eval_set(eval_path)
    results = []
    for case in cases:
        outcome, entry_id, resolved_by, cost_usd = match_fn(case.list_id, case.guess)
        results.append(CaseResult(case, outcome, entry_id, resolved_by, cost_usd))
    return results


def is_false_accept(r: CaseResult) -> bool:
    # Expected reject/clarify, but the matcher confidently returned a wrong match.
    return r.case.expected in ("reject", "clarify") and r.outcome == "match"


def is_false_reject(r: CaseResult) -> bool:
    # Expected a match, but the matcher didn't produce one.
    return r.case.expected == "match" and r.outcome != "match"


def is_correct(r: CaseResult) -> bool:
    if r.case.expected == "match":
        return r.outcome == "match" and r.entry_id == r.case.expected_entry
    return r.outcome == r.case.expected


def print_report(results: list[CaseResult]) -> None:
    total = len(results)
    false_accepts = [r for r in results if is_false_accept(r)]
    false_rejects = [r for r in results if is_false_reject(r)]
    escalations = [r for r in results if r.resolved_by == "llm"]
    total_cost = sum(r.cost_usd for r in results)

    print("=" * 60)
    print(f"EVAL REPORT  ({total} cases, {EVAL_PATH.name})")
    print("=" * 60)
    print(f"{'False accept rate':<28}{len(false_accepts) / total:>8.1%}  ({len(false_accepts)}/{total})")
    print(f"{'False reject rate':<28}{len(false_rejects) / total:>8.1%}  ({len(false_rejects)}/{total})")
    print(f"{'LLM escalation rate':<28}{len(escalations) / total:>8.1%}  ({len(escalations)}/{total})")
    print(f"{'Cost per 1,000 guesses':<28}${total_cost / total * 1000:>7.4f}")
    print()

    print(f"{'Bucket':<16}{'Count':>7}{'Correct':>9}{'Accuracy':>11}")
    print("-" * 60)
    by_bucket: dict[str, list[CaseResult]] = defaultdict(list)
    for r in results:
        by_bucket[r.case.bucket].append(r)
    for bucket in BUCKETS:
        rs = by_bucket.get(bucket, [])
        if not rs:
            continue
        correct = sum(1 for r in rs if is_correct(r))
        print(f"{bucket:<16}{len(rs):>7}{correct:>9}{correct / len(rs):>10.1%}")
    print("=" * 60)


if __name__ == "__main__":
    import sys as _sys

    use_stub = "--stub" in _sys.argv
    results = run_eval(stub_reject_all if use_stub else real_pipeline)
    print_report(results)
