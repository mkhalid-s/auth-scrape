"""Shared pytest fixtures for auth-scrape tests."""
from __future__ import annotations

from pathlib import Path

import pytest


FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture
def fixtures_dir() -> Path:
    return FIXTURES_DIR


@pytest.fixture
def html_fixture(fixtures_dir):
    def _load(name: str) -> str:
        return (fixtures_dir / "html" / name).read_text(encoding="utf-8")
    return _load


@pytest.fixture
def cookie_fixture(fixtures_dir):
    def _path(name: str) -> Path:
        return fixtures_dir / "cookies" / name
    return _path


@pytest.fixture
def profile_fixture(fixtures_dir):
    def _path(name: str) -> Path:
        return fixtures_dir / "profiles" / name
    return _path
