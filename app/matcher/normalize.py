"""Stage 0 — normalize (~0 ms).

Applied to both guesses and list entries at index time. Two entry points:
`normalize_entry` for list data (strips bracketed suffixes like "(Remastered
2011)"), `normalize_guess` for player input (strips conversational filler
like "i think its"). Both then share the same core folding: lowercase,
strip diacritics, strip punctuation, collapse whitespace, drop a leading
article.

Never show normalized text to players — keep the original `display` form
for anything user-facing.
"""
from __future__ import annotations

import re
import unicodedata

_BRACKETED_RE = re.compile(r"[\(\[][^\)\]]*[\)\]]")
_PUNCT_RE = re.compile(r"[^\w\s]", re.UNICODE)
_WHITESPACE_RE = re.compile(r"\s+")
_LEADING_ARTICLE_RE = re.compile(r"^(the|a|an)\s+")

# Longest phrases first so a substring like "the" inside "i think its" isn't
# partially consumed by a shorter, unrelated rule.
_FILLER_PHRASES = sorted(
    [
        "i think its",
        "i think it's",
        "i think it is",
        "the song",
        "the movie",
        "that song",
        "that movie",
        "is it",
        "maybe",
    ],
    key=len,
    reverse=True,
)


def strip_diacritics(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


def strip_bracketed(text: str) -> str:
    return _BRACKETED_RE.sub(" ", text)


def strip_filler(text: str) -> str:
    result = text
    for phrase in _FILLER_PHRASES:
        result = re.sub(rf"\b{re.escape(phrase)}\b", " ", result, flags=re.IGNORECASE)
    return result


def _fold(text: str) -> str:
    text = text.lower()
    text = strip_diacritics(text)
    text = _PUNCT_RE.sub(" ", text)
    text = _WHITESPACE_RE.sub(" ", text).strip()
    text = _LEADING_ARTICLE_RE.sub("", text)
    return text


def normalize_entry(text: str) -> str:
    """Normalize a list entry's display/canonical/alias string."""
    text = strip_bracketed(text)
    return _fold(text)


def normalize_guess(text: str) -> str:
    """Normalize a raw player guess."""
    text = strip_filler(text)
    text = strip_bracketed(text)
    return _fold(text)
