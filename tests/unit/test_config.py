"""Tests for profile loading and validation.

Locks in the P0-4 fix: unknown YAML keys raise ProfileError with a helpful
suggestion instead of a raw TypeError stack trace; numeric coercion;
save-enum validation.
"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from authscrape.config import (
    DEFAULT_LOGIN_URL_PATTERNS,
    ProfileError,
    find_profile,
    list_profiles,
    load_profile,
)


def _write_profile(tmp_path: Path, content: dict, name: str = "p.yaml") -> Path:
    p = tmp_path / name
    p.write_text(yaml.safe_dump(content), encoding="utf-8")
    return p


# ---------- happy path ----------

def test_load_minimal_profile(profile_fixture):
    prof = load_profile(profile_fixture("minimal.yaml"))
    assert prof.name == "minimal"
    assert prof.seeds == ["https://example.com/docs/"]
    # Seed-derived prefix fallback.
    assert prof.crawl.allow_prefixes == ["https://example.com/docs/"]


def test_load_focus_profile(profile_fixture):
    prof = load_profile(profile_fixture("with_focus.yaml"))
    assert prof.focus.enabled
    assert "widget" in prof.focus.keywords
    assert prof.focus.save == "matched_only"
    assert prof.search.url_template == "https://example.com/search?q={query}"


def test_default_login_patterns_attached(profile_fixture):
    prof = load_profile(profile_fixture("minimal.yaml"))
    assert prof.auth.login_url_patterns == DEFAULT_LOGIN_URL_PATTERNS


# ---------- unknown-key rejection (P0-4) ----------

def test_unknown_top_level_key_rejected(tmp_path: Path):
    p = _write_profile(tmp_path, {
        "name": "p", "seeds": ["https://x/"],
        "wrongkey": "value",
    })
    with pytest.raises(ProfileError) as exc:
        load_profile(p)
    assert "wrongkey" in str(exc.value)


def test_unknown_top_level_key_suggests_correction(tmp_path: Path):
    """Typo close to a real key gets a `did you mean` hint."""
    p = _write_profile(tmp_path, {
        "name": "p", "seeds": ["https://x/"],
        "seed": ["https://x/"],  # close to "seeds"
    })
    with pytest.raises(ProfileError) as exc:
        load_profile(p)
    assert "seeds" in str(exc.value)


def test_unknown_crawl_key_rejected(profile_fixture):
    """The bundled bad_unknown_key.yaml has crawl.max_page (typo)."""
    with pytest.raises(ProfileError) as exc:
        load_profile(profile_fixture("bad_unknown_key.yaml"))
    msg = str(exc.value)
    assert "max_page" in msg
    assert "max_pages" in msg  # did-you-mean


def test_unknown_focus_key_rejected(tmp_path: Path):
    p = _write_profile(tmp_path, {
        "name": "p", "seeds": ["https://x/"],
        "focus": {"keyword": ["foo"]},  # should be "keywords"
    })
    with pytest.raises(ProfileError) as exc:
        load_profile(p)
    assert "keyword" in str(exc.value)


# ---------- save-enum validation ----------

def test_invalid_save_mode_rejected(tmp_path: Path):
    p = _write_profile(tmp_path, {
        "name": "p", "seeds": ["https://x/"],
        "focus": {"keywords": ["a"], "save": "matched-and-drilldown"},  # hyphen typo
    })
    with pytest.raises(ProfileError) as exc:
        load_profile(p)
    assert "matched_and_drilldown" in str(exc.value)


def test_valid_save_modes_accepted(tmp_path: Path):
    for mode in ("matched_only", "matched_and_drilldown", "all"):
        p = _write_profile(tmp_path, {
            "name": "p", "seeds": ["https://x/"],
            "focus": {"keywords": ["a"], "save": mode},
        }, name=f"p_{mode}.yaml")
        prof = load_profile(p)
        assert prof.focus.save == mode


# ---------- numeric coercion ----------

def test_min_score_int_coerced_to_float(tmp_path: Path):
    p = _write_profile(tmp_path, {
        "name": "p", "seeds": ["https://x/"],
        "focus": {"keywords": ["a"], "min_score": 1},  # int in YAML
    })
    prof = load_profile(p)
    assert isinstance(prof.focus.min_score, float)
    assert prof.focus.min_score == 1.0


def test_delay_seconds_int_coerced_to_float(tmp_path: Path):
    p = _write_profile(tmp_path, {
        "name": "p", "seeds": ["https://x/"],
        "crawl": {"delay_seconds": 2},
    })
    prof = load_profile(p)
    assert isinstance(prof.crawl.delay_seconds, float)


# ---------- seed validation ----------

def test_missing_seeds_rejected(tmp_path: Path):
    p = _write_profile(tmp_path, {"name": "p"})
    with pytest.raises(ProfileError) as exc:
        load_profile(p)
    assert "seeds" in str(exc.value)


def test_empty_seeds_list_rejected(tmp_path: Path):
    p = _write_profile(tmp_path, {"name": "p", "seeds": []})
    with pytest.raises(ProfileError) as exc:
        load_profile(p)
    assert "seeds" in str(exc.value)


def test_non_http_seed_rejected(tmp_path: Path):
    p = _write_profile(tmp_path, {
        "name": "p", "seeds": ["file:///etc/passwd"],
    })
    with pytest.raises(ProfileError) as exc:
        load_profile(p)
    assert "http" in str(exc.value).lower()


# ---------- find / list profiles ----------

def test_find_profile_returns_explicit_path(profile_fixture):
    p = profile_fixture("minimal.yaml")
    found = find_profile(str(p), [])
    assert found == p


def test_find_profile_searches_yaml_and_yml(tmp_path: Path):
    (tmp_path / "foo.yml").write_text("name: foo\nseeds: [https://x/]\n", encoding="utf-8")
    found = find_profile("foo", [tmp_path])
    assert found.suffix == ".yml"


def test_find_profile_raises_with_helpful_message(tmp_path: Path):
    with pytest.raises(FileNotFoundError) as exc:
        find_profile("nonexistent", [tmp_path])
    assert "nonexistent" in str(exc.value)


def test_list_profiles_dedupes_across_dirs(tmp_path: Path):
    d1 = tmp_path / "d1"
    d1.mkdir()
    d2 = tmp_path / "d2"
    d2.mkdir()
    (d1 / "foo.yaml").write_text("x", encoding="utf-8")
    (d2 / "foo.yaml").write_text("y", encoding="utf-8")
    (d2 / "bar.yaml").write_text("z", encoding="utf-8")
    found = list_profiles([d1, d2])
    names = {p.name for p in found}
    assert names == {"foo.yaml", "bar.yaml"}
