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
    """Scrollable transcript of settled messages."""

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

    def visible_text(self) -> str:
        return "\n".join(self._lines)

    def append_settled(self, role: str, content: str) -> None:
        self._lines.append(f"[{role}] {content}")
        self.update(self.visible_text())


class StreamingAssistantView(Static):
    """Live assistant text while a turn is still streaming."""

    DEFAULT_CSS = """
    StreamingAssistantView {
        height: auto;
        max-height: 12;
        border: solid $primary;
        padding: 0 1;
    }
    """

    def __init__(self, **kwargs) -> None:
        super().__init__("", **kwargs)
        self._content: str | None = None

    def visible_text(self) -> str:
        return self._content or ""

    def set_streaming(self, content: str) -> None:
        self._content = content
        self.update(f"[assistant streaming] {content}")

    def clear(self) -> None:
        self._content = None
        self.update("")


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

    def compose(self) -> ComposeResult:
        with Vertical():
            yield TranscriptView(id="transcript")
            yield StreamingAssistantView(id="streaming")
            yield ToolDisplay(id="tools")
            yield EditorWidget(on_submit=self._on_submit, id="editor")

    def handle_event(self, event: AgentEvent) -> None:
        """Apply an agent runtime event to the four UI blocks."""
        transcript = self.query_one(TranscriptView)
        streaming = self.query_one(StreamingAssistantView)
        tools = self.query_one(ToolDisplay)

        if isinstance(event, (MessageStartEvent, MessageUpdateEvent)) and isinstance(
            event.message, AssistantMessage
        ):
            streaming.set_streaming(event.message.content or "")
            return

        if isinstance(event, MessageEndEvent):
            streaming.clear()
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
