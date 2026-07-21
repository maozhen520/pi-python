"""Settings nested merge and project trust."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any


def default_agent_dir() -> Path:
    return Path.home() / ".pi" / "agent"


def _read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return raw if isinstance(raw, dict) else {}


def deep_merge(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    out = dict(base)
    for key, value in overlay.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = deep_merge(out[key], value)
        else:
            out[key] = value
    return out


def load_settings(
    *,
    cwd: Path,
    agent_dir: Path | None = None,
    project_trusted: bool = False,
) -> dict[str, Any]:
    root = default_agent_dir() if agent_dir is None else agent_dir
    global_settings = _read_json(root / "settings.json")
    project_settings = _read_json(cwd / ".pi" / "settings.json") if project_trusted else {}
    merged = deep_merge(global_settings, project_settings)
    # Ensure v1 keys exist with sensible defaults when absent.
    merged.setdefault("skills", [])
    merged.setdefault("prompts", [])
    merged.setdefault("defaultProjectTrust", "ask")
    merged.setdefault("enableSkillCommands", True)
    return merged


def trust_path(agent_dir: Path | None = None) -> Path:
    root = default_agent_dir() if agent_dir is None else agent_dir
    return root / "trust.json"


def _cwd_key(cwd: Path) -> str:
    return str(cwd.resolve())


def load_trust(cwd: Path, *, agent_dir: Path | None = None) -> bool | None:
    data = _read_json(trust_path(agent_dir))
    value = data.get(_cwd_key(cwd))
    if isinstance(value, bool):
        return value
    return None


def save_trust(cwd: Path, trusted: bool, *, agent_dir: Path | None = None) -> None:
    path = trust_path(agent_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = _read_json(path)
    data[_cwd_key(cwd)] = trusted
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def resolve_project_trust(
    cwd: Path,
    *,
    agent_dir: Path | None = None,
    interactive: bool = False,
    approve_project: bool = False,
    ask: Callable[[Path], bool] | None = None,
) -> bool:
    """Return whether project resources may load.

    Non-interactive: trusted or `--approve` only.
    Interactive: may prompt when defaultProjectTrust is `ask` and no saved decision.
    """
    if approve_project:
        return True
    saved = load_trust(cwd, agent_dir=agent_dir)
    if saved is True:
        return True
    if saved is False:
        return False

    settings = load_settings(cwd=cwd, agent_dir=agent_dir, project_trusted=False)
    # Global-only settings for the default trust policy.
    policy = settings.get("defaultProjectTrust", "ask")
    if policy == "always":
        save_trust(cwd, True, agent_dir=agent_dir)
        return True
    if policy == "never":
        return False

    if not interactive:
        return False
    if ask is None:
        return False
    decision = bool(ask(cwd))
    save_trust(cwd, decision, agent_dir=agent_dir)
    return decision
