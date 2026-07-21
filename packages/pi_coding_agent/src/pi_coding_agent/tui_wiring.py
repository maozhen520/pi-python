"""Map agent runtime events onto pi_tui widgets (wiring lives in coding-agent)."""

from __future__ import annotations

from pi_agent import (
    AgentEvent,
    AssistantMessage,
    MessageEndEvent,
    MessageStartEvent,
    MessageUpdateEvent,
    ToolExecutionEndEvent,
    ToolExecutionStartEvent,
    ToolResultMessage,
    UserMessage,
)
from pi_tui import CodingApp, TranscriptView


def apply_agent_event(app: CodingApp, event: AgentEvent) -> None:
    """Apply one agent runtime event to the unified transcript."""
    transcript = app.query_one(TranscriptView)

    if isinstance(event, (MessageStartEvent, MessageUpdateEvent)) and isinstance(
        event.message, AssistantMessage
    ):
        transcript.set_streaming(event.message.content or "")
        return

    if isinstance(event, MessageEndEvent):
        transcript.clear_streaming()
        message = event.message
        if isinstance(message, UserMessage):
            transcript.append_settled("user", message.content)
        elif isinstance(message, AssistantMessage):
            transcript.append_settled("assistant", message.content or "")
        elif isinstance(message, ToolResultMessage):
            transcript.append_settled("tool", message.content)
        return

    if isinstance(event, ToolExecutionStartEvent):
        transcript.tool_start(event.tool_name, event.args)
        return

    if isinstance(event, ToolExecutionEndEvent):
        transcript.tool_end(
            event.tool_name,
            event.result.content or "",
            is_error=event.is_error,
        )
