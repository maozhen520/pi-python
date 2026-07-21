"""Credential resolution: process env, then optional auth.json."""

from __future__ import annotations

import json
import os
from collections.abc import Mapping, MutableMapping
from pathlib import Path
from typing import Any


def default_auth_path() -> Path:
    return Path.home() / ".pi" / "agent" / "auth.json"


def resolve_credentials(
    *,
    environ: Mapping[str, str] | None = None,
    auth_path: Path | None = None,
) -> dict[str, str]:
    """Merge credentials with env taking precedence over `auth.json`.

    `auth.json` is a flat object of string keys/values (env-var style).
    Returns only credential-like keys (from the file and/or env).
    """
    env = dict(os.environ if environ is None else environ)
    path = default_auth_path() if auth_path is None else auth_path
    file_creds = _load_auth_file(path)

    keys = set(file_creds) | {k for k in env if _is_credential_key(k)}
    out: dict[str, str] = {}
    for key in keys:
        if key in env and isinstance(env[key], str):
            out[key] = env[key]
        elif key in file_creds:
            out[key] = file_creds[key]
    return out


def apply_credentials_to_environ(
    *,
    environ: MutableMapping[str, str] | None = None,
    auth_path: Path | None = None,
) -> dict[str, str]:
    """Resolve credentials and `setdefault` them into `environ` (process env by default)."""
    target: MutableMapping[str, str] = os.environ if environ is None else environ
    resolved = resolve_credentials(environ=dict(target), auth_path=auth_path)
    for key, value in resolved.items():
        target.setdefault(key, value)
    return resolved


def _is_credential_key(key: str) -> bool:
    upper = key.upper()
    return (
        upper.endswith("_API_KEY")
        or upper.endswith("_API_TOKEN")
        or upper.endswith("_ACCESS_TOKEN")
        or upper.startswith("LITELLM_")
        or upper in {"OPENAI_API_BASE", "OPENAI_BASE_URL"}
    )


def _load_auth_file(path: Path) -> dict[str, str]:
    if not path.is_file():
        return {}
    try:
        raw: Any = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(raw, dict):
        return {}
    out: dict[str, str] = {}
    for key, value in raw.items():
        if isinstance(key, str) and isinstance(value, str):
            out[key] = value
    return out
