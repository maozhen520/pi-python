"""Smoke tests for the uv workspace scaffold (#19)."""

from __future__ import annotations

import importlib
import shutil
from importlib import metadata


def test_four_packages_are_importable() -> None:
    for name in ("pi_llm", "pi_agent", "pi_tui", "pi_coding_agent"):
        module = importlib.import_module(name)
        assert module.__name__ == name


def test_piy_console_entrypoint_is_declared() -> None:
    # Console script name must be `piy` (stub body is fine for scaffold).
    eps = metadata.entry_points()
    scripts = eps.select(group="console_scripts")
    names = {ep.name for ep in scripts}
    assert "piy" in names


def test_piy_executable_resolves_on_path() -> None:
    assert shutil.which("piy") is not None
