"""Playwright crawler driven by a Profile.

Modes:
- Default BFS: follow every link within allow_hosts/allow_prefixes.
- Search-driven seeds: if profile.search has a url_template + queries, run
  those searches first and add their result URLs as additional seeds.
- Focused crawl: if profile.focus has keywords, score each fetched page; only
  follow children if the page itself matched (min_score) OR there is remaining
  drilldown budget. drilldown_depth=0 enforces strict matched→matched chains;
  drilldown_depth=N allows N hops past a match before pruning resumes.
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
import time
from collections import deque
from pathlib import Path
from urllib.parse import urldefrag, urljoin, urlparse

from bs4 import BeautifulSoup

from .config import Profile
from .cookies import load_storage_state
from .extractor import extract_main_html, html_to_markdown
from .fetcher import Fetcher, HttpxFetcher, PlaywrightFetcher
from .scoring import score_html, score_url_anchor
from .search import harvest_search_urls
from .state import State, make_item


_SECRET_PATTERNS = [
    re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._~+/=-]{12,}"),
    re.compile(r"(?i)\b(api[_-]?key|token|secret|password)\s*[:=]\s*([^\s`'\"<>]{6,})"),
    re.compile(
        r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----",
        re.DOTALL,
    ),
]


def redact_common_secrets(text: str) -> str:
    """Redact common secret shapes from generated markdown output."""
    redacted = text
    redacted = _SECRET_PATTERNS[0].sub(r"\1[REDACTED]", redacted)
    redacted = _SECRET_PATTERNS[1].sub(r"\1=[REDACTED]", redacted)
    redacted = _SECRET_PATTERNS[2].sub("[REDACTED PRIVATE KEY]", redacted)
    return redacted


def _slugify(url: str) -> str:
    """URL → filename-safe slug with a stable hash suffix.

    The hash suffix prevents collisions: different URLs whose paths
    collapse to the same characters (e.g. `?pageId=1` vs `?pageId=2`,
    or `/Foo` vs `/foo` after lowercasing) would otherwise overwrite
    each other's saved markdown.
    """
    parsed = urlparse(url)
    path = parsed.path.strip("/").replace("/", "_") or "index"
    path = re.sub(r"[^a-zA-Z0-9_\-.]", "_", path)
    if path.endswith(".html"):
        path = path[:-5]
    base = (path[:180] or "index").lower()
    digest = hashlib.sha1(url.encode("utf-8")).hexdigest()[:8]
    return f"{base}-{digest}"


def _is_allowed(url: str, profile: Profile) -> bool:
    parsed = urlparse(url)
    scheme = (parsed.scheme or "").lower()

    # Default-secure: https only. Profiles can opt-in to plaintext via
    # `crawl.allow_http: true`. Cleartext is dangerous because http to an
    # allowed host where SSO cookies are valid will leak them on the wire.
    if scheme == "http":
        if not profile.crawl.allow_http:
            return False
    elif scheme != "https":
        return False  # explicitly reject javascript:, data:, file:, etc.

    if any(url.startswith(p) for p in profile.crawl.deny_prefixes):
        return False
    host = (parsed.hostname or "").lower()
    if host in (h.lower() for h in profile.crawl.allow_hosts):
        return True
    if any(url.startswith(p) for p in profile.crawl.allow_prefixes):
        return True
    return False


def _looks_like_login(url: str, original_url: str, patterns: list[str]) -> bool:
    """True if the post-redirect `url` matches any login/auth-wall pattern,
    OR the host changed away from the original requested host (which usually
    means an SSO redirect)."""
    if any(p in url for p in patterns):
        return True
    orig_host = (urlparse(original_url).hostname or "").lower()
    cur_host = (urlparse(url).hostname or "").lower()
    if orig_host and cur_host and orig_host != cur_host:
        # Host changed during navigation — almost always an SSO bounce.
        # Still allow same-org subdomain hops (docs.x.com → support.x.com)
        # by checking that the registrable suffix differs.
        # Cheap heuristic: last two labels.
        def _suffix(h):
            parts = h.split(".")
            return ".".join(parts[-2:]) if len(parts) >= 2 else h
        if _suffix(orig_host) != _suffix(cur_host):
            return True
    return False


def _should_save(matched: bool, came_from_match: bool, save_mode: str) -> bool:
    if save_mode == "all":
        return True
    if save_mode == "matched_only":
        return matched
    # matched_and_drilldown (default)
    return matched or came_from_match


def crawl(
    profile: Profile,
    cookies_path: Path,
    *,
    out_dir: Path,
    state_path: Path,
    resume: bool = False,
    headed: bool = False,
    no_crawl: bool = False,
    max_pages: int | None = None,
    redact_secrets: bool = False,
    fetcher: Fetcher | None = None,
) -> int:
    """Run a profile-driven crawl.

    Public entry point. By default builds a `PlaywrightFetcher` from the
    cookie file; tests can pass a `fetcher` explicitly (typically a
    `FakeFetcher`) to skip Playwright entirely.
    """
    if fetcher is not None:
        return _run_bfs(
            profile,
            fetcher,
            out_dir=out_dir,
            state_path=state_path,
            resume=resume,
            no_crawl=no_crawl,
            max_pages=max_pages,
            cookies_path=cookies_path,
            redact_secrets=redact_secrets,
        )

    storage = load_storage_state(cookies_path)
    if profile.crawl.engine == "http":
        with HttpxFetcher(storage) as fetcher:
            return _run_bfs(
                profile, fetcher,
                out_dir=out_dir, state_path=state_path,
                resume=resume, no_crawl=no_crawl, max_pages=max_pages,
                cookies_path=cookies_path,
                redact_secrets=redact_secrets,
            )
    # default: playwright
    with PlaywrightFetcher(
        storage,
        headless=not headed,
        content_selectors=profile.extract.content_selectors,
    ) as pw_fetcher:
        return _run_bfs(
            profile,
            pw_fetcher,
            out_dir=out_dir,
            state_path=state_path,
            resume=resume,
            no_crawl=no_crawl,
            max_pages=max_pages,
            cookies_path=cookies_path,
            redact_secrets=redact_secrets,
        )


def _run_bfs(
    profile: Profile,
    fetcher: Fetcher,
    *,
    out_dir: Path,
    state_path: Path,
    resume: bool,
    no_crawl: bool,
    max_pages: int | None,
    cookies_path: Path,
    redact_secrets: bool = False,
) -> int:
    """Pure crawl loop driven by a `Fetcher`. No Playwright dependency.

    Separated from `crawl()` so tests can inject a `FakeFetcher` and exercise
    the BFS / focus / save / link-discovery logic without launching Chromium.
    """
    md_dir = out_dir / "md"
    md_dir.mkdir(parents=True, exist_ok=True)

    state = State.load_or_new(state_path) if resume else State(state_path)
    if not resume:
        state.queue = [
            make_item(s, budget=profile.focus.drilldown_depth, matched=True)
            for s in profile.seeds
        ]
        state.visited = set()
        state.failed = set()
    else:
        # On resume, retry every URL we previously failed (auth wall, transient
        # network, sub-threshold body) — re-exporting cookies and re-running
        # is the documented recovery path, and these URLs deserve a second look.
        if state.failed:
            print(f"Resume: re-queueing {len(state.failed)} previously failed URL(s).")
            for u in sorted(state.failed):
                state.queue.append(
                    make_item(u, budget=profile.focus.drilldown_depth, matched=True)
                )
            state.failed = set()
        if not state.queue:
            print(
                "Resume: queue is empty and no failed URLs to retry — prior "
                "crawl finished cleanly. Drop --resume for a fresh crawl.",
                file=sys.stderr,
            )
            return 0

    cap = max_pages if max_pages is not None else profile.crawl.max_pages
    index_entries: list[tuple[str, str, str]] = []

    print(f"Profile:        {profile.name}")
    print(f"Seeds:          {len(profile.seeds)}")
    print(f"Allow hosts:    {profile.crawl.allow_hosts or '(none)'}")
    print(f"Allow prefixes: {profile.crawl.allow_prefixes or '(none)'}")
    if profile.focus.enabled:
        print(f"Focus keywords: {profile.focus.keywords}")
        print(f"  min_score:    {profile.focus.min_score}")
        print(f"  drilldown:    {profile.focus.drilldown_depth} (0 = strict matched→matched)")
        print(f"  save mode:    {profile.focus.save}")
    if profile.search.url_template and profile.search.queries:
        print(f"Search queries: {profile.search.queries}")
    print(f"Cookies:        {cookies_path}")
    print(f"Output:         {out_dir}")
    print(f"State:          {state_path}")
    print(f"Cap:            {cap} pages")

    # Phase 1: search-driven seed harvest
    if (not resume) and profile.search.url_template and profile.search.queries:
        print("\n--- Search seed harvest ---")
        extra = harvest_search_urls(fetcher, profile.search)
        for u in extra:
            if _is_allowed(u, profile):
                state.queue.append(
                    make_item(u, budget=profile.focus.drilldown_depth, matched=True)
                )
        print(f"Search added {len(extra)} URL(s) to queue.\n")

    # Phase 2: crawl
    queue: deque = deque(state.queue)

    # In-flight set prevents re-popping a URL within the same run before
    # it has been resolved into visited or failed.
    in_flight: set[str] = set()
    # Track consecutive auth-walled pages so we can abort instead of
    # grinding through hundreds of empty/login pages while the user
    # has stepped away.
    consecutive_auth_failures = 0
    auth_abort_threshold = max(
        1, profile.auth.abort_after_consecutive_auth_failures
    )

    def _record_failure(u: str, reason: str) -> None:
        print(f"     ! {reason}", file=sys.stderr)
        state.failed.add(u)
        state.queue = list(queue)
        state.save()

    try:
        while queue and len(state.visited) < cap:
            item = queue.popleft()
            url = urldefrag(item["url"])[0]
            if url in state.visited or url in in_flight:
                continue
            in_flight.add(url)

            budget_in = item["budget"]
            came_from_match = item["matched"]
            tag = ""
            if profile.focus.enabled:
                tag = f"  budget={budget_in} from_match={'Y' if came_from_match else 'N'}"
            print(f"[{len(state.visited)+1:>3}] {url}{tag}")

            result = fetcher.fetch(url)
            if not result.ok:
                _record_failure(url, f"fetch failed: {result.error or result.status}")
                continue

            html = result.html
            final_url = result.url
            status = result.status

            # Check HTTP status — 401/403 are unambiguous auth failures.
            if status in (401, 403):
                consecutive_auth_failures += 1
                _record_failure(url, f"HTTP {status} — auth required")
                if consecutive_auth_failures >= auth_abort_threshold:
                    print(
                        f"\nABORTING: {consecutive_auth_failures} consecutive auth "
                        f"failures (HTTP {status}). Re-export cookies and resume:\n"
                        f"  auth-scrape cookies {profile.name}\n"
                        f"  auth-scrape run {profile.name} --resume",
                        file=sys.stderr,
                    )
                    break
                continue

            # Detect login redirects: post-fetch URL matches a login pattern,
            # or host changed to a different registrable domain.
            if _looks_like_login(final_url, url, profile.auth.login_url_patterns):
                consecutive_auth_failures += 1
                _record_failure(
                    url,
                    f"redirected to login: {final_url} — auth wall detected",
                )
                if consecutive_auth_failures >= auth_abort_threshold:
                    print(
                        f"\nABORTING: {consecutive_auth_failures} consecutive login "
                        f"redirects. Re-export cookies and resume:\n"
                        f"  auth-scrape cookies {profile.name}\n"
                        f"  auth-scrape run {profile.name} --resume",
                        file=sys.stderr,
                    )
                    break
                continue

            title, main_html = extract_main_html(html, profile.extract)
            markdown = html_to_markdown(main_html)
            if len(markdown) < profile.extract.min_content_chars:
                _record_failure(
                    url,
                    f"sub-threshold content ({len(markdown)} chars) — "
                    "may be auth wall or genuinely empty; will retry on --resume",
                )
                continue

            consecutive_auth_failures = 0

            page_score = score_html(html, profile.focus) if profile.focus.enabled else 0.0
            matched = (not profile.focus.enabled) or page_score >= profile.focus.min_score
            save = (not profile.focus.enabled) or _should_save(
                matched, came_from_match, profile.focus.save
            )

            if profile.focus.enabled:
                print(f"     score={page_score:.1f} matched={'Y' if matched else 'N'} save={'Y' if save else 'N'}")

            if save:
                slug = _slugify(url)
                md_path = md_dir / f"{slug}.md"
                if not md_path.resolve().is_relative_to(md_dir.resolve()):
                    print(f"     ! refused unsafe slug path: {md_path}", file=sys.stderr)
                    state.failed.add(url)
                    state.queue = list(queue)
                    state.save()
                    continue
                stamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
                front = (
                    "---\n"
                    f"title: {json.dumps(title)}\n"
                    f"source: {json.dumps(url)}\n"
                    f"scraped_at: {stamp}\n"
                )
                if profile.focus.enabled:
                    front += f"score: {page_score:.2f}\nmatched: {matched}\n"
                front += "---\n\n" + f"# {title}\n\n"
                content = front + markdown + "\n"
                if redact_secrets:
                    content = redact_common_secrets(content)
                md_path.write_text(content, encoding="utf-8")
                index_entries.append(
                    (title or slug, url, md_path.relative_to(out_dir).as_posix())
                )

            state.visited.add(url)

            if not no_crawl:
                if matched:
                    child_budget = profile.focus.drilldown_depth
                elif budget_in > 0:
                    child_budget = budget_in - 1
                else:
                    child_budget = -1

                if child_budget < 0 and profile.focus.enabled:
                    print("     pruning children (no budget, no match)")
                else:
                    soup = BeautifulSoup(html, "lxml")
                    seen_here, queued_here = 0, 0
                    for a in soup.find_all("a", href=True):
                        href = urljoin(url, a["href"])
                        href = urldefrag(href)[0]
                        if not href.startswith(("http://", "https://")):
                            continue
                        seen_here += 1
                        if href in state.visited:
                            continue
                        if not _is_allowed(href, profile):
                            continue
                        link_score = (
                            score_url_anchor(href, a.get_text(" ", strip=True), profile.focus)
                            if profile.focus.enabled else 0.0
                        )
                        promising = link_score > 0
                        pass_budget = (
                            profile.focus.drilldown_depth if promising else child_budget
                        )
                        if pass_budget < 0:
                            continue
                        queue.append(make_item(href, budget=pass_budget, matched=matched))
                        queued_here += 1
                    print(f"     links: {seen_here} seen, {queued_here} queued")

            state.queue = list(queue)
            state.save()
            time.sleep(profile.crawl.delay_seconds)
    finally:
        state.queue = list(queue)
        state.save()

    _write_index(out_dir, index_entries)
    print(f"\nDone. {len(index_entries)} pages saved to {out_dir}/")
    return len(index_entries)


def _write_index(out_dir: Path, entries: list[tuple[str, str, str]]) -> None:
    index_path = out_dir / "INDEX.md"
    lines = ["# Scraped pages", ""]
    for title, url, rel in sorted(entries):
        lines.append(f"- [{title or url}]({rel}) — <{url}>")
    index_path.write_text("\n".join(lines) + "\n")


def combine(out_dir: Path, combined_name: str = "combined.md") -> Path:
    md_dir = out_dir / "md"
    if not md_dir.exists():
        raise FileNotFoundError(f"No scraped pages found at {md_dir}")
    combined = out_dir / combined_name
    parts = []
    for p in sorted(md_dir.glob("*.md")):
        parts.append(p.read_text())
        parts.append("\n\n---\n\n")
    combined.write_text("".join(parts))
    return combined


def search_only(profile: Profile, cookies_path: Path, headed: bool = False) -> list[str]:
    """Run only the search-harvest phase; return discovered URLs without crawling."""
    storage = load_storage_state(cookies_path)
    with PlaywrightFetcher(
        storage,
        headless=not headed,
        content_selectors=profile.extract.content_selectors,
        nav_timeout_ms=30000,
    ) as fetcher:
        return harvest_search_urls(fetcher, profile.search)
