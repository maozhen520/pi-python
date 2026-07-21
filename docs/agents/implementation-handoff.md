# Implementation handoff — Python pi harness

**Map (decisions index):** https://github.com/maozhen520/pi-python/issues/1  
**Glossary:** [`CONTEXT.md`](../../CONTEXT.md)  
**Tracker ops:** [`issue-tracker.md`](./issue-tracker.md)

Wayfinding is **done** for v1 scope: open child tickets on the map are cleared; implement from Decisions so far + glossary + research notes. Do not re-litigate settled tickets unless the destination changes.

## Destination (reminder)

Thin LLM adapter (`pi_llm` / LiteLLM) + agent runtime (`pi_agent`) + Textual TUI (`pi_tui`) + interactive coding CLI (`pi_coding_agent` / `piy`). No orchestrator/chat; no full pi-ai matrix; no TS API or upstream session interchange.

## Suggested build order

1. **Monorepo scaffold** — `uv` workspace; `packages/pi_{llm,agent,tui,coding_agent}/` src layout; CI: ruff + typecheck + pytest.
2. **`pi_llm`** — OpenAI Chat Completions via LiteLLM (`acompletion`); stream for UI; assemble-then-execute tools; capability probes; OpenAI-mapped errors; credentials resolve env → `~/.pi/agent/auth.json`.
3. **`pi_agent`** — Public loop + `Agent`; awaited `subscribe`; `prompt` / `continue` / `steer` / `follow_up`; full event set; AgentMessage vs LLM Message + convert hooks; tool contract + hooks + parallel/sequential.
4. **Built-in tools** (in coding-agent, registered on Agent) — `read` / `write` / `bash` per grill; `edit` = exact multi-replace `edits[]` + `replace_all`, all-or-nothing, per-realpath queue with `write`.
5. **`pi_coding_agent` resources** — discovery roots `~/.pi/agent` + `.pi` + `.agents/skills`; skills/prompts Markdown contracts; settings merge + trust.json; AGENTS/CLAUDE → `<project_context>`.
6. **Session + compaction** — own JSONL under `~/.pi/agent/sessions/<cwd-encoded>/`; Session owns file/branch, Agent owns transcript; auto+manual compaction entries.
7. **`pi_tui` + `piy` wiring** — transcript, streaming assistant, tool display, editor; runtime events → widgets; auth prompt-and-save UX.

## Research notes

| Topic | Path |
|-------|------|
| Agent-core loop/events/tools | [`docs/research/upstream-agent-core.md`](../research/upstream-agent-core.md) |
| Extensibility / skills / templates | [`docs/research/upstream-coding-agent-extensibility.md`](../research/upstream-coding-agent-extensibility.md) |
| LiteLLM streaming & tools | [`docs/research/litellm-streaming-tools.md`](../research/litellm-streaming-tools.md) |
| Edit tool OSS comparison | [`docs/research/edit-tool-designs.md`](../research/edit-tool-designs.md) |

## Testing bar (v1)

Pytest pyramid; recorded LLM chunk fixtures in CI; light Textual pilot tests; no required live LLM in CI.

## Out of scope (do not expand v1)

Orchestrator, pi-chat, themes/packages marketplace, print/JSON/RPC modes, OAuth login matrix, built-in sandbox, upstream session file compat — see map **Out of scope**.
