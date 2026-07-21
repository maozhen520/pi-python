"""Seam: resource discovery + settings/trust against fake HOME + project roots."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pi_coding_agent.resources import (
    expand_prompt_template,
    load_project_context,
    load_resources,
    load_settings,
    load_trust,
    save_trust,
)


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_skills_discovered_from_global_project_and_agents_roots(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "home"
    repo = tmp_path / "repo"
    project = repo / "nested" / "project"
    project.mkdir(parents=True)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setattr(Path, "home", lambda: home)

    _write(
        home / ".pi" / "agent" / "skills" / "global-skill" / "SKILL.md",
        "---\nname: global-skill\ndescription: Global skill\n---\n# Global\n",
    )
    _write(
        home / ".agents" / "skills" / "home-agents" / "SKILL.md",
        "---\nname: home-agents\ndescription: Home agents skill\n---\n# Home\n",
    )
    _write(
        project / ".pi" / "skills" / "proj-skill" / "SKILL.md",
        "---\nname: proj-skill\ndescription: Project skill\n---\n# Proj\n",
    )
    _write(
        project / ".agents" / "skills" / "proj-agents" / "SKILL.md",
        "---\nname: proj-agents\ndescription: Project agents skill\n---\n# Agents\n",
    )
    _write(
        repo / ".agents" / "skills" / "ancestor-agents" / "SKILL.md",
        "---\nname: ancestor-agents\ndescription: Ancestor agents skill\n---\n# Ancestor\n",
    )
    save_trust(project, True, agent_dir=home / ".pi" / "agent")

    resources = load_resources(cwd=project, agent_dir=home / ".pi" / "agent", interactive=False)
    names = {s.name for s in resources.skills}
    assert names == {
        "global-skill",
        "home-agents",
        "proj-skill",
        "proj-agents",
        "ancestor-agents",
    }
    skill = next(s for s in resources.skills if s.name == "proj-skill")
    assert "Proj" in skill.read()


def test_settings_skill_md_path_loads_only_that_skill(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "home"
    project = tmp_path / "project"
    monkeypatch.setattr(Path, "home", lambda: home)
    agent_dir = home / ".pi" / "agent"
    skills_root = agent_dir / "extra-skills"
    _write(
        skills_root / "keep" / "SKILL.md",
        "---\nname: keep\ndescription: Keep me\n---\n",
    )
    _write(
        skills_root / "skip" / "SKILL.md",
        "---\nname: skip\ndescription: Skip me\n---\n",
    )
    _write(
        agent_dir / "settings.json",
        json.dumps({"skills": [str(skills_root / "keep" / "SKILL.md")]}),
    )

    resources = load_resources(cwd=project, agent_dir=agent_dir, interactive=False)
    assert {s.name for s in resources.skills} == {"keep"}


def test_untrusted_project_skills_are_skipped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "home"
    project = tmp_path / "project"
    monkeypatch.setattr(Path, "home", lambda: home)
    _write(
        home / ".pi" / "agent" / "skills" / "global-skill" / "SKILL.md",
        "---\nname: global-skill\ndescription: Global\n---\n",
    )
    _write(
        project / ".pi" / "skills" / "secret" / "SKILL.md",
        "---\nname: secret\ndescription: Secret\n---\n",
    )
    resources = load_resources(cwd=project, agent_dir=home / ".pi" / "agent", interactive=False)
    assert {s.name for s in resources.skills} == {"global-skill"}


def test_prompt_templates_expand_with_placeholders(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "home"
    project = tmp_path / "project"
    monkeypatch.setattr(Path, "home", lambda: home)
    _write(
        home / ".pi" / "agent" / "prompts" / "greet.md",
        "---\ndescription: Say hi\n---\nHello $1 and $@\n",
    )
    _write(
        project / ".pi" / "prompts" / "nested.md",
        "Nested should not load from subdir\n",
    )
    # nested under prompts/subdir should be ignored (non-recursive)
    _write(project / ".pi" / "prompts" / "subdir" / "x.md", "nope\n")
    save_trust(project, True, agent_dir=home / ".pi" / "agent")

    resources = load_resources(cwd=project, agent_dir=home / ".pi" / "agent", interactive=False)
    names = {p.name for p in resources.prompts}
    assert "greet" in names
    assert "x" not in names
    expanded = expand_prompt_template(
        next(p for p in resources.prompts if p.name == "greet"),
        ["Ada", "Bob"],
    )
    assert expanded == "Hello Ada and Ada Bob"


def test_settings_nested_merge_and_trust_persistence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "home"
    project = tmp_path / "project"
    monkeypatch.setattr(Path, "home", lambda: home)
    agent_dir = home / ".pi" / "agent"
    _write(
        agent_dir / "settings.json",
        '{"skills":["global"],"defaultProjectTrust":"ask","enableSkillCommands":true,"extra":{"a":1,"b":2}}',
    )
    _write(
        project / ".pi" / "settings.json",
        '{"prompts":["local"],"extra":{"b":9,"c":3},"enableSkillCommands":false}',
    )
    save_trust(project, True, agent_dir=agent_dir)

    settings = load_settings(cwd=project, agent_dir=agent_dir, project_trusted=True)
    assert settings["skills"] == ["global"]
    assert settings["prompts"] == ["local"]
    assert settings["defaultProjectTrust"] == "ask"
    assert settings["enableSkillCommands"] is False
    assert settings["extra"] == {"a": 1, "b": 9, "c": 3}
    assert load_trust(project, agent_dir=agent_dir) is True


def test_noninteractive_skips_project_unless_trusted_or_approve(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "home"
    project = tmp_path / "project"
    monkeypatch.setattr(Path, "home", lambda: home)
    agent_dir = home / ".pi" / "agent"
    _write(
        project / ".pi" / "skills" / "only-proj" / "SKILL.md",
        "---\nname: only-proj\ndescription: d\n---\n",
    )

    denied = load_resources(cwd=project, agent_dir=agent_dir, interactive=False)
    assert denied.skills == []

    approved = load_resources(
        cwd=project, agent_dir=agent_dir, interactive=False, approve_project=True
    )
    assert {s.name for s in approved.skills} == {"only-proj"}


def test_context_files_prefer_agents_then_claude(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "home"
    monkeypatch.setattr(Path, "home", lambda: home)
    root = tmp_path / "repo"
    nested = root / "pkg" / "mod"
    nested.mkdir(parents=True)
    _write(root / "CLAUDE.md", "root claude\n")
    _write(root / "pkg" / "AGENTS.md", "pkg agents\n")
    _write(nested / "CLAUDE.md", "nested claude\n")

    block = load_project_context(cwd=nested)
    assert "<project_context>" in block
    assert "root claude" in block
    assert "pkg agents" in block
    assert "nested claude" in block
    # Prefer AGENTS.md over CLAUDE.md in the same directory.
    _write(nested / "AGENTS.md", "nested agents\n")
    block2 = load_project_context(cwd=nested)
    assert "nested agents" in block2
    assert "nested claude" not in block2


def test_untrusted_project_prompts_are_skipped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "home"
    project = tmp_path / "project"
    monkeypatch.setattr(Path, "home", lambda: home)
    agent_dir = home / ".pi" / "agent"
    _write(agent_dir / "prompts" / "global.md", "Global prompt\n")
    _write(project / ".pi" / "prompts" / "local.md", "Local prompt\n")

    resources = load_resources(cwd=project, agent_dir=agent_dir, interactive=False)
    assert {p.name for p in resources.prompts} == {"global"}


def test_interactive_trust_prompt_persists_decision(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "home"
    project = tmp_path / "project"
    monkeypatch.setattr(Path, "home", lambda: home)
    agent_dir = home / ".pi" / "agent"
    _write(
        project / ".pi" / "skills" / "asked" / "SKILL.md",
        "---\nname: asked\ndescription: From interactive trust\n---\n",
    )
    asks: list[Path] = []

    def ask(cwd: Path) -> bool:
        asks.append(cwd)
        return True

    resources = load_resources(
        cwd=project,
        agent_dir=agent_dir,
        interactive=True,
        ask_trust=ask,
    )
    assert asks == [project]
    assert {s.name for s in resources.skills} == {"asked"}
    assert load_trust(project, agent_dir=agent_dir) is True


def test_settings_extra_paths_under_project_require_trust(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "home"
    project = tmp_path / "project"
    monkeypatch.setattr(Path, "home", lambda: home)
    agent_dir = home / ".pi" / "agent"
    secret = project / "vendor" / "skills" / "secret" / "SKILL.md"
    _write(
        secret,
        "---\nname: secret\ndescription: Should stay gated\n---\n",
    )
    _write(
        agent_dir / "settings.json",
        json.dumps({"skills": [str(secret.parent.parent)]}),
    )

    denied = load_resources(cwd=project, agent_dir=agent_dir, interactive=False)
    assert denied.skills == []

    save_trust(project, True, agent_dir=agent_dir)
    allowed = load_resources(cwd=project, agent_dir=agent_dir, interactive=False)
    assert {s.name for s in allowed.skills} == {"secret"}
