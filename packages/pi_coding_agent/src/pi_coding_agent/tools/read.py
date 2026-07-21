"""Built-in `read` tool: line windowing + truncation."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pi_agent import AgentTool, AgentToolResult
from pi_coding_agent.tools.path_utils import resolve_to_cwd
from pi_coding_agent.tools.truncate import (
    DEFAULT_MAX_BYTES,
    DEFAULT_MAX_LINES,
    format_size,
    truncate_head,
)

READ_PARAMETERS: dict[str, Any] = {
    "type": "object",
    "properties": {
        "path": {
            "type": "string",
            "description": "Path to the file to read (relative or absolute)",
        },
        "offset": {
            "type": "number",
            "description": "Line number to start reading from (1-indexed)",
        },
        "limit": {"type": "number", "description": "Maximum number of lines to read"},
    },
    "required": ["path"],
}


def create_read_tool(cwd: Path) -> AgentTool:
    async def execute(_tool_call_id: str, args: dict[str, Any], **_kwargs: Any) -> AgentToolResult:
        path = str(args["path"])
        offset = args.get("offset")
        limit = args.get("limit")
        absolute = resolve_to_cwd(path, cwd)
        try:
            text = absolute.read_text(encoding="utf-8")
        except FileNotFoundError:
            raise FileNotFoundError(f"Could not read file: {path}. File not found.") from None
        except IsADirectoryError:
            raise IsADirectoryError(f"Could not read file: {path}. Path is a directory.") from None
        except OSError as exc:
            raise OSError(f"Could not read file: {path}. {exc.strerror or exc}") from None

        all_lines = text.split("\n")
        total_file_lines = len(all_lines)
        start_line = max(0, int(offset) - 1) if offset is not None else 0
        start_display = start_line + 1
        if start_line >= total_file_lines:
            raise ValueError(
                f"Offset {offset} is beyond end of file ({total_file_lines} lines total)"
            )

        user_limited_lines: int | None = None
        if limit is not None:
            end_line = min(start_line + int(limit), total_file_lines)
            selected = "\n".join(all_lines[start_line:end_line])
            user_limited_lines = end_line - start_line
        else:
            selected = "\n".join(all_lines[start_line:])

        truncation = truncate_head(selected)
        details = {"truncation": truncation}

        if truncation.first_line_exceeds_limit:
            first_size = format_size(len(all_lines[start_line].encode("utf-8")))
            output = (
                f"[Line {start_display} is {first_size}, exceeds "
                f"{format_size(DEFAULT_MAX_BYTES)} limit. Use bash: "
                f"sed -n '{start_display}p' {path} | head -c {DEFAULT_MAX_BYTES}]"
            )
            return AgentToolResult(content=output, details=details)

        if truncation.truncated:
            end_display = start_display + truncation.output_lines - 1
            next_offset = end_display + 1
            output = truncation.content
            if truncation.truncated_by == "lines":
                output += (
                    f"\n\n[Showing lines {start_display}-{end_display} of "
                    f"{total_file_lines}. Use offset={next_offset} to continue.]"
                )
            else:
                output += (
                    f"\n\n[Showing lines {start_display}-{end_display} of "
                    f"{total_file_lines} ({format_size(DEFAULT_MAX_BYTES)} limit). "
                    f"Use offset={next_offset} to continue.]"
                )
            return AgentToolResult(content=output, details=details)

        if user_limited_lines is not None and start_line + user_limited_lines < total_file_lines:
            remaining = total_file_lines - (start_line + user_limited_lines)
            next_offset = start_line + user_limited_lines + 1
            output = (
                f"{truncation.content}\n\n"
                f"[{remaining} more lines in file. Use offset={next_offset} to continue.]"
            )
            return AgentToolResult(content=output, details=details)

        return AgentToolResult(content=truncation.content, details=details)

    return AgentTool(
        name="read",
        label="read",
        description=(
            f"Read the contents of a file. For text files, output is truncated to "
            f"{DEFAULT_MAX_LINES} lines or {DEFAULT_MAX_BYTES // 1024}KB (whichever is hit first). "
            "Use offset/limit for large files. When you need the full file, continue with offset "
            "until complete."
        ),
        parameters=READ_PARAMETERS,
        execute=execute,
    )
