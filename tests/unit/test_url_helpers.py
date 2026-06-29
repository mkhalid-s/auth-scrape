"""Tests for URL-handling helpers in crawler.py.

Covers the P0-2 (slug collision) and P0-8 (HTTPS-only) fixes.
"""
from __future__ import annotations

import pytest

from authscrape.config import Profile, CrawlConfig
from authscrape.crawler import _slugify, _is_allowed, _looks_like_login


# ---------- _slugify ----------

def test_slugify_includes_url_hash_suffix():
    """Slug must include a stable hash so different URLs never collide."""
    slug = _slugify("https://example.com/foo/bar")
    assert slug.endswith("-" + slug.rsplit("-", 1)[1])
    assert len(slug.rsplit("-", 1)[1]) == 8


def test_slugify_distinguishes_urls_that_share_a_path():
    """Different URLs that previously collided (different host, query, or
    fragment) now produce distinct slugs because of the hash suffix."""
    a = _slugify("https://a.example.com/foo")
    b = _slugify("https://b.example.com/foo")
    c = _slugify("https://x.example.com/docs/api?v=1")
    d = _slugify("https://x.example.com/docs/api?v=2")
    e = _slugify("https://x.example.com/Foo")
    f = _slugify("https://x.example.com/foo")
    assert a != b, "different hosts must produce different slugs"
    assert c != d, "different query strings must produce different slugs"
    assert e != f, "different case must produce different slugs"


def test_slugify_returns_index_for_root_url():
    slug = _slugify("https://example.com/")
    assert slug.startswith("index-")


def test_slugify_strips_html_extension():
    slug = _slugify("https://example.com/path/page.html")
    assert "page.html" not in slug
    assert "page-" in slug or "_page-" in slug or slug.startswith("path_page-")


def test_slugify_replaces_unsafe_chars():
    """Characters outside [a-zA-Z0-9_\\-.] become underscores."""
    slug = _slugify("https://example.com/path with spaces/and?query")
    base = slug.rsplit("-", 1)[0]
    assert " " not in base
    assert "?" not in base


def test_slugify_truncates_base_to_180_chars():
    long_path = "a" * 500
    slug = _slugify(f"https://example.com/{long_path}")
    base = slug.rsplit("-", 1)[0]
    # 180-char cap on the base, then -<8-char-hash>
    assert len(base) <= 180


def test_slugify_lowercases_base():
    slug = _slugify("https://example.com/UPPER")
    base = slug.rsplit("-", 1)[0]
    assert base == base.lower()


# ---------- _is_allowed ----------

def _profile_with(crawl: CrawlConfig) -> Profile:
    return Profile(name="t", seeds=["https://example.com/"], crawl=crawl)


def test_is_allowed_rejects_http_by_default():
    p = _profile_with(CrawlConfig(allow_hosts=["example.com"]))
    assert _is_allowed("http://example.com/page", p) is False


def test_is_allowed_accepts_http_when_allow_http_is_true():
    p = _profile_with(CrawlConfig(allow_hosts=["example.com"], allow_http=True))
    assert _is_allowed("http://example.com/page", p) is True


def test_is_allowed_accepts_https_to_allowed_host():
    p = _profile_with(CrawlConfig(allow_hosts=["example.com"]))
    assert _is_allowed("https://example.com/page", p) is True


def test_is_allowed_rejects_javascript_scheme():
    p = _profile_with(CrawlConfig(allow_hosts=["example.com"]))
    assert _is_allowed("javascript:alert(1)", p) is False


def test_is_allowed_rejects_data_scheme():
    p = _profile_with(CrawlConfig(allow_hosts=["example.com"]))
    assert _is_allowed("data:text/html,<h1>x</h1>", p) is False


def test_is_allowed_rejects_file_scheme():
    p = _profile_with(CrawlConfig(allow_hosts=["example.com"]))
    assert _is_allowed("file:///etc/passwd", p) is False


def test_is_allowed_host_match_is_case_insensitive():
    p = _profile_with(CrawlConfig(allow_hosts=["Docs.Example.COM"]))
    assert _is_allowed("https://docs.example.com/page", p) is True


def test_is_allowed_uses_prefix_when_no_host_match():
    p = _profile_with(CrawlConfig(allow_prefixes=["https://docs.example.com/cloud/"]))
    assert _is_allowed("https://docs.example.com/cloud/foo", p) is True
    assert _is_allowed("https://docs.example.com/other/foo", p) is False


def test_is_allowed_rejects_when_no_rules_match():
    p = _profile_with(CrawlConfig(allow_hosts=["a.com"]))
    assert _is_allowed("https://b.com/", p) is False


def test_is_allowed_deny_prefix_overrides_allow():
    p = _profile_with(CrawlConfig(
        allow_hosts=["example.com"],
        deny_prefixes=["https://example.com/login"],
    ))
    assert _is_allowed("https://example.com/login/form", p) is False
    assert _is_allowed("https://example.com/page", p) is True


# ---------- _looks_like_login ----------

PATTERNS = ["okta.com", "/login", "/signin"]


def test_looks_like_login_matches_pattern():
    assert _looks_like_login(
        "https://example.okta.com/auth", "https://docs.example.com/", PATTERNS
    ) is True


def test_looks_like_login_matches_login_path():
    assert _looks_like_login(
        "https://docs.example.com/login?next=/x",
        "https://docs.example.com/x",
        PATTERNS,
    ) is True


def test_looks_like_login_detects_cross_domain_redirect():
    """SSO bounce: docs.example.com → example.okta.com is detected even
    if we missed an okta.com substring (registrable-domain heuristic)."""
    assert _looks_like_login(
        "https://random-sso.com/auth",
        "https://docs.example.com/",
        [],
    ) is True


def test_looks_like_login_allows_same_org_subdomain_hops():
    """Within same registrable domain (last 2 labels), don't flag as login."""
    assert _looks_like_login(
        "https://support.example.com/article",
        "https://docs.example.com/",
        [],
    ) is False


def test_looks_like_login_returns_false_for_normal_navigation():
    assert _looks_like_login(
        "https://docs.example.com/page2",
        "https://docs.example.com/page1",
        PATTERNS,
    ) is False
