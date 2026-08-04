# TaskPanel

本地并行任务面板:每个任务独立上下文,支持普通问答与 OCR 代码审查,Web 三栏 UI。

## 快速开始
1. `npm install`(在 frontend/)并 `npm run build`
2. 复制 `.env.example` 为 `.env`,填 `TASKPANEL_LLM_*` 与 `OCR_*`
3. `npm i -g @alibaba-group/open-code-review`(OCR 依赖)
4. `uv run python run.py` → 浏览器打开 http://127.0.0.1:8470

## 配置
见 `.env.example`。数据落在 `~/.taskpanel/`(任务消息、事件、worktree、auth token)。

## 测试
`uv run pytest`
