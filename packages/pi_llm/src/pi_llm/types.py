"""Public types for the thin LLM adapter."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


@dataclass(frozen=True, slots=True)
class ToolCall:
    id: str
    name: str
    arguments: str


@dataclass(frozen=True, slots=True)
class AssistantMessage:
    content: str | None
    tool_calls: list[ToolCall] = field(default_factory=list)
    role: Literal["assistant"] = "assistant"


@dataclass(frozen=True, slots=True)
class TextDelta:
    text: str


@dataclass(frozen=True, slots=True)
class ToolCallDelta:
    index: int
    id: str | None = None
    name: str | None = None
    arguments_delta: str | None = None


@dataclass(frozen=True, slots=True)
class TurnFinished:
    message: AssistantMessage
    finish_reason: str | None = None
    usage: dict[str, Any] | None = None


StreamEvent = TextDelta | ToolCallDelta | TurnFinished
