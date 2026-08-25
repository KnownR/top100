import json

import pytest

from app import db as db_module
from app.matcher import cache as cache_module
from app.matcher import pipeline as pipeline_module
from eval.run_eval import load_eval_set


@pytest.fixture
def temp_list(tmp_path, monkeypatch):
    lists_dir = tmp_path / "lists"
    lists_dir.mkdir()
    monkeypatch.setattr(cache_module, "DATA_LISTS_DIR", lists_dir)
    monkeypatch.setattr(db_module, "DB_PATH", tmp_path / "test.db")
    cache_module._LIST_CACHE.clear()

    def _write(list_id, entries):
        data = {"id": list_id, "title": list_id, "entries": entries}
        (lists_dir / f"{list_id}.json").write_text(json.dumps(data), encoding="utf-8")

    return _write


def test_cache_hit_never_calls_lexical_stage(temp_list, monkeypatch):
    """Guards against the hot path silently becoming expensive: a guess
    that's already in the Stage 1 cache must resolve without touching
    Stage 2 (and, once built, Stage 3/4) at all."""
    temp_list(
        "test_list",
        [{"rank": 1, "id": "india", "display": "India", "canonical": "india", "aliases": [], "disambiguator": None}],
    )
    cache_module.get_list("test_list")
    cache_module.write_back("test_list", "bharath", "india", "match")

    def _boom(*args, **kwargs):
        raise AssertionError("lexical.match should not be called on a cache hit")

    monkeypatch.setattr(pipeline_module.lexical, "match", _boom)

    result = pipeline_module.match_guess("bharath", "test_list")
    assert result.outcome == "match"
    assert result.entry_id == "india"
    assert result.resolved_by == "cache"


def test_pipeline_runs_over_real_eval_sample():
    """Integration test: the real pipeline over a slice of the real eval
    set, exercising real list data end to end. Doesn't assert on accuracy
    (that's what eval/run_eval.py measures) -- just that every case runs
    without error and returns a well-formed, valid outcome."""
    cases = load_eval_set()[:20]
    for case in cases:
        result = pipeline_module.match_guess(case.guess, case.list_id)
        assert result.outcome in ("match", "reject", "clarify")
        assert result.resolved_by in ("cache", "lexical", "embedding", "llm", "reject_floor")
        assert result.latency_ms >= 0
        if result.outcome == "match":
            assert result.entry_id is not None
            assert result.rank is not None
