"""HTML → main content → markdown."""
from __future__ import annotations

from bs4 import BeautifulSoup
from markdownify import markdownify as _md

from .config import ExtractConfig


def extract_main_html(html: str, cfg: ExtractConfig) -> tuple[str, str]:
    soup = BeautifulSoup(html, "lxml")
    title = ""
    if soup.title and soup.title.string:
        title = soup.title.string.strip()

    chosen = None
    for sel in cfg.content_selectors:
        node = soup.select_one(sel)
        if node and node.get_text(strip=True):
            chosen = node
            break
    if chosen is None:
        chosen = soup.body or soup

    for tag in chosen(cfg.strip_tags):
        tag.decompose()

    if cfg.strip_data_uri_images:
        for img in chosen.find_all("img"):
            if (img.get("src") or "").startswith("data:"):
                img.decompose()

    if cfg.strip_inline_svg:
        for svg in chosen.find_all("svg"):
            svg.decompose()

    return title, str(chosen)


def html_to_markdown(html: str) -> str:
    return _md(
        html,
        heading_style="ATX",
        bullets="-",
        code_language="",
        strip=["meta", "link"],
    ).strip()
