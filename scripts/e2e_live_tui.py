#!/usr/bin/env python3
"""Live end-to-end: DeepSeek API → agent harness → TUI, then save a screenshot.

Requires credentials in ~/.pi/agent/auth.json or OPENAI_API_KEY + OPENAI_API_BASE env.

Usage:
    uv run python scripts/e2e_live_tui.py
    uv run python scripts/e2e_live_tui.py --out docs/assets/piy-tui-e2e.png
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from pi_coding_agent.app import CodingSession
from pi_coding_agent.llm_bridge import make_stream_fn
from pi_llm.credentials import apply_credentials_to_environ

from pi_tui import CodingApp, TranscriptView

DEFAULT_MODEL = "openai/deepseek-v4-flash"
DEFAULT_OUT = Path("docs/assets/piy-tui-e2e.png")
PROMPT = "用一句话介绍你自己，不要说别的。"


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Live E2E: API + agent + TUI screenshot")
    parser.add_argument("--cwd", type=Path, default=Path.cwd(), help="Project cwd")
    parser.add_argument("--model", default=DEFAULT_MODEL, help="LiteLLM model id")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help="Screenshot path")
    parser.add_argument("--prompt", default=PROMPT, help="User message to send")
    return parser.parse_args()


async def run_e2e(*, cwd: Path, model: str, out: Path, prompt: str) -> None:
    apply_credentials_to_environ()

    session = CodingSession.create(
        cwd=cwd.resolve(),
        stream_fn=make_stream_fn(model=model),
        approve_project=True,
        interactive=False,
    )
    app = CodingApp(model=model, cwd=str(cwd.resolve()))
    session.bind_tui(app)

    out.parent.mkdir(parents=True, exist_ok=True)

    async with app.run_test(size=(100, 32)) as pilot:
        transcript = app.query_one(TranscriptView)

        await session.prompt(prompt)
        await pilot.pause()

        text = transcript.visible_text()
        if "pi" not in text and "assistant" not in text:
            print("FAIL: no assistant reply in transcript", file=sys.stderr)
            print("transcript:", text, file=sys.stderr)
            raise SystemExit(1)

        if transcript._streaming is not None:  # noqa: SLF001
            print("WARN: streaming not cleared after turn", file=sys.stderr)

        svg_path = app.save_screenshot(
            filename="piy-tui-e2e.svg",
            path=str(out.parent),
        )
        png_path = _svg_to_png(svg_path, out)
        print("OK: assistant replied")
        print(f"transcript preview: {text[:200]}...")
        print(f"screenshot: {png_path}")
        print(f"svg: {svg_path}")


def _svg_to_png(svg_path: str, png_path: Path) -> Path:
    """Best-effort SVG → PNG for README embedding."""
    import subprocess

    png_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        subprocess.run(
            ["qlmanage", "-t", "-s", "1600", "-o", str(png_path.parent), svg_path],
            check=True,
            capture_output=True,
        )
        generated = png_path.parent / (Path(svg_path).name + ".png")
        if generated.is_file():
            generated.replace(png_path)
            return png_path
    except (FileNotFoundError, subprocess.CalledProcessError):
        pass

    # Fallback: reference SVG directly
    return Path(svg_path)


def main() -> None:
    args = _parse_args()
    asyncio.run(
        run_e2e(
            cwd=args.cwd,
            model=args.model,
            out=args.out,
            prompt=args.prompt,
        )
    )


if __name__ == "__main__":
    main()
