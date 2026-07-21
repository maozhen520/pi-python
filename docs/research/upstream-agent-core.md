# Research: upstream `@earendil-works/pi-agent-core` contracts

**Ticket:** [Research: upstream agent-core loop, messages, events, tools](https://github.com/maozhen520/pi-python/issues/2)  
**Map:** [Map: Python pi harness (core + TUI + coding CLI)](https://github.com/maozhen520/pi-python/issues/1)  
**Upstream package:** [`packages/agent`](https://github.com/earendil-works/pi/tree/main/packages/agent) (`@earendil-works/pi-agent-core`)  
**Snapshot:** [`earendil-works/pi@890b3547af23`](https://github.com/earendil-works/pi/commit/890b3547af23) (main tip when researched, 2026-07-21)  
**Scope:** durable concepts a Python agent runtime should honor for design alignment — not API/name parity.

Primary sources:

- [packages/agent/README.md](https://github.com/earendil-works/pi/blob/main/packages/agent/README.md)
- [packages/agent/src/types.ts](https://github.com/earendil-works/pi/blob/main/packages/agent/src/types.ts)
- [packages/agent/src/agent-loop.ts](https://github.com/earendil-works/pi/blob/main/packages/agent/src/agent-loop.ts)
- [packages/agent/src/agent.ts](https://github.com/earendil-works/pi/blob/main/packages/agent/src/agent.ts)
- LLM message shapes: [packages/ai/src/types.ts](https://github.com/earendil-works/pi/blob/main/packages/ai/src/types.ts) (`Message`, `Context`, `AssistantMessageEvent`)

---

## 1. Two layers: loop vs stateful Agent

Upstream splits responsibility cleanly:

| Layer | Entry points | Role |
|-------|--------------|------|
| Low-level loop | `agentLoop` / `agentLoopContinue` / `runAgentLoop*` | Pure turn machine: emit events, call `streamFunction`, run tools, decide whether another turn runs |
| Stateful `Agent` | `prompt` / `continue` / `steer` / `followUp` | Owns transcript, tools, queues, abort; awaits subscribers as a settlement barrier |

Source: [agent.ts](https://github.com/earendil-works/pi/blob/main/packages/agent/src/agent.ts) (`Agent` wraps `runAgentLoop`), [agent-loop.ts](https://github.com/earendil-works/pi/blob/main/packages/agent/src/agent-loop.ts) (loop body).

**Python alignment:** keep a pure loop (events + tools + LLM boundary) separate from a stateful facade that owns messages/tools/queues and awaits listeners. Do not fuse them into one opaque object if SDK consumers need observational streams.

**Important difference:** raw `agentLoop` is observational — it preserves event order but does **not** wait for consumer async handling before later phases. `Agent.subscribe` listeners **are** awaited in registration order; `assistant` `message_end` therefore acts as a barrier before tool preflight (`beforeToolCall` sees state that already includes that assistant message). README + `Agent.processEvents` document this.

Settlement: `agent_end` is the last emitted event, but idle/`waitForIdle`/`await prompt(...)` only resolve after awaited `agent_end` listeners finish (`types.ts` `AgentEvent` docs; `Agent.waitForIdle` / `processEvents`).

---

## 2. AgentMessage vs LLM `Message`

### LLM messages (`@earendil-works/pi-ai`)

`Message = UserMessage | AssistantMessage | ToolResultMessage` with roles `"user" | "assistant" | "toolResult"`.  
`Context = { systemPrompt?, messages: Message[], tools?: Tool[] }`.

Source: [packages/ai/src/types.ts](https://github.com/earendil-works/pi/blob/main/packages/ai/src/types.ts).

### Agent messages

```ts
AgentMessage = Message | CustomAgentMessages[keyof CustomAgentMessages]
```

Apps extend via declaration merging on `CustomAgentMessages`. The loop keeps **AgentMessage** in the transcript; LLM-facing conversion happens only at the provider call boundary.

Source: [types.ts](https://github.com/earendil-works/pi/blob/main/packages/agent/src/types.ts); file header of [agent-loop.ts](https://github.com/earendil-works/pi/blob/main/packages/agent/src/agent-loop.ts): *"Agent loop that works with AgentMessage throughout. Transforms to Message[] only at the LLM call boundary."*

**Python alignment:** transcript type wider than provider payload; custom/UI-only roles allowed; never send custom roles to the model without an explicit convert step.

Default convert (Agent class) keeps only the three LLM roles:

```ts
// agent.ts — defaultConvertToLlm
messages.filter(m => m.role === "user" || m.role === "assistant" || m.role === "toolResult")
```

---

## 3. Message flow: `transformContext` then `convertToLlm`

Documented pipeline ([README](https://github.com/earendil-works/pi/blob/main/packages/agent/README.md)):

```
AgentMessage[] → transformContext() → AgentMessage[] → convertToLlm() → Message[] → LLM
                   (optional)                           (required on loop config)
```

Implemented in `streamAssistantResponse` ([agent-loop.ts](https://github.com/earendil-works/pi/blob/main/packages/agent/src/agent-loop.ts)):

1. Optional `transformContext(messages, signal)` — prune/inject at AgentMessage level  
2. Required `convertToLlm(messages)` — filter/map to `Message[]`  
3. Build `Context { systemPrompt, messages: llmMessages, tools }`  
4. Optional `getApiKey(provider)` then call `streamFunction(model, llmContext, options)`

**Contracts** ([types.ts](https://github.com/earendil-works/pi/blob/main/packages/agent/src/types.ts) on `AgentLoopConfig`):

- `convertToLlm` / `transformContext` / `getApiKey` / queue getters / `shouldStopAfterTurn`: **must not throw or reject**; return safe fallbacks. Throwing aborts the low-level loop without a normal event sequence.
- `StreamFn`: must not throw for request/model failures; encode failure in the assistant stream as `stopReason` `"error"` | `"aborted"` plus `errorMessage`.

**Python alignment:** same two hooks (context transform vs LLM projection), same non-throwing contracts, same “failure is a message/stopReason, not an exception across the stream boundary” rule for the stream adapter.

---

## 4. Agent loop shape

### `prompt` / `runAgentLoop`

1. Append prompt message(s) to a context copy  
2. Emit `agent_start`, then `turn_start`  
3. For each prompt: `message_start` / `message_end` (no streaming for user prompts)  
4. Enter shared `runLoop`

### `continue` / `runAgentLoopContinue`

- No new prompt messages  
- Context must be non-empty; last message role must not be `"assistant"` (steering/follow-up queues can still be drained via `Agent.continue`)  
- Emit `agent_start`, `turn_start`, then `runLoop`  
- Last message must convert to `user` or `toolResult` via `convertToLlm` (documented; not statically validated)

### Shared `runLoop` (inner / outer)

- **Inner while:** while there are more tool calls to follow up **or** pending steering messages:  
  - subsequent turns emit another `turn_start`  
  - inject pending steering messages (`message_start`/`message_end`, append)  
  - `streamAssistantResponse`  
  - on `stopReason` `"error"` | `"aborted"`: `turn_end` (empty toolResults) → `agent_end` → exit  
  - else execute tool calls (if any), append toolResult messages, `turn_end`  
  - optional `prepareNextTurn` (swap context/model/thinking for next provider call)  
  - optional `shouldStopAfterTurn` → if true: `agent_end` (skips steering/follow-up poll and next LLM call)  
  - else poll steering queue  
- **Outer while:** if no more tools/steering, poll follow-up queue; if non-empty, continue; else `agent_end`

A **turn** = one assistant response + its tool executions (README + `AgentEvent` comments).

`Agent.prompt` rejects concurrent runs: use `steer` / `followUp` or wait. Concurrent prompt throws.

---

## 5. Event model

### Event types ([types.ts](https://github.com/earendil-works/pi/blob/main/packages/agent/src/types.ts))

| Event | Payload notes |
|-------|----------------|
| `agent_start` | run begins |
| `agent_end` | `{ messages }` — messages **produced by this run** (prompts + new assistant/tool/steering/follow-up), not full history |
| `turn_start` | start of turn |
| `turn_end` | `{ message, toolResults }` — assistant message + that turn’s `ToolResultMessage[]` |
| `message_start` / `message_end` | user, assistant, toolResult (and any AgentMessage) |
| `message_update` | **assistant only**; includes nested `assistantMessageEvent` (pi-ai stream protocol) |
| `tool_execution_start` | `{ toolCallId, toolName, args }` |
| `tool_execution_update` | `{ ..., partialResult }` |
| `tool_execution_end` | `{ ..., result, isError }` |

### `prompt()` without tools

```
agent_start
turn_start
message_start/end          # user prompt
message_start              # assistant
message_update…            # streaming (text/thinking/toolcall deltas via assistantMessageEvent)
message_end                # assistant
turn_end                   # toolResults: []
agent_end
```

Source: README sequence + `runAgentLoop` / `streamAssistantResponse` / `runLoop`.

### `prompt()` with tools (one tool batch, then final assistant)

```
agent_start
turn_start
message_start/end          # user
message_start → updates → message_end   # assistant with toolCall(s)
tool_execution_start
[tool_execution_update…]
tool_execution_end
message_start/end          # toolResult
turn_end                   # toolResults: [...]
turn_start                 # next turn
message_start → … → message_end         # assistant reply to tool results
turn_end
agent_end
```

Multiple tool calls in one assistant message: see §6 for parallel vs sequential ordering.

### Assistant streaming details

From pi-ai `AssistantMessageEvent`: `start` → partial deltas (`text_*` / `thinking_*` / `toolcall_*`) → terminal `done` | `error`.  
Loop maps: `start` → `message_start`; deltas → `message_update`; `done`/`error` → replace partial in context → `message_end`. If no `start` was seen, emit `message_start` then `message_end` for the final message.

Partial assistant messages are pushed into the loop context during streaming and replaced on completion.

---

## 6. Tools: registration, execution, hooks

### Registration shape (`AgentTool`)

Extends pi-ai `Tool` with:

- `label` — UI  
- `execute(toolCallId, params, signal?, onUpdate?) → AgentToolResult` — **throw on failure** (do not encode errors as success content)  
- optional `prepareArguments`, `executionMode` (`"sequential" | "parallel"`)  
- result: `{ content, details, usage?, addedToolNames?, terminate? }`

Thrown errors → caught → tool result with `isError: true` text content.

### Execution pipeline (per tool call)

1. Emit `tool_execution_start` (args as received on the toolCall)  
2. Resolve tool by name; missing → immediate error result  
3. `prepareArguments` (optional) → `validateToolArguments`  
4. `beforeToolCall` after validation — `{ block: true, reason? }` → error tool result, no execute  
5. `execute` with `onUpdate` → `tool_execution_update` (updates after settle ignored)  
6. `afterToolCall` — field-by-field replace (`content` / `details` / `isError` / `usage` / `terminate`); no deep merge  
7. `tool_execution_end`  
8. Emit toolResult as `message_start` / `message_end`

Hook timing (README + types): `beforeToolCall` after start + validated args; `afterToolCall` after execute, **before** `tool_execution_end` and toolResult message events.

### Parallel vs sequential

- Default `toolExecution`: `"parallel"`  
- Any tool in the batch with `executionMode: "sequential"` forces the whole batch sequential  
- **Parallel:** preflight sequentially; run allowed tools concurrently; emit `tool_execution_end` in **completion** order; emit toolResult messages later in **assistant source** order  
- **Sequential:** prepare → execute → finalize → end → toolResult message, one by one  

### Early stop via `terminate`

If **every** finalized tool result in the batch has `terminate: true` (from `execute` or `afterToolCall`), the loop does **not** make the automatic follow-up LLM call (`hasMoreToolCalls = false` via `shouldTerminateToolBatch`). Mixed batches continue. `terminate` is runtime-only; transcript toolResults stay normal LLM tool results.

### Truncated assistant (`stopReason === "length"`)

Do **not** execute tool calls; emit start/end with error results explaining possible truncated arguments, then continue the loop (model can retry).

### Dynamic tools

`AgentToolResult.addedToolNames` / `ToolResultMessage.addedToolNames` — names that become available from that transcript point (provider-specific deferred loading; others ignore and use `Context.tools`).

---

## 7. Steering, follow-up, and graceful stop

| Mechanism | When drained | Purpose |
|-----------|--------------|---------|
| Steering (`getSteeringMessages` / `Agent.steer`) | After turn completes (tools finished), unless `shouldStopAfterTurn` exits first | Interrupt/redirect mid-run without skipping already-started tool calls |
| Follow-up (`getFollowUpMessages` / `Agent.followUp`) | Only when no more tool follow-ups and no steering | Queue work after the agent would otherwise stop |
| Queue modes | `"one-at-a-time"` (default) or `"all"` | How many queued messages inject at a drain point |
| `shouldStopAfterTurn` | After `turn_end`, after tools finished normally | Emit `agent_end` before queue polls / next LLM; does not abort stream or cancel tools |

---

## 8. Durable contracts checklist (for Python runtime)

Honor these for design alignment even if Python APIs differ:

1. **Transcript ≠ provider payload** — AgentMessage (or equivalent) in state; convert only at LLM call.  
2. **Two-stage prep** — optional AgentMessage transform, then required LLM convert.  
3. **Turn = assistant + tools** — nested under agent_start/end.  
4. **Event sequence** — match §5 for prompt with/without tools; toolResult is a first-class message pair, not only a side channel.  
5. **Tool errors are results** — throw in execute → `isError` toolResult to the model.  
6. **Hooks order** — start → validate → before → execute (+ updates) → after → end → toolResult messages.  
7. **Parallel semantics** — completion-order end events vs source-order persisted toolResults.  
8. **Batch terminate** — only when all finalized results say terminate.  
9. **Stream failures as assistant stopReason**, not thrown out of `StreamFn`.  
10. **Stateful facade barrier** — if exposing Agent-like API, await listeners (especially `message_end` before tools; `agent_end` before idle).  
11. **Single active run** — concurrent `prompt` rejected; steering/follow-up for mid-flight input.  
12. **continue** — resume without new user message; last role must be user/toolResult (after convert).

Out of scope for this note (same package, later tickets): harness sessions/compaction/skills/prompt-templates under `packages/agent/src/harness/`.

---

## 9. One-line gist

Upstream agent-core is a turn loop over AgentMessages that projects to LLM Messages only at stream time, emits a fixed agent/turn/message/tool event sequence, and runs tools with before/after hooks under parallel-or-sequential batching — Python should mirror these contracts, not the TypeScript surface.
