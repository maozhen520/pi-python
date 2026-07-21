# Research: LiteLLM streaming and tool-calling contracts

**Ticket:** [#4](https://github.com/maozhen520/pi-python/issues/4)  
**Map:** [#1](https://github.com/maozhen520/pi-python/issues/1)  
**Date:** 2026-07-21  
**Primary sources:** [LiteLLM docs](https://docs.litellm.ai), [BerriAI/litellm](https://github.com/BerriAI/litellm) (SDK source for stream assembly)

## Question

For a thin Python LLM adapter over LiteLLM, what stable contracts exist for chat completions with streaming and tool/function calling that an agent runtime should depend on — including provider gaps, message shapes, and failure modes? Recommend the narrow upward interface for our thin LLM package.

## Verdict

LiteLLM’s stable contract is the **OpenAI Chat Completions shape**, not a LiteLLM-specific protocol:

- Call surface: `completion` / `acompletion` with OpenAI-style `messages`, `tools`, `tool_choice`, `stream`, etc.
- Non-stream output: `ModelResponse` (`object: chat.completion`) with `choices[0].message` (+ optional `tool_calls`).
- Stream output: iterable of `ModelResponseStream` chunks (`object: chat.completion.chunk`) with `choices[0].delta`.
- Errors: mapped to OpenAI exception types (importable from `litellm` / catchable as `openai.*`).

Our thin LLM package should **re-export a narrow OpenAI-chat subset** of that surface (async stream + tool round-trip), and treat LiteLLM as an implementation detail — not expose Router/Proxy, deprecated `functions=`, or prompt-injection fallbacks as public API.

---

## 1. What LiteLLM guarantees

### 1.1 Unified call + OpenAI response format

LiteLLM’s stated purpose is a single `completion()` interface across 100+ providers using the OpenAI format, with a consistent output shape regardless of provider.

Sources:

- [Getting Started](https://docs.litellm.ai/docs/) — “Call any provider using the same `completion()` interface”; “Every response follows the OpenAI Chat Completions format, regardless of provider.”
- Non-stream vs stream object examples on the same page (`chat.completion` vs `chat.completion.chunk` with `delta`).

### 1.2 Translated OpenAI params (not universal passthrough)

LiteLLM “accepts and translates the OpenAI Chat Completion params across all providers.” Param support is **provider/model dependent**. Discover support with:

```python
from litellm import get_supported_openai_params
get_supported_openai_params(model=..., custom_llm_provider=...)
```

Default behavior: **raise** if an unsupported OpenAI param is passed. Opt-out: `litellm.drop_params = True` or `completion(..., drop_params=True)` (drops unsupported *OpenAI* params only; non-OpenAI kwargs are still passed through).

Source: [Input Params](https://docs.litellm.ai/docs/completion/input)

### 1.3 Sync / async / streaming entrypoints

| Mode | API |
|------|-----|
| Sync non-stream | `litellm.completion(...)` |
| Sync stream | `completion(..., stream=True)` → iterate chunks |
| Async non-stream | `await litellm.acompletion(...)` |
| Async stream | `await acompletion(..., stream=True)` then `async for chunk in response` |

Sources:

- [Streaming + Async](https://docs.litellm.ai/docs/completion/stream)
- [stream (alternate)](https://docs.litellm.ai/stream) — also documents `stream_options={"include_usage": True}`

Helper to rebuild a full `ModelResponse` from collected chunks:

```python
litellm.stream_chunk_builder(chunks, messages=messages)
```

Implementation aggregates streamed `delta.tool_calls` by **index**, concatenating `function.arguments` fragments ([`streaming_chunk_builder_utils.py`](https://github.com/BerriAI/litellm/blob/main/litellm/litellm_core_utils/streaming_chunk_builder_utils.py) — `get_combined_tool_content`).

---

## 2. Message and tool shapes (stable OpenAI subset)

### 2.1 Messages

From [Input Params → Properties of messages](https://docs.litellm.ai/docs/completion/input):

| Field | Notes |
|-------|--------|
| `role` | `system`, `user`, `assistant`, `function`, or `tool` |
| `content` | `string` \| `list[dict]` \| `null` — “required for all messages, but may be null for assistant messages with function calls” |
| `name` | Required when `role == "function"` (legacy) |
| `tool_call_id` | On tool-result messages: which call this answers |
| `function_call` | Legacy assistant field |

`content` may also be multimodal blocks (`text`, `image_url`, `input_audio`, `video_url`, `file`, `document`) — out of scope for v1 agent loop unless we explicitly add vision later.

### 2.2 Tools input (current API)

Prefer **`tools` + `tool_choice`** (OpenAI v1 tools). Shape used throughout LiteLLM’s function-calling guide:

```python
tools = [{
    "type": "function",
    "function": {
        "name": "...",
        "description": "...",
        "parameters": { ... JSON Schema ... },
    },
}]
response = litellm.completion(
    model=...,
    messages=messages,
    tools=tools,
    tool_choice="auto",  # or "none" / force a named function
)
```

Also documented:

- `parallel_tool_calls: bool` — “Whether to enable parallel function calling during tool use. OpenAI default is true.”
- Deprecated: `functions=` / `function_call=` (“Deprecated - Function Calling with `completion(functions=functions)`”).

Source: [Function Calling](https://docs.litellm.ai/docs/completion/function_call), [Input Params](https://docs.litellm.ai/docs/completion/input)

### 2.3 Capability probes (use before promising tools)

```python
litellm.supports_function_calling(model="...")           # bool
litellm.supports_parallel_function_calling(model="...")  # bool
```

Docs examples: `gpt-3.5-turbo` / Azure GPT-4 / xAI grok → True; `palm/chat-bison`, `ollama/llama2` → False for function calling; parallel FC true for `gpt-4-turbo-preview`, false for `gpt-4`.

Source: [Function Calling](https://docs.litellm.ai/docs/completion/function_call)

### 2.4 Assistant tool-call output (non-stream)

Documented round-trip:

1. Read `response.choices[0].message.tool_calls` (list).
2. Each call: `.id`, `.function.name`, `.function.arguments` (**JSON string** — may be invalid; “be sure to handle errors”).
3. `finish_reason` is typically `'tool_calls'` when tools are requested.
4. Append the **assistant message object** (as returned) to `messages`.
5. For each executed call, append:

```python
{
    "tool_call_id": tool_call.id,
    "role": "tool",
    "name": function_name,   # present in LiteLLM examples
    "content": function_response,  # string (often JSON-serialized)
}
```

6. Call `completion` again with the extended transcript.

Source: [Function Calling — Parallel Function calling](https://docs.litellm.ai/docs/completion/function_call) (expected `ModelResponse` with `ChatCompletionMessageToolCall`).

### 2.5 Finish reasons

LiteLLM maps provider finish reasons to OpenAI-compatible values: `stop`, `length`, `tool_calls`, `function_call`, `content_filter`. When the provider’s native value differs, it may appear under `choice.provider_specific_fields["native_finish_reason"]` (example: Gemini `MALFORMED_FUNCTION_CALL`).

Source: [Output — Native Finish Reason](https://docs.litellm.ai/docs/completion/output)

Agent loops that care about “bad tool JSON vs normal stop” should check **native** finish reason, not only the mapped value.

---

## 3. Streaming contracts relevant to agents

### 3.1 Text deltas

Documented access pattern:

```python
for part in response:
    print(part.choices[0].delta.content or "")
```

Chunk JSON shape (docs): `choices[0].delta` with `role` / `content` (and documented nulls for `function_call` / `tool_calls` on text-only chunks).

Sources: [Streaming + Async](https://docs.litellm.ai/docs/completion/stream), [Getting Started](https://docs.litellm.ai/docs/)

### 3.2 Tool calls on the stream

LiteLLM does **not** publish a separate “streaming tools” product API. The contract is the OpenAI chunk delta shape: incremental `delta.tool_calls[]` entries with `index`, optional `id`/`type`, and partial `function.name` / `function.arguments`, assembled either by:

- `litellm.stream_chunk_builder`, or
- a consumer-side accumulator keyed by `tool_calls[].index` (same algorithm LiteLLM uses in source).

Usage token trailer (optional): `stream_options={"include_usage": True}` — final chunk may carry `usage` with empty `choices` ([stream docs](https://docs.litellm.ai/stream)).

### 3.3 Known streaming+tools fragility (provider / assembler)

Historical issues show this path is where provider quirks bite:

- Content **then** tool calls in one stream (assembly previously dropped tools) — fixed path discussed in LiteLLM PRs/issues (e.g. [#2716](https://github.com/BerriAI/litellm/issues/2716), Bedrock/Anthropic assembly work).
- Wrong `index` handling collapsing parallel tool calls (e.g. Groq — [#7621](https://github.com/BerriAI/litellm/issues/7621)).

**Implication for our adapter:** treat “stream text for UI” and “commit a complete assistant+tool_calls message for the agent loop” as two stages; prefer assembling a full message (via `stream_chunk_builder` or our own index-keyed builder) before executing tools. Do not execute tools from partial argument strings.

### 3.4 Streaming failure modes

| Mode | Behavior | Source |
|------|----------|--------|
| Repeated identical chunks | After `REPEATED_STREAMING_CHUNK_LIMIT` (default 100), raises `litellm.InternalServerError` | [Streaming + Async](https://docs.litellm.ai/docs/completion/stream) |
| Errors during stream | Exceptions can surface **while iterating** the stream (same OpenAI-mapped types) | [Exception Mapping — Catching Streaming Exceptions](https://docs.litellm.ai/docs/exception_mapping) |

---

## 4. Provider gaps (what not to depend on globally)

From the param-support table on [Input Params](https://docs.litellm.ai/docs/completion/input) (snapshot; always re-check with `get_supported_openai_params`):

- **`stream`**: widely supported across listed providers.
- **`tools` / `tool_choice`**: present for major chat providers (OpenAI, Azure, Anthropic, OpenRouter, Together, SambaNova, OVHCloud, …) but **missing or model-dependent** for many others (e.g. Replicate, Cohere row shows no tools checkmarks; Github is “model dependent”; Vertex/Bedrock table cells for tools are sparse / model-dependent in the published matrix).
- **`parallel_tool_calls`**: OpenAI-style control; not every model that “supports function calling” supports parallel calls — use `supports_parallel_function_calling`.
- **Non-native tool models**: LiteLLM offers `litellm.add_function_to_prompt = True` to stuff schemas into the prompt for models without function calling ([Function Calling](https://docs.litellm.ai/docs/completion/function_call)). This is a **compatibility hack**, not a structured tool-call contract — **do not** expose it as the default agent path.

Practical rule for pi-python v1: **require** `supports_function_calling(model)` (and preferably native `tools` in `get_supported_openai_params`) for coding-agent sessions; fail fast with a clear error otherwise.

---

## 5. Failure modes the runtime should handle

Mapped exceptions (import from `litellm`; inherit OpenAI types so `except openai.RateLimitError` also works). Extra attributes: `status_code`, `message`, `llm_provider` ([Exception Mapping](https://docs.litellm.ai/docs/exception_mapping)):

| HTTP / class | When it matters for agents |
|--------------|----------------------------|
| `BadRequestError` / `UnsupportedParamsError` | Passed `tools`/`stream_options`/etc. unsupported; or bad request |
| `ContextWindowExceededError` | Transcript too long — compaction / trim hook |
| `ContentPolicyViolationError` | Safety filter (Azure details via `provider_specific_fields`) |
| `AuthenticationError` / `PermissionDeniedError` / `NotFoundError` | Config / model id |
| `Timeout` / `RateLimitError` / `ServiceUnavailableError` / `APIConnectionError` / `InternalServerError` | Retry / backoff (`num_retries`, `fallbacks` exist on `completion` but may stay inside the LLM package) |
| `JSONSchemaValidationError` | Only if using `response_schema` + `enforce_validation` |

Application-level (not always raised by LiteLLM):

- **Invalid / partial tool JSON** in `function.arguments` — documented caution; validate before `json.loads`.
- **Mapped `finish_reason == "stop"` with native malformed tool call** — inspect `native_finish_reason`.
- **Missing `tool_call_id` round-trip** — providers need the assistant tool_calls message + matching tool results.

---

## 6. Recommended narrow upward interface (thin LLM package)

Goal: agent runtime depends on a **small, async, OpenAI-chat-shaped** API; LiteLLM stays behind the door.

### 6.1 Depend on (stable)

1. **Chat Completions message list** with roles `system|user|assistant|tool` (avoid public use of legacy `function` role / `functions=`).
2. **Tool definitions** as `{type: "function", function: {name, description, parameters}}`.
3. **One completion turn** that can return either assistant text, tool calls, or both.
4. **Streaming as an event iterator** over one turn, then a **final assembled assistant message** suitable to append to history.
5. **OpenAI-mapped errors** with a thin wrapper enum for retry vs fatal vs context-window vs auth.
6. **Capability query**: `supports_tools(model) -> bool` (backed by LiteLLM probes + param list).

### 6.2 Suggested surface (sketch — not implementation)

```text
complete(request) -> AssistantTurn
  # non-stream; AssistantTurn = {content, tool_calls[], finish_reason, usage?, raw?}

stream(request) -> AsyncIterator[StreamEvent]
  # StreamEvent =
  #   TextDelta(text) |
  #   ToolCallDelta(index, id?, name?, arguments_delta?) |
  #   TurnFinished(finish_reason, usage?) |
  #   Error(err)

assemble(events|chunks) -> AssistantTurn   # or always yield TurnFinished with assembled message

supports_tools(model) -> bool
supports_parallel_tools(model) -> bool
```

`Request` fields the runtime may set: `model`, `messages`, `tools`, `tool_choice`, `parallel_tool_calls`, sampling knobs we actually use (`temperature`, `max_tokens` / `max_completion_tokens`), `timeout`. Everything else stays kwargs behind an escape hatch, not part of the supported contract.

### 6.3 Explicitly out of the upward API

- LiteLLM Proxy / Router / virtual keys / budgets
- `add_function_to_prompt`
- Deprecated `functions` / `function_call`
- Provider-specific message formats (Anthropic native, Bedrock Converse, etc.) — LiteLLM already translates
- Guaranteeing identical stream chunk boundaries across providers
- Multimodal content blocks (until a later ticket)
- Executing tools inside the LLM package (belongs in agent runtime)

### 6.4 Adapter implementation notes

- Prefer **`acompletion` + `stream=True`** for TUI/SDK responsiveness.
- For tool execution: **wait for assembled `tool_calls` with complete `arguments` strings**.
- Use `stream_chunk_builder` *or* mirror its index-keyed merge; add tests with fixtures that include content+tools and multi-index parallel calls.
- On `UnsupportedParamsError`, do not silently `drop_params` for `tools` — fail visibly.
- Map `ContextWindowExceededError` and content-policy errors to distinct runtime signals.

---

## 7. Citations (primary)

| Topic | URL |
|-------|-----|
| Unified OpenAI format / stream chunk shape | https://docs.litellm.ai/docs/ |
| Streaming, async, `stream_chunk_builder`, loop guard | https://docs.litellm.ai/docs/completion/stream |
| Stream usage option | https://docs.litellm.ai/stream |
| Input params, messages, tools, drop_params, provider matrix | https://docs.litellm.ai/docs/completion/input |
| Function/tool calling, probes, parallel, deprecated functions, prompt fallback | https://docs.litellm.ai/docs/completion/function_call |
| Output format, native finish_reason | https://docs.litellm.ai/docs/completion/output |
| Exception mapping + streaming exceptions | https://docs.litellm.ai/docs/exception_mapping |
| Stream tool assembly source | https://github.com/BerriAI/litellm/blob/main/litellm/litellm_core_utils/streaming_chunk_builder_utils.py |

## 8. Decision for map #1

**Thin LLM package depends on LiteLLM’s OpenAI Chat Completions contract only:** `acompletion` with `messages` + modern `tools`/`tool_choice`, streaming deltas for UI, assemble-then-execute for tool calls, capability probes + OpenAI-mapped errors upward; no Proxy/Router, no `functions=`, no `add_function_to_prompt` as supported agent path.
