"""Harvest seed URLs by running queries against the site's own search endpoint.

Two layers:
- `parse_search_html(html, page_url, search)` — pure parser (no I/O). Tested
  with fixture HTML.
- `harvest_search_urls(fetcher, search)` — I/O driver. Calls a `Fetcher` for
  each query and feeds the response to the pure parser.
"""
from __future__ import annotations

from urllib.parse import quote_plus, urljoin

from bs4 import BeautifulSoup

from .config import SearchConfig
from .fetcher import Fetcher


def parse_search_html(
    html: str,
    page_url: str,
    search: SearchConfig,
) -> list[str]:
    """Extract result-link hrefs from a search-results page's HTML.

    Pure function — no network, no Playwright. Returns absolute URLs in
    document order, deduped, capped at `search.max_results_per_query`.
    """
    if not html:
        return []
    soup = BeautifulSoup(html, "lxml")
    seen: set[str] = set()
    urls: list[str] = []
    for a in soup.select(search.result_selector):
        href = a.get("href")
        if not href:
            continue
        absolute = urljoin(page_url, href)
        if absolute in seen:
            continue
        seen.add(absolute)
        urls.append(absolute)
        if (
            search.max_results_per_query
            and len(urls) >= search.max_results_per_query
        ):
            break
    return urls


def harvest_search_urls(
    fetcher: Fetcher,
    search: SearchConfig,
) -> list[str]:
    """Run each query through `fetcher`, parse results, return deduped URLs."""
    if not search.url_template or not search.queries:
        return []

    seen: set[str] = set()
    out: list[str] = []
    for query in search.queries:
        target = search.url_template.replace("{query}", quote_plus(query))
        result = fetcher.fetch(target)
        if not result.ok:
            print(
                f"     ! search failed for {query!r}: {result.error or result.status}"
            )
            continue
        per_query_urls = parse_search_html(result.html or "", result.url, search)
        per_query = 0
        for u in per_query_urls:
            if u in seen:
                continue
            seen.add(u)
            out.append(u)
            per_query += 1
        print(f"     query {query!r}: {per_query} result(s)")
    return out
