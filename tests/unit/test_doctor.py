"""Tests for the doctor environment-diagnostics module."""
from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from authscrape.doctor import (
    Check,
    FAIL,
    OK,
    WARN,
    _check_cookies_file,
    _check_python,
    run_doctor,
)


def test_check_python_passes_on_supported_version():
    c = _check_python()
    assert c.status == OK
    assert "Python" in c.label


def test_check_cookies_file_missing(tmp_path: Path):
    c = _check_cookies_file(tmp_path / "nope.json")
    assert c.status == WARN
    assert "not found" in c.label


def test_check_cookies_file_malformed(tmp_path: Path):
    p = tmp_path / "cookies.json"
    p.write_text("this is not json", encoding="utf-8")
    c = _check_cookies_file(p)
    assert c.status == FAIL
    assert "malformed" in c.label


def test_check_cookies_file_empty(tmp_path: Path):
    p = tmp_path / "cookies.json"
    p.write_text(json.dumps({"cookies": [], "origins": []}), encoding="utf-8")
    c = _check_cookies_file(p)
    assert c.status == WARN
    assert "empty" in c.label


def test_check_cookies_file_all_expired(tmp_path: Path):
    p = tmp_path / "cookies.json"
    past = time.time() - 1000
    p.write_text(json.dumps({
        "cookies": [
            {"name": "a", "value": "v", "domain": "x.com", "expires": past},
            {"name": "b", "value": "v", "domain": "x.com", "expires": past},
        ],
    }), encoding="utf-8")
    c = _check_cookies_file(p)
    assert c.status == FAIL
    assert "expired" in c.label


def test_check_cookies_file_valid(tmp_path: Path):
    p = tmp_path / "cookies.json"
    future = time.time() + 86400
    p.write_text(json.dumps({
        "cookies": [
            {"name": "a", "value": "v", "domain": "x.com", "expires": future},
            {"name": "b", "value": "v", "domain": "x.com"},  # session cookie
        ],
    }), encoding="utf-8")
    c = _check_cookies_file(p)
    assert c.status == OK
    assert "valid" in c.label
    assert "2 cookies" in c.detail


def test_check_render_includes_label_and_detail():
    c = Check(OK, "Python 3.11.0", "details here")
    rendered = c.render()
    assert "Python 3.11.0" in rendered
    assert "details here" in rendered


def test_run_doctor_returns_appropriate_exit_code(tmp_path: Path, capsys):
    """All-OK environment isn't realistic to construct in a test (we don't
    control Playwright/Chromium presence), so we just assert run_doctor
    completes and returns one of (0, 1, 2)."""
    rc = run_doctor(tmp_path / "nope.json", [tmp_path])
    assert rc in (0, 1, 2)
    captured = capsys.readouterr().out
    assert "Checking auth-scrape environment" in captured


def test_run_doctor_strict_treats_warnings_as_failure(tmp_path: Path, capsys):
    rc = run_doctor(tmp_path / "nope.json", [tmp_path], strict=True)

    assert rc == 2
    captured = capsys.readouterr().out
    assert "Strict mode" in captured or "failure(s)" in captured
