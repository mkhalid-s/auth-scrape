"""Tests for the focused-crawl save policy."""
from __future__ import annotations

from authscrape.crawler import _should_save


def test_should_save_all_mode_always_true():
    assert _should_save(matched=True, came_from_match=True, save_mode="all") is True
    assert _should_save(matched=False, came_from_match=False, save_mode="all") is True


def test_should_save_matched_only_requires_match():
    assert _should_save(matched=True, came_from_match=False, save_mode="matched_only") is True
    assert _should_save(matched=False, came_from_match=True, save_mode="matched_only") is False
    assert _should_save(matched=False, came_from_match=False, save_mode="matched_only") is False


def test_should_save_default_mode_accepts_drilldown():
    """matched_and_drilldown saves matched pages OR pages reached via drilldown."""
    assert _should_save(matched=True, came_from_match=False, save_mode="matched_and_drilldown") is True
    assert _should_save(matched=False, came_from_match=True, save_mode="matched_and_drilldown") is True
    assert _should_save(matched=False, came_from_match=False, save_mode="matched_and_drilldown") is False


def test_should_save_unknown_mode_falls_back_to_default():
    """Unknown modes degrade to matched_and_drilldown semantics. Note:
    config.load_profile validates the enum at load time, so an unknown
    mode reaching here would be a programming error — but the function
    must remain total."""
    assert _should_save(matched=True, came_from_match=False, save_mode="unrecognized") is True
    assert _should_save(matched=False, came_from_match=False, save_mode="unrecognized") is False
