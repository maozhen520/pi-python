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
from pi_tui import CodingApp, StreamingAssistantView, ToolDisplay, TranscriptView


def apply_agent_event(app: CodingApp, event: AgentEvent) -> None:
    """Apply one agent runtime event to the four v1 UI blocks."""
    transcript = app.query_one(TranscriptView)
    streaming = app.query_one(StreamingAssistantView)
    tools = app.query_one(ToolDisplay)

    if isinstance(event, (MessageStartEvent, MessageUpdateEvent)) and isinstance(
        event.message, AssistantMessage
    ):
        streaming.set_streaming(event.message.content or "")
        return

    if isinstance(event, MessageEndEvent):
        streaming.clear()
        message = event.message
        if isinstance(message, UserMessage):
            transcript.append_settled("user", message.content)
        elif isinstance(message, AssistantMessage):
            transcript.append_settled("assistant", message.content or "")
        elif isinstance(message, ToolResultMessage):
            transcript.append_settled("tool", message.content)
        return

    if isinstance(event, ToolExecutionStartEvent):
        tools.tool_start(event.tool_name, event.args)
        return

    if isinstance(event, ToolExecutionEndEvent):
        tools.tool_end(
            event.tool_name,
            event.result.content or "",
            is_error=event.is_error,
        )
