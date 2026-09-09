# 人工验证清单

以下检查依赖真实视频、真实浏览器与已登录的通义千问账号，无法自动化，需要使用者 / 开发者手动跑一遍。

## 1. 后端启动与基础接口

- [ ] `cd backend && ./.venv/bin/uvicorn app.main:app --port 8000` 能正常启动，无异常堆栈。
- [ ] `curl http://localhost:8000/api/health` 返回 ok。
- [ ] `curl http://localhost:8000/api/llm/login-status` 在未登录时返回 `false`，且不报错。

## 2. 首次登录

- [ ] 触发登录（前端点击分析，或 `POST /api/llm/login`），弹出 Chromium 窗口。
- [ ] 在弹出的窗口中完成通义千问登录（扫码或账号密码）。
- [ ] 确认 `backend/.pw-data` 目录已创建。
- [ ] 再次查询 `/api/llm/login-status`，返回值变为 `true`。

## 3. 核对选择器

- [ ] 在已登录的 tongyi.com 页面打开 DevTools，逐项核对 `backend/app/llm/selectors.py`：
  - [ ] `upload_button`（`input[type=file]`）
  - [ ] `chat_input`
  - [ ] `send_button`
  - [ ] `stop_button`
  - [ ] `reply_block`
- [ ] 与实际页面不符的选择器就地修正，只改这一个文件。

## 4. 真实视频跑通 CV 管线

- [ ] 准备一段较短的真实网球片段（固定机位：侧面 / 背面 / 斜角均可，球员完整出现在画面内）。
- [ ] 通过前端界面上传该视频。
- [ ] 首帧出现后点选要分析的球员（或点击「跳过自动选择」）。
- [ ] 确认 `backend/jobs/<job_id>/montages/` 下生成了拼贴图 JPG。
- [ ] 确认 `backend/jobs/<job_id>/result.json` 已写入。

## 5. 大模型分析与前端展示

- [ ] 确认自动化流程把每张拼贴图都上传到了通义千问。
- [ ] 确认返回内容能被解析为结构化 JSON：`stroke_type` / 各分项评分 / `overall` / `issues` / `advice`。
- [ ] 确认前端结果页正确渲染了每个动作卡片。
- [ ] 验证错误分支：
  - [ ] 上传一段没有人的视频 → 提示「未检测到球员」。
  - [ ] 在未登录状态下发起分析 → 出现登录提示，而不是静默失败。
