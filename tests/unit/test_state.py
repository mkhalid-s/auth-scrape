"""Tests for resume-state persistence.

Locks in the P0-3 fix: corrupt files are backed up and warned (not silently
discarded), saves are atomic, and the new `failed` set is round-tripped.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from authscrape.state import State, SCHEMA_VERSION, make_item


def test_round_trip_preserves_visited_failed_and_queue(tmp_path: Path):
    p = tmp_path / "state.json"
    s = State(p)
    s.visited.add("https://example.com/a")
    s.failed.add("https://example.com/b")
    s.queue = [make_item("https://example.com/c", budget=2, matched=True)]
    s.save()

    s2 = State.load_or_new(p)
    assert s2.visited == {"https://example.com/a"}
    assert s2.failed == {"https://example.com/b"}
    assert len(s2.queue) == 1
    assert s2.queue[0]["url"] == "https://example.com/c"
    assert s2.queue[0]["budget"] == 2
    assert s2.queue[0]["matched"] is True


def test_save_is_atomic(tmp_path: Path):
    """Save writes to .tmp then renames — no half-written state file."""
    p = tmp_path / "state.json"
    s = State(p)
    s.visited.add("https://x/a")
    s.save()
    # No leftover .tmp after a successful save.
    assert not p.with_suffix(p.suffix + ".tmp").exists()
    # File parses as JSON.
    data = json.loads(p.read_text(encoding="utf-8"))
    assert data["schema_version"] == SCHEMA_VERSION


def test_save_writes_schema_version(tmp_path: Path):
    p = tmp_path / "state.json"
    s = State(p)
    s.queue = [make_item("https://x/a", 0, False)]
    s.save()
    data = json.loads(p.read_text(encoding="utf-8"))
    assert "schema_version" in data
    assert data["schema_version"] == SCHEMA_VERSION


def test_load_or_new_returns_fresh_when_file_missing(tmp_path: Path):
    p = tmp_path / "doesnotexist.json"
    s = State.load_or_new(p)
    assert s.visited == set()
    assert s.failed == set()
    assert s.queue == []


def test_load_or_new_preserves_corrupt_file(tmp_path: Path, capsys):
    """Corrupt JSON is backed up with `.corrupt-<ts>` suffix, not silently
    discarded — and a warning goes to stderr."""
    p = tmp_path / "state.json"
    p.write_text("this is not json {{{", encoding="utf-8")
    s = State.load_or_new(p)
    assert s.visited == set()
    assert s.queue == []
    # Backup should exist with `.corrupt-` in its name.
    backups = [f for f in tmp_path.iterdir() if ".corrupt-" in f.name]
    assert len(backups) == 1, "corrupt state file must be preserved as a backup"
    captured = capsys.readouterr()
    assert "WARNING" in captured.err
    assert "corrupt" in captured.err


def test_load_or_new_accepts_legacy_string_queue_entries(tmp_path: Path):
    """Older state files had bare-string queue entries; auto-upgrade them."""
    p = tmp_path / "state.json"
    p.write_text(json.dumps({
        "visited": [],
        "queue": ["https://x/a", "https://x/b"],
    }), encoding="utf-8")
    s = State.load_or_new(p)
    assert len(s.queue) == 2
    assert s.queue[0]["url"] == "https://x/a"
    assert s.queue[0]["budget"] == 0
    assert s.queue[0]["matched"] is False


def test_load_or_new_accepts_dict_queue_entries(tmp_path: Path):
    p = tmp_path / "state.json"
    p.write_text(json.dumps({
        "queue": [{"url": "https://x/a", "budget": 3, "matched": True}],
    }), encoding="utf-8")
    s = State.load_or_new(p)
    assert s.queue[0]["budget"] == 3
    assert s.queue[0]["matched"] is True


def test_save_creates_parent_directory(tmp_path: Path):
    p = tmp_path / "nested" / "deep" / "state.json"
    s = State(p)
    s.save()
    assert p.exists()
