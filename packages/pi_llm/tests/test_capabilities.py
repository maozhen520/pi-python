"""Capability probes: unsupported features reported without crashing."""

from __future__ import annotations

from pi_llm import supports_parallel_tools, supports_tools


def test_supports_tools_uses_probe() -> None:
    assert supports_tools("good-model", probe=lambda model: model == "good-model") is True
    assert supports_tools("bad-model", probe=lambda model: model == "good-model") is False


def test_supports_parallel_tools_uses_probe() -> None:
    assert supports_parallel_tools("m", probe=lambda _model: True) is True
    assert supports_parallel_tools("m", probe=lambda _model: False) is False


def test_probe_exception_reports_unsupported() -> None:
    def boom(_model: str) -> bool:
        raise RuntimeError("probe unavailable")

    assert supports_tools("x", probe=boom) is False
    assert supports_parallel_tools("x", probe=boom) is False
