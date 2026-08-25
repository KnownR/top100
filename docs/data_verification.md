# Data verification log

## Task 1 (pre-Phase-4 repair session) — 2026-08-26

Both `populous_countries.json` and `highest_grossing_films.json` were expanded
from 35 to 100 entries in Phase 2 by a background agent using WebFetch/WebSearch.
Before trusting any downstream `hard_negative` labels, both lists were
independently re-verified against their cited sources.

### Method

**Important finding: WebFetch's self-reported rank numbers on these tables
are unreliable and cannot be trusted directly.** The first verification
attempt asked WebFetch to number rows 30-105 of the countries table, and it
returned rank 30 = Mexico. A second fetch of the same page asking for rows
1-30 returned rank 30 = South Korea — a direct contradiction from the same
live page. This is a tool artifact (a summarization model re-deriving row
numbers on a large table, not reading a stable index), not a real data
error — but it looked exactly like the 20-rank systematic shift you'd
expect from a model-hallucinated expansion, so it's worth recording as a
false alarm that was caught and resolved, not waved away.

The reliable method used instead: anchor on a known, unambiguous entity
name and ask WebFetch for the next N names in table order, with **no rank
numbers in the prompt or response** — order/adjacency is what the
summarizer transcribes faithfully; self-reported absolute numbers are not.
Every one of our claimed entries was then checked by position relative to
a real anchor, not by an asserted rank number.

### `populous_countries.json` (source: Wikipedia, "List of countries and
dependencies by population")

Verified via four overlapping fetches, together covering the full 1-100
range against real, live table order:

- Rows 1-12 (direct): India, China, US, Indonesia, Pakistan, Nigeria,
  Brazil, Bangladesh, Russia, Mexico, Japan, DR Congo — **matches file
  exactly.**
- Rows 1-30 (direct): confirmed same, ending South Korea at 30 — **matches.**
- 20 rows after "Uganda" (our rank 35): Afghanistan...Niger — **matches
  file ranks 36-55 exactly.**
- 25 rows after "Niger" (our rank 55): Syria...Tunisia — **matches file
  ranks 56-80 exactly.**
- 22 rows after "Tunisia" (our rank 80): Jordan...Switzerland (20 of the
  22), then Belarus, Togo (real ranks 101-102, beyond our top 100) —
  **matches file ranks 81-100 exactly**, and additionally confirms Belarus
  and Togo are the real next two entries past our cutoff (used in Task 2).

**Result: zero incorrect entries found.** Full 100-entry order verified
against the live source, not just a 20-entry spot check.

### `highest_grossing_films.json` (source: Wikipedia "List of
highest-grossing films" for ranks 1-50, Box Office Mojo all-time worldwide
chart for ranks 51-100)

- Wikipedia rows 1-35 (direct): Avatar...Aquaman — **matches file exactly.**
- 20 rows after "Aquaman" (our rank 35): LOTR Return of the King...Rogue
  One — **matches file ranks 36-50 exactly.**
- Box Office Mojo ranks 51-100 (direct chart fetch): BOM's own rank 51 is
  Rogue One, which duplicates our rank 50 (a known boundary overlap
  between the two sources, already correctly deduplicated by the original
  curator — confirmed Rogue One appears exactly once in the file, at rank
  50). Once that one-position offset is accounted for, BOM ranks 52-100
  (49 titles) map 1:1 in order onto our file's ranks 51-99, and BOM's
  implied rank 101 (not fetched) would be our rank 100, Guardians of the
  Galaxy Vol. 2 — consistent with a clean, correctly-shifted merge.

**Result: zero incorrect entries found** across the full 100-entry range.

### Conclusion

Contrary to the working assumption going in, neither list required any
correction — both are accurate reproductions of their cited sources'
current ordering, verified end-to-end via anchor-based cross-checks rather
than trusting either the original curation agent's self-report or a single
WebFetch's self-numbered output. This does not rule out the underlying
sources themselves changing over time (population estimates and box-office
running totals are both live-updated), only that our snapshot matches the
source at verification time (2026-08-26).
