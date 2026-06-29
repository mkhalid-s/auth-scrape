"""Tests for cookie loading + host export.

Locks in the P0-1 fix: exported cookies.json gets mode 0600 and the file
isn't world-readable at any point. Also covers Cookie-Editor / Playwright
storage_state polymorphism.
"""
from __future__ import annotations

import json
import os
import stat
import sys
from pathlib import Path

import pytest

from authscrape.cookies import export_from_browser, load_storage_state


# ---------- load_storage_state ----------

def test_load_playwright_storage_state(cookie_fixture):
    data = load_storage_state(cookie_fixture("playwright_storage.json"))
    assert "cookies" in data
    assert data["cookies"][0]["name"] == "session"


def test_load_cookie_editor_array(cookie_fixture):
    """Cookie-Editor exports as a JSON array; should be normalized to
    Playwright storage_state shape."""
    data = load_storage_state(cookie_fixture("cookie_editor.json"))
    assert "cookies" in data
    assert "origins" in data
    cookies = data["cookies"]
    session = next(c for c in cookies if c["name"] == "session")
    assert session["sameSite"] == "Lax"  # "lax" → "Lax"
    assert "expires" in session
    tracking = next(c for c in cookies if c["name"] == "tracking")
    assert tracking["sameSite"] == "None"  # "no_restriction" → "None"


def test_load_unrecognized_format_raises(tmp_path: Path):
    p = tmp_path / "weird.json"
    p.write_text(json.dumps(42), encoding="utf-8")
    with pytest.raises(ValueError):
        load_storage_state(p)


def test_load_malformed_json_raises(cookie_fixture):
    with pytest.raises(json.JSONDecodeError):
        load_storage_state(cookie_fixture("malformed.json"))


# ---------- export_from_browser file-mode (P0-1) ----------

class _FakeCookie:
    def __init__(self, name, value, domain, path="/", expires=None,
                 secure=False):
        self.name = name
        self.value = value
        self.domain = domain
        self.path = path
        self.expires = expires
        self.secure = secure


def _patch_browser_cookie3(monkeypatch, jar):
    """Stub `browser_cookie3.load()` to return our fake jar."""
    import types
    mod = types.SimpleNamespace(load=lambda: jar)
    monkeypatch.setitem(sys.modules, "browser_cookie3", mod)


@pytest.mark.skipif(os.name == "nt", reason="POSIX file modes only")
def test_exported_cookie_file_has_mode_0600(monkeypatch, tmp_path: Path):
    """The single highest-impact P0-1 fix — verify the file mode."""
    jar = [_FakeCookie("session", "abc", "example.com", expires=None, secure=True)]
    _patch_browser_cookie3(monkeypatch, jar)

    out = tmp_path / "cookies.json"
    n = export_from_browser(domains=["example.com"], out_path=out)

    assert n == 1
    mode = stat.S_IMODE(out.stat().st_mode)
    assert mode == 0o600, f"expected 0600, got {oct(mode)}"


def test_export_filters_by_domain(monkeypatch, tmp_path: Path):
    jar = [
        _FakeCookie("a", "v", "example.com"),
        _FakeCookie("b", "v", "other.com"),
    ]
    _patch_browser_cookie3(monkeypatch, jar)
    out = tmp_path / "cookies.json"
    n = export_from_browser(domains=["example.com"], out_path=out)
    assert n == 1
    data = json.loads(out.read_text(encoding="utf-8"))
    assert {c["name"] for c in data["cookies"]} == {"a"}


def test_export_raises_when_no_cookies_match(monkeypatch, tmp_path: Path):
    jar = [_FakeCookie("a", "v", "other.com")]
    _patch_browser_cookie3(monkeypatch, jar)
    with pytest.raises(RuntimeError):
        export_from_browser(domains=["example.com"], out_path=tmp_path / "c.json")


def test_export_warns_when_writing_inside_git_tree(monkeypatch, tmp_path: Path, capsys):
    """cookies.json inside a git working tree is a credential-leak risk
    — warn loudly to stderr."""
    git_root = tmp_path / "repo"
    git_root.mkdir()
    (git_root / ".git").mkdir()
    out = git_root / "subdir" / "cookies.json"
    out.parent.mkdir()

    jar = [_FakeCookie("a", "v", "example.com")]
    _patch_browser_cookie3(monkeypatch, jar)

    export_from_browser(domains=["example.com"], out_path=out)
    err = capsys.readouterr().err
    assert "WARNING" in err
    assert "git" in err.lower()
