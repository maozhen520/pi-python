"""Console entrypoint for `piy`."""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import os
import sys
from pathlib import Path

from pi_llm.credentials import apply_credentials_to_environ, default_auth_path

from pi_coding_agent.app import (
    CodingSession,
    ask_trust_default,
    ensure_credentials_interactive,
)
from pi_coding_agent.llm_bridge import make_stream_fn
from pi_tui import CodingApp, TranscriptView


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="piy", description="Interactive coding agent")
    parser.add_argument("--cwd", type=Path, default=None, help="Project working directory")
    parser.add_argument(
        "--approve",
        action="store_true",
        help="Approve loading project .pi / .agents resources without prompting",
    )
    parser.add_argument(
        "--session",
        type=Path,
        default=None,
        help="Resume a session JSONL file",
    )
    parser.add_argument(
        "--model",
        default=os.environ.get("PIY_MODEL", "gpt-4o-mini"),
        help="LiteLLM model id",
    )
    parser.add_argument(
        "--non-interactive",
        action="store_true",
        help="Disable interactive prompts (trust/auth)",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = _parse_args(argv)
    cwd = (args.cwd or Path.cwd()).resolve()
    interactive = not args.non_interactive

    auth_path = default_auth_path()
    if interactive:
        ensure_credentials_interactive(
            required_keys=["OPENAI_API_KEY"],
            auth_path=auth_path,
            prompt_fn=lambda key: input(f"Enter value for {key} (saved to {auth_path}): "),
        )
    apply_credentials_to_environ(auth_path=auth_path)

    stream_fn = make_stream_fn(model=args.model)
    ask = ask_trust_default if interactive else None
    if args.session is not None:
        session = CodingSession.resume(
            args.session,
            cwd=cwd,
            stream_fn=stream_fn,
            interactive=interactive,
            approve_project=args.approve,
            ask_trust=ask,
        )
    else:
        session = CodingSession.create(
            cwd=cwd,
            stream_fn=stream_fn,
            interactive=interactive,
            approve_project=args.approve,
            ask_trust=ask,
        )

    try:
        asyncio.run(_run_interactive(session))
    except KeyboardInterrupt:
        print("\nInterrupted.", file=sys.stderr)
        raise SystemExit(130) from None


async def _run_interactive(session: CodingSession) -> None:
    queue: asyncio.Queue[str] = asyncio.Queue()

    def on_submit(text: str) -> None:
        queue.put_nowait(text)

    app = CodingApp(on_submit=on_submit)
    session.bind_tui(app)

    async def worker() -> None:
        while True:
            text = await queue.get()
            if text.strip() in {"/exit", "/quit"}:
                app.exit()
                return
            try:
                await session.prompt(text)
            except Exception as exc:  # noqa: BLE001 — keep TUI alive on turn errors
                app.query_one(TranscriptView).append_settled("error", str(exc))

    worker_task = asyncio.create_task(worker())
    try:
        await app.run_async()
    finally:
        worker_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await worker_task
