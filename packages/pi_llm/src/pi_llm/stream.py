"""Async stream over one chat-completion turn via LiteLLM `acompletion`."""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from typing import Any

from pi_llm.errors import map_provider_error
from pi_llm.types import (
    AssistantMessage,
    StreamEvent,
    TextDelta,
    ToolCall,
    ToolCallDelta,
    TurnFinished,
)

ACompletion = Callable[..., Awaitable[Any]]


async def stream(
    request: Mapping[str, Any],
    *,
    acompletion: ACompletion | None = None,
) -> AsyncIterator[StreamEvent]:
    """Stream one turn: text/tool deltas for UI, then a fully assembled message.

    Tool calls are never considered ready for execution until `TurnFinished`.
    """
    call = acompletion or _default_acompletion
    kwargs = dict(request)
    kwargs.setdefault("stream", True)

    try:
        response = await call(**kwargs)
    except Exception as exc:
        raise map_provider_error(exc) from exc

    content_parts: list[str] = []
    tool_parts: dict[int, dict[str, str]] = {}
    finish_reason: str | None = None
    usage: dict[str, Any] | None = None

    try:
        async for chunk in response:
            if getattr(chunk, "usage", None) is not None:
                usage = _usage_as_dict(chunk.usage)

            choices = getattr(chunk, "choices", None) or []
            if not choices:
                continue
            choice = choices[0]
            reason = getattr(choice, "finish_reason", None)
            if reason is not None:
                finish_reason = reason

            delta = getattr(choice, "delta", None)
            if delta is None:
                continue

            text = getattr(delta, "content", None)
            if text:
                content_parts.append(text)
                yield TextDelta(text)

            tool_calls = getattr(delta, "tool_calls", None) or []
            for tc in tool_calls:
                index = int(getattr(tc, "index", 0))
                bucket = tool_parts.setdefault(index, {"id": "", "name": "", "arguments": ""})
                tc_id = getattr(tc, "id", None)
                if tc_id:
                    bucket["id"] = str(tc_id)
                fn = getattr(tc, "function", None)
                name = getattr(fn, "name", None) if fn is not None else None
                args = getattr(fn, "arguments", None) if fn is not None else None
                # Name usually arrives once; arguments stream as fragments.
                if name and not bucket["name"]:
                    bucket["name"] = str(name)
                if args:
                    bucket["arguments"] += str(args)
                yield ToolCallDelta(
                    index=index,
                    id=str(tc_id) if tc_id else None,
                    name=str(name) if name else None,
                    arguments_delta=str(args) if args else None,
                )
    except Exception as exc:
        raise map_provider_error(exc) from exc

    message = AssistantMessage(
        content="".join(content_parts) or None,
        tool_calls=[
            ToolCall(
                id=tool_parts[i]["id"] or f"call_{i}",
                name=tool_parts[i]["name"],
                arguments=tool_parts[i]["arguments"],
            )
            for i in sorted(tool_parts)
        ],
    )
    yield TurnFinished(message=message, finish_reason=finish_reason, usage=usage)


async def _default_acompletion(**kwargs: Any) -> Any:
    from litellm import acompletion as litellm_acompletion

    from pi_llm.credentials import apply_credentials_to_environ

    apply_credentials_to_environ()
    return await litellm_acompletion(**kwargs)


def _usage_as_dict(usage: Any) -> dict[str, Any]:
    if isinstance(usage, Mapping):
        return dict(usage)
    return {
        key: getattr(usage, key)
        for key in ("prompt_tokens", "completion_tokens", "total_tokens")
        if getattr(usage, key, None) is not None
    }
