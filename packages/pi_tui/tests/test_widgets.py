"""Seam: light Textual pilots — inject runtime events, assert widget-facing updates."""

from __future__ import annotations

import pytest
from pi_agent.types import AssistantStreamTextDelta

from pi_agent import (
    AgentToolResult,
    AssistantMessage,
    MessageEndEvent,
    MessageStartEvent,
    MessageUpdateEvent,
    ToolExecutionEndEvent,
    ToolExecutionStartEvent,
    UserMessage,
)
from pi_tui import (
    CodingApp,
    EditorWidget,
    StreamingAssistantView,
    ToolDisplay,
    TranscriptView,
)


@pytest.mark.asyncio
async def test_transcript_updates_from_message_events() -> None:
    app = CodingApp()
    async with app.run_test() as pilot:
        transcript = app.query_one(TranscriptView)
        app.handle_event(MessageEndEvent(message=UserMessage(content="hello user")))
        await pilot.pause()
        assert "hello user" in transcript.visible_text()

        app.handle_event(
            MessageEndEvent(message=AssistantMessage(content="hello assistant", stop_reason="stop"))
        )
        await pilot.pause()
        assert "hello assistant" in transcript.visible_text()


@pytest.mark.asyncio
async def test_streaming_assistant_updates_incrementally() -> None:
    app = CodingApp()
    async with app.run_test() as pilot:
        streaming = app.query_one(StreamingAssistantView)
        partial = AssistantMessage(content="")
        app.handle_event(MessageStartEvent(message=partial))
        app.handle_event(
            MessageUpdateEvent(
                message=AssistantMessage(content="Hel"),
                assistant_message_event=AssistantStreamTextDelta(
                    partial=AssistantMessage(content="Hel"),
                    delta="Hel",
                ),
            )
        )
        await pilot.pause()
        assert "Hel" in streaming.visible_text()

        app.handle_event(
            MessageUpdateEvent(
                message=AssistantMessage(content="Hello"),
                assistant_message_event=AssistantStreamTextDelta(
                    partial=AssistantMessage(content="Hello"),
                    delta="lo",
                ),
            )
        )
        await pilot.pause()
        assert streaming.visible_text() == "Hello"

        app.handle_event(
            MessageEndEvent(message=AssistantMessage(content="Hello", stop_reason="stop"))
        )
        await pilot.pause()
        assert streaming.visible_text() == ""
        assert "Hello" in app.query_one(TranscriptView).visible_text()


@pytest.mark.asyncio
async def test_tool_display_shows_start_and_end() -> None:
    app = CodingApp()
    async with app.run_test() as pilot:
        tools = app.query_one(ToolDisplay)
        app.handle_event(
            ToolExecutionStartEvent(
                tool_call_id="1",
                tool_name="read",
                args={"path": "a.txt"},
            )
        )
        await pilot.pause()
        assert "read" in tools.visible_text()
        assert "a.txt" in tools.visible_text()

        app.handle_event(
            ToolExecutionEndEvent(
                tool_call_id="1",
                tool_name="read",
                result=AgentToolResult(content="ok"),
                is_error=False,
            )
        )
        await pilot.pause()
        assert "ok" in tools.visible_text()
        assert "done" in tools.visible_text()


@pytest.mark.asyncio
async def test_editor_accepts_multiline_and_submits() -> None:
    submitted: list[str] = []
    app = CodingApp(on_submit=lambda text: submitted.append(text))
    async with app.run_test() as pilot:
        editor = app.query_one(EditorWidget)
        editor.set_text("line1\nline2")
        await pilot.pause()
        assert "line1" in editor.text
        editor.submit()
        await pilot.pause()
        assert submitted == ["line1\nline2"]
        assert editor.text == ""
