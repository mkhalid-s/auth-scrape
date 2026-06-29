"""Tests for the profile scaffolding helpers."""
from __future__ import annotations

from pathlib import Path

import pytest

from authscrape.config import load_profile
from authscrape.scaffold import (
    _allow_prefix_from_seed,
    _registrable_domain,
    render_profile_yaml,
    validate_name,
    write_profile,
)


def test_registrable_domain_two_label():
    assert _registrable_domain("example.com") == "example.com"


def test_registrable_domain_multi_label():
    assert _registrable_domain("docs.staging.example.net") == "example.net"


def test_registrable_domain_lowercases():
    assert _registrable_domain("Docs.Example.COM") == "example.com"


def test_allow_prefix_from_seed_directory_url():
    assert (
        _allow_prefix_from_seed("https://docs.x.com/private/project/")
        == "https://docs.x.com/private/project/"
    )


def test_allow_prefix_from_seed_file_url():
    """A non-directory seed has its last path component trimmed."""
    assert (
        _allow_prefix_from_seed("https://docs.x.com/private/project/page")
        == "https://docs.x.com/private/project/"
    )


def test_allow_prefix_from_seed_root():
    assert _allow_prefix_from_seed("https://x.com/") == "https://x.com/"


def test_validate_name_accepts_valid():
    validate_name("team-docs")
    validate_name("ai_connect")
    validate_name("foo123")


def test_validate_name_rejects_empty():
    with pytest.raises(ValueError):
        validate_name("")


def test_validate_name_rejects_leading_digit():
    with pytest.raises(ValueError):
        validate_name("123foo")


def test_validate_name_rejects_special_chars():
    with pytest.raises(ValueError):
        validate_name("foo bar")
    with pytest.raises(ValueError):
        validate_name("foo/bar")


def test_render_profile_yaml_minimal_loads_back(tmp_path: Path):
    """The rendered YAML must round-trip through load_profile cleanly."""
    text = render_profile_yaml(
        name="test-profile",
        site="https://docs.example.com/foo/",
    )
    p = tmp_path / "test-profile.yaml"
    p.write_text(text, encoding="utf-8")
    prof = load_profile(p)
    assert prof.name == "test-profile"
    assert prof.seeds == ["https://docs.example.com/foo/"]
    assert "https://docs.example.com/foo/" in prof.crawl.allow_prefixes
    assert "example.com" in prof.auth.cookie_domains
    assert "okta.com" in prof.auth.cookie_domains


def test_render_profile_yaml_with_keywords_enables_focus(tmp_path: Path):
    text = render_profile_yaml(
        name="kw",
        site="https://x.com/foo",
        keywords=["alpha", "beta"],
    )
    p = tmp_path / "kw.yaml"
    p.write_text(text, encoding="utf-8")
    prof = load_profile(p)
    assert prof.focus.enabled
    assert prof.focus.keywords == ["alpha", "beta"]
    assert prof.focus.save == "matched_only"


def test_render_profile_yaml_without_keywords_leaves_focus_commented(tmp_path: Path):
    text = render_profile_yaml(name="nofocus", site="https://x.com/")
    assert "# focus:" in text  # commented-out, ready to enable
    p = tmp_path / "nofocus.yaml"
    p.write_text(text, encoding="utf-8")
    prof = load_profile(p)
    assert not prof.focus.enabled


def test_render_profile_yaml_rejects_non_http_site():
    with pytest.raises(ValueError):
        render_profile_yaml(name="bad", site="file:///etc/passwd")


def test_render_profile_yaml_rejects_bare_string():
    with pytest.raises(ValueError):
        render_profile_yaml(name="bad", site="not-a-url")


def test_render_profile_yaml_uses_custom_cookie_domains(tmp_path: Path):
    text = render_profile_yaml(
        name="cd",
        site="https://x.com/",
        cookie_domains=["only-this.com"],
    )
    p = tmp_path / "cd.yaml"
    p.write_text(text, encoding="utf-8")
    prof = load_profile(p)
    assert prof.auth.cookie_domains == ["only-this.com"]


def test_write_profile_writes_to_path(tmp_path: Path):
    yaml = render_profile_yaml(name="w", site="https://x.com/")
    out = tmp_path / "w.yaml"
    path = write_profile(name="w", yaml_text=yaml, out_path=out)
    assert path == out
    assert out.exists()


def test_write_profile_refuses_overwrite_without_force(tmp_path: Path):
    yaml = render_profile_yaml(name="w", site="https://x.com/")
    out = tmp_path / "w.yaml"
    write_profile(name="w", yaml_text=yaml, out_path=out)
    with pytest.raises(FileExistsError):
        write_profile(name="w", yaml_text=yaml, out_path=out)


def test_write_profile_overwrites_with_force(tmp_path: Path):
    out = tmp_path / "w.yaml"
    write_profile(name="w", yaml_text="first", out_path=out)
    write_profile(name="w", yaml_text="second", out_path=out, force=True)
    assert out.read_text() == "second"
