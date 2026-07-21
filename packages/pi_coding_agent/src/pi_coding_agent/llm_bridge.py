"""Bridge `pi_llm.stream` into `pi_agent` StreamFn events."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Sequence
from typing import Any

from pi_agent import (
    AgentTool,
    AssistantMessage,
    AssistantStreamDone,
    AssistantStreamError,
    AssistantStreamEvent,
    AssistantStreamStart,
    AssistantStreamTextDelta,
    AssistantStreamToolCallDelta,
    LlmMessage,
    StreamRequest,
    ToolCall,
    ToolResultMessage,
    UserMessage,
)
from pi_llm import TextDelta, ToolCallDelta, TurnFinished
from pi_llm import stream as litellm_stream


def _tool_to_openai(tool: AgentTool) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": tool.name,
            "description": tool.description or "",
            "parameters": tool.parameters or {"type": "object", "properties": {}},
        },
    }


def _messages_to_openai(messages: Sequence[LlmMessage]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for message in messages:
        if isinstance(message, UserMessage):
            out.append({"role": "user", "content": message.content})
        elif isinstance(message, AssistantMessage):
            row: dict[str, Any] = {"role": "assistant", "content": message.content}
            if message.tool_calls:
                row["tool_calls"] = [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.name,
                            "arguments": json.dumps(tc.arguments),
                        },
                    }
                    for tc in message.tool_calls
                ]
            out.append(row)
        elif isinstance(message, ToolResultMessage):
            out.append(
                {
                    "role": "tool",
                    "tool_call_id": message.tool_call_id,
                    "content": message.content,
                }
            )
    return out


def make_stream_fn(*, model: str) -> Any:
    async def stream_fn(request: StreamRequest) -> AsyncIterator[AssistantStreamEvent]:
        openai_messages = _messages_to_openai(request.messages)
        kwargs: dict[str, Any] = {
            "model": model,
            "messages": openai_messages,
            "stream": True,
        }
        if request.system_prompt:
            kwargs["messages"] = [
                {"role": "system", "content": request.system_prompt},
                *openai_messages,
            ]
        if request.tools:
            kwargs["tools"] = [_tool_to_openai(t) for t in request.tools]
            kwargs["tool_choice"] = "auto"

        partial = AssistantMessage(content="")
        yield AssistantStreamStart(partial=partial)

        try:
            async for event in litellm_stream(kwargs):
                if isinstance(event, TextDelta):
                    content = (partial.content or "") + event.text
                    partial = AssistantMessage(
                        content=content,
                        tool_calls=list(partial.tool_calls),
                    )
                    yield AssistantStreamTextDelta(partial=partial, delta=event.text)
                elif isinstance(event, ToolCallDelta):
                    yield AssistantStreamToolCallDelta(
                        partial=partial,
                        tool_call_id=event.id or "",
                        name=event.name,
                        arguments_delta=event.arguments_delta,
                    )
                elif isinstance(event, TurnFinished):
                    tool_calls: list[ToolCall] = []
                    for tc in event.message.tool_calls:
                        try:
                            args = json.loads(tc.arguments) if tc.arguments else {}
                        except json.JSONDecodeError:
                            args = {"_raw": tc.arguments}
                        if not isinstance(args, dict):
                            args = {"_raw": args}
                        tool_calls.append(ToolCall(id=tc.id, name=tc.name, arguments=args))
                    stop = "toolUse" if tool_calls else "stop"
                    if event.finish_reason == "length":
                        stop = "length"
                    done = AssistantMessage(
                        content=event.message.content,
                        tool_calls=tool_calls,
                        stop_reason=stop,  # type: ignore[arg-type]
                    )
                    yield AssistantStreamDone(message=done)
                    return
        except Exception as exc:
            err = AssistantMessage(
                content=None,
                stop_reason="error",
                error_message=str(exc),
            )
            yield AssistantStreamError(message=err)

    return stream_fn
