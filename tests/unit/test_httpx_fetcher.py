"""Tests for HttpxFetcher.

Uses respx to stub HTTP responses without hitting the network.
"""
from __future__ import annotations

import pytest

respx = pytest.importorskip("respx", reason="respx not installed; install with .[dev]")

from authscrape.fetcher import FetchResult, HttpxFetcher


@respx.mock
def test_httpx_fetcher_returns_html_on_200():
    respx.get("https://example.com/page").respond(
        status_code=200, text="<html><body>hi</body></html>",
    )
    with HttpxFetcher({"cookies": []}) as f:
        r = f.fetch("https://example.com/page")
    assert r.ok
    assert r.status == 200
    assert "<body>hi</body>" in r.html


@respx.mock
def test_httpx_fetcher_captures_status_code():
    respx.get("https://example.com/forbidden").respond(status_code=403)
    with HttpxFetcher({"cookies": []}) as f:
        r = f.fetch("https://example.com/forbidden")
    assert r.status == 403


@respx.mock
def test_httpx_fetcher_follows_redirects_and_captures_final_url():
    respx.get("https://example.com/old").respond(
        status_code=301, headers={"Location": "https://example.com/new"},
    )
    respx.get("https://example.com/new").respond(status_code=200, text="moved")
    with HttpxFetcher({"cookies": []}) as f:
        r = f.fetch("https://example.com/old")
    assert r.url == "https://example.com/new"
    assert r.status == 200


@respx.mock
def test_httpx_fetcher_returns_error_on_exception():
    respx.get("https://example.com/x").mock(side_effect=Exception("network down"))
    with HttpxFetcher({"cookies": []}) as f:
        r = f.fetch("https://example.com/x")
    assert not r.ok
    assert r.error == "network down"


@respx.mock
def test_httpx_fetcher_translates_storage_state_cookies():
    """Cookies declared in storage_state must be sent on requests to the
    matching domain."""
    received_cookie = []

    def handler(request):
        received_cookie.append(request.headers.get("cookie", ""))
        import httpx
        return httpx.Response(200, text="ok")

    respx.get("https://example.com/p").mock(side_effect=handler)
    with HttpxFetcher({
        "cookies": [
            {"name": "session", "value": "abc123",
             "domain": ".example.com", "path": "/"},
        ],
    }) as f:
        r = f.fetch("https://example.com/p")
    assert r.ok
    assert "session=abc123" in received_cookie[0]


def test_httpx_fetcher_is_a_fetcher_protocol_member():
    """Static type-shape check — HttpxFetcher must implement Fetcher."""
    from authscrape.fetcher import Fetcher

    f: Fetcher = HttpxFetcher({"cookies": []})
    assert hasattr(f, "fetch")
