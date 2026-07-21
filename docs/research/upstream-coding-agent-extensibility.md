# Research: upstream coding-agent extensibility

**Ticket:** [#3](https://github.com/maozhen520/pi-python/issues/3)  
**Map:** [#1](https://github.com/maozhen520/pi-python/issues/1)  
**Upstream:** [`earendil-works/pi`](https://github.com/earendil-works/pi) package `@earendil-works/pi-coding-agent`  
**Sources pinned to:** `main` @ `890b3547af23` (fetched 2026-07-21)

## Question

How does upstream `@earendil-works/pi-coding-agent` express extensibility — Extensions, Skills, Prompt Templates, Themes, Packages — and which on-disk / runtime contracts matter for our v1 surface (custom tools, skills, prompt templates, project/session config)? What can be deferred (themes, packages)?

## Verdict (for v1)

Upstream separates **executable harness plugins** (Extensions = TypeScript modules) from **declarative LLM resources** (Skills + Prompt Templates = Markdown) and from **distribution** (Packages) / **TUI cosmetics** (Themes). Settings + project trust gate which of these load.

For pi-python v1, keep the same mental model and prioritize:

| Keep for v1 | Defer |
|-------------|--------|
| Custom tools (Python registration API, not jiti/TS) | Themes (JSON TUI palettes) |
| Skills (Agent Skills–style Markdown + progressive disclosure) | Pi Packages (`pi install`, npm/git gallery, `package.json#pi`) |
| Prompt templates (`/name` Markdown expanders) | Full Extension lifecycle / TUI custom components / RPC+print modes |
| Project + global config (`.pi/settings.json`, `~/.pi/agent/…`, trust) | Shareable package filtering / `pi config` resource toggles |

Themes and Packages can wait without breaking the model: they are delivery and presentation layers over the same four resource kinds (extensions, skills, prompts, themes).

---

## 1. Five extensibility surfaces

### 1.1 Extensions (code plugins)

Docs: [`packages/coding-agent/docs/extensions.md`](https://github.com/earendil-works/pi/blob/890b3547af23/packages/coding-agent/docs/extensions.md)

- TypeScript modules exporting `default function (pi: ExtensionAPI)` (sync or async).
- Loaded via [jiti](https://github.com/unjs/jiti) (TS without compile).
- Capabilities: lifecycle events, `registerTool`, `registerCommand` / shortcut / flag, session entries, custom TUI rendering, providers, UI dialogs.
- Auto-discovery:

  | Location | Scope |
  |----------|--------|
  | `~/.pi/agent/extensions/*.ts` or `*/index.ts` | Global |
  | `.pi/extensions/*.ts` or `*/index.ts` | Project (after trust) |

- Also: `settings.json` → `extensions` paths; CLI `-e` / `--extension`; packages.
- Security: full host permissions; project-local extensions only after project trust.

Runtime contract (source): [`src/core/extensions/types.ts`](https://github.com/earendil-works/pi/blob/890b3547af23/packages/coding-agent/src/core/extensions/types.ts)

- `ExtensionFactory = (pi: ExtensionAPI) => void | Promise<void>`
- `ToolDefinition`: `name`, `label`, `description`, TypeBox `parameters`, `execute(...)`, optional `promptSnippet` / `promptGuidelines`, optional `renderCall` / `renderResult`, optional `executionMode`.
- Tool result: `{ content: [{ type: "text", text }], details?, usage?, terminate? }`; errors via **throw**, not return flags.
- Modes: `ctx.mode` ∈ `"tui" | "rpc" | "json" | "print"`; UI only when `ctx.hasUI`.

**v1 implication:** Mirror the *roles* (register tools + optional slash commands + event hooks later), not the TS/jiti loader. Custom tools are the Extension capability that maps cleanly to Python SDK/CLI.

### 1.2 Skills (on-demand capability packs)

Docs: [`packages/coding-agent/docs/skills.md`](https://github.com/earendil-works/pi/blob/890b3547af23/packages/coding-agent/docs/skills.md)  
Source: [`src/core/skills.ts`](https://github.com/earendil-works/pi/blob/890b3547af23/packages/coding-agent/src/core/skills.ts)

- Implements [Agent Skills](https://agentskills.io/specification) with lenient validation (warnings still load; missing `description` rejects).
- Pi exception vs standard: skill `name` need **not** match parent directory.
- Progressive disclosure: startup injects names/descriptions (XML) into system prompt; model `read`s full `SKILL.md` when needed; optional `/skill:name` command.
- On-disk:

  ```
  my-skill/
  ├── SKILL.md          # required: YAML frontmatter + body
  ├── scripts/          # freeform
  ├── references/
  └── assets/
  ```

- Frontmatter (required): `name`, `description`. Optional: `license`, `compatibility`, `metadata`, `allowed-tools`, `disable-model-invocation`.
- Name rules (enforced as warnings): ≤64 chars, `[a-z0-9-]`, no leading/trailing/consecutive hyphens; description ≤1024 chars.
- Discovery locations:

  - Global: `~/.pi/agent/skills/`, `~/.agents/skills/`
  - Project (trusted): `.pi/skills/`, `.agents/skills/` walking ancestors to git root (or FS root)
  - Settings `skills[]`, packages, CLI `--skill` (additive even with `--no-skills`)
  - In `.pi` / agent skills dirs: root `.md` files count as skills; in `.agents/skills/`, root `.md` ignored — only `SKILL.md` trees

**v1 implication:** Treat Skills as a first-class on-disk Markdown contract (compatible with Agent Skills / other harnesses). Do not require packaging.

### 1.3 Prompt Templates (slash expanders)

Docs: [`packages/coding-agent/docs/prompt-templates.md`](https://github.com/earendil-works/pi/blob/890b3547af23/packages/coding-agent/docs/prompt-templates.md)  
Source: [`src/core/prompt-templates.ts`](https://github.com/earendil-works/pi/blob/890b3547af23/packages/coding-agent/src/core/prompt-templates.ts)

- Markdown files; **filename** (sans `.md`) becomes `/name`.
- Locations: `~/.pi/agent/prompts/*.md`, `.pi/prompts/*.md` (trusted), settings `prompts[]`, packages, `--prompt-template`.
- Discovery under `prompts/` is **non-recursive**.
- Frontmatter: optional `description`, optional `argument-hint`.
- Body substitution: `$1`…, `$@` / `$ARGUMENTS`, `${N:-default}`, `${@:N}`, `${@:N:L}` (bash-style; no recursive expand of substituted values).
- Disable with `--no-prompt-templates`.

**v1 implication:** Small, stable contract — Markdown + frontmatter + argument placeholders. High value / low cost for interactive CLI.

### 1.4 Themes (defer)

Docs: [`packages/coding-agent/docs/themes.md`](https://github.com/earendil-works/pi/blob/890b3547af23/packages/coding-agent/docs/themes.md)

- JSON color tokens for TUI (`~/.pi/agent/themes/*.json`, `.pi/themes/`, settings, packages).
- Selected via `settings.theme`.
- Orthogonal to agent loop / tools / skills.

**Defer:** presentation only; ship a fixed TUI palette until a Python TUI design needs theming.

### 1.5 Packages (defer)

Docs: [`packages/coding-agent/docs/packages.md`](https://github.com/earendil-works/pi/blob/890b3547af23/packages/coding-agent/docs/packages.md)

- Distribution bundle for the four resource kinds via npm / git / local path.
- Manifest: `package.json` → `"pi": { extensions, skills, prompts, themes }` or convention dirs `extensions/`, `skills/`, `prompts/`, `themes/`.
- CLI: `pi install` / `remove` / `list` / `update`; writes `packages` into user or project settings (`-l`).
- Project packages install on startup **after trust**.
- Filtering, gallery metadata (`pi-package` keyword), peerDeps for core packages — ecosystem concerns.

**Defer:** v1 can load local paths + settings arrays without install/marketplace. Packages are a packaging layer, not a new semantic type.

---

## 2. Config & discovery contracts that matter for v1

### 2.1 Directory layout

Source: [`src/config.ts`](https://github.com/earendil-works/pi/blob/890b3547af23/packages/coding-agent/src/config.ts)

| Path | Role |
|------|------|
| `CONFIG_DIR_NAME` default `.pi` | Project config root name |
| `~/.pi/agent/` (`getAgentDir()`) | Global agent dir; override `PI_CODING_AGENT_DIR` |
| `~/.pi/agent/settings.json` | Global settings |
| `.pi/settings.json` | Project settings (override, nested merge) |
| `~/.pi/agent/trust.json` | Persisted project trust |
| `~/.pi/agent/{extensions,skills,prompts,themes}/` | Global resources |
| `.pi/{extensions,skills,prompts,themes}/` | Project resources |
| `sessionDir` / `PI_CODING_AGENT_SESSION_DIR` / `--session-dir` | Session storage location |

Docs: [`packages/coding-agent/docs/settings.md`](https://github.com/earendil-works/pi/blob/890b3547af23/packages/coding-agent/docs/settings.md)

Resource path settings (resolve relative to owning settings file’s directory):

- `packages`, `extensions`, `skills`, `prompts`, `themes` (arrays; globs / `!` / `+` / `-`)
- `enableSkillCommands` (default true)

### 2.2 Project trust

Before loading project `.pi/*`, project settings, project packages, or project `.agents/skills`, interactive pi prompts (or uses saved `trust.json` / `defaultProjectTrust`: `ask` | `always` | `never`). Non-interactive modes do not prompt; without saved trust they ignore project resources unless `--approve` / `always`.

Extension hook `project_trust` can decide earlier (user/global/CLI extensions only).

**v1 implication:** Keep a trust gate (even if UX is simpler) so project-local code/skills are not silently executed.

### 2.3 Context files (related, not a fifth package type)

Source: [`src/core/resource-loader.ts`](https://github.com/earendil-works/pi/blob/890b3547af23/packages/coding-agent/src/core/resource-loader.ts) → `loadProjectContextFiles`

- Per directory, first hit among: `AGENTS.md`, `AGENTS.MD`, `CLAUDE.md`, `CLAUDE.MD`.
- Loads global from `agentDir`, then walks from `cwd` up to filesystem root (ancestor files ordered outer→inner).
- Injected into system prompt as `<project_context>…</project_context>` ([`system-prompt.ts`](https://github.com/earendil-works/pi/blob/890b3547af23/packages/coding-agent/src/core/system-prompt.ts)).

Useful for v1 project config / conventions; map ticket still lists exact discovery as open — upstream’s choice is a strong default.

### 2.4 ResourceLoader as the runtime seam

Docs: [`packages/coding-agent/docs/sdk.md`](https://github.com/earendil-works/pi/blob/890b3547af23/packages/coding-agent/docs/sdk.md)  
Source: `DefaultResourceLoader` in `resource-loader.ts`

Unified discovery/reload API for:

- extensions, skills, prompts, themes
- agents/context files
- system / append system prompts
- CLI/SDK overrides (`noSkills`, path additions, factory injection)

`resources_discover` extension event can add skill/prompt/theme paths after `session_start`.

**v1 implication:** One loader concept (Python) that feeds the agent session — even if themes/packages stubs are empty.

---

## 3. Runtime contracts for custom tools (v1-critical)

From Extensions docs + `ToolDefinition`:

1. **Registration API** — name/label/description/schema/`execute`; optional prompt snippets/guidelines.
2. **Schema** — upstream uses TypeBox (+ `StringEnum` for Google); Python can use JSON Schema / Pydantic with the same fields exposed to the model.
3. **Execute signature** — toolCallId, params, abort signal, streaming `onUpdate`, context (`cwd`, UI, session helpers).
4. **Result shape** — multimodal-ish `content[]` to the LLM + opaque `details` for UI/state.
5. **Lifecycle events** (later) — `tool_call` can `{ block, reason }`; `tool_result` can modify; `before_agent_start` can inject system/user content.
6. **Parallel file mutations** — upstream queues via `withFileMutationQueue`; if v1 supports parallel tools + custom file writers, need an equivalent.

What v1 can skip initially: custom TUI renderers, `registerShortcut`/`registerFlag`, provider registration, compaction/tree hooks, RPC/print mode UI shims.

---

## 4. Mental model (what must stay coherent)

```text
Settings + Trust
      │
      ▼
 ResourceLoader ──► Extensions (code: tools, commands, hooks)
                 ├─► Skills (Markdown: progressive disclosure)
                 ├─► Prompt templates (Markdown: /slash expand)
                 └─► Themes (JSON: TUI)          [defer]
      ▲
 Packages (npm/git/local install into settings) [defer]
```

- **Skills ≠ Extensions:** skills instruct the model; extensions run in-process code.
- **Prompt templates ≠ Skills:** templates always expand into the user prompt; skills are catalogued and loaded on demand.
- **Packages ≠ a capability:** only a way to ship the above.
- **Themes ≠ agent semantics:** only TUI colors.

Deferring themes/packages does **not** force a later redesign if local path discovery + settings arrays exist from day one.

---

## 5. Recommended v1 on-disk / API surface (alignment, not implementation)

Suggested parity (names can be Python-idiomatic; layout should stay recognizable):

| Concern | Upstream contract to mirror |
|---------|------------------------------|
| Global dir | `~/.pi/agent/` or env override |
| Project dir | `.pi/` |
| Settings | JSON merge: global ← project; keys for `skills` / `prompts` / `extensions` paths |
| Trust | Persist decisions before loading project resources |
| Skills | `SKILL.md` + Agent Skills frontmatter; `/skill:name`; system-prompt listing |
| Prompt templates | `prompts/*.md` non-recursive; `/filename`; `$1`/`$@` substitution |
| Custom tools | Programmatic register (SDK + optional project/global plugin modules in Python) |
| Context | Optional `AGENTS.md` / `CLAUDE.md` walk (decide in a later ticket) |
| Themes / Packages | Stub settings keys or ignore until post-v1 |

---

## 6. Source index

| Topic | Primary docs | Primary source |
|-------|--------------|----------------|
| Extensions | `docs/extensions.md` | `src/core/extensions/types.ts`, `loader.ts` |
| Skills | `docs/skills.md` | `src/core/skills.ts` |
| Prompt templates | `docs/prompt-templates.md` | `src/core/prompt-templates.ts` |
| Packages | `docs/packages.md` | `src/core/package-manager.ts` |
| Settings / trust | `docs/settings.md` | `src/core/settings-manager.ts`, `src/config.ts` |
| Themes | `docs/themes.md` | interactive theme loader |
| Unified load | `docs/sdk.md` | `src/core/resource-loader.ts` |
| System prompt injection | — | `src/core/system-prompt.ts` |

All paths under `https://github.com/earendil-works/pi/tree/890b3547af23/packages/coding-agent/`.

---

## 7. Open items (out of this ticket)

- Exact Python plugin module format (entrypoints vs `.py` discovery) — product decision, not upstream fact.
- Whether to keep `.pi` dirname / `AGENTS.md` names vs Python-native names while staying “semantically aligned”.
- How much of the Extension event bus lands in v1 vs later.
)
