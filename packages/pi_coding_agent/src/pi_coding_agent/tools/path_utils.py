"""Path helpers for built-in tools."""

from __future__ import annotations

from pathlib import Path


def resolve_to_cwd(path: str, cwd: Path) -> Path:
    candidate = Path(path)
    if candidate.is_absolute():
        return candidate
    return (cwd / candidate).resolve()
