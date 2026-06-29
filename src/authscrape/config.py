"""Profile loading and validation."""
from __future__ import annotations

import difflib
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Any

import yaml


class ProfileError(ValueError):
    """Profile validation failure with a user-readable message."""


def _build(cls, raw: dict | None, *, where: str):
    """Construct a config dataclass from a raw YAML dict, rejecting unknown
    keys with a helpful 'did you mean' suggestion.

    Without this, `CrawlConfig(**raw["crawl"])` raises a raw TypeError
    stack trace on any typo — every first-time user trips on it.
    """
    if not raw:
        return cls()
    if not isinstance(raw, dict):
        raise ProfileError(
            f"`{where}` must be a mapping (got {type(raw).__name__})"
        )
    known = {f.name for f in fields(cls)}
    unknown = [k for k in raw.keys() if k not in known]
    if unknown:
        bad = unknown[0]
        suggestion = difflib.get_close_matches(bad, known, n=1, cutoff=0.6)
        hint = f"  (did you mean `{suggestion[0]}`?)" if suggestion else ""
        valid = ", ".join(sorted(known))
        raise ProfileError(
            f"unknown key `{bad}` in `{where}`{hint}\n"
            f"  valid keys: {valid}"
        )
    return cls(**raw)


DEFAULT_CONTENT_SELECTORS = [
    "main",
    "article",
    "[role='main']",
    ".content-body",
    ".main-content",
    "#content",
    ".content",
]

DEFAULT_STRIP_TAGS = [
    "script", "style", "nav", "header", "footer", "aside", "noscript",
]


@dataclass
class CrawlConfig:
    allow_hosts: list[str] = field(default_factory=list)
    allow_prefixes: list[str] = field(default_factory=list)
    deny_prefixes: list[str] = field(default_factory=list)
    max_pages: int = 200
    delay_seconds: float = 1.0
    follow_sitemaps: bool = False
    # Allow plaintext http:// targets. Off by default — http to an allowed
    # SSO-cookie host would leak session cookies cleartext to network observers.
    allow_http: bool = False
    # Fetcher engine: "playwright" renders JS via Chromium (default — works for
    # any site); "http" uses an httpx session, ~10x faster but won't work on
    # SPAs that require JS to render content.
    engine: str = "playwright"


# Default URL substrings that mean "we got bounced to a login page."
# Match is on URL after redirects (page.url after goto).
DEFAULT_LOGIN_URL_PATTERNS = [
    "okta.com",
    "oktapreview.com",
    "login.microsoftonline.com",
    "login.live.com",
    "accounts.google.com",
    "/login",
    "/signin",
    "/sign-in",
    "/auth/login",
]


@dataclass
class AuthConfig:
    cookie_domains: list[str] = field(default_factory=list)
    # URL substrings that, if they appear in the post-redirect URL, indicate
    # an auth wall. Override per profile; defaults cover Okta/MS/Google +
    # common login paths.
    login_url_patterns: list[str] = field(
        default_factory=lambda: list(DEFAULT_LOGIN_URL_PATTERNS)
    )
    # After this many consecutive auth-walled pages, abort the crawl with
    # a clear "re-export cookies" message.
    abort_after_consecutive_auth_failures: int = 3


@dataclass
class ExtractConfig:
    content_selectors: list[str] = field(default_factory=lambda: list(DEFAULT_CONTENT_SELECTORS))
    strip_tags: list[str] = field(default_factory=lambda: list(DEFAULT_STRIP_TAGS))
    strip_inline_svg: bool = True
    strip_data_uri_images: bool = True
    min_content_chars: int = 80


@dataclass
class OutputConfig:
    dir: str = "output"
    per_page: bool = True
    combined: str | None = "combined.md"


@dataclass
class SearchConfig:
    """Optional: harvest additional seed URLs from the site's own search."""
    url_template: str = ""        # e.g. "https://docs.example.com/search?q={query}"
    result_selector: str = "a"    # CSS selector for result-link <a> tags
    queries: list[str] = field(default_factory=list)
    max_results_per_query: int = 20


DEFAULT_SCORE_WEIGHTS = {
    "title": 5.0,
    "h1": 4.0,
    "h2": 3.0,
    "url": 2.0,
    "anchor": 2.0,
    "body": 1.0,
}


@dataclass
class FocusConfig:
    """Optional: focused (keyword-driven) crawling."""
    keywords: list[str] = field(default_factory=list)
    min_score: float = 1.0
    # When a page matches, allow this many further levels of crawl from it
    # *regardless* of whether the children themselves match.
    # 0 → strict: only match → match chains are followed.
    # N → relaxed: allow N intermediate hops past a match.
    drilldown_depth: int = 2
    # save policy: matched_only | matched_and_drilldown | all
    save: str = "matched_and_drilldown"
    score_weights: dict = field(default_factory=lambda: dict(DEFAULT_SCORE_WEIGHTS))

    @property
    def enabled(self) -> bool:
        return bool(self.keywords)


@dataclass
class Profile:
    name: str
    description: str = ""
    seeds: list[str] = field(default_factory=list)
    crawl: CrawlConfig = field(default_factory=CrawlConfig)
    auth: AuthConfig = field(default_factory=AuthConfig)
    extract: ExtractConfig = field(default_factory=ExtractConfig)
    output: OutputConfig = field(default_factory=OutputConfig)
    search: SearchConfig = field(default_factory=SearchConfig)
    focus: FocusConfig = field(default_factory=FocusConfig)
    path: Path | None = None


_TOP_LEVEL_KEYS = {
    "name", "description", "seeds",
    "crawl", "auth", "extract", "output", "search", "focus",
}

_VALID_SAVE_MODES = {"matched_only", "matched_and_drilldown", "all"}
_VALID_ENGINES = {"playwright", "http"}


def load_profile(path: Path) -> Profile:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as e:
        raise ProfileError(f"YAML parse error in {path}: {e}") from e
    if not isinstance(raw, dict):
        raise ProfileError(
            f"Profile {path} must be a YAML mapping (got {type(raw).__name__})"
        )

    # Reject unknown top-level keys with a helpful suggestion.
    unknown = [k for k in raw.keys() if k not in _TOP_LEVEL_KEYS]
    if unknown:
        bad = unknown[0]
        suggestion = difflib.get_close_matches(bad, _TOP_LEVEL_KEYS, n=1, cutoff=0.6)
        hint = f"  (did you mean `{suggestion[0]}`?)" if suggestion else ""
        raise ProfileError(
            f"unknown top-level key `{bad}` in {path}{hint}\n"
            f"  valid keys: {', '.join(sorted(_TOP_LEVEL_KEYS))}"
        )

    name = raw.get("name") or path.stem

    crawl: CrawlConfig = _build(CrawlConfig, raw.get("crawl"), where="crawl")
    auth: AuthConfig = _build(AuthConfig, raw.get("auth"), where="auth")
    extract: ExtractConfig = _build(ExtractConfig, raw.get("extract"), where="extract")
    output: OutputConfig = _build(OutputConfig, raw.get("output"), where="output")
    search: SearchConfig = _build(SearchConfig, raw.get("search"), where="search")
    focus: FocusConfig = _build(FocusConfig, raw.get("focus"), where="focus")

    # Coerce numeric types so `min_score: 1` (int) and `min_score: 1.0` (float)
    # behave identically downstream.
    crawl.delay_seconds = float(crawl.delay_seconds)
    extract.min_content_chars = int(extract.min_content_chars)
    crawl.max_pages = int(crawl.max_pages)
    focus.min_score = float(focus.min_score)
    focus.drilldown_depth = int(focus.drilldown_depth)

    # Validate the focus.save enum so a typo doesn't silently fall through to
    # the default branch.
    if focus.save not in _VALID_SAVE_MODES:
        suggestion = difflib.get_close_matches(focus.save, _VALID_SAVE_MODES, n=1, cutoff=0.5)
        hint = f"  (did you mean `{suggestion[0]}`?)" if suggestion else ""
        raise ProfileError(
            f"invalid focus.save value `{focus.save}`{hint}\n"
            f"  valid values: {', '.join(sorted(_VALID_SAVE_MODES))}"
        )

    if crawl.engine not in _VALID_ENGINES:
        suggestion = difflib.get_close_matches(crawl.engine, _VALID_ENGINES, n=1, cutoff=0.5)
        hint = f"  (did you mean `{suggestion[0]}`?)" if suggestion else ""
        raise ProfileError(
            f"invalid crawl.engine value `{crawl.engine}`{hint}\n"
            f"  valid values: {', '.join(sorted(_VALID_ENGINES))}"
        )

    seeds = raw.get("seeds") or []
    if not seeds:
        raise ProfileError(f"Profile {path} has no seeds")
    if not isinstance(seeds, list) or not all(isinstance(s, str) for s in seeds):
        raise ProfileError(f"Profile {path}: seeds must be a list of strings")
    # Reject non-http(s) seeds early.
    bad_seeds = [s for s in seeds if not s.startswith(("http://", "https://"))]
    if bad_seeds:
        raise ProfileError(
            f"Profile {path}: seeds must start with http:// or https://\n"
            f"  bad: {bad_seeds[0]}"
        )

    if not crawl.allow_hosts and not crawl.allow_prefixes:
        # Fall back to seed-derived prefixes so the crawl doesn't trivially exit.
        crawl.allow_prefixes = sorted({s.rsplit("/", 1)[0] + "/" for s in seeds})

    return Profile(
        name=name,
        description=raw.get("description", ""),
        seeds=seeds,
        crawl=crawl,
        auth=auth,
        extract=extract,
        output=output,
        search=search,
        focus=focus,
        path=path,
    )


def find_profile(name_or_path: str, search_dirs: list[Path]) -> Path:
    p = Path(name_or_path)
    if p.exists():
        return p
    for d in search_dirs:
        for ext in (".yaml", ".yml"):
            cand = d / f"{name_or_path}{ext}"
            if cand.exists():
                return cand
    raise FileNotFoundError(
        f"Profile '{name_or_path}' not found. Searched: {search_dirs}"
    )


def list_profiles(search_dirs: list[Path]) -> list[Path]:
    seen: set[str] = set()
    profiles: list[Path] = []
    for d in search_dirs:
        if not d.exists():
            continue
        for p in sorted(d.glob("*.y*ml")):
            if p.name not in seen:
                profiles.append(p)
                seen.add(p.name)
    return profiles
