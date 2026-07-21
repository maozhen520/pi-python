"""Seam: light Textual pilots — drive widgets via public APIs (no agent wiring)."""

from __future__ import annotations

import pytest

from pi_tui import (
    CodingApp,
    EditorWidget,
    StreamingAssistantView,
    ToolDisplay,
    TranscriptView,
)


@pytest.mark.asyncio
async def test_transcript_appends_settled_messages() -> None:
    app = CodingApp()
    async with app.run_test() as pilot:
        transcript = app.query_one(TranscriptView)
        transcript.append_settled("user", "hello user")
        await pilot.pause()
        assert "hello user" in transcript.visible_text()

        transcript.append_settled("assistant", "hello assistant")
        await pilot.pause()
        assert "hello assistant" in transcript.visible_text()


@pytest.mark.asyncio
async def test_streaming_assistant_updates_incrementally() -> None:
    app = CodingApp()
    async with app.run_test() as pilot:
        streaming = app.query_one(StreamingAssistantView)
        streaming.set_streaming("Hel")
        await pilot.pause()
        assert "Hel" in streaming.visible_text()

        streaming.set_streaming("Hello")
        await pilot.pause()
        assert streaming.visible_text() == "Hello"

        streaming.clear()
        app.query_one(TranscriptView).append_settled("assistant", "Hello")
        await pilot.pause()
        assert streaming.visible_text() == ""
        assert "Hello" in app.query_one(TranscriptView).visible_text()


@pytest.mark.asyncio
async def test_tool_display_shows_start_and_end() -> None:
    app = CodingApp()
    async with app.run_test() as pilot:
        tools = app.query_one(ToolDisplay)
        tools.tool_start("read", {"path": "a.txt"})
        await pilot.pause()
        assert "read" in tools.visible_text()
        assert "a.txt" in tools.visible_text()

        tools.tool_end("read", "ok", is_error=False)
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


@pytest.mark.asyncio
async def test_editor_ctrl_j_submits() -> None:
    submitted: list[str] = []
    app = CodingApp(on_submit=lambda text: submitted.append(text))
    async with app.run_test() as pilot:
        editor = app.query_one(EditorWidget)
        editor.focus()
        editor.set_text("ship it")
        await pilot.press("ctrl+j")
        await pilot.pause()
        assert submitted == ["ship it"]
        assert editor.text == ""
