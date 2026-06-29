"""Tests for the Fetcher abstraction and the BFS-with-FakeFetcher integration.

This is the payoff for extracting the Fetcher: we can drive the full crawl
loop end-to-end without launching Chromium.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from authscrape.config import (
    AuthConfig,
    CrawlConfig,
    ExtractConfig,
    FocusConfig,
    OutputConfig,
    Profile,
    SearchConfig,
)
from authscrape.crawler import _run_bfs, redact_common_secrets
from authscrape.fetcher import FetchResult


# ---------- FakeFetcher ----------

class FakeFetcher:
    """In-memory fetcher returning canned results.

    Use:
        FakeFetcher({
            "https://x/a": "<main>...</main>",          # 200 ok
            "https://x/b": ("<html>", 200, "https://x/c"),  # redirect to /c
            "https://x/c": ("", 403, None),                 # auth wall
            "https://x/d": (None, None, None, "boom"),      # exception
        })
    """

    def __init__(self, pages: dict):
        self._pages = pages
        self.calls: list[str] = []

    def fetch(self, url: str) -> FetchResult:
        self.calls.append(url)
        v = self._pages.get(url)
        if v is None:
            return FetchResult(url=url, html=None, status=404, error="not in fake fetcher")
        if isinstance(v, str):
            return FetchResult(url=url, html=v, status=200)
        # Tuple form: (html, status, final_url[, error])
        if len(v) == 3:
            html, status, final = v
            return FetchResult(url=final or url, html=html, status=status)
        if len(v) == 4:
            html, status, final, err = v
            return FetchResult(url=final or url, html=html, status=status, error=err)
        raise AssertionError(f"bad fake fetcher value: {v!r}")


# ---------- helpers ----------

def _profile(seeds, **overrides):
    crawl = CrawlConfig(
        allow_hosts=overrides.pop("allow_hosts", ["x.test"]),
        max_pages=overrides.pop("max_pages", 50),
        delay_seconds=0.0,  # don't sleep in tests
    )
    focus = overrides.pop("focus", FocusConfig())
    auth = overrides.pop("auth", AuthConfig())
    extract = overrides.pop(
        "extract",
        ExtractConfig(min_content_chars=overrides.pop("min_content_chars", 5)),
    )
    return Profile(
        name=overrides.pop("name", "test"),
        seeds=seeds,
        crawl=crawl,
        auth=auth,
        extract=extract,
        output=OutputConfig(),
        search=overrides.pop("search", SearchConfig()),
        focus=focus,
    )


def _page(title, body, links=()):
    link_html = "".join(f'<a href="{u}">{t}</a>' for u, t in links)
    return f"""<!doctype html>
<html><head><title>{title}</title></head>
<body><main>
<h1>{title}</h1>
<p>{body}</p>
{link_html}
</main></body></html>"""


# ---------- core BFS via FakeFetcher ----------

def test_run_bfs_visits_seed_and_saves_markdown(tmp_path: Path):
    fetcher = FakeFetcher({
        "https://x.test/a": _page("Alpha", "Body content goes here, plenty of it."),
    })
    profile = _profile(["https://x.test/a"])

    n = _run_bfs(
        profile, fetcher,
        out_dir=tmp_path / "out",
        state_path=tmp_path / "state.json",
        resume=False, no_crawl=False, max_pages=None,
        cookies_path=tmp_path / "cookies.json",
    )

    assert n == 1
    assert fetcher.calls == ["https://x.test/a"]
    md_files = list((tmp_path / "out" / "md").glob("*.md"))
    assert len(md_files) == 1
    content = md_files[0].read_text()
    assert "# Alpha" in content
    assert "source:" in content


def test_run_bfs_follows_links(tmp_path: Path):
    fetcher = FakeFetcher({
        "https://x.test/a": _page(
            "Alpha", "Body content for alpha. Long enough.",
            links=[("/b", "B"), ("/c", "C")],
        ),
        "https://x.test/b": _page("Beta", "Body content for beta. Long enough."),
        "https://x.test/c": _page("Gamma", "Body content for gamma. Long enough."),
    })
    profile = _profile(["https://x.test/a"])
    _run_bfs(
        profile, fetcher,
        out_dir=tmp_path / "out",
        state_path=tmp_path / "state.json",
        resume=False, no_crawl=False, max_pages=None,
        cookies_path=tmp_path / "cookies.json",
    )
    assert set(fetcher.calls) == {
        "https://x.test/a", "https://x.test/b", "https://x.test/c",
    }


def test_run_bfs_respects_no_crawl(tmp_path: Path):
    fetcher = FakeFetcher({
        "https://x.test/a": _page(
            "Alpha", "Plenty of body content here.",
            links=[("/b", "B"), ("/c", "C")],
        ),
    })
    profile = _profile(["https://x.test/a"])
    _run_bfs(
        profile, fetcher,
        out_dir=tmp_path / "out",
        state_path=tmp_path / "state.json",
        resume=False, no_crawl=True, max_pages=None,
        cookies_path=tmp_path / "cookies.json",
    )
    assert fetcher.calls == ["https://x.test/a"]


def test_run_bfs_respects_max_pages_cap(tmp_path: Path):
    fetcher = FakeFetcher({
        f"https://x.test/p{i}": _page(
            f"P{i}", "Plenty of body content here.",
            links=[(f"/p{i+1}", f"P{i+1}")],
        )
        for i in range(10)
    })
    profile = _profile(["https://x.test/p0"], max_pages=3)
    n = _run_bfs(
        profile, fetcher,
        out_dir=tmp_path / "out",
        state_path=tmp_path / "state.json",
        resume=False, no_crawl=False, max_pages=3,
        cookies_path=tmp_path / "cookies.json",
    )
    assert n == 3


def test_run_bfs_filters_disallowed_hosts(tmp_path: Path):
    fetcher = FakeFetcher({
        "https://x.test/a": _page(
            "Alpha", "Plenty of body content.",
            links=[("/b", "B"), ("https://other.test/c", "C")],
        ),
        "https://x.test/b": _page("Beta", "Plenty of body content."),
    })
    profile = _profile(["https://x.test/a"])
    _run_bfs(
        profile, fetcher,
        out_dir=tmp_path / "out",
        state_path=tmp_path / "state.json",
        resume=False, no_crawl=False, max_pages=None,
        cookies_path=tmp_path / "cookies.json",
    )
    assert "https://other.test/c" not in fetcher.calls
    assert "https://x.test/b" in fetcher.calls


# ---------- auth-failure handling ----------

def test_run_bfs_aborts_after_consecutive_auth_failures(tmp_path: Path):
    fetcher = FakeFetcher({
        "https://x.test/a": ("", 403, None),
        "https://x.test/b": ("", 403, None),
        "https://x.test/c": ("", 403, None),
        "https://x.test/d": ("", 403, None),
    })
    profile = _profile(
        ["https://x.test/a", "https://x.test/b", "https://x.test/c", "https://x.test/d"],
        auth=AuthConfig(abort_after_consecutive_auth_failures=2),
    )
    n = _run_bfs(
        profile, fetcher,
        out_dir=tmp_path / "out",
        state_path=tmp_path / "state.json",
        resume=False, no_crawl=False, max_pages=None,
        cookies_path=tmp_path / "cookies.json",
    )
    assert n == 0
    # After 2 consecutive 403s the loop aborts; not all 4 are fetched.
    assert len(fetcher.calls) <= 3


def test_run_bfs_login_redirect_records_failure(tmp_path: Path):
    fetcher = FakeFetcher({
        "https://x.test/a": ("<html>", 200, "https://x.test/login?next=/a"),
    })
    profile = _profile(["https://x.test/a"])
    n = _run_bfs(
        profile, fetcher,
        out_dir=tmp_path / "out",
        state_path=tmp_path / "state.json",
        resume=False, no_crawl=False, max_pages=None,
        cookies_path=tmp_path / "cookies.json",
    )
    assert n == 0
    # The original URL (not the redirected one) is recorded as failed
    # so --resume retries it after cookie refresh.
    import json
    state = json.loads((tmp_path / "state.json").read_text())
    assert "https://x.test/a" in state["failed"]


def test_run_bfs_visited_failed_separation_after_failure(tmp_path: Path):
    """A URL that fetches but produces no usable content goes to `failed`,
    not `visited`, so --resume can retry it."""
    fetcher = FakeFetcher({
        "https://x.test/a": _page("A", "tiny"),  # below min_content_chars
    })
    profile = _profile(
        ["https://x.test/a"],
        extract=ExtractConfig(min_content_chars=500),
    )
    _run_bfs(
        profile, fetcher,
        out_dir=tmp_path / "out",
        state_path=tmp_path / "state.json",
        resume=False, no_crawl=False, max_pages=None,
        cookies_path=tmp_path / "cookies.json",
    )
    import json
    state = json.loads((tmp_path / "state.json").read_text())
    assert "https://x.test/a" in state["failed"]
    assert "https://x.test/a" not in state["visited"]


def test_run_bfs_resume_retries_failed(tmp_path: Path):
    """First run: page returns 403 → marked failed. Second run with --resume
    after a cookie refresh: page now returns content → must be retried, not
    skipped via visited."""
    profile = _profile(["https://x.test/a"])
    state_path = tmp_path / "state.json"

    # First run — 403.
    f1 = FakeFetcher({"https://x.test/a": ("", 403, None)})
    _run_bfs(
        profile, f1,
        out_dir=tmp_path / "out", state_path=state_path,
        resume=False, no_crawl=False, max_pages=None,
        cookies_path=tmp_path / "cookies.json",
    )

    # Second run — now succeeds with --resume.
    f2 = FakeFetcher({
        "https://x.test/a": _page("Alpha", "Plenty of content this time."),
    })
    n = _run_bfs(
        profile, f2,
        out_dir=tmp_path / "out", state_path=state_path,
        resume=True, no_crawl=False, max_pages=None,
        cookies_path=tmp_path / "cookies.json",
    )
    assert n == 1
    assert "https://x.test/a" in f2.calls


# ---------- focus mode ----------

def test_run_bfs_focus_mode_only_saves_matched(tmp_path: Path):
    fetcher = FakeFetcher({
        "https://x.test/a": _page(
            "Widget Guide", "All about the widget. Body has widget twice. widget.",
            links=[("/b", "Boring")],
        ),
        "https://x.test/b": _page(
            "Boring", "Talks about something else entirely, with no keyword.",
        ),
    })
    profile = _profile(
        ["https://x.test/a"],
        focus=FocusConfig(
            keywords=["widget"],
            min_score=1.0,
            drilldown_depth=0,  # strict matched→matched
            save="matched_only",
        ),
    )
    _run_bfs(
        profile, fetcher,
        out_dir=tmp_path / "out", state_path=tmp_path / "state.json",
        resume=False, no_crawl=False, max_pages=None,
        cookies_path=tmp_path / "cookies.json",
    )
    md_files = list((tmp_path / "out" / "md").glob("*.md"))
    assert len(md_files) == 1
    assert "widget" in md_files[0].read_text().lower()


def test_redact_common_secrets_masks_known_shapes():
    text = (
        "Authorization: Bearer abcdefghijklmnopqrstuvwxyz\n"
        "api_key = sk_test_abcdefghijklmnopqrstuvwxyz\n"
        "-----BEGIN PRIVATE KEY-----\nabc123\n-----END PRIVATE KEY-----"
    )

    redacted = redact_common_secrets(text)

    assert "abcdefghijklmnopqrstuvwxyz" not in redacted
    assert "sk_test" not in redacted
    assert "abc123" not in redacted
    assert "[REDACTED]" in redacted


def test_run_bfs_redacts_saved_markdown_when_enabled(tmp_path: Path):
    secret = "tokentestabcdefghijklmnopqrstuvwxyz"
    fetcher = FakeFetcher({
        "https://x.test/a": _page(
            "Secrets",
            f"Configuration includes token = {secret} for testing only.",
        ),
    })
    profile = _profile(["https://x.test/a"])

    _run_bfs(
        profile, fetcher,
        out_dir=tmp_path / "out",
        state_path=tmp_path / "state.json",
        resume=False, no_crawl=False, max_pages=None,
        cookies_path=tmp_path / "cookies.json",
        redact_secrets=True,
    )

    md_files = list((tmp_path / "out" / "md").glob("*.md"))
    assert len(md_files) == 1
    content = md_files[0].read_text()
    assert secret not in content
    assert "token=[REDACTED]" in content
