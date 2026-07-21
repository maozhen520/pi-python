# 架构与扩展点

本文说明四个包如何协作、`piy` 一次交互的数据流，以及 v1 已留的扩展口子。

## 四包关系

```text
┌─────────────────────────────────────────────────────────────┐
│  pi_coding_agent  (piy CLI + 产品层)                         │
│  ├─ cli.py          入口、凭证、TUI 主循环                    │
│  ├─ app.py          CodingSession：组装一切                   │
│  ├─ resources/      Skills / Prompts / Settings / 上下文    │
│  ├─ tools/          内置 read/write/edit/bash               │
│  ├─ session/        JSONL 持久化 + compaction               │
│  ├─ llm_bridge.py   pi_llm → Agent StreamFn                 │
│  └─ tui_wiring.py   Agent 事件 → pi_tui                     │
└───────────────┬─────────────────────────────┬───────────────┘
                │                             │
        ┌───────▼───────┐             ┌───────▼───────┐
        │   pi_agent    │             │    pi_tui     │
        │ Agent SDK     │             │ Textual UI    │
        │ agent_loop    │             │ 无 agent 逻辑 │
        └───────┬───────┘             └───────────────┘
                │
        ┌───────▼───────┐
        │    pi_llm     │
        │ LiteLLM 薄层  │
        └───────────────┘
```

| 包 | 职责 | 不应放入 |
|----|------|----------|
| `pi_llm` | 调 LiteLLM、流式 chunk、凭证、错误映射 | TUI、工具执行、会话文件 |
| `pi_agent` | 无状态 `agent_loop` + 有状态 `Agent`；事件、tool calling | 文件 IO、资源发现 |
| `pi_tui` | 可复用 Textual 组件 | Agent 编排、LLM 调用 |
| `pi_coding_agent` | 内置工具、资源、会话、`piy` 入口、TUI 接线 | 通用 agent 库逻辑（应在 pi_agent） |

**依赖方向（只允许向下）：**  
`pi_coding_agent` → `pi_agent` + `pi_tui` + `pi_llm`；`pi_agent` 不依赖 `pi_tui` / `pi_coding_agent`。

---

## 运行核心：一次 `prompt` 的路径

```text
用户输入 (EditorWidget)
    → cli._run_interactive worker
    → CodingSession.prompt(text)
         ├─ /compact → session.compact()（只写 JSONL，不调模型）
         ├─ /模板名   → expand_prompt_template()
         └─ agent.prompt(text)
              → agent_loop
                   ├─ transform_context(messages)  ← Session compaction 视图
                   ├─ convert_to_llm → StreamRequest
                   ├─ stream_fn (llm_bridge → pi_llm.stream)
                   ├─ 工具参数齐全后 execute tool
                   └─ subscribe 事件 → tui_wiring → TranscriptView
    → 新消息 append 到 Session JSONL
    → maybe_auto_compact（近窗口触发）
```

要点：

- **完整 transcript** 在 `Agent.messages` 与 Session JSONL 里；**发给模型的上下文** 经 `transform_context` 投影（compaction 后 = summary + 近期尾部）。
- **TUI 不订阅 LiteLLM 原始流**，只消费 `pi_agent` 的 `AgentEvent`（`message_*`、`tool_execution_*` 等）。

---

## 扩展点一览

### 1. 工具（Tools）

**定义位置：** `packages/pi_coding_agent/src/pi_coding_agent/tools/`

| 文件 | 工具 | 说明 |
|------|------|------|
| `read.py` | `read` | 按行窗读取 + 截断 |
| `write.py` | `write` | 整文件写 |
| `edit.py` | `edit` | 多段精确替换 |
| `bash.py` | `bash` | shell，session cwd |
| `__init__.py` | `create_builtin_tools()` | 注册入口 |

**类型定义在 `pi_agent`：**

```python
from pi_agent import AgentTool, AgentToolResult

async def execute(tool_call_id: str, args: dict, **kwargs) -> AgentToolResult:
    return AgentToolResult(content="ok")

tool = AgentTool(
    name="my_tool",
    description="What the model sees",
    parameters={"type": "object", "properties": {...}, "required": [...]},
    execute=execute,
)
```

**自定义工具（SDK / 嵌入）：**

```python
from pathlib import Path
from pi_agent import Agent
from pi_coding_agent.app import CodingSession
from pi_coding_agent.llm_bridge import make_stream_fn
from pi_coding_agent.tools import create_builtin_tools

builtin = create_builtin_tools(cwd=Path("."))
custom = AgentTool(name="grep", ..., execute=my_execute)

session = CodingSession.create(
    cwd=Path("."),
    stream_fn=make_stream_fn(model="openai/deepseek-v4-flash"),
    approve_project=True,
)
# 创建后替换 tools 列表，或在 Agent(...) 构造时传入
session.agent.tools = [*builtin, custom]
```

v1 **没有**上游 pi 的 TypeScript Extensions 运行时；自定义工具 = 构造 `AgentTool` 并传给 `Agent.tools`。

**钩子（`pi_agent`）：** `before_tool_call` / `after_tool_call` 可在 loop 配置或 Agent 上注册，用于拦截或改写工具结果（见 `pi_agent.types.BeforeToolCallResult`）。

---

### 2. Skills

**发现：** `pi_coding_agent/resources/loader.py` → `discover_skills_in_dir`

**扫描根（优先级由合并顺序决定）：**

| 路径 | 需 trust |
|------|----------|
| `~/.pi/agent/skills/` | 否 |
| `~/.agents/skills/` | 否 |
| `<project>/.pi/skills/` | 是 |
| 祖先 `.agents/skills/` | 是 |

**注入方式：** `build_system_prompt()` 把 skill 名 + description 写入 `<skills>` 块；模型用 **`read` 工具** 读 `SKILL.md` 全文。Skill 不是可执行插件。

**扩展：** 在对应目录新增 `my-skill/SKILL.md`（YAML frontmatter + 正文），无需改代码。

---

### 3. Prompt Templates

**发现：** `resources/prompts.py` — `prompts/*.md`（非递归），文件名 = `/name`。

**展开：** `CodingSession._expand_slash()`；占位符 `$1`、`$@`、`${1:-default}`（与上游同款）。

**扩展：** 在 `~/.pi/agent/prompts/` 或信任后的 `.pi/prompts/` 放 `review.md`，编辑器输入 `/review src/foo.py`。

---

### 4. Settings

**加载：** `resources/settings.py` — 全局 `~/.pi/agent/settings.json` + 项目 `.pi/settings.json` 嵌套 merge。

**v1 常用键：**

| 键 | 用途 |
|----|------|
| `skills` / `prompts` | 额外扫描路径数组 |
| `contextWindow` | 自动 compaction 窗口（默认 128000） |
| `reserveTokens` | 预留 token（默认 20000） |
| `keepRecentTokens` | compaction 后保留近期尾部（默认 800） |
| `defaultProjectTrust` | 默认是否信任项目 |
| `enableSkillCommands` | 是否暴露 skill 斜杠命令 |

---

### 5. 项目上下文（Context）

**加载：** `resources/context.py` — 沿 cwd 祖先找 `AGENTS.md` / `CLAUDE.md` 等，拼成 `project_context`。

**注入：** `build_system_prompt()` → `<project_context>`。**不受 trust 门控**（与 `.pi/skills` 不同）。

---

### 6. 项目信任（Trust）

**逻辑：** `resources/settings.py` → `resolve_project_trust`；持久化 `~/.pi/agent/trust.json`。

未信任时：**不加载** `.pi/` 与项目 `.agents/skills`；CLI `--approve` 或交互确认可放行。

---

### 7. 凭证（Credentials）

**解析：** `pi_llm/credentials.py` — 环境变量优先，其次 `~/.pi/agent/auth.json`。

**扩展 LLM 后端：** 换 `OPENAI_API_BASE` + LiteLLM model id；或实现自定义 `StreamFn` 传给 `Agent`（绕过 `make_stream_fn`）。

---

### 8. 会话与 Compaction

**存储：** `session/store.py` — `~/.pi/agent/sessions/<cwd-encoded>/*.jsonl`。

**Compaction：**

| 操作 | 行为 |
|------|------|
| 手动 `/compact [说明]` | `session.compact()` 写 compaction 条目到 JSONL |
| 自动 | `maybe_auto_compact()` 在 `prompt` 结束后按 token 估算触发 |
| 模型可见上下文 | `Agent.transform_context` → `apply_compaction_view()`：一条 summary `UserMessage` + 近期消息尾部 |

Agent **保留完整 live transcript**；只有发给模型的视图被压缩。恢复会话：`CodingSession.resume(path, ...)` 或 `piy --session <jsonl>`。

**SDK：** `SessionStore` 支持 `create` / `resume` / `list` / `branch` / `fork`（CLI 尚未全部暴露为子命令）。

---

### 9. Agent SDK（嵌入非 TUI 应用）

```python
from pi_agent import Agent
from pi_coding_agent.llm_bridge import make_stream_fn

agent = Agent(
    stream_fn=make_stream_fn(model="gpt-4o-mini"),
    system_prompt="...",
    tools=[...],
    transform_context=my_transform,  # 可选：改写发给模型的消息列表
)

unsub = agent.subscribe(lambda e: print(e.type, e))
await agent.prompt("Hello")
```

**扩展口子：**

| API | 用途 |
|-----|------|
| `transform_context` | 发给模型前的消息投影（compaction、过滤、注入） |
| `subscribe` | 事件驱动 UI / 日志 / 测试 |
| `stream_fn` | 替换 LLM 实现 |
| `tools` | 工具列表 |
| `steer` / `follow_up` | 队列语义（v1 CLI 未接键盘队列） |

---

### 10. TUI

**组件：** `pi_tui` — `CodingApp`、`TranscriptView`、`EditorWidget`。

**接线：** `pi_coding_agent/tui_wiring.py` — **唯一**把 `AgentEvent` 映射到 widget 的地方；换 UI 只需换此文件或 `bind_tui` 实现。

**扩展：** 可 `CodingApp` 子类化或自建 App，`session.bind_tui(app)` 复用事件流。

---

## v1 未实现（勿当作扩展点）

- TypeScript Extensions / npm Packages 生态
- Themes
- print / JSON / RPC 模式
- OAuth、`/login` 多厂商矩阵
- 与上游 pi session 文件互读
- 内置沙箱（bash 继承宿主权限）

详见 [`CONTEXT.md`](../CONTEXT.md) 与 [`implementation-handoff.md`](agents/implementation-handoff.md)。

## 关键文件索引

```text
packages/pi_coding_agent/src/pi_coding_agent/
  cli.py              # piy 入口
  app.py              # CodingSession、system prompt、prompt/compact
  llm_bridge.py       # make_stream_fn
  tui_wiring.py       # Agent → TUI
  tools/__init__.py   # create_builtin_tools
  resources/loader.py # load_resources
  session/store.py    # Session、compaction、JSONL

packages/pi_agent/src/pi_agent/
  agent.py            # Agent SDK
  loop.py             # agent_loop
  types.py            # AgentTool、AgentEvent、StreamFn

packages/pi_llm/src/pi_llm/
  stream.py           # LiteLLM 流式
  credentials.py      # auth.json

packages/pi_tui/src/pi_tui/
  widgets.py          # CodingApp 布局
```
