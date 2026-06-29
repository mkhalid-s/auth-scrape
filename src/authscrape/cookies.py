"""Cookie loading and host-side export."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any


def _warn_if_inside_git_tree(path: Path) -> None:
    """Print a warning if `path` is inside a git working tree.

    cookies.json is a bearer credential — accidentally `git add .`-ing it
    is the most common way live SSO tokens leak into a repo's history.
    """
    p = path.resolve().parent
    for ancestor in [p, *p.parents]:
        if (ancestor / ".git").exists():
            print(
                f"WARNING: writing cookies to {path} which is inside a git "
                f"working tree at {ancestor}. cookies.json contains live SSO "
                "credentials — make sure it is gitignored, or move it to "
                "~/.auth-scrape/cookies/.",
                file=sys.stderr,
            )
            return


def load_storage_state(path: Path) -> dict[str, Any]:
    """Accept Playwright storage_state JSON, Cookie-Editor array, or our own export."""
    data = json.loads(path.read_text())

    if isinstance(data, dict) and "cookies" in data:
        return data

    if not isinstance(data, list):
        raise ValueError(f"Unrecognized cookie file format: {path}")

    cookies = []
    for c in data:
        cookie = {
            "name": c["name"],
            "value": c["value"],
            "domain": c.get("domain", ""),
            "path": c.get("path", "/"),
        }
        if "expirationDate" in c:
            cookie["expires"] = float(c["expirationDate"])
        elif isinstance(c.get("expires"), (int, float)):
            cookie["expires"] = float(c["expires"])
        if c.get("secure") is not None:
            cookie["secure"] = bool(c["secure"])
        if c.get("httpOnly") is not None:
            cookie["httpOnly"] = bool(c["httpOnly"])
        ss = c.get("sameSite")
        if isinstance(ss, str):
            low = ss.lower()
            if low == "lax":
                cookie["sameSite"] = "Lax"
            elif low == "strict":
                cookie["sameSite"] = "Strict"
            elif low in ("none", "no_restriction"):
                cookie["sameSite"] = "None"
        cookies.append(cookie)

    return {"cookies": cookies, "origins": []}


def export_from_browser(
    domains: list[str],
    out_path: Path,
    browser: str = "auto",
) -> int:
    """Export cookies from the host browser profile via browser_cookie3."""
    try:
        import browser_cookie3 as bc
    except ImportError as e:
        raise RuntimeError(
            "browser-cookie3 is required for the cookies subcommand. "
            "Install with: pip install 'auth-scrape[host-cookies]' "
            "or: pip install browser-cookie3"
        ) from e

    if browser == "auto":
        jar = bc.load()
    else:
        fn = getattr(bc, browser, None)
        if fn is None:
            raise ValueError(f"Unknown browser: {browser!r}")
        jar = fn()

    cookies = []
    for c in jar:
        if domains and not any(d in (c.domain or "") for d in domains):
            continue
        entry = {
            "name": c.name,
            "value": c.value,
            "domain": c.domain,
            "path": c.path or "/",
        }
        if c.expires:
            entry["expires"] = float(c.expires)
        if c.secure:
            entry["secure"] = True
        cookies.append(entry)

    if not cookies:
        raise RuntimeError(
            f"No matching cookies found. Domains filter: {domains}. "
            "Make sure you're signed in in the chosen browser."
        )

    _warn_if_inside_git_tree(out_path)

    # Write with restrictive perms (0600) — cookies.json is a bearer credential.
    # Use os.open + O_CREAT|O_WRONLY|O_TRUNC with mode so there is no brief
    # world-readable window between create and chmod. On Windows mode bits
    # are largely ignored; ACL hardening is the user's responsibility there.
    payload = json.dumps({"cookies": cookies, "origins": []}, indent=2)
    fd = os.open(out_path, os.O_CREAT | os.O_WRONLY | os.O_TRUNC, 0o600)
    try:
        os.write(fd, payload.encode("utf-8"))
    finally:
        os.close(fd)
    # Ensure mode even if file pre-existed with wider perms.
    try:
        os.chmod(out_path, 0o600)
    except OSError:
        pass
    return len(cookies)
