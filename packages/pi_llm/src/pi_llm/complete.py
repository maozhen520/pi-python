"""Non-stream completion turn via LiteLLM `acompletion`."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from pi_llm.errors import map_provider_error
from pi_llm.stream import ACompletion, _default_acompletion
from pi_llm.types import AssistantMessage, ToolCall, TurnFinished


async def complete(
    request: Mapping[str, Any],
    *,
    acompletion: ACompletion | None = None,
) -> TurnFinished:
    """One non-stream chat-completion turn (modern `tools` / `tool_choice` ok)."""
    call = acompletion or _default_acompletion
    kwargs = dict(request)
    kwargs["stream"] = False

    try:
        response = await call(**kwargs)
    except Exception as exc:
        raise map_provider_error(exc) from exc

    choices = getattr(response, "choices", None) or []
    if not choices:
        return TurnFinished(message=AssistantMessage(content=None), finish_reason=None)

    choice = choices[0]
    message = getattr(choice, "message", None)
    content = getattr(message, "content", None) if message is not None else None
    raw_tools = getattr(message, "tool_calls", None) if message is not None else None

    tool_calls: list[ToolCall] = []
    for i, tc in enumerate(raw_tools or []):
        fn = getattr(tc, "function", None)
        tool_calls.append(
            ToolCall(
                id=str(getattr(tc, "id", None) or f"call_{i}"),
                name=str(getattr(fn, "name", "") if fn is not None else ""),
                arguments=str(getattr(fn, "arguments", "") if fn is not None else ""),
            )
        )

    usage = getattr(response, "usage", None)
    usage_dict: dict[str, Any] | None = None
    if isinstance(usage, Mapping):
        usage_dict = dict(usage)
    elif usage is not None:
        usage_dict = {
            key: getattr(usage, key)
            for key in ("prompt_tokens", "completion_tokens", "total_tokens")
            if getattr(usage, key, None) is not None
        }

    return TurnFinished(
        message=AssistantMessage(content=content, tool_calls=tool_calls),
        finish_reason=getattr(choice, "finish_reason", None),
        usage=usage_dict,
    )
