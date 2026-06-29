"""Tests for the pure search-results parser.

This is the testability payoff for splitting `parse_search_html` out of
`harvest_search_urls` — we can test the parser with fixture HTML, no
Playwright needed.
"""
from __future__ import annotations

from authscrape.config import SearchConfig
from authscrape.fetcher import FetchResult
from authscrape.search import harvest_search_urls, parse_search_html


def test_parse_search_html_extracts_result_links():
    html = """
    <div>
      <a class="result" href="/page/1">One</a>
      <a class="result" href="/page/2">Two</a>
      <a href="/nav">nav (not a result)</a>
    </div>
    """
    cfg = SearchConfig(result_selector="a.result")
    urls = parse_search_html(html, "https://example.com/search?q=x", cfg)
    assert urls == [
        "https://example.com/page/1",
        "https://example.com/page/2",
    ]


def test_parse_search_html_resolves_relative_urls_against_page_url():
    html = '<a class="r" href="page/1">One</a>'
    cfg = SearchConfig(result_selector="a.r")
    urls = parse_search_html(html, "https://example.com/section/", cfg)
    assert urls == ["https://example.com/section/page/1"]


def test_parse_search_html_dedupes_within_page():
    html = """
    <a class="r" href="/page/1">A</a>
    <a class="r" href="/page/1">B</a>
    <a class="r" href="/page/2">C</a>
    """
    cfg = SearchConfig(result_selector="a.r")
    urls = parse_search_html(html, "https://x/", cfg)
    assert urls == ["https://x/page/1", "https://x/page/2"]


def test_parse_search_html_respects_max_results_per_query():
    html = "".join(f'<a class="r" href="/p{i}">{i}</a>' for i in range(50))
    cfg = SearchConfig(result_selector="a.r", max_results_per_query=5)
    urls = parse_search_html(html, "https://x/", cfg)
    assert len(urls) == 5


def test_parse_search_html_empty_input():
    cfg = SearchConfig(result_selector="a.r")
    assert parse_search_html("", "https://x/", cfg) == []
    assert parse_search_html("<div>no anchors</div>", "https://x/", cfg) == []


def test_parse_search_html_skips_anchors_without_href():
    html = '<a class="r">no href</a><a class="r" href="/p">link</a>'
    cfg = SearchConfig(result_selector="a.r")
    urls = parse_search_html(html, "https://x/", cfg)
    assert urls == ["https://x/p"]


def test_harvest_search_urls_returns_empty_when_no_template():
    """If the profile doesn't define a search block, harvest is a no-op."""
    cfg = SearchConfig()  # url_template = "" by default
    class _NoFetcher:
        def fetch(self, url):  # pragma: no cover — must not be called
            raise AssertionError("fetcher must not be called when search disabled")
    assert harvest_search_urls(_NoFetcher(), cfg) == []


def test_harvest_search_urls_uses_fetcher_per_query():
    """Driver hits each query URL once via the injected Fetcher and
    accumulates results."""
    cfg = SearchConfig(
        url_template="https://x/search?q={query}",
        result_selector="a.r",
        queries=["alpha", "beta"],
        max_results_per_query=10,
    )

    pages = {
        "https://x/search?q=alpha": '<a class="r" href="/a1">a1</a><a class="r" href="/a2">a2</a>',
        "https://x/search?q=beta": '<a class="r" href="/b1">b1</a>',
    }

    class _F:
        def fetch(self, url):
            return FetchResult(url=url, html=pages[url], status=200)

    urls = harvest_search_urls(_F(), cfg)
    assert urls == ["https://x/a1", "https://x/a2", "https://x/b1"]


def test_harvest_search_urls_handles_failed_fetch():
    """A failed search-page fetch logs and is skipped, not fatal."""
    cfg = SearchConfig(
        url_template="https://x/search?q={query}",
        result_selector="a.r",
        queries=["alpha", "beta"],
    )

    class _F:
        def fetch(self, url):
            if "alpha" in url:
                return FetchResult(url=url, html=None, status=500, error="boom")
            return FetchResult(url=url, html='<a class="r" href="/b">b</a>', status=200)

    urls = harvest_search_urls(_F(), cfg)
    assert urls == ["https://x/b"]


def test_harvest_search_urls_url_encodes_query():
    """Spaces and special chars in queries are quote_plus-encoded."""
    cfg = SearchConfig(
        url_template="https://x/search?q={query}",
        result_selector="a",
        queries=["hello world"],
    )

    seen_url = []

    class _F:
        def fetch(self, url):
            seen_url.append(url)
            return FetchResult(url=url, html="", status=200)

    harvest_search_urls(_F(), cfg)
    assert seen_url == ["https://x/search?q=hello+world"]


def test_harvest_search_urls_dedupes_across_queries():
    """A URL returned by two queries is only emitted once."""
    cfg = SearchConfig(
        url_template="https://x/search?q={query}",
        result_selector="a.r",
        queries=["alpha", "beta"],
    )
    pages = {
        "https://x/search?q=alpha": '<a class="r" href="/shared">x</a>',
        "https://x/search?q=beta": '<a class="r" href="/shared">x</a><a class="r" href="/uniq">u</a>',
    }

    class _F:
        def fetch(self, url):
            return FetchResult(url=url, html=pages[url], status=200)

    urls = harvest_search_urls(_F(), cfg)
    assert urls == ["https://x/shared", "https://x/uniq"]
