"""Credentials: env first, then optional ~/.pi/agent/auth.json."""

from __future__ import annotations

import json
from pathlib import Path

from pi_llm import apply_credentials_to_environ, resolve_credentials


def test_env_wins_over_auth_file(tmp_path: Path) -> None:
    auth = tmp_path / "auth.json"
    auth.write_text(json.dumps({"OPENAI_API_KEY": "from-file"}), encoding="utf-8")

    creds = resolve_credentials(
        environ={"OPENAI_API_KEY": "from-env"},
        auth_path=auth,
    )
    assert creds["OPENAI_API_KEY"] == "from-env"


def test_auth_file_fills_missing_env(tmp_path: Path) -> None:
    auth = tmp_path / "auth.json"
    auth.write_text(
        json.dumps({"OPENAI_API_KEY": "from-file", "ANTHROPIC_API_KEY": "anth-file"}),
        encoding="utf-8",
    )

    creds = resolve_credentials(
        environ={"ANTHROPIC_API_KEY": "anth-env"},
        auth_path=auth,
    )
    assert creds["OPENAI_API_KEY"] == "from-file"
    assert creds["ANTHROPIC_API_KEY"] == "anth-env"


def test_missing_auth_file_is_ok(tmp_path: Path) -> None:
    creds = resolve_credentials(
        environ={"OPENAI_API_KEY": "only-env"},
        auth_path=tmp_path / "missing.json",
    )
    assert creds == {"OPENAI_API_KEY": "only-env"}


def test_non_credential_env_keys_are_ignored(tmp_path: Path) -> None:
    creds = resolve_credentials(environ={"FOO": "1"}, auth_path=tmp_path / "missing.json")
    assert creds == {}


def test_apply_credentials_does_not_override_env(tmp_path: Path) -> None:
    auth = tmp_path / "auth.json"
    auth.write_text(json.dumps({"OPENAI_API_KEY": "from-file"}), encoding="utf-8")
    environ = {"OPENAI_API_KEY": "from-env"}

    apply_credentials_to_environ(environ=environ, auth_path=auth)
    assert environ["OPENAI_API_KEY"] == "from-env"


def test_apply_credentials_fills_missing(tmp_path: Path) -> None:
    auth = tmp_path / "auth.json"
    auth.write_text(json.dumps({"OPENAI_API_KEY": "from-file"}), encoding="utf-8")
    environ: dict[str, str] = {}

    apply_credentials_to_environ(environ=environ, auth_path=auth)
    assert environ["OPENAI_API_KEY"] == "from-file"
