"""Reusable Textual widgets for the coding CLI UI."""

from __future__ import annotations

from collections.abc import Callable

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.widgets import Static, TextArea


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

    def tool_end(self, name: str, content: str, *, is_error: bool) -> None:
        status = "error" if is_error else "done"
        preview = content.strip().replace("\n", " ")
        if len(preview) > 80:
            preview = preview[:77] + "..."
        self._lines.append(f"← {name} [{status}] {preview}")
        self.update(self.visible_text())


class EditorWidget(TextArea):
    """Multiline bottom editor; Ctrl+J submits."""

    BINDINGS = [
        Binding("ctrl+j", "submit_prompt", "Submit", priority=True),
    ]

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

    def action_submit_prompt(self) -> None:
        self.submit()


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
