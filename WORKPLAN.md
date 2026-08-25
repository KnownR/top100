# Top 100 — Multiplayer Ranked Guessing Game

**Working plan for implementation. Read this fully before writing code.**

---

## 0. What we are building

A party game. Each round shows a category ("Most populous countries", "Highest-grossing films of all time"). Players type guesses. If a guess matches the entry at rank *N* on a hidden 100-item list, the player scores *N* points — so obscure correct answers are worth far more than obvious ones. After a set number of rounds, highest total wins.

The game is the surface. **The engineering substance of this project is the guess-matching pipeline**: resolving free-text player input to list entries fast, cheaply, and with near-zero false accepts. That is what gets measured, tuned, and written up.

### Non-negotiable design decisions (already settled — do not redesign these)

| Decision | Choice | Why |
|---|---|---|
| Round model | **Async**, not live-synced | Real-time lobby sync is a week of non-AI work. Everyone plays the same round on their own clock; results reveal together. |
| Duplicate guesses | **Independent scoring** — two players can both score the same entry | Removes speed pressure, removes race conditions. |
| Lists | **Hand-curated, static JSON** | LLM-generated rankings are wrong often enough to break player trust instantly. |
| Matching bias | **False accepts are much worse than false rejects** | Players tolerate "try again". They rage at being credited for the wrong entry, and rage harder at being denied a correct one. Tune accordingly. |
| LLM role | Adjudicator for ambiguous matches only | Not for generating lists, not for scoring, not in the hot path. |

### Success criteria

The project is done when the README opens with this table, filled in with real measured numbers:

| Metric | Target |
|---|---|
| False accept rate | < 1% |
| False reject rate | < 8% |
| LLM escalation rate | < 5% of guesses |
| p95 match latency | < 150 ms |
| Cost per 1,000 guesses | reported, whatever it is |

Plus a layer-ablation table (lexical only → +embeddings → +LLM) and a threshold sweep plot.

---

## 1. Stack

Keep it boring. Nothing here should be a research question.

- **Backend:** Python 3.11+, FastAPI, Uvicorn
- **Storage:** SQLite via SQLModel or plain `sqlite3`. No Postgres, no ORM ceremony.
- **Lexical matching:** `rapidfuzz`
- **Embeddings:** `sentence-transformers`, model `BAAI/bge-small-en-v1.5` (or `all-MiniLM-L6-v2`). Runs on CPU. 100 entries is nothing.
- **LLM:** Anthropic API, small/fast model. One call site only.
- **Frontend:** Single-page vanilla JS + HTML, or React if preferred. No framework debate. The UI must be functional and clean, not elaborate.
- **Deploy:** Render / Railway / Fly.io. Must end up at a public URL.

### Repo layout

```
top100/
  data/
    lists/                  # curated category lists, one JSON per category
    aliases/                # hand-written aliases, one JSON per category
    eval/
      match_eval.jsonl      # the 200-pair eval set
  app/
    main.py                 # FastAPI app, routes
    game.py                 # round lifecycle, scoring, player state
    matcher/
      __init__.py
      normalize.py          # Stage 0
      cache.py              # Stage 1
      lexical.py            # Stage 2
      embed.py              # Stage 3
      llm.py                # Stage 4
      pipeline.py           # orchestration + thresholds
      config.py             # ALL thresholds live here, nowhere else
    db.py
  eval/
    run_eval.py             # runs eval set, prints metrics table
    sweep.py                # threshold sweep, writes plot
    ablation.py             # lexical / +embed / +llm comparison
  static/                   # frontend
  tests/
  README.md
```

**Rule:** every threshold constant lives in `matcher/config.py`. Zero magic numbers scattered in the matching code. The sweep script mutates that config; if thresholds are hardcoded elsewhere, the sweep is meaningless.

---

## 2. Data formats

### List file — `data/lists/populous_countries.json`

```json
{
  "id": "populous_countries",
  "title": "Most Populous Countries",
  "subtitle": "By population, 2024 estimates",
  "source": "UN World Population Prospects 2024",
  "source_url": "https://...",
  "curated_at": "2026-08-25",
  "entries": [
    {
      "rank": 1,
      "display": "India",
      "canonical": "india",
      "aliases": ["bharat", "republic of india"],
      "disambiguator": null
    },
    {
      "rank": 2,
      "display": "China",
      "canonical": "china",
      "aliases": ["prc", "peoples republic of china"],
      "disambiguator": null
    }
  ]
}
```

`disambiguator` is used when two entries could share a guess — e.g. on a songs list, two entries titled "Hello" would carry disambiguators `"Adele"` and `"Lionel Richie"`. The UI uses this when asking a player to be more specific.

Every list must carry a real `source` and `source_url`. If a list can't be sourced, it doesn't ship.

### Eval file — `data/eval/match_eval.jsonl`

One JSON object per line:

```json
{"id": "e001", "list_id": "songs_2026", "guess": "blinding lite", "expected": "match", "expected_entry": "blinding_lights", "bucket": "clean_positive", "note": "typo"}
{"id": "e002", "list_id": "songs_2026", "guess": "hotel california", "expected": "reject", "expected_entry": null, "bucket": "hard_negative", "note": "real song, not on this list"}
{"id": "e003", "list_id": "songs_2026", "guess": "hello", "expected": "clarify", "expected_entry": null, "bucket": "ambiguous", "note": "two Hellos on list"}
{"id": "e004", "list_id": "songs_2026", "guess": "asdkjhasd", "expected": "reject", "expected_entry": null, "bucket": "adversarial", "note": "gibberish"}
```

`expected` is one of `match` | `reject` | `clarify`.

---

## 3. The matching pipeline

Five stages. Each stage either resolves or passes down. Every stage must return a structured result recording which stage decided, the score, and the latency — this trace is surfaced in the UI and is what makes the project look like engineering rather than a chatbot.

### Result contract

```python
@dataclass
class MatchResult:
    outcome: Literal["match", "reject", "clarify"]
    entry_id: str | None
    rank: int | None
    resolved_by: Literal["cache", "lexical", "embedding", "llm", "reject_floor"]
    score: float
    runner_up_score: float | None
    candidates: list[str]          # for clarify
    latency_ms: float
    cost_usd: float                # 0.0 unless llm
```

### Stage 0 — Normalize (~0 ms)

Applied to both guesses and list entries at index time.

- Lowercase; strip diacritics (NFKD); strip punctuation; collapse whitespace
- Strip parenthetical/bracketed suffixes from list entries: `(Remastered 2011)`, `(feat. X)`, `(Deluxe Edition)`, `[Official Video]`
- Drop leading articles: `the`, `a`, `an`
- Strip player filler: `the song`, `that movie`, `i think its`, `is it`, `maybe`

Keep both the normalized form and the original `display` form. Never show normalized text to players.

### Stage 1 — Exact / alias cache (~1 ms)

Dict: normalized string → entry ID. Populated with:

1. Every entry's normalized `display`
2. Every entry's `canonical` and hand-written `aliases`
3. **Every previously adjudicated guess** — accepted *and* rejected

Point 3 is the important one. Every LLM adjudication is written back here, so the system gets faster and cheaper the more the game is played. Persist this to SQLite so it survives restarts. Report cache hit rate over time in the README — it should climb visibly.

Hit → resolve immediately with `resolved_by="cache"`.

### Stage 2 — Lexical fuzzy (~5 ms)

`rapidfuzz.fuzz.token_set_ratio` against all normalized entries in the active list. Catches typos and word-order variation: `"blinding lite"`, `"weeknd blinding lights"`.

- `score >= LEX_ACCEPT (92)` **and** `score - runner_up >= LEX_GAP (8)` → **accept**
- `score < LEX_FLOOR (55)` → skip to Stage 3
- otherwise → Stage 3

The gap condition is not optional. High score with a close runner-up means ambiguity, not confidence.

### Stage 3 — Embedding similarity (~10 ms)

Embed all entries once at list load; cache the vectors to disk. Embed the guess, cosine against all.

Catches semantic hits that lexical misses: `"the weeknd's big 2020 song"`, `"the one about not being able to sleep"`.

- `cos >= EMB_ACCEPT (0.88)` **and** `cos - runner_up >= EMB_GAP (0.06)` → **accept**
- `cos < EMB_FLOOR (0.55)` → **reject**, `resolved_by="reject_floor"`
- otherwise → Stage 4

### Stage 4 — LLM adjudicator (~800 ms, target < 3% of guesses)

Only the uncertain band reaches here. Send the guess plus the **top 5 candidates only** — never the full list. Full-list prompts are more expensive and measurably worse.

Response schema:

```json
{ "match": "entry_id_or_null", "confidence": 0.0, "reason": "brief" }
```

Prompt must contain, near-verbatim:

> Only return a match if you are confident the player meant this specific entry. If two or more candidates are plausible, return null. A wrong match is worse than no match.

- `confidence >= LLM_ACCEPT (0.8)` and `match != null` → **accept**
- `match == null` and ≥2 candidates scored closely upstream → **clarify** (UI asks player to be more specific, using `disambiguator`)
- otherwise → **reject**

Write every outcome back to the Stage 1 cache, accepts and rejects alike.

Timeout at 2 s → reject, log it, increment a counter surfaced in eval output. Malformed JSON → one retry, then reject. Never crash a round on an LLM failure.

### The ambiguity trap (read this twice)

Player types `"hello"` on a songs list containing both "Hello — Adele" and "Hello — Lionel Richie". Both score high; the gap is tiny. This **must** escalate, and the LLM **must** return null, and the UI **must** ask the player to be more specific.

Never silently pick one. This is the single most damaging failure mode in the game.

---

## 4. Build order

Strict dependency order. Do not skip ahead — particularly not past Phase 1.

### Phase 1 — Eval set first (do this before writing any matcher code)

Write the 200 labelled pairs by hand, across two or three lists. Bucket distribution:

| Bucket | Count | What goes in it |
|---|---|---|
| `clean_positive` | 80 | typos, abbreviations, partial titles, artist-included forms, casing/punctuation variants |
| `hard_negative` | 60 | genuinely not on the list but lexically or semantically close. **False accepts hide here.** |
| `ambiguous` | 40 | two plausible candidates; correct behavior is `clarify`, not `match` |
| `adversarial` | 20 | gibberish, empty string, emoji, the category name itself, prompt-injection attempts |

This is tedious and it is the highest-leverage work in the project. Tuning against vibes instead of a labelled set is how this project fails.

Also write `eval/run_eval.py` now — it should run against a stub matcher that rejects everything, and print the metrics table. Getting the harness working before the matcher means every subsequent phase is measurable the moment it lands.

### Phase 2 — Lists

Curate **15 lists**, hand-verified, each with a real source URL. Suggested (pick ones with stable, citable data):

most populous countries · highest-grossing films · tallest buildings · most spoken languages · largest countries by area · most-followed Instagram accounts · best-selling video games · longest rivers · most Olympic gold medals by country · highest mountains · most-visited countries by tourists · largest companies by market cap · best-selling books · most populous cities · longest-reigning monarchs

Avoid anything requiring licensed chart data (Billboard, Spotify official charts) unless the source explicitly permits redistribution.

Write hand aliases for the top ~20 entries of each list. That alone will kill a large share of escalations.

### Phase 3 — Stages 0–2, measured

Normalize, cache, lexical. Run the eval set. Record the numbers — this is the baseline every later layer is compared against. Expect roughly: decent on clean positives, poor on ambiguous, some false accepts on hard negatives.

### Phase 4 — Stage 3, measured

Add embeddings. Re-run eval. Record delta.

### Phase 5 — Stage 4, measured

Add the LLM adjudicator. Re-run eval. Record delta, escalation rate, and cost per 1,000 guesses.

### Phase 6 — Threshold sweep

`eval/sweep.py`: grid-sweep the four thresholds (`LEX_ACCEPT`, `LEX_GAP`, `EMB_ACCEPT`, `EMB_GAP`) against the eval set. Plot false-accept rate vs false-reject rate. Pick the knee of the curve, weighting false accepts roughly 3× worse than false rejects.

**This plot is the single most interview-valuable artifact in the repo.** Save it to `docs/threshold_sweep.png` and put it in the README.

### Phase 7 — Game layer

Only now build the actual game:

- Create room → returns a join code
- Players join with a name (no auth, no accounts)
- Host starts a round; a category is drawn; timer runs (90 s default)
- Players submit guesses; each is matched and scored live
- Round ends → reveal: full 100-item list with each player's hits marked
- N rounds (default 5) → final scoreboard

Rules: independent scoring across players; a player cannot score the same entry twice in a round; rejected guesses cost nothing but are logged.

### Phase 8 — Frontend + trace view

Functional, clean, fast. Plus: a **debug/trace panel** (toggleable) showing for each guess which stage resolved it, the scores, the runner-up gap, and the latency.

That panel is what makes a recruiter clicking the link see engineering rather than a form box. Do not skip it.

### Phase 9 — Deploy + README

Public URL. README structure, in this order:

1. One-line description + live link + screenshot/GIF
2. **Results table** (the success-criteria metrics, filled in)
3. **Ablation table** (lexical → +embed → +LLM: accuracy, latency, cost per layer)
4. **Threshold sweep plot** + one paragraph on why the chosen operating point
5. Architecture description of the pipeline
6. What didn't work — be specific and honest; this section is worth more than it looks
7. Setup instructions (last, not first)

---

## 5. Testing

- Unit tests for `normalize.py` — the strip rules are where silent bugs live
- Unit tests per stage with fixed inputs and expected outcomes
- One integration test: full pipeline over 20 eval pairs
- One test that the LLM stage is **not** called for a clean cache hit (guards against the hot path silently becoming expensive)
- Mock the LLM in all tests. Tests must run offline.

---

## 6. Things that will go wrong

**Thresholds tuned against a handful of examples instead of the eval set.** The eval set exists precisely to stop this. Never change a threshold without re-running it.

**Escalation rate creeping above 5%.** Every escalation is ~800 ms and real money. If it climbs, the fix is almost always more aliases or better normalization, not a bigger model.

**The LLM matching too eagerly.** Default LLM behavior is to be helpful and find a match. The prompt must fight this. If false accepts are high, harden the prompt before touching thresholds.

**Building the game before the matcher.** Then there's a pretty UI wrapping a matcher nobody measured, and the project has no story.

**Scope creep into live multiplayer sync.** Async was chosen deliberately. Adding WebSocket lobby sync, reconnection, and state reconciliation is a week of work that adds nothing to the project's actual thesis.

**Cutting the trace panel for time.** It is cheap and it is disproportionately what makes the project read as serious.

If time runs short, cut in this order: number of lists (15 → 8), frontend polish, then round count. **Never** cut the eval set, the sweep, or the trace panel.

---

## 7. Definition of done

- [ ] 200-pair eval set written and committed
- [ ] 15 lists curated with sources
- [ ] Pipeline hits all five success-criteria targets
- [ ] Ablation table produced from real runs
- [ ] Threshold sweep plot committed
- [ ] Game playable end-to-end by 3–5 people
- [ ] Trace panel working
- [ ] Deployed at a public URL
- [ ] README written, metrics-first
- [ ] "What didn't work" section written honestly
