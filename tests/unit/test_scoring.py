"""Tests for keyword scoring."""
from __future__ import annotations

from authscrape.config import FocusConfig
from authscrape.scoring import score_html, score_url_anchor


def _focus(keywords=None, **overrides):
    cfg = FocusConfig(keywords=keywords or [])
    for k, v in overrides.items():
        setattr(cfg, k, v)
    return cfg


def test_score_html_zero_when_disabled():
    f = _focus(keywords=[])
    assert score_html("<p>workflow</p>", f) == 0.0


def test_score_html_weights_title_higher_than_body(html_fixture):
    """Page with keyword in title only should score higher than same word
    once in body, given default weights (title=5, body=1)."""
    title_only = "<html><head><title>workflow</title></head><body><p>x</p></body></html>"
    body_only = "<html><head><title>x</title></head><body><p>workflow</p></body></html>"
    f = _focus(keywords=["workflow"])
    s_title = score_html(title_only, f)
    s_body = score_html(body_only, f)
    assert s_title > s_body


def test_score_html_uses_word_boundary():
    """`plan` must not match `planet`."""
    html = "<html><body><p>planet</p></body></html>"
    f = _focus(keywords=["plan"])
    assert score_html(html, f) == 0.0


def test_score_html_case_insensitive():
    html = "<html><body><p>WORKFLOW</p></body></html>"
    f = _focus(keywords=["workflow"])
    assert score_html(html, f) > 0.0


def test_score_html_uses_fixture_keywords_in_title(html_fixture):
    f = _focus(keywords=["workflow"])
    score = score_html(html_fixture("keywords_in_title.html"), f)
    # title has "workflow" (5) + h1 "workflow" (4) = at least 9
    assert score >= 9.0


def test_score_url_anchor_matches_in_path():
    f = _focus(keywords=["workflow"])
    assert score_url_anchor("https://example.com/workflow/intro", "intro", f) > 0


def test_score_url_anchor_zero_when_no_match():
    f = _focus(keywords=["workflow"])
    assert score_url_anchor("https://example.com/other", "click here", f) == 0.0


def test_score_url_anchor_zero_when_disabled():
    f = _focus(keywords=[])
    assert score_url_anchor("https://example.com/workflow", "workflow", f) == 0.0


def test_score_html_handles_missing_title():
    html = "<html><body><p>workflow</p></body></html>"
    f = _focus(keywords=["workflow"])
    # body=1.0
    assert score_html(html, f) == 1.0


def test_score_html_uses_custom_weights():
    html = "<html><head><title>x</title></head><body><p>workflow</p></body></html>"
    f = _focus(keywords=["workflow"])
    f.score_weights = {"title": 5.0, "h1": 4.0, "h2": 3.0, "url": 2.0,
                       "anchor": 2.0, "body": 99.0}
    assert score_html(html, f) == 99.0
