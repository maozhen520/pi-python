"""Seam: thin piy integration — fake LLM + temp dirs prove the interactive main path."""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from pi_agent.types import (
    AssistantStreamDone,
    AssistantStreamEvent,
    AssistantStreamStart,
    AssistantStreamTextDelta,
)
from pi_coding_agent.app import CodingSession, build_system_prompt
from pi_coding_agent.resources import save_trust
from pi_coding_agent.tui_wiring import apply_agent_event
from pi_llm.credentials import resolve_credentials

from pi_agent import (
    AgentToolResult,
    AssistantMessage,
    MessageEndEvent,
    MessageStartEvent,
    MessageUpdateEvent,
    StreamFn,
    StreamRequest,
    ToolCall,
    ToolExecutionEndEvent,
    ToolExecutionStartEvent,
    ToolResultMessage,
    UserMessage,
)
from pi_tui import CodingApp, StreamingAssistantView, ToolDisplay, TranscriptView


def _scripted_stream(responses: list[AssistantMessage]):
    remaining = list(responses)

    async def stream_fn(
        request: StreamRequest,
    ) -> AsyncIterator[AssistantStreamEvent]:
        msg = remaining.pop(0)
        yield AssistantStreamStart(partial=AssistantMessage(content=""))
        yield AssistantStreamDone(message=msg)

    return stream_fn


def _delta_stream(text: str) -> StreamFn:
    async def stream_fn(
        request: StreamRequest,
    ) -> AsyncIterator[AssistantStreamEvent]:
        partial = AssistantMessage(content="")
        yield AssistantStreamStart(partial=partial)
        for char in text:
            content = (partial.content or "") + char
            partial = AssistantMessage(content=content)
            yield AssistantStreamTextDelta(partial=partial, delta=char)
        yield AssistantStreamDone(message=AssistantMessage(content=text, stop_reason="stop"))

    return stream_fn


@pytest.mark.asyncio
async def test_coding_session_main_path_with_tools_resources_resume(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "home"
    project = tmp_path / "project"
    project.mkdir()
    monkeypatch.setattr(Path, "home", lambda: home)
    agent_dir = home / ".pi" / "agent"
    agent_dir.mkdir(parents=True)

    (project / "AGENTS.md").write_text("Use concise edits.\n", encoding="utf-8")
    skill_dir = agent_dir / "skills" / "demo"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\nname: demo\ndescription: Demo skill\n---\n# Demo\n",
        encoding="utf-8",
    )
    (agent_dir / "prompts" / "hi.md").parent.mkdir(parents=True, exist_ok=True)
    (agent_dir / "prompts" / "hi.md").write_text(
        "---\ndescription: hi\n---\nHello $1\n",
        encoding="utf-8",
    )
    save_trust(project, True, agent_dir=agent_dir)
    (project / "hello.txt").write_text("hello from disk\n", encoding="utf-8")

    # First session: read a file via fake LLM tool call.
    session = CodingSession.create(
        cwd=project,
        agent_dir=agent_dir,
        sessions_root=agent_dir / "sessions",
        stream_fn=_scripted_stream(
            [
                AssistantMessage(
                    content=None,
                    tool_calls=[ToolCall(id="1", name="read", arguments={"path": "hello.txt"})],
                    stop_reason="toolUse",
                ),
                AssistantMessage(content="read complete", stop_reason="stop"),
            ]
        ),
        interactive=False,
        approve_project=True,
    )
    assert (
        "project_context" in session.system_prompt or "Use concise edits" in session.system_prompt
    )
    assert "demo" in session.system_prompt
    assert any(t.name == "read" for t in session.agent.tools)

    events: list[str] = []
    session.agent.subscribe(lambda e: events.append(e.type))
    await session.prompt("read hello.txt")
    results = [m for m in session.agent.messages if isinstance(m, ToolResultMessage)]
    assert results and "hello from disk" in results[0].content
    assert "tool_execution_end" in events

    session_path = session.session.path

    # Resume prior JSONL session.
    resumed = CodingSession.resume(
        session_path,
        cwd=project,
        agent_dir=agent_dir,
        stream_fn=_scripted_stream([AssistantMessage(content="resumed ok", stop_reason="stop")]),
        interactive=False,
        approve_project=True,
    )
    assert any(
        isinstance(m, AssistantMessage) and m.content == "read complete"
        for m in resumed.agent.messages
    )
    await resumed.prompt("continue please")
    assert resumed.agent.messages[-1].content == "resumed ok"


def test_build_system_prompt_includes_skills_and_context(tmp_path: Path) -> None:
    from pi_coding_agent.resources import LoadedResources, Skill
    from pi_coding_agent.resources.prompts import PromptTemplate

    skill_path = tmp_path / "SKILL.md"
    skill_path.write_text("body", encoding="utf-8")
    resources = LoadedResources(
        skills=[Skill(name="s1", description="d1", path=skill_path)],
        prompts=[PromptTemplate(name="p1", description="pd", path=tmp_path / "p1.md", body="x")],
        project_context="<project_context>\nctx\n</project_context>",
    )
    prompt = build_system_prompt(resources)
    assert "s1" in prompt
    assert "d1" in prompt
    assert "ctx" in prompt


def test_auth_prompt_and_save_skeleton(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from pi_coding_agent.app import ensure_credentials_interactive

    home = tmp_path / "home"
    monkeypatch.setattr(Path, "home", lambda: home)
    auth_path = home / ".pi" / "agent" / "auth.json"
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    saved = ensure_credentials_interactive(
        required_keys=["OPENAI_API_KEY"],
        auth_path=auth_path,
        prompt_fn=lambda key: f"secret-for-{key}",
    )
    assert saved["OPENAI_API_KEY"] == "secret-for-OPENAI_API_KEY"
    assert auth_path.is_file()
    resolved = resolve_credentials(environ={}, auth_path=auth_path)
    assert resolved["OPENAI_API_KEY"] == "secret-for-OPENAI_API_KEY"


def test_trust_approve_flag_wired(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    home = tmp_path / "home"
    project = tmp_path / "project"
    project.mkdir()
    monkeypatch.setattr(Path, "home", lambda: home)
    agent_dir = home / ".pi" / "agent"
    skill = project / ".pi" / "skills" / "local" / "SKILL.md"
    skill.parent.mkdir(parents=True)
    skill.write_text("---\nname: local\ndescription: L\n---\n", encoding="utf-8")

    session = CodingSession.create(
        cwd=project,
        agent_dir=agent_dir,
        sessions_root=agent_dir / "sessions",
        stream_fn=_scripted_stream([]),
        interactive=False,
        approve_project=True,
    )
    assert "local" in session.system_prompt


@pytest.mark.asyncio
async def test_bind_tui_applies_runtime_events_to_widgets(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "home"
    project = tmp_path / "project"
    project.mkdir()
    monkeypatch.setattr(Path, "home", lambda: home)
    agent_dir = home / ".pi" / "agent"

    session = CodingSession.create(
        cwd=project,
        agent_dir=agent_dir,
        sessions_root=agent_dir / "sessions",
        stream_fn=_scripted_stream(
            [AssistantMessage(content="done via events", stop_reason="stop")]
        ),
        interactive=False,
        approve_project=True,
    )
    app = CodingApp()
    unsub = session.bind_tui(app)
    async with app.run_test() as pilot:
        transcript = app.query_one(TranscriptView)
        streaming = app.query_one(StreamingAssistantView)
        tools = app.query_one(ToolDisplay)

        apply_agent_event(app, MessageEndEvent(message=UserMessage(content="hello user")))
        await pilot.pause()
        assert "hello user" in transcript.visible_text()

        apply_agent_event(app, MessageStartEvent(message=AssistantMessage(content="")))
        apply_agent_event(
            app,
            MessageUpdateEvent(
                message=AssistantMessage(content="Hel"),
                assistant_message_event=AssistantStreamTextDelta(
                    partial=AssistantMessage(content="Hel"),
                    delta="Hel",
                ),
            ),
        )
        await pilot.pause()
        assert "Hel" in streaming.visible_text()

        apply_agent_event(
            app,
            ToolExecutionStartEvent(
                tool_call_id="1",
                tool_name="read",
                args={"path": "a.txt"},
            ),
        )
        apply_agent_event(
            app,
            ToolExecutionEndEvent(
                tool_call_id="1",
                tool_name="read",
                result=AgentToolResult(content="ok"),
                is_error=False,
            ),
        )
        await pilot.pause()
        assert "read" in tools.visible_text()
        assert "ok" in tools.visible_text()

        await session.prompt("go")
        await pilot.pause()
        assert "done via events" in transcript.visible_text()
        assert streaming.visible_text() == ""

    unsub()


def test_cli_main_wires_piy_entry(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from pi_coding_agent import cli

    home = tmp_path / "home"
    project = tmp_path / "project"
    project.mkdir()
    monkeypatch.setattr(Path, "home", lambda: home)
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")

    captured: dict[str, CodingSession] = {}

    async def fake_run_interactive(session: CodingSession) -> None:
        captured["session"] = session

    monkeypatch.setattr(cli, "_run_interactive", fake_run_interactive)
    monkeypatch.setattr(cli, "make_stream_fn", lambda **_: _scripted_stream([]))

    cli.main(["--non-interactive", "--approve", "--cwd", str(project)])

    session = captured["session"]
    assert session.cwd == project.resolve()
    assert any(t.name == "read" for t in session.agent.tools)
    assert any(t.name == "write" for t in session.agent.tools)
    assert any(t.name == "edit" for t in session.agent.tools)
    assert any(t.name == "bash" for t in session.agent.tools)


@pytest.mark.asyncio
async def test_bind_tui_streaming_deltas_via_session_prompt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "home"
    project = tmp_path / "project"
    project.mkdir()
    monkeypatch.setattr(Path, "home", lambda: home)
    agent_dir = home / ".pi" / "agent"

    session = CodingSession.create(
        cwd=project,
        agent_dir=agent_dir,
        sessions_root=agent_dir / "sessions",
        stream_fn=_delta_stream("Hello"),
        interactive=False,
        approve_project=True,
    )
    app = CodingApp()
    event_types: list[str] = []
    unsub_events = session.agent.subscribe(lambda e: event_types.append(e.type))
    unsub_tui = session.bind_tui(app)

    async with app.run_test() as pilot:
        streaming = app.query_one(StreamingAssistantView)
        transcript = app.query_one(TranscriptView)
        await session.prompt("go")
        await pilot.pause()
        assert "message_update" in event_types
        assert "Hello" in transcript.visible_text()
        assert streaming.visible_text() == ""

    unsub_tui()
    unsub_events()
