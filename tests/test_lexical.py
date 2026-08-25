from app.matcher import config
from app.matcher.cache import Entry, ListData
from app.matcher.lexical import match
from app.matcher.normalize import normalize_entry


def _entry(id_, display, aliases=None):
    aliases = aliases or []
    forms = {normalize_entry(display)}
    forms.update(normalize_entry(a) for a in aliases)
    return Entry(
        id=id_,
        rank=1,
        display=display,
        canonical=display.lower(),
        aliases=aliases,
        disambiguator=None,
        normalized_forms=sorted(forms),
    )


def _list(entries):
    ld = ListData(id="t", title="t", entries=entries)
    ld.entries_by_id = {e.id: e for e in entries}
    return ld


def test_accepts_close_typo_with_clear_gap():
    ld = _list([_entry("usa", "United States of America"), _entry("uk", "United Kingdom")])
    result = match("united state of america", ld)
    assert result.decision == "accept"
    assert result.entry_id == "usa"


def test_rejects_below_floor():
    ld = _list([_entry("india", "India")])
    result = match("zzz qqq xyz", ld)
    assert result.decision == "continue"
    assert result.score < config.LEX_FLOOR


def test_identical_tie_does_not_accept():
    # The "Hello" ambiguity trap: two entries score identically, so the gap
    # condition must refuse to silently pick one.
    ld = _list([_entry("hello_a", "Hello"), _entry("hello_b", "Hello")])
    result = match("hello", ld)
    assert result.decision == "continue"
    assert result.score == result.runner_up_score


def test_empty_guess_does_not_accept():
    ld = _list([_entry("india", "India")])
    result = match("", ld)
    assert result.decision == "continue"


def test_empty_list_does_not_accept():
    result = match("india", _list([]))
    assert result.decision == "continue"
    assert result.entry_id is None
