"""Built-in `edit` tool: exact multi-replace with optional replace_all."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pi_agent import AgentTool, AgentToolResult
from pi_coding_agent.tools.file_mutation_queue import with_file_mutation_queue
from pi_coding_agent.tools.path_utils import resolve_to_cwd

EDIT_PARAMETERS: dict[str, Any] = {
    "type": "object",
    "properties": {
        "path": {
            "type": "string",
            "description": "Path to the file to edit (relative or absolute)",
        },
        "edits": {
            "type": "array",
            "description": (
                "One or more targeted replacements matched against the original file "
                "(not incrementally). Do not include overlapping edits."
            ),
            "items": {
                "type": "object",
                "properties": {
                    "oldText": {"type": "string"},
                    "newText": {"type": "string"},
                    "replace_all": {
                        "type": "boolean",
                        "description": "Replace every occurrence of oldText (default false)",
                    },
                },
                "required": ["oldText", "newText"],
            },
        },
    },
    "required": ["path", "edits"],
}


@dataclass(frozen=True, slots=True)
class _Edit:
    old_text: str
    new_text: str
    replace_all: bool


@dataclass(frozen=True, slots=True)
class _Match:
    edit_index: int
    start: int
    end: int
    new_text: str


def _normalize_to_lf(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")


def _detect_line_ending(content: str) -> str:
    crlf = content.find("\r\n")
    lf = content.find("\n")
    if lf == -1:
        return "\n"
    if crlf == -1:
        return "\n"
    return "\r\n" if crlf < lf else "\n"


def _restore_line_endings(text: str, ending: str) -> str:
    if ending == "\r\n":
        return text.replace("\n", "\r\n")
    return text


def _strip_bom(content: str) -> tuple[str, str]:
    if content.startswith("\ufeff"):
        return "\ufeff", content[1:]
    return "", content


def prepare_edit_arguments(args: dict[str, Any]) -> dict[str, Any]:
    prepared = dict(args)
    edits = prepared.get("edits")
    if isinstance(edits, str):
        import json

        try:
            parsed = json.loads(edits)
        except json.JSONDecodeError:
            parsed = None
        if isinstance(parsed, list):
            prepared["edits"] = parsed
    if isinstance(prepared.get("oldText"), str) and isinstance(prepared.get("newText"), str):
        existing = list(prepared.get("edits") or [])
        if not isinstance(existing, list):
            existing = []
        existing.append({"oldText": prepared.pop("oldText"), "newText": prepared.pop("newText")})
        prepared["edits"] = existing
    return prepared


def apply_edits(content: str, edits: list[_Edit], path: str) -> str:
    """Apply exact multi-replace against the original (LF-normalized) file content."""
    base = _normalize_to_lf(content)
    if not edits:
        raise ValueError("Edit tool input is invalid. edits must contain at least one replacement.")

    matches: list[_Match] = []
    for i, edit in enumerate(edits):
        if not edit.old_text:
            raise ValueError(
                f"edits[{i}].oldText must not be empty in {path}."
                if len(edits) > 1
                else f"oldText must not be empty in {path}."
            )
        occurrences = base.count(edit.old_text)
        if occurrences == 0:
            raise ValueError(
                f"Could not find the exact text in {path}. The old text must match exactly "
                "including all whitespace and newlines."
                if len(edits) == 1
                else (
                    f"Could not find edits[{i}] in {path}. "
                    "The oldText must match exactly including all whitespace and newlines."
                )
            )
        if edit.replace_all:
            start = 0
            while True:
                idx = base.find(edit.old_text, start)
                if idx == -1:
                    break
                matches.append(
                    _Match(
                        edit_index=i,
                        start=idx,
                        end=idx + len(edit.old_text),
                        new_text=edit.new_text,
                    )
                )
                start = idx + len(edit.old_text)
        else:
            if occurrences > 1:
                raise ValueError(
                    f"Found {occurrences} occurrences of the text in {path}. The text must be "
                    "unique. Please provide more context to make it unique, or set replace_all."
                    if len(edits) == 1
                    else (
                        f"Found {occurrences} occurrences of edits[{i}] in {path}. "
                        "Each oldText must be unique unless replace_all is true."
                    )
                )
            idx = base.find(edit.old_text)
            matches.append(
                _Match(
                    edit_index=i,
                    start=idx,
                    end=idx + len(edit.old_text),
                    new_text=edit.new_text,
                )
            )

    matches.sort(key=lambda m: m.start)
    for prev, cur in zip(matches, matches[1:], strict=False):
        if prev.end > cur.start:
            raise ValueError(
                f"edits[{prev.edit_index}] and edits[{cur.edit_index}] overlap in {path}. "
                "Merge them into one edit or target disjoint regions."
            )

    result = base
    for match in reversed(matches):
        result = result[: match.start] + match.new_text + result[match.end :]

    if result == base:
        raise ValueError(f"No changes made to {path}. The replacements produced identical content.")
    return result


def create_edit_tool(cwd: Path) -> AgentTool:
    async def execute(_tool_call_id: str, args: dict[str, Any], **_kwargs: Any) -> AgentToolResult:
        path = str(args["path"])
        raw_edits = args.get("edits")
        if not isinstance(raw_edits, list) or not raw_edits:
            raise ValueError(
                "Edit tool input is invalid. edits must contain at least one replacement."
            )

        edits = [
            _Edit(
                old_text=_normalize_to_lf(str(item["oldText"])),
                new_text=_normalize_to_lf(str(item["newText"])),
                replace_all=bool(item.get("replace_all", False)),
            )
            for item in raw_edits
        ]
        absolute = resolve_to_cwd(path, cwd)

        async def mutate() -> AgentToolResult:
            try:
                raw = absolute.read_text(encoding="utf-8")
            except FileNotFoundError:
                raise FileNotFoundError(f"Could not edit file: {path}. File not found.") from None
            except OSError as exc:
                raise OSError(f"Could not edit file: {path}. {exc.strerror or exc}") from None

            bom, text = _strip_bom(raw)
            ending = _detect_line_ending(text)
            new_content = apply_edits(text, edits, path)
            final = bom + _restore_line_endings(new_content, ending)
            try:
                absolute.write_text(final, encoding="utf-8")
            except OSError as exc:
                raise OSError(
                    f"Could not write edited file: {path}. {exc.strerror or exc}"
                ) from None

            return AgentToolResult(
                content=f"Successfully replaced {len(edits)} block(s) in {path}.",
                details={"edits": len(edits)},
            )

        return await with_file_mutation_queue(absolute, mutate)

    return AgentTool(
        name="edit",
        label="edit",
        description=(
            "Edit a single file using exact text replacement. Prefer reading the file with `read` "
            "before editing so oldText matches current contents (soft guidance, not a hard lock). "
            "Every edits[].oldText must match a unique, non-overlapping region of the "
            "original file unless replace_all is true. If two changes affect the same block "
            "or nearby lines, merge "
            "them into one edit instead of emitting overlapping edits."
        ),
        parameters=EDIT_PARAMETERS,
        prepare_arguments=prepare_edit_arguments,
        execute=execute,
    )
