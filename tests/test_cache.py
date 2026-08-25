import json

import pytest

from app import db as db_module
from app.matcher import cache as cache_module


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


def test_unique_forms_are_cached(temp_list):
    temp_list(
        "test_list",
        [
            {"rank": 1, "id": "india", "display": "India", "canonical": "india", "aliases": ["bharat"], "disambiguator": None},
            {"rank": 2, "id": "china", "display": "China", "canonical": "china", "aliases": [], "disambiguator": None},
        ],
    )
    cache_module.get_list("test_list")
    assert cache_module.lookup("test_list", "india") == ("india", "match")
    assert cache_module.lookup("test_list", "bharat") == ("india", "match")
    assert cache_module.lookup("test_list", "china") == ("china", "match")


def test_unknown_guess_is_not_a_cache_hit(temp_list):
    temp_list(
        "test_list",
        [{"rank": 1, "id": "india", "display": "India", "canonical": "india", "aliases": [], "disambiguator": None}],
    )
    cache_module.get_list("test_list")
    assert cache_module.lookup("test_list", "brazil") is None


def test_colliding_forms_are_not_auto_resolved(temp_list):
    # Two "Hello" entries sharing an identical normalized form -- the
    # ambiguity trap from WORKPLAN section 3. Neither should silently win.
    temp_list(
        "songs",
        [
            {"rank": 1, "id": "hello_adele", "display": "Hello", "canonical": "hello", "aliases": [], "disambiguator": "Adele"},
            {"rank": 2, "id": "hello_lionel", "display": "Hello", "canonical": "hello", "aliases": [], "disambiguator": "Lionel Richie"},
        ],
    )
    cache_module.get_list("songs")
    assert cache_module.lookup("songs", "hello") is None


def test_write_back_persists_and_is_reused_after_reload(temp_list):
    temp_list(
        "test_list",
        [{"rank": 1, "id": "india", "display": "India", "canonical": "india", "aliases": [], "disambiguator": None}],
    )
    cache_module.get_list("test_list")
    assert cache_module.lookup("test_list", "bharath") is None

    cache_module.write_back("test_list", "bharath", "india", "match")
    assert cache_module.lookup("test_list", "bharath") == ("india", "match")

    # Simulate a process restart: drop the in-memory list cache, reload from
    # the JSON file + SQLite. The adjudication must have survived.
    cache_module._LIST_CACHE.clear()
    assert cache_module.lookup("test_list", "bharath") == ("india", "match")


def test_write_back_persists_rejects_too(temp_list):
    temp_list(
        "test_list",
        [{"rank": 1, "id": "india", "display": "India", "canonical": "india", "aliases": [], "disambiguator": None}],
    )
    cache_module.get_list("test_list")
    cache_module.write_back("test_list", "gibberish", None, "reject")
    assert cache_module.lookup("test_list", "gibberish") == (None, "reject")
