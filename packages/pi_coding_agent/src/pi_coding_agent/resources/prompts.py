"""Prompt template discovery and `/name` expansion."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

_FRONTMATTER_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*\n?(.*)\Z", re.DOTALL)


@dataclass(frozen=True, slots=True)
class PromptTemplate:
    name: str
    description: str
    path: Path
    body: str


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


def discover_prompts_in_dir(root: Path) -> list[PromptTemplate]:
    if not root.is_dir():
        return []
    prompts: list[PromptTemplate] = []
    for md in sorted(root.glob("*.md")):
        try:
            text = md.read_text(encoding="utf-8")
        except OSError:
            continue
        meta, body = _parse_frontmatter(text)
        prompts.append(
            PromptTemplate(
                name=md.stem,
                description=meta.get("description", ""),
                path=md,
                body=body,
            )
        )
    return prompts


def expand_prompt_template(template: PromptTemplate, args: list[str]) -> str:
    """Expand upstream-style placeholders: $1..$N, $@ / $ARGUMENTS, ${N:-default}."""
    text = template.body

    def replace_default(match: re.Match[str]) -> str:
        index = int(match.group(1))
        default = match.group(2)
        if 1 <= index <= len(args):
            return args[index - 1]
        return default

    text = re.sub(r"\$\{(\d+):-([^}]*)\}", replace_default, text)

    def replace_slice(match: re.Match[str]) -> str:
        start = int(match.group(1))
        length = match.group(2)
        sliced = args[start - 1 :]
        if length is not None:
            sliced = sliced[: int(length)]
        return " ".join(sliced)

    text = re.sub(r"\$\{@:(\d+)(?::(\d+))?\}", replace_slice, text)
    text = text.replace("$@", " ".join(args))
    text = text.replace("$ARGUMENTS", " ".join(args))

    for i, arg in enumerate(args, start=1):
        text = text.replace(f"${i}", arg)

    # Clear unmatched numbered placeholders.
    text = re.sub(r"\$\d+", "", text)
    return text.rstrip("\n")
