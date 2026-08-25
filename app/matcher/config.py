"""All matcher thresholds live here, nowhere else.

eval/sweep.py (Phase 6) mutates these values to grid-search the operating
point. If a threshold is hardcoded anywhere in matcher/*, the sweep is
meaningless — don't do that.
"""

# Stage 2 — lexical (rapidfuzz token_set_ratio, 0-100 scale)
LEX_ACCEPT = 92
LEX_GAP = 8
LEX_FLOOR = 55

# Stage 3 — embedding cosine similarity (0-1 scale)
EMB_ACCEPT = 0.88
EMB_GAP = 0.06
EMB_FLOOR = 0.55

# Stage 4 — LLM adjudicator confidence (0-1 scale)
LLM_ACCEPT = 0.8

# Stage 4 — timeout before a guess is rejected and logged
LLM_TIMEOUT_SECONDS = 2.0
