"""Tests for macOS TUI helpers."""

from __future__ import annotations

from pathlib import Path

import pytest

from pi_tui.mac import short_model_name, shorten_path


def test_shorten_path_replaces_home(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(Path, "home", lambda: Path("/Users/alice"))
    assert shorten_path("/Users/alice/proj", max_len=80) == "~/proj"


def test_short_model_name_strips_provider() -> None:
    assert short_model_name("openai/deepseek-v4-flash") == "deepseek-v4-flash"
