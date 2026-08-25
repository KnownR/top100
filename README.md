# Top 100

Multiplayer ranked guessing game. See `WORKPLAN.md` for the full spec and
build plan. This README is a placeholder until Phase 9 (deploy + README),
when it gets replaced with the metrics-first structure WORKPLAN specifies.

## Data freeze (2026-08-26)

`data/lists/*.json` and `data/eval/match_eval.jsonl` are **frozen** as of
the pre-Phase-4 repair session (see `docs/data_verification.md` for the
verification work that preceded this freeze):

- `populous_countries.json` and `highest_grossing_films.json` were
  independently re-verified against their cited live sources and found
  correct (see `docs/data_verification.md`).
- The `hard_negative` bucket was rebuilt using real entries at ranks
  101-140 of each list (just outside the top 100), replacing the batch
  that had gone stale when Phase 2 expanded the lists to 100 entries.

**Do not edit any list file or the eval set without explicitly re-auditing
the eval set afterward.** Concretely: if a list's entries, ranks, or count
change, re-run a check for whether any `hard_negative` guess in
`data/eval/match_eval.jsonl` is now actually on the list (a guess can
silently become a legitimate match if the list grows to include it), and
whether any `expected_entry` reference still points at a real entry. This
already happened once (Phase 2) and quietly corrupted 19 eval labels
without anyone noticing until the matcher's numbers stopped making sense.
