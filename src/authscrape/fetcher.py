"""Fetcher abstraction — separates "how do we render a URL into HTML" from
the BFS / scoring / save logic in `crawler.py`.

Two implementations:

- `PlaywrightFetcher` — the production fetcher. Boots a Chromium browser
  with the user's cookies injected as Playwright `storage_state`, navigates,
  waits for content selectors + networkidle, and returns the rendered HTML.

- `FakeFetcher` (in tests) — returns canned HTML for given URLs without a
  browser. Used to exercise the BFS / focus / save / link-discovery logic
  without launching Chromium.

The `Fetcher` protocol is the single seam: the crawl loop only knows how to
call `fetcher.fetch(url) -> FetchResult`. Adding an httpx-based fetcher for
static sites later is a new class, not a fork of the crawler.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


@dataclass
class FetchResult:
    """Outcome of one URL fetch.

    Attributes:
        url:    Final URL after redirects (may differ from requested).
        html:   Rendered HTML content. None if the fetch errored.
        status: HTTP status code if available. None for non-HTTP fetchers.
        error:  Stringified exception if the fetch failed; otherwise None.
    """
    url: str
    html: str | None
    status: int | None
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None and self.html is not None


class Fetcher(Protocol):
    """Protocol every fetcher implementation conforms to."""

    def fetch(self, url: str) -> FetchResult: ...


# -- PlaywrightFetcher -------------------------------------------------------

DEFAULT_CONTENT_SELECTORS = [
    "main",
    "article",
    "[role='main']",
    ".content-body",
    ".main-content",
    "#content",
    ".content",
]


class PlaywrightFetcher:
    """Production fetcher backed by Playwright + Chromium.

    Use as a context manager so the browser/playwright lifecycle is
    deterministic — no leaked Chromium subprocesses on exception:

        with PlaywrightFetcher(storage_state) as fetcher:
            r = fetcher.fetch("https://example.com")
    """

    def __init__(
        self,
        storage_state: dict[str, Any],
        *,
        headless: bool = True,
        content_selectors: list[str] | None = None,
        nav_timeout_ms: int = 45000,
        selector_timeout_ms: int = 4000,
        networkidle_timeout_ms: int = 10000,
    ) -> None:
        self._storage = storage_state
        self._headless = headless
        self._content_selectors = content_selectors or DEFAULT_CONTENT_SELECTORS
        self._nav_timeout = nav_timeout_ms
        self._selector_timeout = selector_timeout_ms
        self._networkidle_timeout = networkidle_timeout_ms

        self._pw_cm = None
        self._pw = None
        self._browser = None
        self._context = None
        self._page = None

    def __enter__(self) -> "PlaywrightFetcher":
        # Imported here so importing the package doesn't pull Playwright in
        # for callers that only need the protocol or FakeFetcher.
        from playwright.sync_api import sync_playwright

        self._pw_cm = sync_playwright()
        self._pw = self._pw_cm.__enter__()
        self._browser = self._pw.chromium.launch(headless=self._headless)
        self._context = self._browser.new_context(storage_state=self._storage)
        self._page = self._context.new_page()
        self._page.set_default_timeout(self._nav_timeout)
        return self

    def __exit__(self, exc_type, exc_val, tb) -> bool:
        # Close in reverse order; never let an inner failure mask an outer one.
        try:
            if self._browser is not None:
                self._browser.close()
        except Exception:
            pass
        try:
            if self._pw_cm is not None:
                self._pw_cm.__exit__(exc_type, exc_val, tb)
        except Exception:
            pass
        return False  # don't swallow the exception

    def fetch(self, url: str) -> FetchResult:
        page = self._page
        if page is None:
            return FetchResult(
                url=url, html=None, status=None,
                error="PlaywrightFetcher.fetch called before __enter__",
            )
        try:
            response = page.goto(url, wait_until="domcontentloaded")
            for sel in self._content_selectors:
                try:
                    page.wait_for_selector(
                        sel, timeout=self._selector_timeout, state="visible"
                    )
                    break
                except Exception:
                    continue
            try:
                page.wait_for_load_state(
                    "networkidle", timeout=self._networkidle_timeout
                )
            except Exception:
                pass
            html = page.content()
        except Exception as e:
            return FetchResult(url=url, html=None, status=None, error=str(e))
        status = response.status if response is not None else None
        return FetchResult(url=page.url, html=html, status=status, error=None)


# -- HttpxFetcher ------------------------------------------------------------

DEFAULT_USER_AGENT = (
    "auth-scrape/0.1 (+https://github.com/mkhalid-s/auth-scrape)"
)


class HttpxFetcher:
    """Lightweight fetcher for static / server-rendered docs.

    Order of magnitude faster than Playwright for sites that don't need
    JS — most documentation portals (Hugo, MkDocs, Sphinx, Confluence
    Server, etc.) fall in this bucket. Cookies from a Playwright
    `storage_state` are translated to httpx cookies one-for-one.

    Use as a context manager so the underlying connection pool is closed:

        with HttpxFetcher(storage_state) as fetcher:
            r = fetcher.fetch("https://example.com")
    """

    def __init__(
        self,
        storage_state: dict[str, Any],
        *,
        follow_redirects: bool = True,
        timeout_s: float = 30.0,
        user_agent: str | None = None,
        verify: bool = True,
    ) -> None:
        self._storage = storage_state
        self._follow_redirects = follow_redirects
        self._timeout_s = timeout_s
        self._user_agent = user_agent or DEFAULT_USER_AGENT
        self._verify = verify
        self._client = None

    def _build_client(self):
        # Imported lazily so consumers who only use PlaywrightFetcher don't
        # pay the httpx import cost.
        import httpx

        cookies = httpx.Cookies()
        for c in self._storage.get("cookies", []):
            domain = (c.get("domain") or "").lstrip(".")
            try:
                cookies.set(
                    name=c["name"],
                    value=c["value"],
                    domain=domain,
                    path=c.get("path", "/"),
                )
            except Exception:
                # Skip individual bad cookies rather than fail the whole jar.
                continue

        return httpx.Client(
            cookies=cookies,
            follow_redirects=self._follow_redirects,
            timeout=self._timeout_s,
            verify=self._verify,
            headers={
                "User-Agent": self._user_agent,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9",
            },
        )

    def __enter__(self) -> "HttpxFetcher":
        self._client = self._build_client()
        return self

    def __exit__(self, exc_type, exc_val, tb) -> bool:
        if self._client is not None:
            try:
                self._client.close()
            except Exception:
                pass
        return False

    def fetch(self, url: str) -> FetchResult:
        if self._client is None:
            # Allow non-context-manager use too — build the client lazily.
            self._client = self._build_client()
        try:
            r = self._client.get(url)
        except Exception as e:
            return FetchResult(url=url, html=None, status=None, error=str(e))
        # str(r.url) gives the post-redirect final URL
        return FetchResult(
            url=str(r.url),
            html=r.text,
            status=r.status_code,
            error=None,
        )
