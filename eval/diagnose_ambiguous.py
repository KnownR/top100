"""Diagnostic for Task 3 (pre-Phase-4 repair session): is the ambiguous
bucket's 0% accuracy because ties are detected-but-mishandled, or because
the clarify path is simply never reached at all?

Answer (see report below): the gap check in matcher/lexical.py DOES
correctly compute score/runner-up/gap for every guess, and that data
survives into MatchResult.score / MatchResult.runner_up_score even on a
reject. But matcher/pipeline.py's `match_guess` (see the comment at its
"reject rather than risk a false accept" line) collapses every single
non-accept lexical decision -- both "nothing scored close" and "two things
tied at the top" -- into the exact same outcome="reject",
resolved_by="reject_floor" result. There is no line of code anywhere in
app/matcher/ that ever constructs outcome="clarify"; the Literal type
allows it, but nothing produces it. This is fully expected per the
pipeline.py docstring/comment: clarify is Stage 4's job (WORKPLAN section
3: "match == null and >=2 candidates scored closely upstream -> clarify"),
and Stage 4 doesn't exist yet. It is not a bug to fix here -- Task 3 is
diagnosis only, not a fix.

This script provides the concrete evidence: it re-derives, for every
ambiguous-bucket eval case, whether a genuine tie was actually detected
underneath the collapsed "reject" outcome.
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.matcher import config
from app.matcher.pipeline import match_guess
from eval.run_eval import load_eval_set


def classify(result) -> str:
    """Recover, post-hoc, which branch of lexical.match produced this
    result -- information the pipeline itself discards."""
    if result.resolved_by == "cache":
        return "resolved_by_cache (never reached lexical scoring at all)"
    if result.outcome == "match":
        return "accepted (not ambiguous)"
    if result.score < config.LEX_FLOOR:
        return "below_floor (no plausible candidate; not a tie)"
    gap = result.score - (result.runner_up_score or 0.0)
    if result.score >= config.LEX_ACCEPT and gap < config.LEX_GAP:
        return f"GENUINE_TIE_DETECTED (score={result.score:.1f}, runner_up={result.runner_up_score:.1f}, gap={gap:.1f})"
    return f"mid_range_no_accept (score={result.score:.1f}, runner_up={result.runner_up_score})"


def main() -> None:
    all_cases = load_eval_set()

    clarify_count = sum(1 for c in all_cases if match_guess(c.guess, c.list_id).outcome == "clarify")
    print("=" * 70)
    print(f"outcome=='clarify' across all {len(all_cases)} eval cases: {clarify_count}")
    print("=" * 70)

    ambiguous = [c for c in all_cases if c.bucket == "ambiguous"]
    tie_detected = 0
    below_floor = 0
    accepted_wrong = 0
    other = 0

    print(f"\n{'id':<6}{'guess':<40}{'classification'}")
    print("-" * 100)
    for c in ambiguous:
        result = match_guess(c.guess, c.list_id)
        label = classify(result)
        print(f"{c.id:<6}{c.guess[:38]:<40}{label}")
        if "GENUINE_TIE_DETECTED" in label:
            tie_detected += 1
        elif "below_floor" in label:
            below_floor += 1
        elif result.outcome == "match":
            accepted_wrong += 1
        else:
            other += 1

    print("-" * 100)
    print(f"\nOf {len(ambiguous)} ambiguous-bucket cases:")
    print(f"  {tie_detected} had a genuine gap-check tie detected underneath the collapsed reject")
    print(f"  {below_floor} never scored close to anything (no tie to detect)")
    print(f"  {accepted_wrong} were wrongly accepted outright (known franchise-containment limitation)")
    print(f"  {other} other (mid-range score, no accept, no clean tie)")
    print(
        "\nConclusion: the clarify outcome is unreachable dead code, not a "
        "mishandled detection. lexical.match() already computes the gap "
        "correctly (see the GENUINE_TIE_DETECTED rows above) -- the "
        "information exists, but pipeline.match_guess() has no branch that "
        "turns 'score>=LEX_ACCEPT and gap<LEX_GAP' into outcome='clarify'; "
        "every non-accept path funnels into the same reject_floor result. "
        "Fixing this is Stage 4's job per WORKPLAN, not a Phase-3 patch."
    )


if __name__ == "__main__":
    main()
