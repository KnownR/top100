"""Runs the labelled eval set through a matcher and prints a metrics table.

Phase 1: wired to a stub matcher that rejects every guess, just to prove the
harness works before matcher/ exists. Later phases swap `match_fn` for the
real pipeline (see `run_eval`) without touching this script.
"""
from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
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
    score: float = 0.0
    runner_up_score: float | None = None


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


MatchFnResult = tuple[Outcome, "str | None", str, float, float, "float | None"]


def stub_reject_all(list_id: str, guess: str) -> MatchFnResult:
    """Dumb stub matcher: rejects every guess. Proves the harness works."""
    return "reject", None, "reject_floor", 0.0, 0.0, None


def real_pipeline(list_id: str, guess: str) -> MatchFnResult:
    """Wraps app.matcher.pipeline.match_guess to the match_fn signature."""
    from app.matcher.pipeline import match_guess

    result = match_guess(guess, list_id)
    return (
        result.outcome,
        result.entry_id,
        result.resolved_by,
        result.cost_usd,
        result.score,
        result.runner_up_score,
    )


def run_eval(
    match_fn: Callable[[str, str], MatchFnResult],
    eval_path: Path = EVAL_PATH,
) -> list[CaseResult]:
    cases = load_eval_set(eval_path)
    results = []
    for case in cases:
        outcome, entry_id, resolved_by, cost_usd, score, runner_up_score = match_fn(case.list_id, case.guess)
        results.append(CaseResult(case, outcome, entry_id, resolved_by, cost_usd, score, runner_up_score))
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


OUTCOMES: tuple[Outcome, ...] = ("match", "reject", "clarify")

RESOLVED_BY_STAGES = ("cache", "lexical", "embedding", "llm", "reject_floor")

FAILURES_PATH = Path(__file__).resolve().parent.parent / "data" / "eval" / "failures.jsonl"


def print_confusion_matrix(results: list[CaseResult]) -> None:
    # Rows: expected outcome. Columns: actual outcome. A clarify-case
    # wrongly matched and a reject-case wrongly matched both land in the
    # "match" column, but they're different failures needing different
    # fixes (an ambiguity the pipeline should have flagged, vs. a hard
    # negative it should never have entertained at all) -- this matrix is
    # what makes that distinction visible instead of both just inflating
    # the same "false accept" number.
    matrix: dict[str, dict[str, int]] = {e: {a: 0 for a in OUTCOMES} for e in OUTCOMES}
    for r in results:
        matrix[r.case.expected][r.outcome] += 1

    print(f"{'expected \\ actual':<20}{'match':>10}{'reject':>10}{'clarify':>10}")
    print("-" * 60)
    for expected in OUTCOMES:
        row = matrix[expected]
        print(f"{expected:<20}{row['match']:>10}{row['reject']:>10}{row['clarify']:>10}")
    print("=" * 60)


def print_stage_counts(results: list[CaseResult]) -> None:
    counts = Counter(r.resolved_by for r in results)
    total = len(results)
    print(f"{'Stage':<16}{'Count':>7}{'Share':>9}")
    print("-" * 60)
    for stage in RESOLVED_BY_STAGES:
        n = counts.get(stage, 0)
        if n == 0 and stage not in counts:
            continue
        print(f"{stage:<16}{n:>7}{n / total:>8.1%}")
    unexpected = set(counts) - set(RESOLVED_BY_STAGES)
    for stage in sorted(unexpected):
        print(f"{stage:<16}{counts[stage]:>7}{counts[stage] / total:>8.1%}")
    print("=" * 60)


def classify_failure(r: CaseResult) -> str:
    """More granular than false_accept/false_reject: separates out a
    right-outcome-wrong-entity match (e.g. "frozen2" landing on "frozen"
    instead of "frozen_2") and a not-flagged ambiguity (expected clarify,
    got reject) from each other -- both would otherwise be invisible
    inside the coarser is_false_accept/is_false_reject buckets."""
    if is_false_accept(r):
        return "false_accept"
    if is_false_reject(r):
        return "false_reject"
    if r.case.expected == "match" and r.outcome == "match":
        return "wrong_entity_match"
    if r.case.expected == "clarify" and r.outcome == "reject":
        return "ambiguous_not_clarified"
    return "other"


def write_failures(results: list[CaseResult], path: Path = FAILURES_PATH) -> int:
    failures = [r for r in results if not is_correct(r)]
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for r in failures:
            f.write(
                json.dumps(
                    {
                        "id": r.case.id,
                        "list_id": r.case.list_id,
                        "guess": r.case.guess,
                        "bucket": r.case.bucket,
                        "expected": r.case.expected,
                        "expected_entry": r.case.expected_entry,
                        "note": r.case.note,
                        "actual_outcome": r.outcome,
                        "actual_entry_id": r.entry_id,
                        "resolved_by": r.resolved_by,
                        "score": round(r.score, 2),
                        "runner_up_score": round(r.runner_up_score, 2) if r.runner_up_score is not None else None,
                        "failure_kind": classify_failure(r),
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )
    return len(failures)


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
    print()

    print("Confusion matrix (expected outcome vs. actual outcome):")
    print_confusion_matrix(results)
    print()

    print("Guesses resolved at each stage:")
    print_stage_counts(results)
    print()

    n_failures = write_failures(results)
    print(f"{n_failures} failing case(s) written to {FAILURES_PATH.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    import sys as _sys

    use_stub = "--stub" in _sys.argv
    results = run_eval(stub_reject_all if use_stub else real_pipeline)
    print_report(results)
