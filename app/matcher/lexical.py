"""Stage 2 — lexical fuzzy (~5 ms).

rapidfuzz token_set_ratio against every normalized form (display, canonical,
aliases) of every entry in the active list. An entry's score is the best
score across its own forms. Catches typos and word-order variation.

The gap-from-runner-up condition is not optional: a high score with a close
runner-up means ambiguity, not confidence, and must not be silently accepted.
"""
from __future__ import annotations

from dataclasses import dataclass

from rapidfuzz import fuzz

from . import config
from .cache import ListData

Decision = str  # "accept" | "continue"


@dataclass
class LexicalResult:
    entry_id: str | None
    score: float
    runner_up_score: float | None
    decision: Decision


def match(normalized_guess: str, list_data: ListData) -> LexicalResult:
    if not normalized_guess or not list_data.entries:
        return LexicalResult(None, 0.0, None, "continue")

    scores: list[tuple[str, float]] = []
    for entry in list_data.entries:
        best = max(
            fuzz.token_set_ratio(normalized_guess, form)
            for form in entry.normalized_forms
        )
        scores.append((entry.id, best))

    scores.sort(key=lambda pair: pair[1], reverse=True)
    top_id, top_score = scores[0]
    runner_up_score = scores[1][1] if len(scores) > 1 else None

    if top_score < config.LEX_FLOOR:
        return LexicalResult(None, top_score, runner_up_score, "continue")

    gap = top_score - (runner_up_score if runner_up_score is not None else 0.0)
    if top_score >= config.LEX_ACCEPT and gap >= config.LEX_GAP:
        return LexicalResult(top_id, top_score, runner_up_score, "accept")

    return LexicalResult(None, top_score, runner_up_score, "continue")
