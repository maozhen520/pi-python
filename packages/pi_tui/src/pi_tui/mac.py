"""macOS-specific helpers for the coding CLI TUI."""

from __future__ import annotations

from pathlib import Path


def shorten_path(path: str, *, max_len: int = 48) -> str:
    """Replace home with ~ and truncate long paths for narrow terminals."""
    if not path or path == "—":
        return path
    try:
        resolved = str(Path(path).expanduser())
    except (OSError, ValueError):
        resolved = path
    home = str(Path.home())
    if resolved.startswith(home):
        resolved = "~" + resolved[len(home) :]
    if len(resolved) <= max_len:
        return resolved
    head = resolved[: max_len // 2 - 1]
    tail = resolved[-(max_len // 2 - 2) :]
    return f"{head}…{tail}"


def short_model_name(model: str) -> str:
    """Show the tail of a LiteLLM model id (e.g. deepseek-v4-flash)."""
    if not model:
        return "—"
    if "/" in model:
        return model.rsplit("/", 1)[-1]
    return model
