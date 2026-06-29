"""Keyword scoring for focused crawling.

Two scopes:
- score_html: rank a fetched page (title/h1/h2/body weighted).
- score_url_anchor: rank a candidate link before fetching, from URL+anchor text only.
"""
from __future__ import annotations

import re
from urllib.parse import urlparse

from bs4 import BeautifulSoup

from .config import FocusConfig


_re_cache: dict[str, re.Pattern] = {}


def _kw_re(keyword: str) -> re.Pattern:
    rx = _re_cache.get(keyword)
    if rx is None:
        rx = re.compile(r"\b" + re.escape(keyword) + r"\b", re.IGNORECASE)
        _re_cache[keyword] = rx
    return rx


def score_html(html: str, focus: FocusConfig) -> float:
    if not focus.enabled:
        return 0.0
    soup = BeautifulSoup(html, "lxml")
    title = (soup.title.string or "") if soup.title else ""
    h1 = " ".join(t.get_text(" ", strip=True) for t in soup.find_all("h1"))
    h2 = " ".join(t.get_text(" ", strip=True) for t in soup.find_all(["h2", "h3"]))
    body = soup.body.get_text(" ", strip=True) if soup.body else ""

    w = focus.score_weights
    score = 0.0
    for kw in focus.keywords:
        rx = _kw_re(kw)
        score += len(rx.findall(title or "")) * w.get("title", 5.0)
        score += len(rx.findall(h1)) * w.get("h1", 4.0)
        score += len(rx.findall(h2)) * w.get("h2", 3.0)
        score += len(rx.findall(body)) * w.get("body", 1.0)
    return score


def score_url_anchor(url: str, anchor_text: str, focus: FocusConfig) -> float:
    if not focus.enabled:
        return 0.0
    w = focus.score_weights
    path = urlparse(url).path or ""
    score = 0.0
    for kw in focus.keywords:
        rx = _kw_re(kw)
        score += len(rx.findall(path)) * w.get("url", 2.0)
        score += len(rx.findall(anchor_text or "")) * w.get("anchor", 2.0)
    return score
