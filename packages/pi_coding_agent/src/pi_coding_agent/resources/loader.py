"""Unified resource loader for skills, prompts, settings, trust, context."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from pi_coding_agent.resources.context import load_project_context
from pi_coding_agent.resources.prompts import PromptTemplate, discover_prompts_in_dir
from pi_coding_agent.resources.settings import (
    default_agent_dir,
    load_settings,
    resolve_project_trust,
)
from pi_coding_agent.resources.skills import (
    Skill,
    ancestor_agents_skill_dirs,
    discover_skills_in_dir,
)


@dataclass(slots=True)
class LoadedResources:
    skills: list[Skill] = field(default_factory=list)
    prompts: list[PromptTemplate] = field(default_factory=list)
    settings: dict = field(default_factory=dict)
    project_trusted: bool = False
    project_context: str = ""


def load_resources(
    *,
    cwd: Path | None = None,
    agent_dir: Path | None = None,
    interactive: bool = False,
    approve_project: bool = False,
    ask_trust: Callable[[Path], bool] | None = None,
) -> LoadedResources:
    root = Path.cwd() if cwd is None else Path(cwd)
    agent = default_agent_dir() if agent_dir is None else Path(agent_dir)
    trusted = resolve_project_trust(
        root,
        agent_dir=agent,
        interactive=interactive,
        approve_project=approve_project,
        ask=ask_trust,
    )
    settings = load_settings(cwd=root, agent_dir=agent, project_trusted=trusted)

    skills: list[Skill] = []
    seen_skill: set[str] = set()

    def add_skills(items: list[Skill]) -> None:
        for skill in items:
            if skill.name not in seen_skill:
                skills.append(skill)
                seen_skill.add(skill.name)

    add_skills(discover_skills_in_dir(agent / "skills", agents_layout=False))
    add_skills(discover_skills_in_dir(Path.home() / ".agents" / "skills", agents_layout=True))
    if trusted:
        add_skills(discover_skills_in_dir(root / ".pi" / "skills", agents_layout=False))
        for agents_dir in ancestor_agents_skill_dirs(root):
            add_skills(discover_skills_in_dir(agents_dir, agents_layout=True))

    for extra in settings.get("skills") or []:
        if isinstance(extra, str):
            path = Path(extra)
            if not path.is_absolute():
                path = (agent if not trusted else root) / path
            if path.is_file() and path.name == "SKILL.md":
                add_skills(discover_skills_in_dir(path.parent.parent, agents_layout=False))
            elif path.is_dir():
                add_skills(discover_skills_in_dir(path, agents_layout=False))

    prompts: list[PromptTemplate] = []
    seen_prompt: set[str] = set()

    def add_prompts(items: list[PromptTemplate]) -> None:
        for prompt in items:
            if prompt.name not in seen_prompt:
                prompts.append(prompt)
                seen_prompt.add(prompt.name)

    add_prompts(discover_prompts_in_dir(agent / "prompts"))
    if trusted:
        add_prompts(discover_prompts_in_dir(root / ".pi" / "prompts"))

    for extra in settings.get("prompts") or []:
        if isinstance(extra, str):
            path = Path(extra)
            if path.is_file():
                add_prompts(discover_prompts_in_dir(path.parent))
            elif path.is_dir():
                add_prompts(discover_prompts_in_dir(path))

    return LoadedResources(
        skills=skills,
        prompts=prompts,
        settings=settings,
        project_trusted=trusted,
        project_context=load_project_context(root),
    )
