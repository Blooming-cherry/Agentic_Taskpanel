# TaskPanel Web —— 并行任务面板设计规格

- **日期**: 2026-08-04
- **状态**: 已批准
- **目标**: 复刻 Codex 桌面端任务面板体验的本地 Web 面板,并行运行多个相互隔离的 AI agent 任务,从根本上避免"多任务串行导致上下文窗口挤占"。

## 1. 背景与目标

用户在 CLI 下使用 Claude Code 进行多个任务时,遇到两个问题:

1. **上下文挤占**:不同任务在同一个会话里串行执行,历史不断累积,上下文被相互占用。
2. **任务隔离缺失**:没有 Codex 桌面端那样的"任务面板"——多任务并行、各自独立上下文、随时切换查看。

**结论**: 不采用 Claude Code 原生的子代理/会话方案作为唯一手段,而是自建一个本地 Web 面板,复刻 Codex 桌面端的三栏布局与"并行线程"心智。

**关键前提**: 用户的后端是 **DeepSeek,通过 Anthropic 兼容端点映射**(非 Anthropic 官方 API)。因此:

- **Managed Agents(Anthropic 服务端托管会话)不可用**。
- 上下文隔离由面板自行实现:**每个任务各自维护一份独立的消息历史**,在本地。
- 模型调用走 Anthropic 兼容的 `/v1/messages` 协议(经 SDK 或裸 HTTP)。

## 2. 架构总览

```
taskpanel/
├── taskpanel-core/          # 纯逻辑,无 UI,可单测
│   ├── llm.py               # LLMClient 接口 + 双实现 + 能力探测
│   ├── agent_loop.py        # AgentLoop:每任务独立消息历史的工具循环
│   ├── task.py              # Task 状态机
│   ├── tools/               # 内置工具:文件 / bash / OCR
│   └── config.py            # 配置加载(base_url/api_key/model/并发)
├── taskpanel-store/         # 持久化
│   ├── store.py             # JSONL 消息 + meta.json + 恢复
│   └── worktree.py          # git worktree 隔离
├── taskpanel-web/           # Web 视图层
│   ├── server.py            # FastAPI + WebSocket
│   └── frontend/            # React + Vite 前端
└── docs/superpowers/specs/  # 本规格
```

三个单元职责单一、通过明确定义的接口通信,可独立理解和测试。

## 3. taskpanel-core

### 3.1 LLMClient(接口)

```
interface LLMClient:
    async def chat_stream(messages, tools) -> AsyncIterator[LLMEvent]
    async def probe_capabilities() -> Capabilities
```

- **`AnthropicSDKClient`**: 用 `anthropic` SDK,`base_url` 指向 DeepSeek 映射端点,`Anthropic` 协议流式。
- **`RawHTTPClient`**: 直接 `httpx` POST `{base_url}/v1/messages`,兜底(当 shim 与 SDK 流式协议不兼容时)。
- **能力探测 `probe_capabilities()`**: 建任务时发一条带工具定义的测试消息,检测:
  - `tool_use` 支持: 模型能发起工具调用并正确回传 → 启用工具集。
  - 不支持 → **自动降级为纯文本问答**(无工具)。
- 选实现: 默认走 `AnthropicSDKClient`;若探测/运行时报协议错,回退 `RawHTTPClient`。

### 3.2 AgentLoop

- 每个任务一个 `AgentLoop` 实例,维护**独立的消息历史** `messages: list[dict]`。
- 循环:
  1. 发送 `messages` + 可用工具 → 流式接收。
  2. 若返回 `tool_use` → 执行工具(异步,不阻塞其它任务)→ 把结果作为 tool_result 回填 → 回到 1。
  3. 若无 `tool_use` → 任务结束,输出最终回复。
- 上限: 单任务最大工具循环轮数(默认 20),防死循环。
- 流式事件(文本增量 / tool_use / tool_result / 完成)推给调度层 → WebSocket → 前端。

### 3.3 Task 状态机

```
queued → running → (waiting_tool) → done
                ↘ paused → running        # 用户打断生成,保留上下文
                ↘ error → (可重试 running)
                ↘ stopped                  # 用户终止,不可续
```

字段: `id`、`title`(自动,取首条消息前 30 字,可改名)、`kind`(`project` / `chat`)、`prompt`、`cwd`、`worktree`(可选)、`messages`、`status`、`token_count`、`created_at`、`updated_at`、`error`。

### 3.4 任务类型(复刻 Codex 的 Project / Chat)

- **`project`**: 绑定一个仓库目录,可读写文件、跑脚本、做 OCR review;**可选 git worktree 隔离**(见 §5),多个 project 任务同仓库并发互不污染。
- **`chat`**: 不绑定目录,纯问答/研究,工具受限(不写文件)。

### 3.5 内置工具集

| 工具 | 说明 | 权限 |
|---|---|---|
| `read_file` | 读文件 | project 内 / 白名单 |
| `write_file` | 写文件 | 仅 project 任务 |
| `bash` | 运行脚本/命令 | 受 `cwd` 约束,默认禁破坏性命令 |
| `ocr_review` | 见 §4 | 仅 project 任务 |
| `web`(可选) | HTTP 抓取 | v1 可选,默认关 |

工具执行隔离在任务 `cwd`/worktree 内;`write_file`/`bash` 默认仅 `project` 任务、仅工作区目录。

## 4. OCR 集成(alibaba/open-code-review)

项目: [`github.com/alibaba/open-code-review`](https://github.com/alibaba/open-code-review),Apache-2.0,CLI 包 `@alibaba-group/open-code-review`(`ocr` 命令)。要求 **Git ≥ 2.41**(本机 2.54 ✓),支持 Windows ✓,支持 **Anthropic 兼容端点** ✓。

### 4.1 接入模式

- **OCR-managed(主)**: 面板把 `ocr` 作为子进程任务运行,OCR 自己调用配置好的 LLM(指向 DeepSeek 映射)。
  - 命令: `ocr review --audience agent --background "<业务上下文>" [--commit X | --from A --to B]`;`ocr scan --path <dir>` 整文件审计。
  - 环境变量: `OCR_LLM_URL=<base_url>/v1/messages`、`OCR_LLM_TOKEN`、`OCR_LLM_MODEL`、`OCR_USE_ANTHROPIC=true`。
  - 前置校验: 启动时 `ocr llm test`。
  - 结果: `ocr session comments --json <session-id>` 解析为结构化 line-level 发现列表。
- **Delegation 模式(二期)**: 把 `ocr delegate preview` / `ocr delegate rule` 封装成 agent 工具,让通用 agent 任务借用 OCR 的确定性文件选择 + 规则解析做 review(宿主 = 面板的 agent,OCR 不配置 LLM)。

### 4.2 Review 任务输出

- 面板右栏 **Review 面板**展示: 发现列表(严重级 High/Medium/Low 筛选)、文件/行号锚点、对应 diff 预览。
- 支持一键在发现与 diff 之间跳转(二期: 逐条接受/拒绝)。

## 5. 并行与隔离

- **默认全并行**(对齐 Codex 心智): 新任务不排队。可选配置 `max_parallel` 限制并发,超出排队 `queued`。
- **每任务独立消息历史** → 上下文天然隔离,互不挤占。
- **worktree 隔离**: project 任务可选 `worktree: true`,创建独立 `git worktree`(detached HEAD)作为任务 cwd,多个改码/审查任务同仓库并行不冲突。任务结束后按需保留或清理。
- 全局"共享记忆"目录 `~/.taskpanel/shared/`: 任务间显式交换信息,默认关闭。

## 6. taskpanel-store(持久化)

- 每任务 `~/.taskpanel/tasks/<id>/`:
  - `messages.jsonl`: 每轮消息即写(流式增量落盘)。
  - `meta.json`: 状态、标题、kind、cwd、worktree、token、时间戳。
- 启动时扫描已有任务,`resume` 恢复: 恢复状态与消息历史,可继续 follow-up 或重跑。
- 崩溃安全: JSONL 每轮写入,重启自动恢复。

## 7. taskpanel-web(视图层)

### 7.1 后端

- **FastAPI + uvicorn**,绑定 `127.0.0.1`(仅本机,免鉴权)。
- REST 端点:
  - `POST /api/tasks` 新建任务(`kind`、`prompt`、`cwd`、`worktree`)
  - `GET /api/tasks` 列表
  - `GET /api/tasks/{id}` 详情
  - `POST /api/tasks/{id}/messages` follow-up 续聊
  - `POST /api/tasks/{id}/stop` 终止 / `pause` 打断
  - `DELETE /api/tasks/{id}` 删除
  - `GET /api/tasks/{id}/review` OCR 发现
- **WebSocket `/ws/tasks`**: 推送任务状态变更与流式输出事件(增量文本 / tool_use / tool_result / status)。
- 配置: `config.toml` 或环境变量 —— `[llm] base_url/api_key/model`、`[ocr] env` 透传、`[panel] max_parallel/bind/host`。

### 7.2 前端(React + Vite)

三栏布局,复刻 Codex 桌面:

```
┌──────────────┬──────────────────────────┬─────────────┐
│ 左栏         │ 中栏(对话流)             │ 右栏         │
│ · New Task   │ · 选中任务流式输出        │ · Review 面板│
│ · Search     │ · 底部输入框(follow-up)  │  · 发现列表  │
│ · 任务列表   │                          │  · diff 预览 │
│  (project/   │                          │  (可折叠)    │
│   chat 分组) │                          │             │
├──────────────┴──────────────────────────┴─────────────┤
│ 状态栏: 当前分支 / 累计 token / 任务计数 / 后端连接      │
└────────────────────────────────────────────────────────┘
```

- 交互: 点击任务切换(不中断运行)、`Ctrl+N` 新建、`Ctrl+K` 搜索、`Esc` 折叠右栏、状态徽标(运行/排队/完成/错误)。
- 流式渲染: 通过 WebSocket 增量更新;tool_use 以可折叠卡片展示(调用了哪个工具、入参、结果)。
- 技术: React 18 + Vite,构建产物由 FastAPI 静态托管,浏览器打开 `http://127.0.0.1:<port>`。
- 二期可选: 用 Electron 包装成真正桌面壳(先浏览器跑通)。

## 8. 错误处理

- **API 失败/超时**: 指数退避重试(最多 3 次)→ 仍失败标记 `error`,保留上下文可重试。
- **工具执行失败**: 把错误信息作为 `tool_result` 回填给模型继续。
- **shim 协议不兼容**: 自动从 `AnthropicSDKClient` 回退 `RawHTTPClient`;tool_use 不支持则降级纯文本。
- **面板崩溃**: JSONL 每轮落盘,重启自动恢复。

## 9. 测试

- **core 单测**: 状态机转换、AgentLoop 工具分支(fake LLM 响应)、store 往返、能力探测 mock、config 加载。
- **API 测试**: FastAPI 端点 CRUD + WebSocket 事件(mock LLM)。
- **OCR 冒烟**: 对一个小 git 仓库实际跑 `ocr llm test` + `ocr review`。
- **前端冒烟**: 起后端 + `npm run build` + 打开页面验证三栏渲染与任务创建。

## 10. 范围与延迟项

**v1 包含**: 普通问答任务、OCR review 任务、并行隔离、worktree 隔离、follow-up 续聊、自动标题、JSONL 持久化恢复、三栏 Web UI、能力探测与降级。

**明确延迟(不在 v1)**:
- Automations(定时任务)、Plugins 市场、拖拽排序、Cloud 模式。
- Electron 桌面壳包装。
- OCR Delegation 模式(作为通用 agent 工具)。
- Review 发现的逐条接受/拒绝(需写回代码)。
- 多用户/远程访问。

## 11. 技术栈清单

- Python 3.11+、uv
- FastAPI + uvicorn + websockets
- anthropic SDK(可选,仅作 HTTP 客户端)+ httpx
- React 18 + Vite
- npm(`@alibaba-group/open-code-review`,OCR)
- git ≥ 2.41(已满足)

## 12. 成功标准

1. 面板里同时跑 ≥3 个任务(含 1 个 OCR review),各任务上下文互不干扰。
2. 任务间切换查看不中断运行;follow-up 能继续独立上下文。
3. 重启面板后任务可恢复。
4. OCR review 结果在右栏以结构化发现展示。
5. DeepSeek 映射不支持 tool_use 时,自动降级且仍能完成纯文本问答。
