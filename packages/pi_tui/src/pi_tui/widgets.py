"""Reusable Textual widgets for the coding CLI UI."""

from __future__ import annotations

from collections.abc import Callable

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.events import Key
from textual.widgets import Static, TextArea

from pi_tui.mac import short_model_name, shorten_path
from pi_tui.theme import APP_CSS

_EMPTY_HINT = "与 agent 对话 — ↵ 发送，⇧↵ 换行，/compact、/exit"


def _shorten(text: str, limit: int = 96) -> str:
    one_line = text.strip().replace("\n", " ")
    if len(one_line) <= limit:
        return one_line
    return one_line[: limit - 3] + "..."


class HeaderBar(Static):
    """Minimal top strip."""

    DEFAULT_CSS = "HeaderBar { dock: top; height: 1; background: #111114; }"

    def __init__(self, **kwargs) -> None:
        super().__init__("", markup=True, **kwargs)

    def on_mount(self) -> None:
        self.update("[bold #e4e4e7]piy[/] [dim]coding agent[/]")


class FooterBar(Static):
    """Status line: model, cwd, Mac shortcuts."""

    DEFAULT_CSS = "FooterBar { dock: bottom; height: 1; background: #111114; }"

    def __init__(self, *, model: str = "", cwd: str = "", **kwargs) -> None:
        super().__init__("", markup=True, **kwargs)
        self._model = model
        self._cwd = cwd

    def on_mount(self) -> None:
        self._refresh()

    def set_context(self, *, model: str | None = None, cwd: str | None = None) -> None:
        if model is not None:
            self._model = model
        if cwd is not None:
            self._cwd = cwd
        self._refresh()

    def _refresh(self) -> None:
        model = short_model_name(self._model)
        cwd = shorten_path(self._cwd)
        self.update(
            f"[#7dd3fc]{model}[/] [dim]│[/] [#71717a]{cwd}[/] [dim]│[/] "
            f"[bold]↵[/] 发送  [bold]⇧↵[/] 换行  [bold]⌃C[/] 退出"
        )


class TranscriptView(Static):
    """Unified message stream — full repaint each update to avoid RichLog ghosting."""

    def __init__(self, **kwargs) -> None:
        super().__init__(f"[dim]{_EMPTY_HINT}[/]", markup=True, **kwargs)
        self._blocks: list[str] = []
        self._plain_lines: list[str] = []
        self._streaming: str | None = None

    def visible_text(self) -> str:
        parts = list(self._plain_lines)
        if self._streaming is not None:
            parts.append(self._streaming)
        return "\n".join(parts)

    def _compose_markup(self) -> str:
        if not self._blocks and self._streaming is None:
            return f"[dim]{_EMPTY_HINT}[/]"
        parts = list(self._blocks)
        if self._streaming is not None:
            body = self._streaming.replace("\n", "\n  ")
            parts.append(f"[bold #7dd3fc]pi[/] …\n  {body}")
        return "\n\n".join(parts)

    def _paint(self) -> None:
        self.update(self._compose_markup())

    def _append_block(self, *, markup: str, plain: str) -> None:
        self._blocks.append(markup)
        self._plain_lines.append(plain)
        self._paint()

    def append_settled(self, role: str, content: str) -> None:
        labels = {"user": "you", "assistant": "pi", "tool": "tool", "error": "error"}
        label = labels.get(role, role)
        body = content.replace("\n", "\n  ")
        plain = f"{label}:\n  {body}"
        self._append_block(markup=f"[bold]{label}[/]\n  {body}", plain=plain)

    def set_streaming(self, content: str) -> None:
        self._streaming = content
        self._paint()

    def clear_streaming(self) -> None:
        self._streaming = None
        self._paint()

    def tool_start(self, name: str, args: dict) -> None:
        arg_preview = ", ".join(f"{k}={v!r}" for k, v in args.items())
        plain = f"▸ {name} {arg_preview}"
        self._append_block(
            markup=f"[#a78bfa]▸ {name}[/] [dim]{arg_preview}[/]",
            plain=plain,
        )

    def tool_end(self, name: str, content: str, *, is_error: bool) -> None:
        status = "failed" if is_error else "done"
        preview = _shorten(content)
        plain = f"  {name} {status}: {preview}"
        color = "#f87171" if is_error else "#34d399"
        self._append_block(
            markup=f"[dim]  {name}[/] [{color}]{status}[/] [dim]{preview}[/]",
            plain=plain,
        )


class EditorWidget(TextArea):
    """Bottom editor — Mac-first: ↵ submit, ⇧↵ newline (matches upstream pi)."""

    BINDINGS = [
        Binding("ctrl+j", "submit_prompt", "Send", show=False),
    ]

    def __init__(self, on_submit: Callable[[str], None] | None = None, **kwargs) -> None:
        super().__init__(**kwargs)
        self.border_title = "message"
        self._on_submit = on_submit

    @property
    def text(self) -> str:  # type: ignore[override]
        return self.document.text

    def set_text(self, value: str) -> None:
        self.load_text(value)

    def submit(self) -> None:
        value = self.text
        if not value.strip():
            return
        if self._on_submit is not None:
            self._on_submit(value)
        self.load_text("")

    def action_submit_prompt(self) -> None:
        self.submit()

    def on_key(self, event: Key) -> None:
        if event.key == "enter":
            event.prevent_default()
            event.stop()
            self.action_submit_prompt()


class CodingApp(App[None]):
    """Upstream pi layout: messages + editor + footer."""

    CSS = APP_CSS
    BINDINGS = [
        Binding("ctrl+c", "request_quit", "Quit", show=False),
    ]

    def __init__(
        self,
        on_submit: Callable[[str], None] | None = None,
        *,
        model: str = "",
        cwd: str = "",
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self._on_submit = on_submit
        self._model = model
        self._cwd = cwd

    def compose(self) -> ComposeResult:
        yield HeaderBar(id="header")
        with Vertical(id="layout-main"):
            yield TranscriptView(id="transcript")
            yield EditorWidget(on_submit=self._on_submit, id="editor")
        yield FooterBar(model=self._model, cwd=self._cwd, id="footer")

    def action_request_quit(self) -> None:
        self.exit()
