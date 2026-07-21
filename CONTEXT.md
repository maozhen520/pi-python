# pi-python

Python 实现对齐 [earendil-works/pi](https://github.com/earendil-works/pi) 的语义与扩展模型：薄 LLM 对接、agent runtime、TUI、可日常使用的 coding CLI。

## Language

**Destination**:
交付与上游语义/扩展模型对齐、API 按 Python 习惯自洽的完整实现：薄 LLM 对接层、agent runtime、TUI、可日常改代码的交互式 coding CLI。`orchestrator` 与 chat 不在范围内。
_Avoid_: 仅规格不交付；TypeScript API 逐函数兼容；完整多厂商统一层

**Thin LLM adapter**:
对外部模型的薄对接层；默认经由聚合库（如 LiteLLM）提供 agent runtime 所需的补全/工具调用/流式能力，不重做上游 `pi-ai` 级的完整多厂商统一 API。
_Avoid_: pi-ai 完整移植；自研全量 provider 矩阵

**Agent runtime**:
带 tool calling 与状态管理的 agent 循环核心，对标上游 `pi-agent-core`。
_Avoid_: agent-core（除非特指上游包名）

**Agent (SDK)**:
`pi_agent` 的有状态门面：持有 transcript/tools/队列，暴露 `prompt` / `continue` / `steer` / `follow_up`，并以按序 await 的 `subscribe` 作为事件结算屏障。
_Avoid_: 把纯 loop 当成唯一嵌入面；并发 `prompt`；让 TUI 直订 LiteLLM stream

**Agent loop**:
无状态（相对 transcript 所有权而言）的纯回合机：发事件、调 LLM 边界、执行工具；不等待消费者异步处理。
_Avoid_: 与 `Agent` 合成单一不透明对象；在 loop 层做 awaited settlement

**AgentMessage**:
Agent transcript 中的消息类型，可宽于发给模型的角色集（含自定义/UI 专用消息）。
_Avoid_: 把 transcript 限定为 provider 三角色；未经投影把自定义角色送进模型

**LLM Message**:
投影后发给模型的消息：`user` / `assistant` / `toolResult`（经 `transform_context` → `convert_to_llm`）。
_Avoid_: 与 AgentMessage 混称；在 stream 边界之外散落转换

**Coding CLI**:
可日常用来改代码的交互式命令行 agent，对标上游 `pi-coding-agent` 的主路径能力（多轮、工具、会话续跑、可用扩展点），不要求一上来对齐全部周边功能。
_Avoid_: 仅库无 CLI；功能清单 100% 对齐上游

**Built-in tools**:
默认内置工具集：`read`、`write`、`edit`、`bash`。v1：`read`（按行窗+截断）、`write`（整文件写）、`edit`（`edits[]` 精确多替换 + 可选 `replace_all`，相对原文件、唯一/不重叠、all-or-nothing，与 `write` 共 per-file 队列）、`bash`（session cwd、可选 timeout、输出截断、无沙箱）。
_Avoid_: 第一期塞满周边工具；用 gitignore/路径沙箱冒充安全边界；把 Python traceback 塞进工具结果给模型；以 unified diff/散文 SEARCH-REPLACE 作主 edit 工具；深度模糊自动套用

**Extension surface (v1)**:
第一期扩展面：可注册 tools、Skills、Prompt Templates、会话/项目配置；Themes 与可发布 Packages 后置。
_Avoid_: 第一期就要完整 Packages 生态；无扩展只能改源码

**Skill**:
按需加载的能力说明包；磁盘上为 Agent Skills 式目录（`SKILL.md` + YAML frontmatter），经发现注入目录后由模型按需 `read` 全文。
_Avoid_: 把 skill 做成可执行插件；第一期自创非 Markdown 布局

**Prompt Template**:
斜杠展开的 Markdown 提示模板；`prompts/` 下非递归 `*.md`，文件名即 `/name`，正文支持上游同款参数占位替换。
_Avoid_: 与 Skill 混为一谈；第一期另造占位语法

**Resource discovery roots**:
声明式资源的全局/项目根：`~/.pi/agent/` 与项目 `.pi/`（项目侧经 trust）；Skills 另兼扫 `~/.agents/skills/` 与祖先 `.agents/skills/`；可用 settings 路径数组与 CLI 附加/关闭。
_Avoid_: 默认改用 `~/.piy` / `.piy`；把 Packages 安装当成发现前提

**Settings**:
全局/项目 JSON 配置：`~/.pi/agent/settings.json` 与 `.pi/settings.json`，嵌套 merge（项目覆盖全局）；v1 认 `skills` / `prompts` / `defaultProjectTrust` / `enableSkillCommands`。
_Avoid_: 另起 `piy.toml` 作为默认；v1 就实现 themes/packages 键语义

**Project trust**:
加载项目 `.pi` 资源与项目 `.agents/skills` 前的许可门；决定持久化在 `~/.pi/agent/trust.json`；交互可问，非交互默认不加载（除非已信任或 `--approve`）。
_Avoid_: 静默信任任意项目目录；把 trust 做成完整权限/沙箱系统

**Context file**:
项目说明 Markdown（每目录优先 `AGENTS.md`，否则 `CLAUDE.md` 等）；沿目录祖先收集后注入 system prompt 的 `<project_context>`。
_Avoid_: 当成第五种可安装 package 类型；与 Skill / Prompt Template 混名

**Run modes (v1)**:
第一期运行模式：interactive CLI，以及可 import 的 Python SDK；print/JSON 与 RPC 后置。
_Avoid_: 第一期四种模式齐套

**Session persistence**:
会话可续跑、可分支、按项目存放；自有 JSONL（header `version` + 消息树），默认在 `~/.pi/agent/sessions/<cwd-encoded>/`；不与上游 session 文件互读。
_Avoid_: 上游 session 格式兼容；第一期无持久化；把完整 runtime 事件流当唯一落盘内容

**Session**:
一次可持久化的对话实例：拥有 JSONL 文件与当前分支指针，负责 resume/list/branch/fork；把活跃分支消息加载进 `Agent`。
_Avoid_: 让 `Agent` 直接绑文件路径；与上游 session 文件混读

**Compaction**:
在上下文将满时把较旧消息收成摘要检查点，使模型只看到 summary + 近期尾部；自动近窗口触发与手动 `/compact`；写入自有 session JSONL 的 `compaction` 条目。
_Avoid_: 靠删改历史行冒充压缩；v1 就做 branch summarization；把 compaction 当成与上游文件互操作

**Credentials**:
调用 LiteLLM 所需的提供者密钥；解析顺序为进程环境变量优先，其次可选的 `~/.pi/agent/auth.json`；交互式 `piy` 可提示并写入该文件。
_Avoid_: v1 OAuth/订阅登录；OS keychain；把密钥写进 settings.json；在 `pi_llm` 里做 TUI 采集

**Testing strategy (v1)**:
以各包 pytest 单测为主、少量假 StreamFn 集成测为辅；`pi_llm` 用录制/手写 chunk 夹具；`pi_tui` 用轻量 Textual pilot；CI 跑 uv/lint/类型检查/pytest，不强制 live LLM。
_Avoid_: 把真 API 当合并门禁；TUI 像素金标；几乎只靠手工 dogfood

**TUI**:
终端 UI 层；建在 Textual 上，以可复用 widget/布局形式放在 `pi_tui`；对齐上游「组件 + 流式消息 + 编辑器」心智，不移植差分渲染引擎。agent 事件接线与 `piy` 入口在 `pi_coding_agent`。
_Avoid_: 网页 UI；像素级对齐上游 pi-tui；自研差分渲染；以 prompt_toolkit / Rich 单独作为应用框架；把 agent 编排焊进 `pi_tui`

**Coding CLI UI (v1)**:
交互式 `piy` 第一期界面块：可滚动 transcript、流式助手文本、工具调用展示、底部多行输入；由 agent runtime 事件驱动 widget 增量更新。
_Avoid_: v1 Themes；自定义 TUI 组件扩展；复杂权限/对话框套件；TUI 直接订阅 LiteLLM 原始 stream

**Design alignment**:
行为与扩展模型对齐上游；包结构与公开 API 按 Python 习惯自洽，不依赖上游运行时。
_Avoid_: API 兼容层；混用上游 TypeScript 包

**Package layout**:
Monorepo 内四个可独立安装的包，分别对应薄 LLM 对接、agent runtime、TUI、coding CLI。
_Avoid_: 单一巨包；把 LLM 对接焊进 runtime

**Package names**:
四包 PyPI 与 import 同形：`pi_llm`、`pi_agent`、`pi_tui`、`pi_coding_agent`。
_Avoid_: 无后缀的 `pi`；PyPI 连字符与 import 两套名字（除非另有决定）

**Monorepo directories**:
包放在 `packages/pi_*/`，各包采用 src layout。
_Avoid_: 根目录扁平多包；单 `src/` 塞满多包

**Workspace tooling**:
用 `uv` workspace 管理 monorepo（根与各包 `pyproject.toml`）。
_Avoid_: Poetry multiproject 作为默认；无 workspace 手工 path 依赖

**CLI entrypoint**:
coding CLI 的控制台命令名为 `piy`（由 `pi_coding_agent` 提供）。
_Avoid_: `pi`（易与他物冲突时仍可用 `piy`）；把入口挂在非 coding 包上
