"""Reusable Textual widgets for the coding CLI UI."""

from __future__ import annotations

from collections.abc import Callable

from textual.app import App, ComposeResult
from textual.containers import Vertical
from textual.widgets import Static, TextArea

from pi_agent import (
    AgentEvent,
    AgentToolResult,
    AssistantMessage,
    MessageEndEvent,
    MessageStartEvent,
    MessageUpdateEvent,
    ToolExecutionEndEvent,
    ToolExecutionStartEvent,
    ToolResultMessage,
    UserMessage,
)


class TranscriptView(Static):
    """Scrollable transcript of settled + streaming messages."""

    DEFAULT_CSS = """
    TranscriptView {
        height: 1fr;
        border: solid $accent;
        overflow-y: auto;
        padding: 0 1;
    }
    """

    def __init__(self, **kwargs) -> None:
        super().__init__("", **kwargs)
        self._lines: list[str] = []
        self._streaming: str | None = None

    def visible_text(self) -> str:
        parts = list(self._lines)
        if self._streaming is not None:
            parts.append(self._streaming)
        return "\n".join(parts)

    def append_settled(self, role: str, content: str) -> None:
        self._streaming = None
        self._lines.append(f"[{role}] {content}")
        self.update(self.visible_text())

    def set_streaming(self, content: str) -> None:
        self._streaming = f"[assistant*] {content}"
        self.update(self.visible_text())

    def clear_streaming(self) -> None:
        self._streaming = None
        self.update(self.visible_text())


class ToolDisplay(Static):
    """Shows in-flight and completed tool calls."""

    DEFAULT_CSS = """
    ToolDisplay {
        height: auto;
        max-height: 8;
        border: solid $warning;
        padding: 0 1;
    }
    """

    def __init__(self, **kwargs) -> None:
        super().__init__("", **kwargs)
        self._lines: list[str] = []

    def visible_text(self) -> str:
        return "\n".join(self._lines)

    def tool_start(self, name: str, args: dict) -> None:
        self._lines.append(f"→ {name} {args}")
        self.update(self.visible_text())

    def tool_end(self, name: str, result: AgentToolResult, *, is_error: bool) -> None:
        status = "error" if is_error else "done"
        preview = (result.content or "").strip().replace("\n", " ")
        if len(preview) > 80:
            preview = preview[:77] + "..."
        self._lines.append(f"← {name} [{status}] {preview}")
        self.update(self.visible_text())


class EditorWidget(TextArea):
    """Multiline bottom editor with submit helper."""

    DEFAULT_CSS = """
    EditorWidget {
        height: 5;
        border: solid $success;
    }
    """

    def __init__(self, on_submit: Callable[[str], None] | None = None, **kwargs) -> None:
        super().__init__(**kwargs)
        self._on_submit = on_submit

    @property
    def text(self) -> str:  # type: ignore[override]
        return self.document.text

    def set_text(self, value: str) -> None:
        self.load_text(value)

    def submit(self) -> None:
        value = self.text
        if self._on_submit is not None:
            self._on_submit(value)
        self.load_text("")


class CodingApp(App[None]):
    """Minimal layout wiring the four v1 UI blocks."""

    CSS = """
    Screen {
        layout: vertical;
    }
    """

    def __init__(self, on_submit: Callable[[str], None] | None = None, **kwargs) -> None:
        super().__init__(**kwargs)
        self._on_submit = on_submit
        self._stream_buffer = ""

    def compose(self) -> ComposeResult:
        with Vertical():
            yield TranscriptView(id="transcript")
            yield ToolDisplay(id="tools")
            yield EditorWidget(on_submit=self._on_submit, id="editor")

    def handle_event(self, event: AgentEvent) -> None:
        transcript = self.query_one(TranscriptView)
        tools = self.query_one(ToolDisplay)

        if isinstance(event, MessageStartEvent) and isinstance(event.message, AssistantMessage):
            self._stream_buffer = event.message.content or ""
            transcript.set_streaming(self._stream_buffer)
            return

        if isinstance(event, MessageUpdateEvent) and isinstance(event.message, AssistantMessage):
            self._stream_buffer = event.message.content or ""
            transcript.set_streaming(self._stream_buffer)
            return

        if isinstance(event, MessageEndEvent):
            message = event.message
            if isinstance(message, UserMessage):
                transcript.append_settled("user", message.content)
            elif isinstance(message, AssistantMessage):
                transcript.append_settled("assistant", message.content or "")
            elif isinstance(message, ToolResultMessage):
                transcript.append_settled("tool", message.content)
            return

        if isinstance(event, ToolExecutionStartEvent):
            tools.tool_start(event.tool_name, event.args)
            return

        if isinstance(event, ToolExecutionEndEvent):
            tools.tool_end(event.tool_name, event.result, is_error=event.is_error)
