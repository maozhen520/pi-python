"""Skill discovery from Agent Skills-style directories."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

_FRONTMATTER_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*\n?(.*)\Z", re.DOTALL)


@dataclass(frozen=True, slots=True)
class Skill:
    name: str
    description: str
    path: Path

    def read(self) -> str:
        return self.path.read_text(encoding="utf-8")


def _parse_frontmatter(text: str) -> tuple[dict[str, str], str]:
    match = _FRONTMATTER_RE.match(text)
    if not match:
        return {}, text
    meta: dict[str, str] = {}
    for line in match.group(1).splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        meta[key.strip()] = value.strip().strip("\"'")
    return meta, match.group(2)


def _load_skill_file(path: Path) -> Skill | None:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    meta, _body = _parse_frontmatter(text)
    name = meta.get("name") or path.parent.name
    description = meta.get("description")
    if not description:
        return None
    return Skill(name=name, description=description, path=path)


def discover_skills_in_dir(root: Path, *, agents_layout: bool = False) -> list[Skill]:
    """Discover skills under a directory.

    - `.pi/skills` / `~/.pi/agent/skills`: `SKILL.md` trees; root `.md` also allowed.
    - `.agents/skills`: only `*/SKILL.md` trees (root `.md` ignored).
    """
    if not root.is_dir():
        return []
    skills: list[Skill] = []
    seen: set[str] = set()

    if not agents_layout:
        for md in sorted(root.glob("*.md")):
            skill = _load_skill_file(md)
            if skill and skill.name not in seen:
                skills.append(skill)
                seen.add(skill.name)

    for child in sorted(root.iterdir()):
        if not child.is_dir():
            continue
        skill_md = child / "SKILL.md"
        if skill_md.is_file():
            skill = _load_skill_file(skill_md)
            if skill and skill.name not in seen:
                skills.append(skill)
                seen.add(skill.name)
    return skills


def ancestor_agents_skill_dirs(cwd: Path) -> list[Path]:
    dirs: list[Path] = []
    current = cwd.resolve()
    for directory in [current, *current.parents]:
        candidate = directory / ".agents" / "skills"
        if candidate.is_dir():
            dirs.append(candidate)
        if (directory / ".git").exists():
            break
    return dirs
