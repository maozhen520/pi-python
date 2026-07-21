"""Coding session wiring: Agent + tools + resources + session + optional TUI."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from pi_agent import Agent, AgentEvent, StreamFn
from pi_coding_agent.resources import LoadedResources, expand_prompt_template, load_resources
from pi_coding_agent.session import Session, SessionStore, apply_compaction_view
from pi_coding_agent.tools import create_builtin_tools
from pi_tui import CodingApp


def build_system_prompt(resources: LoadedResources) -> str:
    parts = [
        "You are a coding agent with read/write/edit/bash tools.",
        "Prefer `read` before `edit` so replacements match current file contents.",
    ]
    if resources.skills:
        lines = ["<skills>"]
        for skill in resources.skills:
            lines.append(f'<skill name="{skill.name}">{skill.description}</skill>')
        lines.append("</skills>")
        lines.append("Read a skill's SKILL.md with the read tool when you need full instructions.")
        parts.append("\n".join(lines))
    if resources.prompts:
        names = ", ".join(f"/{p.name}" for p in resources.prompts)
        parts.append(f"Available prompt templates: {names}")
    if resources.project_context:
        parts.append(resources.project_context)
    return "\n\n".join(parts)


def ensure_credentials_interactive(
    *,
    required_keys: list[str],
    auth_path: Path,
    prompt_fn: Callable[[str], str],
    environ: dict[str, str] | None = None,
) -> dict[str, str]:
    """Prompt-and-save missing credentials to auth.json (interactive skeleton)."""
    env = dict(environ or {})
    existing: dict[str, str] = {}
    if auth_path.is_file():
        try:
            raw = json.loads(auth_path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                existing = {
                    k: v for k, v in raw.items() if isinstance(k, str) and isinstance(v, str)
                }
        except (OSError, json.JSONDecodeError):
            existing = {}

    saved = dict(existing)
    for key in required_keys:
        if env.get(key) or saved.get(key):
            continue
        value = prompt_fn(key)
        if value:
            saved[key] = value
    auth_path.parent.mkdir(parents=True, exist_ok=True)
    auth_path.write_text(json.dumps(saved, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return saved


def ask_trust_default(cwd: Path) -> bool:
    """Interactive trust prompt skeleton (non-TUI fallback)."""
    answer = input(f"Trust project resources under {cwd}? [y/N] ").strip().lower()
    return answer in {"y", "yes"}


@dataclass
class CodingSession:
    """Wires resources, built-in tools, Session persistence, and Agent."""

    cwd: Path
    agent: Agent
    session: Session
    resources: LoadedResources
    system_prompt: str
    store: SessionStore
    _persisted_count: int = field(default=0, repr=False)

    @classmethod
    def create(
        cls,
        *,
        cwd: Path,
        stream_fn: StreamFn,
        agent_dir: Path | None = None,
        sessions_root: Path | None = None,
        interactive: bool = False,
        approve_project: bool = False,
        ask_trust: Callable[[Path], bool] | None = None,
    ) -> CodingSession:
        resources = load_resources(
            cwd=cwd,
            agent_dir=agent_dir,
            interactive=interactive,
            approve_project=approve_project,
            ask_trust=ask_trust,
        )
        system_prompt = build_system_prompt(resources)
        store = SessionStore(root=sessions_root or (Path.home() / ".pi" / "agent" / "sessions"))
        session = store.create(cwd=cwd)
        agent = Agent(
            stream_fn=stream_fn,
            system_prompt=system_prompt,
            tools=create_builtin_tools(cwd=cwd),
            messages=[],
            transform_context=cls._make_transform(session),
        )
        return cls(
            cwd=cwd,
            agent=agent,
            session=session,
            resources=resources,
            system_prompt=system_prompt,
            store=store,
            _persisted_count=0,
        )

    @classmethod
    def resume(
        cls,
        path: Path,
        *,
        cwd: Path,
        stream_fn: StreamFn,
        agent_dir: Path | None = None,
        interactive: bool = False,
        approve_project: bool = False,
        ask_trust: Callable[[Path], bool] | None = None,
        sessions_root: Path | None = None,
    ) -> CodingSession:
        resources = load_resources(
            cwd=cwd,
            agent_dir=agent_dir,
            interactive=interactive,
            approve_project=approve_project,
            ask_trust=ask_trust,
        )
        system_prompt = build_system_prompt(resources)
        store = SessionStore(root=sessions_root or (Path.home() / ".pi" / "agent" / "sessions"))
        session = store.resume(path)
        agent = Agent(
            stream_fn=stream_fn,
            system_prompt=system_prompt,
            tools=create_builtin_tools(cwd=cwd),
            messages=session.model_messages(),
            transform_context=cls._make_transform(session),
        )
        return cls(
            cwd=cwd,
            agent=agent,
            session=session,
            resources=resources,
            system_prompt=system_prompt,
            store=store,
            _persisted_count=len(session.messages),
        )

    @staticmethod
    def _make_transform(session: Session):
        def transform(messages):
            if session._compactions:
                return apply_compaction_view(list(messages), session._compactions[-1])
            return list(messages)

        return transform

    async def prompt(self, text: str) -> None:
        if text.startswith("/compact"):
            instructions = text[len("/compact") :].strip()
            self.handle_compact(instructions)
            return
        if text.startswith("/") and not text.startswith("//"):
            expanded = self._expand_slash(text)
            if expanded is not None:
                text = expanded
        before = len(self.agent.messages)
        await self.agent.prompt(text)
        for message in self.agent.messages[before:]:
            self.session.append_message(message)
            self._persisted_count += 1

    def handle_compact(self, instructions: str = "") -> None:
        summary = f"[compacted{': ' + instructions if instructions else ''}]"
        entry = self.session.compact(
            summary=summary,
            keep_recent_tokens=800,
            instructions=instructions,
        )
        self.agent.messages = apply_compaction_view(self.session.messages, entry)

    def _expand_slash(self, text: str) -> str | None:
        body = text[1:]
        name, _, arg_str = body.partition(" ")
        prompt = next((p for p in self.resources.prompts if p.name == name), None)
        if prompt is None:
            return None
        args = arg_str.split() if arg_str else []
        return expand_prompt_template(prompt, args)

    def bind_tui(self, app: CodingApp) -> Callable[[], None]:
        def on_event(event: AgentEvent) -> None:
            app.handle_event(event)

        return self.agent.subscribe(on_event)
