"""Tests for HTML → main content → markdown extraction."""
from __future__ import annotations

from authscrape.config import ExtractConfig
from authscrape.extractor import extract_main_html, html_to_markdown


def test_extract_main_uses_main_tag(html_fixture):
    title, html = extract_main_html(html_fixture("simple_main.html"), ExtractConfig())
    assert title == "Simple Page"
    assert "Heading One" in html
    # Nav and footer are stripped.
    assert "Top nav links" not in html
    assert "Footer content" not in html


def test_extract_main_falls_back_when_no_selector_matches(html_fixture):
    """No <main>, no <body> wrapper either — should fall back to soup root."""
    cfg = ExtractConfig()
    title, html = extract_main_html(html_fixture("no_main_no_body.html"), cfg)
    # Title may be empty (no <title>); content should still be present.
    assert "Loose paragraph" in html


def test_extract_main_strips_data_uri_images(html_fixture):
    cfg = ExtractConfig(strip_data_uri_images=True)
    _, html = extract_main_html(html_fixture("with_data_uri.html"), cfg)
    assert "data:image" not in html
    # But real images stay.
    assert "real.png" in html


def test_extract_main_preserves_data_uri_when_disabled(html_fixture):
    cfg = ExtractConfig(strip_data_uri_images=False)
    _, html = extract_main_html(html_fixture("with_data_uri.html"), cfg)
    assert "data:image" in html


def test_extract_main_strips_inline_svg(html_fixture):
    cfg = ExtractConfig(strip_inline_svg=True)
    _, html = extract_main_html(html_fixture("with_inline_svg.html"), cfg)
    assert "<svg" not in html
    # Content around the SVG is preserved.
    assert "More content after the svg" in html


def test_extract_main_preserves_svg_when_disabled(html_fixture):
    cfg = ExtractConfig(strip_inline_svg=False)
    _, html = extract_main_html(html_fixture("with_inline_svg.html"), cfg)
    assert "<svg" in html


def test_html_to_markdown_atx_headings():
    md = html_to_markdown("<h1>One</h1><h2>Two</h2>")
    # ATX headings start with #.
    assert md.startswith("# One")


def test_html_to_markdown_strips_meta_and_link():
    md = html_to_markdown('<meta name="x"><link rel="stylesheet"><p>body</p>')
    assert "meta" not in md.lower() or "<meta" not in md
    assert "<link" not in md
    assert "body" in md


def test_html_to_markdown_empty_input():
    assert html_to_markdown("") == ""


def test_extract_main_returns_empty_title_when_no_title_tag():
    title, _ = extract_main_html("<html><body><p>x</p></body></html>", ExtractConfig())
    assert title == ""
