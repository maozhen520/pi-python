#!/usr/bin/env python3
"""Mac Terminal UX probe: render TUI at common macOS terminal sizes."""

from __future__ import annotations

import asyncio
from pathlib import Path

from pi_tui import CodingApp, EditorWidget, TranscriptView

# Typical macOS sizes: Terminal.app default-ish, iTerm2 comfortable, large display
SIZES = {
    "terminal-80x24": (80, 24),
    "iterm-120x40": (120, 40),
    "large-160x50": (160, 50),
}
OUT_DIR = Path("docs/assets/mac-probe")


async def probe_size(name: str, cols: int, rows: int) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    app = CodingApp(
        model="openai/deepseek-v4-flash",
        cwd="/Users/maozhen/Documents/pi-python",
    )
    async with app.run_test(size=(cols, rows)) as pilot:
        transcript = app.query_one(TranscriptView)
        editor = app.query_one(EditorWidget)

        app.save_screenshot(filename=f"{name}-idle.svg", path=str(OUT_DIR))
        print(f"{name}: idle screenshot saved")

        transcript.append_settled("user", "你好，帮我读一下 README.md 的前三行")
        transcript.tool_start("read", {"path": "README.md", "offset": 1, "limit": 3})
        transcript.set_streaming("好的，我先读取 README")
        editor.set_text("继续")
        await pilot.pause()
        app.save_screenshot(filename=f"{name}-active.svg", path=str(OUT_DIR))
        await pilot.pause(delay=0.05)

        transcript.tool_end("read", "# pi-python\n\nPython 实现...", is_error=False)
        transcript.clear_streaming()
        transcript.append_settled(
            "assistant",
            "已读取 README 前三行：\n# pi-python\n\nPython 实现对齐...",
        )
        await pilot.pause()
        app.save_screenshot(filename=f"{name}-settled.svg", path=str(OUT_DIR))
        print(f"{name}: active + settled screenshots saved")


async def main() -> None:
    for name, (cols, rows) in SIZES.items():
        await probe_size(name, cols, rows)
    print(f"Probe complete → {OUT_DIR.resolve()}")


if __name__ == "__main__":
    asyncio.run(main())
