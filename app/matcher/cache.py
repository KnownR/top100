"""Stage 1 — exact / alias cache (~1 ms).

Populated at list-load time with every entry's normalized display,
canonical, and hand-written aliases. Every LLM adjudication (accept AND
reject) is written back here and persisted to SQLite, so the system gets
faster and cheaper the more the game is played.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from .. import db
from . import normalize

Outcome = Literal["match", "reject", "clarify"]

DATA_LISTS_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "lists"


@dataclass
class Entry:
    id: str
    rank: int
    display: str
    canonical: str
    aliases: list[str]
    disambiguator: str | None
    normalized_forms: list[str]


@dataclass
class ListData:
    id: str
    title: str
    entries: list[Entry]
    entries_by_id: dict[str, Entry] = field(default_factory=dict)
    # normalized string -> entry_id, from display/canonical/aliases
    exact_lookup: dict[str, str] = field(default_factory=dict)
    # normalized string -> (entry_id_or_None, outcome), from persisted LLM adjudications
    adjudicated: dict[str, tuple[str | None, Outcome]] = field(default_factory=dict)

    def rank_of(self, entry_id: str | None) -> int | None:
        if entry_id is None:
            return None
        entry = self.entries_by_id.get(entry_id)
        return entry.rank if entry else None


_LIST_CACHE: dict[str, ListData] = {}


def _load_entry(raw: dict) -> Entry:
    # List files use "canonical" as the entry id when no explicit "id" is given.
    entry_id = raw.get("id") or raw["canonical"]
    aliases = raw.get("aliases", [])
    forms = {normalize.normalize_entry(raw["display"])}
    forms.add(normalize.normalize_entry(raw["canonical"]))
    for alias in aliases:
        forms.add(normalize.normalize_entry(alias))
    forms.discard("")
    return Entry(
        id=entry_id,
        rank=raw["rank"],
        display=raw["display"],
        canonical=raw["canonical"],
        aliases=aliases,
        disambiguator=raw.get("disambiguator"),
        normalized_forms=sorted(forms),
    )


def _load_adjudicated(list_id: str) -> dict[str, tuple[str | None, Outcome]]:
    conn = db.get_connection()
    try:
        rows = conn.execute(
            "SELECT normalized_guess, entry_id, outcome FROM match_cache WHERE list_id = ?",
            (list_id,),
        ).fetchall()
    finally:
        conn.close()
    return {row[0]: (row[1], row[2]) for row in rows}


def get_list(list_id: str) -> ListData:
    if list_id in _LIST_CACHE:
        return _LIST_CACHE[list_id]

    path = DATA_LISTS_DIR / f"{list_id}.json"
    with open(path, encoding="utf-8") as f:
        raw = json.load(f)

    entries = [_load_entry(e) for e in raw["entries"]]
    list_data = ListData(id=raw["id"], title=raw["title"], entries=entries)
    list_data.entries_by_id = {e.id: e for e in entries}

    claims: dict[str, set[str]] = {}
    for entry in entries:
        for form in entry.normalized_forms:
            claims.setdefault(form, set()).add(entry.id)

    for form, entry_ids in claims.items():
        if len(entry_ids) == 1:
            list_data.exact_lookup[form] = next(iter(entry_ids))
        # A form claimed by >1 entry (e.g. "avatar" as both the 2009 film's
        # canonical and a shared alias on its sequels) is genuinely
        # ambiguous. Deliberately NOT cached here, so it falls through to
        # Stage 2, whose score-gap check refuses to silently pick one
        # instead of short-circuiting straight to a single "exact" match.

    list_data.adjudicated = _load_adjudicated(list_id)

    _LIST_CACHE[list_id] = list_data
    return list_data


def lookup(list_id: str, normalized_guess: str) -> tuple[str | None, Outcome] | None:
    """Returns (entry_id_or_None, outcome) on a cache hit, else None."""
    list_data = get_list(list_id)

    if normalized_guess in list_data.adjudicated:
        return list_data.adjudicated[normalized_guess]

    entry_id = list_data.exact_lookup.get(normalized_guess)
    if entry_id is not None:
        return entry_id, "match"

    return None


def write_back(
    list_id: str,
    normalized_guess: str,
    entry_id: str | None,
    outcome: Outcome,
) -> None:
    """Persist an adjudication (accept or reject) so it's a cache hit next time."""
    list_data = get_list(list_id)
    list_data.adjudicated[normalized_guess] = (entry_id, outcome)

    conn = db.get_connection()
    try:
        conn.execute(
            """
            INSERT INTO match_cache (list_id, normalized_guess, entry_id, outcome, resolved_by)
            VALUES (?, ?, ?, ?, 'llm')
            ON CONFLICT(list_id, normalized_guess) DO UPDATE SET
                entry_id = excluded.entry_id,
                outcome = excluded.outcome,
                resolved_by = excluded.resolved_by
            """,
            (list_id, normalized_guess, entry_id, outcome),
        )
        conn.commit()
    finally:
        conn.close()
