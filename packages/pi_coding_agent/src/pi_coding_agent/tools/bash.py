"""Built-in `bash` tool: session cwd, optional timeout, output truncation."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from pi_agent import AgentTool, AgentToolResult
from pi_coding_agent.tools.truncate import (
    DEFAULT_MAX_BYTES,
    DEFAULT_MAX_LINES,
    format_size,
    truncate_tail,
)

BASH_PARAMETERS: dict[str, Any] = {
    "type": "object",
    "properties": {
        "command": {"type": "string", "description": "Bash command to execute"},
        "timeout": {
            "type": "number",
            "description": "Timeout in seconds (optional, no default timeout)",
        },
    },
    "required": ["command"],
}


def create_bash_tool(cwd: Path) -> AgentTool:
    async def execute(_tool_call_id: str, args: dict[str, Any], **_kwargs: Any) -> AgentToolResult:
        command = str(args["command"])
        timeout = args.get("timeout")
        if not cwd.is_dir():
            raise FileNotFoundError(
                f"Working directory does not exist: {cwd}\nCannot execute bash commands."
            )

        timeout_s: float | None = None
        if timeout is not None:
            timeout_s = float(timeout)
            if timeout_s <= 0 or timeout_s != timeout_s:  # NaN check
                raise ValueError("Invalid timeout: must be a finite number of seconds")

        try:
            proc = await asyncio.create_subprocess_shell(
                command,
                cwd=str(cwd),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
        except OSError as exc:
            raise OSError(f"Failed to start bash command: {exc.strerror or exc}") from None

        try:
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout_s)
        except TimeoutError:
            proc.kill()
            try:
                await proc.communicate()
            except Exception:
                pass
            raise TimeoutError(f"Command timed out after {timeout} seconds") from None

        text = stdout.decode("utf-8", errors="replace")
        truncation = truncate_tail(text)
        details: dict[str, Any] | None = None
        output = truncation.content or "(no output)"
        if truncation.truncated:
            details = {"truncation": truncation}
            start_line = truncation.total_lines - truncation.output_lines + 1
            end_line = truncation.total_lines
            if truncation.truncated_by == "lines":
                output += (
                    f"\n\n[Showing lines {start_line}-{end_line} of {truncation.total_lines}. "
                    "Output truncated.]"
                )
            else:
                output += (
                    f"\n\n[Showing lines {start_line}-{end_line} of {truncation.total_lines} "
                    f"({format_size(DEFAULT_MAX_BYTES)} limit). Output truncated.]"
                )

        if proc.returncode not in (0, None):
            raise RuntimeError(f"{output}\n\nCommand exited with code {proc.returncode}")

        return AgentToolResult(content=output, details=details)

    return AgentTool(
        name="bash",
        label="bash",
        description=(
            f"Execute a bash command in the current working directory. Returns stdout and stderr. "
            f"Output is truncated to last {DEFAULT_MAX_LINES} lines or "
            f"{DEFAULT_MAX_BYTES // 1024}KB (whichever is hit first). "
            "Optionally provide a timeout in seconds. No sandbox — host process permissions apply."
        ),
        parameters=BASH_PARAMETERS,
        execute=execute,
    )
