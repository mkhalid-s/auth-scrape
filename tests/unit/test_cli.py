"""Tests for CLI-only safety behavior."""
from __future__ import annotations

from authscrape.cli import main


def test_run_requires_authorization_before_cookie_check(profile_fixture, capsys):
    rc = main(["run", str(profile_fixture("minimal.yaml"))])

    assert rc == 2
    captured = capsys.readouterr()
    assert "explicit authorization" in captured.err
    assert "Cookie file not found" not in captured.err


def test_run_with_authorization_reaches_cookie_check(profile_fixture, tmp_path, capsys):
    missing = tmp_path / "missing-cookies.json"

    rc = main([
        "run",
        str(profile_fixture("minimal.yaml")),
        "--cookies",
        str(missing),
        "--i-have-authorization",
    ])

    assert rc == 1
    captured = capsys.readouterr()
    assert "Cookie file not found" in captured.err


def test_run_dry_run_prints_scope_without_cookie_or_output(profile_fixture, tmp_path, capsys):
    out_dir = tmp_path / "out"
    missing = tmp_path / "missing-cookies.json"

    rc = main([
        "run",
        str(profile_fixture("minimal.yaml")),
        "--cookies",
        str(missing),
        "--out",
        str(out_dir),
        "--dry-run",
    ])

    assert rc == 0
    captured = capsys.readouterr()
    assert "auth-scrape run dry run" in captured.out
    assert "https://example.com/docs/" in captured.out
    assert str(missing) in captured.out
    assert not out_dir.exists()
