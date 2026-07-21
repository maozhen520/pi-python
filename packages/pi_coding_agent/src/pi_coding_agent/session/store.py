"""Session JSONL persistence: create / resume / list / branch / fork + compaction."""

from __future__ import annotations

import json
import re
import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pi_agent import (
    AgentMessage,
    AssistantMessage,
    CustomMessage,
    ToolCall,
    ToolResultMessage,
    UserMessage,
)

SESSION_VERSION = 1


def encode_cwd(cwd: Path) -> str:
    text = str(cwd.resolve())
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", text).strip("_")
    return safe or "root"


def estimate_tokens(text: str) -> int:
    """Approximate token count (~4 chars/token)."""
    if not text:
        return 0
    return max(1, (len(text) + 3) // 4)


def default_sessions_root() -> Path:
    return Path.home() / ".pi" / "agent" / "sessions"


@dataclass(frozen=True, slots=True)
class CompactionEntry:
    summary: str
    keep_recent_tokens: int
    instructions: str = ""
    created_at: str = ""
    type: str = "compaction"
    role: str = "compaction"


@dataclass(frozen=True, slots=True)
class SessionInfo:
    id: str
    path: Path
    cwd: str
    updated_at: str
    branch: str


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _serialize_message(message: AgentMessage, *, branch: str) -> dict[str, Any]:
    if isinstance(message, UserMessage):
        return {
            "type": "message",
            "branch": branch,
            "role": "user",
            "content": message.content,
        }
    if isinstance(message, AssistantMessage):
        payload: dict[str, Any] = {
            "type": "message",
            "branch": branch,
            "role": "assistant",
            "content": message.content,
            "stop_reason": message.stop_reason,
            "error_message": message.error_message,
            "tool_calls": [
                {
                    "id": tc.id,
                    "name": tc.name,
                    "arguments": tc.arguments,
                }
                for tc in message.tool_calls
            ],
        }
        return payload
    if isinstance(message, ToolResultMessage):
        return {
            "type": "message",
            "branch": branch,
            "role": "toolResult",
            "tool_call_id": message.tool_call_id,
            "tool_name": message.tool_name,
            "content": message.content,
            "is_error": message.is_error,
        }
    if isinstance(message, CustomMessage):
        return {
            "type": "message",
            "branch": branch,
            "role": message.role,
            "content": message.content,
            "data": message.data,
        }
    raise TypeError(f"Unsupported message type: {type(message)!r}")


def _deserialize_message(row: dict[str, Any]) -> AgentMessage:
    role = row.get("role")
    if role == "user":
        return UserMessage(content=str(row.get("content") or ""))
    if role == "assistant":
        tool_calls = [
            ToolCall(
                id=str(tc.get("id") or ""),
                name=str(tc.get("name") or ""),
                arguments=dict(tc.get("arguments") or {}),
            )
            for tc in row.get("tool_calls") or []
            if isinstance(tc, dict)
        ]
        return AssistantMessage(
            content=row.get("content"),
            tool_calls=tool_calls,
            stop_reason=row.get("stop_reason"),
            error_message=row.get("error_message"),
        )
    if role == "toolResult":
        return ToolResultMessage(
            tool_call_id=str(row.get("tool_call_id") or ""),
            tool_name=str(row.get("tool_name") or ""),
            content=str(row.get("content") or ""),
            is_error=bool(row.get("is_error")),
        )
    return CustomMessage(
        role=str(role or "custom"),
        content=row.get("content"),
        data=dict(row.get("data") or {}),
    )


def _message_tokens(message: AgentMessage) -> int:
    if isinstance(message, (UserMessage, ToolResultMessage)):
        return estimate_tokens(message.content)
    if isinstance(message, AssistantMessage):
        parts = [message.content or ""]
        for tc in message.tool_calls:
            parts.append(tc.name)
            parts.append(json.dumps(tc.arguments, sort_keys=True))
        return estimate_tokens(" ".join(parts))
    if isinstance(message, CustomMessage):
        return estimate_tokens(str(message.content))
    return 0


def apply_compaction_view(
    messages: Sequence[AgentMessage],
    compaction: CompactionEntry,
) -> list[AgentMessage]:
    """Model-facing view: summary + recent tail by keep_recent_tokens."""
    keep: list[AgentMessage] = []
    budget = compaction.keep_recent_tokens
    used = 0
    for message in reversed(list(messages)):
        cost = _message_tokens(message)
        if keep and used + cost > budget:
            break
        keep.append(message)
        used += cost
    keep.reverse()
    summary = UserMessage(content=compaction.summary)
    return [summary, *keep]


@dataclass
class Session:
    """Owns JSONL file + branch pointer; expose messages for Agent to copy/load."""

    path: Path
    id: str
    cwd: str
    branch: str = "main"
    _messages: list[AgentMessage] = field(default_factory=list)
    _compactions: list[CompactionEntry] = field(default_factory=list)
    _branches: dict[str, int] = field(default_factory=lambda: {"main": 0})

    @property
    def messages(self) -> list[AgentMessage]:
        return list(self._messages)

    def entries(self) -> list[Any]:
        return [*self._messages, *self._compactions]

    def append_message(self, message: AgentMessage) -> None:
        self._messages.append(message)
        self._append_json(_serialize_message(message, branch=self.branch))

    def create_branch(self, name: str) -> Session:
        if name in self._branches:
            raise ValueError(f"Branch already exists: {name}")
        self._branches[name] = len(self._messages)
        self._append_json(
            {
                "type": "branch",
                "name": name,
                "from": self.branch,
                "at": len(self._messages),
                "created_at": _now(),
            }
        )
        child = Session(
            path=self.path,
            id=self.id,
            cwd=self.cwd,
            branch=name,
            _messages=list(self._messages),
            _compactions=list(self._compactions),
            _branches=dict(self._branches),
        )
        child._set_branch_pointer(name)
        return child

    def fork(self) -> Session:
        new_id = uuid.uuid4().hex[:12]
        new_path = self.path.with_name(f"{new_id}.jsonl")
        header = {
            "type": "header",
            "version": SESSION_VERSION,
            "id": new_id,
            "cwd": self.cwd,
            "branch": self.branch,
            "created_at": _now(),
            "forked_from": self.id,
        }
        lines = [json.dumps(header, ensure_ascii=False)]
        for message in self._messages:
            lines.append(
                json.dumps(
                    _serialize_message(message, branch=self.branch),
                    ensure_ascii=False,
                )
            )
        for compaction in self._compactions:
            lines.append(
                json.dumps(
                    {
                        "type": "compaction",
                        "branch": self.branch,
                        "summary": compaction.summary,
                        "keep_recent_tokens": compaction.keep_recent_tokens,
                        "instructions": compaction.instructions,
                        "created_at": compaction.created_at or _now(),
                    },
                    ensure_ascii=False,
                )
            )
        new_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return Session.load(new_path)

    def compact(
        self,
        *,
        summary: str,
        keep_recent_tokens: int,
        instructions: str = "",
    ) -> CompactionEntry:
        entry = CompactionEntry(
            summary=summary,
            keep_recent_tokens=keep_recent_tokens,
            instructions=instructions,
            created_at=_now(),
        )
        self._compactions.append(entry)
        self._append_json(
            {
                "type": "compaction",
                "branch": self.branch,
                "summary": entry.summary,
                "keep_recent_tokens": entry.keep_recent_tokens,
                "instructions": entry.instructions,
                "created_at": entry.created_at,
            }
        )
        return entry

    def maybe_auto_compact(
        self,
        *,
        context_window: int,
        reserve_tokens: int,
        keep_recent_tokens: int,
        summarize: Callable[[Sequence[AgentMessage], str], str],
        instructions: str = "",
    ) -> bool:
        total = sum(_message_tokens(m) for m in self._messages)
        if total <= context_window - reserve_tokens:
            return False
        summary = summarize(self._messages, instructions)
        self.compact(
            summary=summary,
            keep_recent_tokens=keep_recent_tokens,
            instructions=instructions,
        )
        return True

    def model_messages(self) -> list[AgentMessage]:
        if not self._compactions:
            return self.messages
        return apply_compaction_view(self._messages, self._compactions[-1])

    def _set_branch_pointer(self, branch: str) -> None:
        self.branch = branch
        self._append_json({"type": "pointer", "branch": branch, "at": _now()})

    def _append_json(self, row: dict[str, Any]) -> None:
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")

    @classmethod
    def load(cls, path: Path) -> Session:
        lines = path.read_text(encoding="utf-8").splitlines()
        if not lines:
            raise ValueError(f"Empty session file: {path}")
        header = json.loads(lines[0])
        if header.get("type") != "header":
            raise ValueError(f"Missing session header in {path}")

        rows = [json.loads(line) for line in lines[1:] if line.strip()]
        branches = {"main": 0}
        active = str(header.get("branch") or "main")
        compactions: list[CompactionEntry] = []
        for row in rows:
            row_type = row.get("type")
            if row_type == "branch":
                branches[str(row["name"])] = int(row.get("at") or 0)
            elif row_type == "pointer":
                active = str(row.get("branch") or active)
            elif row_type == "compaction":
                if row.get("branch", "main") in {active, "main"}:
                    compactions.append(
                        CompactionEntry(
                            summary=str(row.get("summary") or ""),
                            keep_recent_tokens=int(row.get("keep_recent_tokens") or 0),
                            instructions=str(row.get("instructions") or ""),
                            created_at=str(row.get("created_at") or ""),
                        )
                    )

        fork_at = branches.get(active, 0) if active != "main" else None
        main_count = 0
        messages: list[AgentMessage] = []
        for row in rows:
            if row.get("type") != "message":
                continue
            label = row.get("branch", "main")
            if active == "main":
                if label == "main":
                    messages.append(_deserialize_message(row))
                continue
            if label == "main":
                if main_count < (fork_at or 0):
                    messages.append(_deserialize_message(row))
                    main_count += 1
            elif label == active:
                messages.append(_deserialize_message(row))

        return cls(
            path=path,
            id=str(header["id"]),
            cwd=str(header.get("cwd") or ""),
            branch=active,
            _messages=messages,
            _compactions=compactions,
            _branches=branches,
        )


@dataclass(slots=True)
class SessionStore:
    root: Path

    def __post_init__(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)

    def _cwd_dir(self, cwd: Path) -> Path:
        path = self.root / encode_cwd(cwd)
        path.mkdir(parents=True, exist_ok=True)
        return path

    def create(self, *, cwd: Path) -> Session:
        session_id = uuid.uuid4().hex[:12]
        path = self._cwd_dir(cwd) / f"{session_id}.jsonl"
        header = {
            "type": "header",
            "version": SESSION_VERSION,
            "id": session_id,
            "cwd": str(cwd.resolve()),
            "branch": "main",
            "created_at": _now(),
        }
        path.write_text(json.dumps(header, ensure_ascii=False) + "\n", encoding="utf-8")
        return Session(path=path, id=session_id, cwd=str(cwd.resolve()), branch="main")

    def resume(self, path: Path) -> Session:
        return Session.load(path)

    def list_sessions(self, *, cwd: Path) -> list[SessionInfo]:
        directory = self._cwd_dir(cwd)
        items: list[SessionInfo] = []
        for path in sorted(directory.glob("*.jsonl")):
            try:
                session = Session.load(path)
            except (OSError, ValueError, json.JSONDecodeError, KeyError):
                continue
            items.append(
                SessionInfo(
                    id=session.id,
                    path=path,
                    cwd=session.cwd,
                    updated_at=_now(),
                    branch=session.branch,
                )
            )
        return items
