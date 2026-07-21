"""Project context files → `<project_context>` injection."""

from __future__ import annotations

from pathlib import Path

_CONTEXT_NAMES = ("AGENTS.md", "AGENTS.MD", "CLAUDE.md", "CLAUDE.MD")


def _pick_context_file(directory: Path) -> Path | None:
    for name in _CONTEXT_NAMES:
        candidate = directory / name
        if candidate.is_file():
            return candidate
    return None


def collect_context_files(cwd: Path) -> list[Path]:
    """Walk ancestors outer→inner; per directory prefer AGENTS.md else CLAUDE.md peers."""
    current = cwd.resolve()
    chain = list(reversed([current, *current.parents]))
    # Limit walk to filesystem root only; include all ancestors.
    files: list[Path] = []
    for directory in chain:
        picked = _pick_context_file(directory)
        if picked is not None:
            files.append(picked)
    return files


def load_project_context(cwd: Path) -> str:
    parts: list[str] = []
    for path in collect_context_files(cwd):
        try:
            text = path.read_text(encoding="utf-8").strip()
        except OSError:
            continue
        if text:
            parts.append(f"## {path.name} ({path.parent})\n\n{text}")
    if not parts:
        return ""
    body = "\n\n".join(parts)
    return f"<project_context>\n{body}\n</project_context>"
