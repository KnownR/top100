"""Orchestration of the matching pipeline.

Phase 3 scope: Stages 0-2 only (normalize, cache, lexical). Stages 3
(embedding) and 4 (LLM) land in Phases 4-5 — until then, anything that
survives Stage 2 without accepting falls through to a reject floor. That's
the expected Phase-3 baseline: decent on clean positives, poor on
ambiguous, some false accepts possible on hard negatives (rapidfuzz alone
can be fooled by a lexically-close wrong answer).
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Literal

from . import cache, lexical, normalize

Outcome = Literal["match", "reject", "clarify"]
ResolvedBy = Literal["cache", "lexical", "embedding", "llm", "reject_floor"]


@dataclass
class MatchResult:
    outcome: Outcome
    entry_id: str | None
    rank: int | None
    resolved_by: ResolvedBy
    score: float
    runner_up_score: float | None
    candidates: list[str] = field(default_factory=list)
    latency_ms: float = 0.0
    cost_usd: float = 0.0


def match_guess(guess: str, list_id: str) -> MatchResult:
    start = time.perf_counter()
    list_data = cache.get_list(list_id)
    normalized = normalize.normalize_guess(guess)

    cache_hit = cache.lookup(list_id, normalized)
    if cache_hit is not None:
        entry_id, outcome = cache_hit
        return _finish(
            outcome, entry_id, list_data.rank_of(entry_id), "cache", 100.0, None, start
        )

    lex = lexical.match(normalized, list_data)
    if lex.decision == "accept":
        # Deliberately not written back to the Stage 1 cache: only Stage 4
        # (LLM) adjudications get persisted (see WORKPLAN section 3). A
        # cached lexical/embedding decision would permanently bypass Stage
        # 2's gap check on repeat, surviving even a later threshold change.
        return _finish(
            "match",
            lex.entry_id,
            list_data.rank_of(lex.entry_id),
            "lexical",
            lex.score,
            lex.runner_up_score,
            start,
        )

    # No Stage 3/4 yet (Phase 4/5) -> reject rather than risk a false accept.
    return _finish("reject", None, None, "reject_floor", lex.score, lex.runner_up_score, start)


def _finish(
    outcome: Outcome,
    entry_id: str | None,
    rank: int | None,
    resolved_by: ResolvedBy,
    score: float,
    runner_up_score: float | None,
    start: float,
) -> MatchResult:
    latency_ms = (time.perf_counter() - start) * 1000
    return MatchResult(
        outcome=outcome,
        entry_id=entry_id,
        rank=rank,
        resolved_by=resolved_by,
        score=score,
        runner_up_score=runner_up_score,
        latency_ms=latency_ms,
    )
