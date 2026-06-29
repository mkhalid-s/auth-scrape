"""Environment diagnostics — `auth-scrape doctor`.

Catches the three most common first-run failures before the user spends
20 minutes debugging:

1. Playwright / Chromium not installed
2. Running inside a container with no access to host browser keystore
   (so `auth-scrape cookies` will silently produce an empty jar)
3. cookies.json missing, malformed, or fully expired
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import time
from dataclasses import dataclass
from importlib.metadata import PackageNotFoundError, version as _pkg_version
from pathlib import Path


OK = "[ OK ]"
WARN = "[WARN]"
FAIL = "[FAIL]"


@dataclass
class Check:
    status: str  # OK / WARN / FAIL
    label: str
    detail: str = ""

    def render(self) -> str:
        head = f"  {self.status} {self.label}"
        if not self.detail:
            return head
        # Indent detail lines under the check.
        lines = self.detail.rstrip().split("\n")
        return head + "\n" + "\n".join(f"        {l}" for l in lines)


def _check_python() -> Check:
    v = sys.version_info
    if v >= (3, 10):
        return Check(OK, f"Python {v.major}.{v.minor}.{v.micro}")
    return Check(
        FAIL, f"Python {v.major}.{v.minor}.{v.micro}",
        "auth-scrape requires Python >= 3.10",
    )


def _check_self() -> Check:
    try:
        v = _pkg_version("auth-scrape")
        return Check(OK, f"auth-scrape {v}")
    except PackageNotFoundError:
        return Check(WARN, "auth-scrape (not pip-installed)",
                     "Running from source tree. `pip install -e .` for dev.")


def _check_playwright() -> Check:
    try:
        import playwright  # noqa: F401
    except ImportError:
        return Check(FAIL, "playwright importable",
                     "Install: pip install 'playwright>=1.40'")
    try:
        from playwright import _impl  # type: ignore
        # Best-effort version probe.
        v = _pkg_version("playwright")
        return Check(OK, f"playwright {v} importable")
    except Exception:
        return Check(OK, "playwright importable")


def _check_chromium() -> Check:
    """Heuristic: Playwright caches browsers under PLAYWRIGHT_BROWSERS_PATH
    or in a platform-default cache directory. We just check whether the
    `playwright` CLI can find Chromium."""
    cli = shutil.which("playwright")
    if cli is None:
        return Check(WARN, "Chromium present (could not check)",
                     "Run: playwright install chromium")
    # We don't shell out to the real CLI here (slow, side-effecty).
    # Instead, look in common cache locations.
    candidates = [
        os.environ.get("PLAYWRIGHT_BROWSERS_PATH"),
        Path.home() / ".cache" / "ms-playwright",                  # Linux
        Path.home() / "Library" / "Caches" / "ms-playwright",      # macOS
        Path(os.environ.get("LOCALAPPDATA", "")) / "ms-playwright",  # Windows
    ]
    for c in candidates:
        if not c:
            continue
        p = Path(c) if not isinstance(c, Path) else c
        if p.exists() and any(p.glob("chromium-*")):
            return Check(OK, f"Chromium present at {p}")
    return Check(WARN, "Chromium binary not located",
                 "Run: playwright install chromium")


def _check_browser_cookie3() -> Check:
    try:
        import browser_cookie3  # noqa: F401
        try:
            v = _pkg_version("browser-cookie3")
            return Check(OK, f"browser-cookie3 {v} importable")
        except PackageNotFoundError:
            return Check(OK, "browser-cookie3 importable")
    except ImportError:
        return Check(WARN, "browser-cookie3 not installed",
                     "Optional. Install for `auth-scrape cookies`:\n"
                     "  pip install 'auth-scrape[host-cookies]'")


def _check_container() -> Check:
    """Devcontainer / Docker: the `cookies` subcommand can't reach the host
    browser keystore, so this is a hard limitation worth surfacing."""
    if Path("/.dockerenv").exists():
        return Check(
            WARN, "Running inside a container",
            "/.dockerenv detected. `auth-scrape cookies` cannot reach the\n"
            "host browser keystore — run cookies on your host machine and\n"
            "copy cookies.json into the container.",
        )
    if os.environ.get("REMOTE_CONTAINERS") or os.environ.get("CODESPACES"):
        return Check(
            WARN, "Running in a remote/devcontainer environment",
            "Run `auth-scrape cookies` on your host, copy the result in.",
        )
    return Check(OK, "Native environment (not a container)")


def _check_cookies_file(path: Path) -> Check:
    if not path.exists():
        return Check(
            WARN, f"cookies.json not found at {path}",
            "Run: auth-scrape cookies <profile>",
        )
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        return Check(FAIL, f"cookies.json malformed at {path}", str(e))

    cookies = data.get("cookies", []) if isinstance(data, dict) else (
        data if isinstance(data, list) else []
    )
    if not cookies:
        return Check(WARN, f"cookies.json present but empty at {path}",
                     "Re-export with: auth-scrape cookies <profile>")

    now = time.time()
    expired = [c for c in cookies if "expires" in c and c["expires"] < now]
    if len(expired) == len(cookies):
        return Check(FAIL,
                     f"cookies.json: all {len(cookies)} cookies are expired",
                     "Re-export with: auth-scrape cookies <profile>")
    earliest = min(
        (c["expires"] for c in cookies if "expires" in c and c["expires"] >= now),
        default=None,
    )
    detail = f"{len(cookies)} cookies"
    if earliest:
        ts = time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime(earliest))
        detail += f", earliest non-expired expiry at {ts}"
    if expired:
        detail += f"\n{len(expired)} of those are already expired"
    return Check(OK, f"cookies.json valid at {path}", detail)


def _check_profiles(search_dirs) -> Check:
    """Reused from cli; lazy-import to avoid circular import in __init__."""
    from .config import list_profiles
    profiles = list_profiles(search_dirs)
    if not profiles:
        return Check(WARN, "0 profiles found",
                     "Create one: auth-scrape init <name> --site <url>")
    detail = "\n".join(f"- {p.stem}  ({p})" for p in profiles)
    return Check(OK, f"{len(profiles)} profile(s) found", detail)


def run_doctor(cookies_path: Path, profile_search_dirs, *, strict: bool = False) -> int:
    """Run all checks and print a report. Returns exit code:
    0 = all OK, 1 = warnings only, 2 = at least one FAIL.

    In strict mode, warnings also return 2 so CI/preflight checks can fail
    closed when the environment is incomplete.
    """
    checks = [
        _check_python(),
        _check_self(),
        _check_playwright(),
        _check_chromium(),
        _check_browser_cookie3(),
        _check_container(),
        _check_cookies_file(cookies_path),
        _check_profiles(profile_search_dirs),
    ]
    print("Checking auth-scrape environment...\n")
    for c in checks:
        print(c.render())
    print()

    fails = sum(1 for c in checks if c.status == FAIL)
    warns = sum(1 for c in checks if c.status == WARN)
    if fails:
        print(f"{fails} failure(s), {warns} warning(s). Fix the failures and re-run.")
        return 2
    if warns:
        if strict:
            print(f"Strict mode: {warns} warning(s) treated as failure.")
            return 2
        print(f"All required checks passed. {warns} warning(s) — review above.")
        return 1
    print("All systems go.")
    return 0
