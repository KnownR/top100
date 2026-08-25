from app.matcher.normalize import normalize_entry, normalize_guess


def test_lowercases():
    assert normalize_guess("INDIA") == "india"


def test_strips_diacritics():
    assert normalize_entry("Beyoncé") == "beyonce"


def test_strips_punctuation():
    assert normalize_guess("u.s.a.") == "u s a"


def test_collapses_whitespace():
    assert normalize_guess("  blinding    lights  ") == "blinding lights"


def test_drops_leading_article_the():
    assert normalize_entry("The Avengers") == "avengers"


def test_drops_leading_article_a():
    assert normalize_entry("A Quiet Place") == "quiet place"


def test_does_not_drop_mid_string_article():
    # Only a LEADING article is dropped, not "the" appearing later.
    assert normalize_entry("Avatar: The Way of Water") == "avatar the way of water"


def test_strips_bracketed_suffix_parens():
    assert normalize_entry("Bohemian Rhapsody (Remastered 2011)") == "bohemian rhapsody"


def test_strips_bracketed_suffix_brackets():
    assert normalize_entry("Some Song [Official Video]") == "some song"


def test_strips_player_filler_i_think_its():
    assert normalize_guess("i think its blinding lights") == "blinding lights"


def test_strips_player_filler_maybe():
    assert normalize_guess("maybe titanic") == "titanic"


def test_strips_player_filler_is_it():
    assert normalize_guess("is it avatar") == "avatar"


def test_never_returns_original_case_for_display():
    # normalize_* must not be confused with the display form -- sanity check
    # that normalization actually changes casing rather than being a no-op.
    assert normalize_guess("INDIA") != "INDIA"
