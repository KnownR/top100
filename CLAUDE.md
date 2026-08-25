# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

"Top 100" is a party guessing game (players guess entries on a hidden 100-item ranked list, scoring `rank` points per correct guess). The game itself is a thin shell — **the actual substance of this project is the guess-matching pipeline**: resolving messy free-text player input to the correct list entry, cheaply, fast, and with near-zero false accepts. Everything about priorities, scope, and what "done" means is measured against that pipeline, not the game UI.

**Read `WORKPLAN.md` in full before doing any non-trivial work here.** It is the spec: exact data schemas, per-stage thresholds and logic, the phase-by-phase build order, and the definition of done. This file only covers what WORKPLAN.md doesn't: the current implementation state and lessons already learned the hard way. Don't duplicate WORKPLAN.md's content here — when in doubt, that file wins.

Non-negotiable decisions already made in WORKPLAN.md (do not revisit): async rounds (no live multiplayer sync), independent per-player scoring, hand-curated static JSON lists (never LLM-generated), false accepts weighted far worse than false rejects, and the LLM used only as a last-resort adjudicator — never in the hot path, never for scoring or list generation.

## Build order is strict — do not skip phases

WORKPLAN.md section 4 defines the build order (eval set → lists → Stage 0-2 → Stage 3 → Stage 4 → threshold sweep → game → frontend → deploy). Do not write game/UI code before the matcher is measured, and do not change a threshold in `app/matcher/config.py` without re-running `eval/run_eval.py` afterward. The eval set is the highest-leverage artifact in the repo — never weaken a label just to make a number look better; if a fix is needed, fix the matcher or fix a genuinely mislabeled case, and say which.

**Current status:** Phases 1-3 are done (eval set, 15 curated lists, Stages 0-2 implemented and measured). Stage 3 (embeddings), Stage 4 (LLM), the threshold sweep, and everything game/frontend-related (Phases 4-9) are not yet built.

## Commands

```bash
pip install -r requirements.txt      # rapidfuzz + pytest (only deps needed so far)

python eval/run_eval.py              # run the 200-pair eval set through the real pipeline, print metrics
python eval/run_eval.py --stub       # same, but against the reject-everything stub (sanity check the harness itself)

python -m pytest tests/ -q           # full test suite
python -m pytest tests/test_lexical.py -q   # single test file
python -m pytest tests/test_cache.py::test_colliding_forms_are_not_auto_resolved -q  # single test
```

There is no git repo initialized yet, no build/lint step, and no `app/main.py` (FastAPI app) yet — those come with the game phase.

`data/top100.db` is the SQLite Stage-1 adjudication cache. It's a disposable local artifact (gitignored) — delete it freely if you need a clean state; it gets recreated on next run.

## Architecture

The pipeline lives entirely in `app/matcher/` and is staged: each stage either resolves the guess or passes it down to the next.

- `config.py` — **every threshold, everywhere.** `LEX_ACCEPT`/`LEX_GAP`/`LEX_FLOOR`, `EMB_*`, `LLM_ACCEPT`. `eval/sweep.py` (Phase 6, not built yet) will grid-search these. Never hardcode a threshold anywhere else in `matcher/`.
- `normalize.py` — Stage 0. Two entry points, not one: `normalize_entry()` (list data — strips bracketed suffixes like "(Remastered 2011)") and `normalize_guess()` (player input — strips conversational filler like "i think its"). Both share a common fold (lowercase, strip diacritics, strip punctuation, collapse whitespace, drop a *leading* article only — "the" mid-string is left alone, which matters for titles like "Avatar: The Way of Water").
- `cache.py` — Stage 1. Loads a list JSON file once (module-level `_LIST_CACHE`), builds `Entry.normalized_forms` from display+canonical+aliases, and an `exact_lookup` dict for O(1) hits. **Critical invariant:** if a normalized form is claimed by more than one entry (e.g. two entries both normalizing to "hello"), it is deliberately *excluded* from `exact_lookup` rather than assigned to whichever entry loaded first — this is what makes the WORKPLAN "ambiguity trap" ("never silently pick one") actually hold, letting the guess fall through to Stage 2's gap check instead of being silently resolved. Persisted adjudications live in SQLite (`app/db.py`, table `match_cache`) and are merged in via `ListData.adjudicated`.
- `lexical.py` — Stage 2. `rapidfuzz.fuzz.token_set_ratio`, scored per-entry as the max across that entry's `normalized_forms`. Accepts only if `score >= LEX_ACCEPT` **and** `score - runner_up >= LEX_GAP` — the gap check, not the raw score, is what prevents ties from being silently resolved.
- `pipeline.py` — orchestrates cache → lexical → (Stage 3/4, not built yet — currently just falls through to reject). **Only Stage 4 (LLM) results get written back to the Stage 1 cache** (`cache.write_back`), never Stage 2/3. Caching a probabilistic mid-pipeline decision would permanently freeze it against future threshold retuning, defeating the entire point of the sweep script — this was a real bug found and fixed during Phase 3, not a hypothetical.

### A known, accepted limitation (don't try to "fix" this with more lexical hacks)

`rapidfuzz.fuzz.token_set_ratio` scores 100 whenever one string's tokens are a pure subset of the other's, in *either* direction. This means a franchise family sharing vocabulary (e.g. "Avatar" / "Avatar: The Way of Water" / "Avatar: Fire and Ash") can score identically regardless of how specific the guess actually is — a bare "avatar" guess correctly ties across all three (good, triggers ambiguity), but so can longer guesses like "avatar movie" or even, in the reverse direction, one entry's own full canonical title tested against a shorter sibling. Adding shared aliases across sibling entries to force explicit ties was tried and reverted — it fixed some cases but broke specific, unambiguous guesses like "avatar way of water" by making them falsely tie too. This is an inherent lexical-matching limitation, not a bug to keep patching: Stage 3 (semantic embeddings) and Stage 4 (LLM adjudication) are the actual fix, per WORKPLAN's own design. The current Stage 1-3 false-accept rate on these cases is the honest, correct baseline for the ablation table — don't chase it lower with lexical-only tricks.

### Testing patterns

- `tests/conftest.py` inserts the repo root onto `sys.path` (needed because `app/` isn't installed as a package and tests run from `tests/`).
- Tests that touch `cache.py` must isolate both the list directory and the SQLite path via `monkeypatch` (see the `temp_list` fixture in `tests/test_cache.py`/`tests/test_pipeline.py`) and must clear `cache_module._LIST_CACHE` before each case — the module-level list cache otherwise leaks state between tests.
- `app/db.py`'s `get_connection()` resolves `DB_PATH` at call time (not as a bound default argument) specifically so tests can monkeypatch `db.DB_PATH` — don't change it back to a default-parameter pattern, that silently breaks test isolation.
- Mock/avoid the LLM in all tests once Stage 4 exists — tests must run offline.

## Data

- `data/lists/*.json` — one file per category. Schema: `id`/`title`/`subtitle`/`source`/`source_url`/`curated_at`/`entries[]`, each entry `rank`/`id`/`display`/`canonical`/`aliases`/`disambiguator`. **Every list must carry a real, verifiable `source_url`** — several lists here are intentionally short of the "100 entries" target (e.g. `most_spoken_languages` at 38, `longest_reigning_monarchs` at 25) because the underlying real-world data genuinely doesn't support more reliably-sourced entries; that's a deliberate curation decision, not a shortcut, and should never be papered over by fabricating rows.
- `data/eval/match_eval.jsonl` — the 200-pair hand-labeled eval set, one JSON object per line: `id`/`list_id`/`guess`/`expected` (`match`|`reject`|`clarify`)/`expected_entry`/`bucket` (`clean_positive`|`hard_negative`|`ambiguous`|`adversarial`)/`note`. If you change what a list contains, re-check whether any eval case's expected label went stale (this happened for real during Phase 2 — expanding a list's entry count silently turned several `hard_negative` cases into legitimate matches). A quick way to audit: normalize every eval guess and check whether it now exactly matches an entry that wasn't there before.
