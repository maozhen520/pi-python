"""Seam: light Textual pilots — drive widgets via public APIs (no agent wiring)."""

from __future__ import annotations

import pytest

from pi_tui import CodingApp, EditorWidget, TranscriptView


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
        transcript = app.query_one(TranscriptView)
        transcript.set_streaming("Hel")
        await pilot.pause()
        assert "Hel" in transcript.visible_text()

        transcript.set_streaming("Hello")
        await pilot.pause()
        assert "Hello" in transcript.visible_text()

        transcript.clear_streaming()
        transcript.append_settled("assistant", "Hello")
        await pilot.pause()
        assert "Hello" in transcript.visible_text()
        assert transcript._streaming is None  # noqa: SLF001


@pytest.mark.asyncio
async def test_tool_display_shows_start_and_end() -> None:
    app = CodingApp()
    async with app.run_test() as pilot:
        transcript = app.query_one(TranscriptView)
        transcript.tool_start("read", {"path": "a.txt"})
        await pilot.pause()
        assert "read" in transcript.visible_text()
        assert "a.txt" in transcript.visible_text()

        transcript.tool_end("read", "ok", is_error=False)
        await pilot.pause()
        assert "ok" in transcript.visible_text()
        assert "done" in transcript.visible_text()


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
async def test_editor_enter_submits() -> None:
    submitted: list[str] = []
    app = CodingApp(on_submit=lambda text: submitted.append(text))
    async with app.run_test() as pilot:
        editor = app.query_one(EditorWidget)
        editor.focus()
        editor.set_text("ship it")
        await pilot.press("enter")
        await pilot.pause()
        assert submitted == ["ship it"]
        assert editor.text == ""


@pytest.mark.asyncio
async def test_editor_ctrl_j_still_submits() -> None:
    submitted: list[str] = []
    app = CodingApp(on_submit=lambda text: submitted.append(text))
    async with app.run_test() as pilot:
        editor = app.query_one(EditorWidget)
        editor.focus()
        editor.set_text("legacy submit")
        await pilot.press("ctrl+j")
        await pilot.pause()
        assert submitted == ["legacy submit"]
