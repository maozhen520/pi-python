"""Reusable Textual widgets for the coding CLI UI."""

from __future__ import annotations

from collections.abc import Callable

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.events import Key
from textual.widgets import RichLog, TextArea

from pi_tui.mac import short_model_name, shorten_path
from pi_tui.theme import APP_CSS

_EMPTY_HINT = "与 agent 对话 — ↵ 发送，⇧↵ 换行，/compact、/exit"


def _shorten(text: str, limit: int = 96) -> str:
    one_line = text.strip().replace("\n", " ")
    if len(one_line) <= limit:
        return one_line
    return one_line[: limit - 3] + "..."


class HeaderBar(RichLog):
    """Minimal top strip."""

    DEFAULT_CSS = "HeaderBar { dock: top; height: 1; background: #111114; }"

    def on_mount(self) -> None:
        self.write("[bold #e4e4e7]piy[/] [dim]coding agent[/]")


class FooterBar(RichLog):
    """Status line: model, cwd, Mac shortcuts."""

    DEFAULT_CSS = "FooterBar { dock: bottom; height: 1; background: #111114; }"

    def __init__(self, *, model: str = "", cwd: str = "", **kwargs) -> None:
        super().__init__(**kwargs)
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
        self.clear()
        self.write(
            f"[#7dd3fc]{model}[/] [dim]│[/] [#71717a]{cwd}[/] [dim]│[/] "
            f"[bold]↵[/] 发送  [bold]⇧↵[/] 换行  [bold]⌃C[/] 退出"
        )


class TranscriptView(RichLog):
    """Unified message stream: history, streaming, and tool calls."""

    def __init__(self, **kwargs) -> None:
        super().__init__(highlight=True, markup=True, wrap=True, **kwargs)
        self._plain_lines: list[str] = []
        self._streaming: str | None = None

    def on_mount(self) -> None:
        self.write(f"[dim]{_EMPTY_HINT}[/]")

    def visible_text(self) -> str:
        parts = list(self._plain_lines)
        if self._streaming is not None:
            parts.append(self._streaming)
        return "\n".join(parts)

    def _write_block(self, line: str, *, plain: str) -> None:
        if not self._plain_lines and self._streaming is None:
            self.clear()
        self._plain_lines.append(plain)
        self.write(line)

    def append_settled(self, role: str, content: str) -> None:
        labels = {"user": "you", "assistant": "pi", "tool": "tool", "error": "error"}
        label = labels.get(role, role)
        body = content.replace("\n", "\n  ")
        plain = f"{label}:\n  {body}"
        self._write_block(f"[bold]{label}[/]\n  {body}", plain=plain)

    def set_streaming(self, content: str) -> None:
        self._streaming = content
        self.clear()
        for plain in self._plain_lines:
            self.write(plain)
        self.write(f"[bold #7dd3fc]pi[/] …\n  {content.replace(chr(10), chr(10) + '  ')}")

    def clear_streaming(self) -> None:
        self._streaming = None

    def tool_start(self, name: str, args: dict) -> None:
        arg_preview = ", ".join(f"{k}={v!r}" for k, v in args.items())
        plain = f"▸ {name} {arg_preview}"
        self._write_block(f"[#a78bfa]▸ {name}[/] [dim]{arg_preview}[/]", plain=plain)

    def tool_end(self, name: str, content: str, *, is_error: bool) -> None:
        status = "failed" if is_error else "done"
        preview = _shorten(content)
        plain = f"  {name} {status}: {preview}"
        color = "#f87171" if is_error else "#34d399"
        self._write_block(f"[dim]  {name}[/] [{color}]{status}[/] [dim]{preview}[/]", plain=plain)


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
        yield HeaderBar(id="header", markup=True)
        with Vertical(id="layout-main"):
            yield TranscriptView(id="transcript")
            yield EditorWidget(on_submit=self._on_submit, id="editor")
        yield FooterBar(model=self._model, cwd=self._cwd, id="footer", markup=True)

    def action_request_quit(self) -> None:
        self.exit()
