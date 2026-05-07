"""Tests for canonicalize_material_key — used to deduplicate materials
across CMS soft-delete / restore cycles."""

from src.db.postgres import canonicalize_material_key


def test_basic_lowercase_and_kind_prefix():
    assert canonicalize_material_key("glass", "Бронзовое 6мм") == "glass:бронзовое-6мм"


def test_strips_punctuation_and_collapses_runs():
    assert canonicalize_material_key("frame", "Чёрный  матовый!!") == "frame:чёрный-матовый"


def test_trims_leading_and_trailing_dashes():
    assert canonicalize_material_key("glass", "  --- abc ---  ") == "glass:abc"


def test_kind_is_lowercased():
    assert canonicalize_material_key("FRAME", "Алюминий") == "frame:алюминий"


def test_collision_for_logically_same_name():
    """Master entered the same material with different surface formatting —
    must collapse to the same canonical_key."""
    a = canonicalize_material_key("glass", "Бронзовое 6мм")
    b = canonicalize_material_key("glass", "БРОНЗОВОЕ  6мм!")
    c = canonicalize_material_key("glass", "  бронзовое   6мм   ")
    assert a == b == c


def test_distinct_for_different_kind():
    """Same human name but different kind must NOT collide."""
    g = canonicalize_material_key("glass", "Бронза")
    f = canonicalize_material_key("frame", "Бронза")
    assert g != f


def test_handles_empty_name_safely():
    """Don't crash if master submitted whitespace — they'll see a 422 from the API
    layer, but the helper itself should still produce a key."""
    assert canonicalize_material_key("glass", "   ") == "glass:noname"
