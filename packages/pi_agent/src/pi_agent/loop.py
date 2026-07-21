"""Pure agent loop: events, LLM stream boundary, tool execution."""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from dataclasses import dataclass
from typing import Any, TypeVar, cast

from pi_agent.types import (
    AfterToolCallContext,
    AgentContext,
    AgentEndEvent,
    AgentEvent,
    AgentLoopConfig,
    AgentMessage,
    AgentStartEvent,
    AgentTool,
    AgentToolResult,
    AssistantMessage,
    AssistantStreamDone,
    AssistantStreamError,
    AssistantStreamEvent,
    AssistantStreamStart,
    AssistantStreamTextDelta,
    AssistantStreamToolCallDelta,
    BeforeToolCallContext,
    MessageEndEvent,
    MessageStartEvent,
    MessageUpdateEvent,
    StreamFn,
    StreamRequest,
    ToolCall,
    ToolExecutionEndEvent,
    ToolExecutionStartEvent,
    ToolExecutionUpdateEvent,
    ToolResultMessage,
    TurnEndEvent,
    TurnStartEvent,
    UserMessage,
)

T = TypeVar("T")
Emit = Callable[[AgentEvent], Awaitable[None] | None]


@dataclass(slots=True)
class _ToolBatch:
    messages: list[ToolResultMessage]
    terminate: bool


@dataclass(slots=True)
class _FinalizedToolCall:
    tool_call: ToolCall
    result: AgentToolResult
    is_error: bool


@dataclass(slots=True)
class _PreparedToolCall:
    tool_call: ToolCall
    tool: AgentTool
    args: dict[str, Any]


@dataclass(slots=True)
class _ImmediateToolCall:
    result: AgentToolResult
    is_error: bool


@dataclass(slots=True)
class _ExecutedToolCall:
    result: AgentToolResult
    is_error: bool


async def _maybe_await(value: T | Awaitable[T]) -> T:
    if inspect.isawaitable(value):
        return cast(T, await value)
    return cast(T, value)


async def agent_loop(
    prompts: Sequence[AgentMessage],
    context: AgentContext,
    config: AgentLoopConfig,
    stream_fn: StreamFn,
) -> AsyncIterator[AgentEvent]:
    """Observational async iterator over one prompt run (does not await external subscribers)."""
    queue: asyncio.Queue[AgentEvent | None] = asyncio.Queue()

    async def emit(event: AgentEvent) -> None:
        await queue.put(event)

    async def runner() -> None:
        try:
            await run_agent_loop(list(prompts), context, config, emit, stream_fn)
        finally:
            await queue.put(None)

    task = asyncio.create_task(runner())
    try:
        while True:
            item = await queue.get()
            if item is None:
                break
            yield item
    finally:
        await task


async def agent_loop_continue(
    context: AgentContext,
    config: AgentLoopConfig,
    stream_fn: StreamFn,
) -> AsyncIterator[AgentEvent]:
    """Continue from existing context without appending a new prompt message."""
    queue: asyncio.Queue[AgentEvent | None] = asyncio.Queue()

    async def emit(event: AgentEvent) -> None:
        await queue.put(event)

    async def runner() -> None:
        try:
            await run_agent_loop_continue(context, config, emit, stream_fn)
        finally:
            await queue.put(None)

    task = asyncio.create_task(runner())
    try:
        while True:
            item = await queue.get()
            if item is None:
                break
            yield item
    finally:
        await task


async def run_agent_loop(
    prompts: list[AgentMessage],
    context: AgentContext,
    config: AgentLoopConfig,
    emit: Emit,
    stream_fn: StreamFn,
) -> list[AgentMessage]:
    new_messages: list[AgentMessage] = list(prompts)
    current = AgentContext(
        system_prompt=context.system_prompt,
        messages=[*context.messages, *prompts],
        tools=list(context.tools),
    )

    await _emit(emit, AgentStartEvent())
    await _emit(emit, TurnStartEvent())
    for prompt in prompts:
        await _emit(emit, MessageStartEvent(message=prompt))
        await _emit(emit, MessageEndEvent(message=prompt))

    await _run_loop(current, new_messages, config, emit, stream_fn)
    return new_messages


async def run_agent_loop_continue(
    context: AgentContext,
    config: AgentLoopConfig,
    emit: Emit,
    stream_fn: StreamFn,
) -> list[AgentMessage]:
    if not context.messages:
        raise ValueError("Cannot continue: no messages in context")
    if context.messages[-1].role == "assistant":
        raise ValueError("Cannot continue from message role: assistant")

    new_messages: list[AgentMessage] = []
    current = AgentContext(
        system_prompt=context.system_prompt,
        messages=list(context.messages),
        tools=list(context.tools),
    )

    await _emit(emit, AgentStartEvent())
    await _emit(emit, TurnStartEvent())
    await _run_loop(current, new_messages, config, emit, stream_fn)
    return new_messages


async def _emit(emit: Emit, event: AgentEvent) -> None:
    result = emit(event)
    if inspect.isawaitable(result):
        await result


async def _run_loop(
    current_context: AgentContext,
    new_messages: list[AgentMessage],
    config: AgentLoopConfig,
    emit: Emit,
    stream_fn: StreamFn,
) -> None:
    first_turn = True
    pending = await _poll_messages(config.get_steering_messages)

    while True:
        has_more_tool_calls = True
        while has_more_tool_calls or pending:
            if not first_turn:
                await _emit(emit, TurnStartEvent())
            else:
                first_turn = False

            if pending:
                for message in pending:
                    await _emit(emit, MessageStartEvent(message=message))
                    await _emit(emit, MessageEndEvent(message=message))
                    current_context.messages.append(message)
                    new_messages.append(message)
                pending = []

            message = await _stream_assistant_response(current_context, config, emit, stream_fn)
            new_messages.append(message)

            if message.stop_reason in ("error", "aborted"):
                await _emit(emit, TurnEndEvent(message=message, tool_results=[]))
                await _emit(emit, AgentEndEvent(messages=list(new_messages)))
                return

            tool_results: list[ToolResultMessage] = []
            has_more_tool_calls = False
            if message.tool_calls:
                if message.stop_reason == "length":
                    batch = await _fail_truncated_tool_calls(message.tool_calls, emit)
                else:
                    batch = await _execute_tool_calls(current_context, message, config, emit)
                tool_results = batch.messages
                has_more_tool_calls = not batch.terminate
                for result in tool_results:
                    current_context.messages.append(result)
                    new_messages.append(result)

            await _emit(emit, TurnEndEvent(message=message, tool_results=tool_results))

            if config.should_stop_after_turn and await _maybe_await(
                config.should_stop_after_turn(
                    message=message,
                    tool_results=tool_results,
                    context=current_context,
                    new_messages=new_messages,
                )
            ):
                await _emit(emit, AgentEndEvent(messages=list(new_messages)))
                return

            pending = await _poll_messages(config.get_steering_messages)

        follow_ups = await _poll_messages(config.get_follow_up_messages)
        if follow_ups:
            pending = follow_ups
            continue
        break

    await _emit(emit, AgentEndEvent(messages=list(new_messages)))


async def _poll_messages(
    getter: Callable[[], Awaitable[list[AgentMessage]] | list[AgentMessage]] | None,
) -> list[AgentMessage]:
    if getter is None:
        return []
    return list(await _maybe_await(getter()))


async def _stream_assistant_response(
    context: AgentContext,
    config: AgentLoopConfig,
    emit: Emit,
    stream_fn: StreamFn,
) -> AssistantMessage:
    messages: Sequence[AgentMessage] = context.messages
    if config.transform_context:
        try:
            messages = await _maybe_await(config.transform_context(messages))
        except Exception:
            messages = context.messages

    try:
        llm_messages = list(await _maybe_await(config.convert_to_llm(messages)))
    except Exception:
        llm_messages = [
            m for m in messages if isinstance(m, (UserMessage, AssistantMessage, ToolResultMessage))
        ]
    request = StreamRequest(
        system_prompt=context.system_prompt,
        messages=llm_messages,
        tools=list(context.tools),
    )

    stream_result = stream_fn(request)
    if inspect.isawaitable(stream_result):
        stream = await cast(Awaitable[AsyncIterator[AssistantStreamEvent]], stream_result)
    else:
        stream = cast(AsyncIterator[AssistantStreamEvent], stream_result)

    partial: AssistantMessage | None = None
    added_partial = False

    async for event in stream:
        if isinstance(event, AssistantStreamStart):
            partial = event.partial
            context.messages.append(partial)
            added_partial = True
            await _emit(emit, MessageStartEvent(message=partial))
        elif isinstance(event, (AssistantStreamTextDelta, AssistantStreamToolCallDelta)):
            if partial is not None:
                partial = event.partial
                context.messages[-1] = partial
                await _emit(
                    emit,
                    MessageUpdateEvent(message=partial, assistant_message_event=event),
                )
        elif isinstance(event, (AssistantStreamDone, AssistantStreamError)):
            final = event.message
            if added_partial:
                context.messages[-1] = final
            else:
                context.messages.append(final)
                await _emit(emit, MessageStartEvent(message=final))
            await _emit(emit, MessageEndEvent(message=final))
            return final

    raise RuntimeError("StreamFn ended without AssistantStreamDone/Error")


async def _fail_truncated_tool_calls(
    tool_calls: list[ToolCall],
    emit: Emit,
) -> _ToolBatch:
    messages: list[ToolResultMessage] = []
    for tool_call in tool_calls:
        await _emit(
            emit,
            ToolExecutionStartEvent(
                tool_call_id=tool_call.id,
                tool_name=tool_call.name,
                args=tool_call.arguments,
            ),
        )
        result = AgentToolResult(
            content=(
                f'Tool call "{tool_call.name}" was not executed: the response hit the output '
                "token limit, so its arguments may be truncated. Re-issue the tool call with "
                "complete arguments."
            ),
        )
        await _emit(
            emit,
            ToolExecutionEndEvent(
                tool_call_id=tool_call.id,
                tool_name=tool_call.name,
                result=result,
                is_error=True,
            ),
        )
        msg = ToolResultMessage(
            tool_call_id=tool_call.id,
            tool_name=tool_call.name,
            content=result.content,
            is_error=True,
            details=result.details,
        )
        await _emit(emit, MessageStartEvent(message=msg))
        await _emit(emit, MessageEndEvent(message=msg))
        messages.append(msg)
    return _ToolBatch(messages=messages, terminate=False)


async def _execute_tool_calls(
    current_context: AgentContext,
    assistant_message: AssistantMessage,
    config: AgentLoopConfig,
    emit: Emit,
) -> _ToolBatch:
    tool_calls = assistant_message.tool_calls
    has_sequential = False
    for tc in tool_calls:
        tool = _find_tool(current_context.tools, tc.name)
        if tool is not None and tool.execution_mode == "sequential":
            has_sequential = True
            break
    if config.tool_execution == "sequential" or has_sequential:
        return await _execute_tool_calls_sequential(
            current_context, assistant_message, tool_calls, config, emit
        )
    return await _execute_tool_calls_parallel(
        current_context, assistant_message, tool_calls, config, emit
    )


def _find_tool(tools: list[AgentTool], name: str) -> AgentTool | None:
    for tool in tools:
        if tool.name == name:
            return tool
    return None


async def _execute_tool_calls_sequential(
    current_context: AgentContext,
    assistant_message: AssistantMessage,
    tool_calls: list[ToolCall],
    config: AgentLoopConfig,
    emit: Emit,
) -> _ToolBatch:
    finalized: list[_FinalizedToolCall] = []
    messages: list[ToolResultMessage] = []

    for tool_call in tool_calls:
        await _emit(
            emit,
            ToolExecutionStartEvent(
                tool_call_id=tool_call.id,
                tool_name=tool_call.name,
                args=tool_call.arguments,
            ),
        )
        preparation = await _prepare_tool_call(
            current_context, assistant_message, tool_call, config
        )
        if isinstance(preparation, _ImmediateToolCall):
            outcome = _FinalizedToolCall(
                tool_call=tool_call,
                result=preparation.result,
                is_error=preparation.is_error,
            )
        else:
            executed = await _execute_prepared_tool_call(preparation, emit)
            outcome = await _finalize_executed_tool_call(
                current_context, assistant_message, preparation, executed, config
            )

        await _emit(
            emit,
            ToolExecutionEndEvent(
                tool_call_id=outcome.tool_call.id,
                tool_name=outcome.tool_call.name,
                result=outcome.result,
                is_error=outcome.is_error,
            ),
        )
        msg = _tool_result_message(outcome)
        await _emit(emit, MessageStartEvent(message=msg))
        await _emit(emit, MessageEndEvent(message=msg))
        finalized.append(outcome)
        messages.append(msg)

    return _ToolBatch(messages=messages, terminate=_should_terminate(finalized))


async def _execute_tool_calls_parallel(
    current_context: AgentContext,
    assistant_message: AssistantMessage,
    tool_calls: list[ToolCall],
    config: AgentLoopConfig,
    emit: Emit,
) -> _ToolBatch:
    # Serialize emit so Agent.subscribe handlers settle without interleaving.
    emit_lock = asyncio.Lock()

    async def locked_emit(event: AgentEvent) -> None:
        async with emit_lock:
            await _emit(emit, event)

    coros: list[Awaitable[_FinalizedToolCall]] = []

    for tool_call in tool_calls:
        await locked_emit(
            ToolExecutionStartEvent(
                tool_call_id=tool_call.id,
                tool_name=tool_call.name,
                args=tool_call.arguments,
            ),
        )
        preparation = await _prepare_tool_call(
            current_context, assistant_message, tool_call, config
        )
        if isinstance(preparation, _ImmediateToolCall):
            outcome = _FinalizedToolCall(
                tool_call=tool_call,
                result=preparation.result,
                is_error=preparation.is_error,
            )
            await locked_emit(
                ToolExecutionEndEvent(
                    tool_call_id=tool_call.id,
                    tool_name=tool_call.name,
                    result=outcome.result,
                    is_error=outcome.is_error,
                ),
            )
            coros.append(_resolve(outcome))
            continue

        async def run_one(prep: _PreparedToolCall = preparation) -> _FinalizedToolCall:
            executed = await _execute_prepared_tool_call(prep, locked_emit)
            finalized = await _finalize_executed_tool_call(
                current_context, assistant_message, prep, executed, config
            )
            await locked_emit(
                ToolExecutionEndEvent(
                    tool_call_id=finalized.tool_call.id,
                    tool_name=finalized.tool_call.name,
                    result=finalized.result,
                    is_error=finalized.is_error,
                ),
            )
            return finalized

        coros.append(run_one())

    ordered = list(await asyncio.gather(*coros))
    messages: list[ToolResultMessage] = []
    for outcome in ordered:
        msg = _tool_result_message(outcome)
        await locked_emit(MessageStartEvent(message=msg))
        await locked_emit(MessageEndEvent(message=msg))
        messages.append(msg)

    return _ToolBatch(messages=messages, terminate=_should_terminate(ordered))


async def _resolve(value: _FinalizedToolCall) -> _FinalizedToolCall:
    return value


def _should_terminate(finalized: list[_FinalizedToolCall]) -> bool:
    return bool(finalized) and all(item.result.terminate is True for item in finalized)


def _tool_result_message(outcome: _FinalizedToolCall) -> ToolResultMessage:
    return ToolResultMessage(
        tool_call_id=outcome.tool_call.id,
        tool_name=outcome.tool_call.name,
        content=outcome.result.content,
        is_error=outcome.is_error,
        details=outcome.result.details,
    )


def _validate_tool_arguments(tool: AgentTool, args: dict[str, Any]) -> dict[str, Any]:
    """Lightweight JSON-Schema-ish check against AgentTool.parameters when present."""
    schema = tool.parameters
    if not schema:
        return args
    if not isinstance(args, dict):
        raise TypeError(f"Tool {tool.name} arguments must be an object")
    required = schema.get("required")
    if isinstance(required, list):
        missing = [key for key in required if key not in args]
        if missing:
            raise ValueError(
                f"Tool {tool.name} missing required arguments: {', '.join(map(str, missing))}"
            )
    return args


async def _prepare_tool_call(
    current_context: AgentContext,
    assistant_message: AssistantMessage,
    tool_call: ToolCall,
    config: AgentLoopConfig,
) -> _PreparedToolCall | _ImmediateToolCall:
    tool = _find_tool(current_context.tools, tool_call.name)
    if tool is None:
        return _ImmediateToolCall(
            result=AgentToolResult(content=f"Tool {tool_call.name} not found"),
            is_error=True,
        )
    if tool.execute is None:
        return _ImmediateToolCall(
            result=AgentToolResult(content=f"Tool {tool_call.name} has no execute handler"),
            is_error=True,
        )

    try:
        args = dict(tool_call.arguments)
        if tool.prepare_arguments is not None:
            args = tool.prepare_arguments(args)
        args = _validate_tool_arguments(tool, args)
        if config.before_tool_call is not None:
            before = await _maybe_await(
                config.before_tool_call(
                    BeforeToolCallContext(
                        assistant_message=assistant_message,
                        tool_call=tool_call,
                        args=args,
                        context=current_context,
                    )
                )
            )
            if before is not None and before.block:
                return _ImmediateToolCall(
                    result=AgentToolResult(
                        content=before.reason or "Tool execution was blocked",
                    ),
                    is_error=True,
                )
        return _PreparedToolCall(tool_call=tool_call, tool=tool, args=args)
    except Exception as exc:
        return _ImmediateToolCall(
            result=AgentToolResult(content=str(exc)),
            is_error=True,
        )


async def _execute_prepared_tool_call(prepared: _PreparedToolCall, emit: Emit) -> _ExecutedToolCall:
    tool = prepared.tool
    tool_call = prepared.tool_call
    accepting = True
    update_tasks: list[asyncio.Task[None]] = []

    def on_update(partial: AgentToolResult) -> None:
        nonlocal accepting
        if not accepting:
            return

        async def _emit_update() -> None:
            await _emit(
                emit,
                ToolExecutionUpdateEvent(
                    tool_call_id=tool_call.id,
                    tool_name=tool_call.name,
                    args=tool_call.arguments,
                    partial_result=partial,
                ),
            )

        update_tasks.append(asyncio.create_task(_emit_update()))

    assert tool.execute is not None
    try:
        result = await tool.execute(tool_call.id, prepared.args, on_update=on_update)
        accepting = False
        if update_tasks:
            await asyncio.gather(*update_tasks)
        return _ExecutedToolCall(result=result, is_error=False)
    except Exception as exc:
        accepting = False
        if update_tasks:
            await asyncio.gather(*update_tasks)
        return _ExecutedToolCall(
            result=AgentToolResult(content=str(exc)),
            is_error=True,
        )


async def _finalize_executed_tool_call(
    current_context: AgentContext,
    assistant_message: AssistantMessage,
    prepared: _PreparedToolCall,
    executed: _ExecutedToolCall,
    config: AgentLoopConfig,
) -> _FinalizedToolCall:
    result = executed.result
    is_error = executed.is_error

    if config.after_tool_call is not None:
        try:
            after = await _maybe_await(
                config.after_tool_call(
                    AfterToolCallContext(
                        assistant_message=assistant_message,
                        tool_call=prepared.tool_call,
                        args=prepared.args,
                        result=result,
                        is_error=is_error,
                        context=current_context,
                    )
                )
            )
            if after is not None:
                result = AgentToolResult(
                    content=after.content if after.content is not None else result.content,
                    details=after.details if after.details is not None else result.details,
                    terminate=(
                        after.terminate if after.terminate is not None else result.terminate
                    ),
                )
                if after.is_error is not None:
                    is_error = after.is_error
        except Exception as exc:
            result = AgentToolResult(content=str(exc))
            is_error = True

    return _FinalizedToolCall(
        tool_call=prepared.tool_call,
        result=result,
        is_error=is_error,
    )
