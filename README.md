# 网球视频动作分析工具

本地运行、个人自用的网球视频分析工具。上传一段自己练球/对打的视频（手机或相机固定机位，侧面 / 背面 / 斜角均可），工具会自动检测并跟踪画面中的球员，从整段视频里挑出 2~3 个拍摄效果最清晰的击球动作，为每个动作生成一张"准备(引拍) / 击球 / 随挥"三帧拼贴图；然后通过浏览器自动化（Playwright）把拼贴图上传到**通义千问网页版**（tongyi.com，模拟人工操作，**不调用收费 API**），由大模型判定动作类型（正手 / 反手 / 发球）、给出量化评分与技术纠错建议，最后回传前端按动作卡片展示。

## 目录结构

```
backend/app/
  config.py            全局可调参数（抽帧率、择优数量、峰值阈值、LLM 重试等）
  schemas.py           数据结构定义（FrameDet / SwingEvent / JobResult 等）与序列化
  storage.py           job 目录管理、result.json 落盘与读取
  jobs.py              JobManager：后台线程执行管线、记录进度、向 SSE 推送事件
  pipeline.py          完整管线编排：抽帧 → 检测 → 择优 → 拼贴图 → 大模型分析
  main.py              FastAPI 应用入口，注册各路由与 CORS
backend/app/cv/
  frames.py            OpenCV 按指定 fps 抽帧，保留帧序号与时间戳
  detect.py            YOLO 检测/跟踪集成层：person 跟踪 + 球拍检测 + 手腕关键点
  geometry.py          几何工具：框中心、面积、边缘距离、速度计算
  keyframes.py         由速度峰值推导「准备 / 击球 / 随挥」三帧与裁剪框
  quality.py           候选击球点质量打分（置信度、人物框大小、峰值锐度等）
  select.py            按回合分组、去重，选出 2~3 个最优且时间分散的动作
  montage.py           把三帧裁剪图横向拼成一张带阶段标注的拼贴图
backend/app/llm/
  browser.py           常驻 Playwright Chromium 会话（单 owner 线程 marshal 调用）
  tongyi.py            通义千问网页自动化：上传图片、发送提问、抓取回复、串行队列
  parse.py             从模型回复文本中提取并解析结构化 JSON
  prompts.py           发给大模型的分析提示词
  selectors.py         通义千问网页 CSS 选择器（网页改版时只改这一个文件）
backend/app/routes/
  upload.py            POST /api/jobs 上传视频、创建任务
  progress.py          GET /api/jobs/{id}/events 进度 SSE 流
  results.py           GET /api/jobs/{id}/result 结果、/montages/{name} 拼贴图
  session.py           GET /api/llm/login-status 登录状态、POST /api/llm/login 触发登录
frontend/src/          React + Vite + TS 前端：上传、球员点选、进度、结果卡片
```

## 环境依赖与安装（macOS）

**必须使用 Python 3.11**。本项目用 python3.11 虚拟环境构建：Python 3.14 没有 torch 轮子，而本机为 x86_64 Mac，使用 torch 2.2.2 的 CPU-only 版本。

后端：

```
cd backend
python3.11 -m venv .venv
./.venv/bin/pip install -r requirements.txt
./.venv/bin/playwright install chromium
```

说明：

- `requirements.txt` 同时锁定了 `opencv-python` 与 `opencv-python-headless` 到 `4.10.*`（4.14 在本机没有可用轮子）。
- YOLO 跟踪器需要 `lap` 包；若 `pip install lap` 源码编译失败，程序会自动改用内置的 scipy 兜底实现，**无需手动处理**。

前端：

```
cd frontend && npm install
```

## 运行

后端：

```
cd backend && ./.venv/bin/uvicorn app.main:app --port 8000
```

前端：

```
cd frontend && npm run dev
```

然后打开终端里打印的 localhost 地址（Vite，通常是 5173）。前端会访问后端 `http://localhost:8000`。

## 首次使用必读（浏览器自动化）

- 首次使用时，在界面上点击「分析」。如果通义千问尚未登录，程序会提示你，并弹出一个 Chromium 窗口——**手动登录一次**（扫码或账号密码即可）。登录态保存在 `backend/.pw-data/`（Playwright 持久化用户目录），之后运行会自动复用。
- **重要**：`backend/app/llm/selectors.py` 里的 CSS 选择器是**初始猜测值**。登录后如果分析卡住超时、或页面结构与预期不符，请在 tongyi.com 打开 DevTools，核对并修正该文件中的选择器（`upload_button` 的 `input[type=file]`、`chat_input`、`send_button`、`stop_button`、`reply_block`）。这一步需要手动完成，改这一个文件即可。
- 浏览器以 headful 模式运行（会看到一个可见的 Chromium 窗口）。**分析过程中不要关闭它**；若被关闭，下次动作时会自动重新启动浏览器（可能需要重新登录）。

## 使用流程

上传视频 → （画面中有多人时）点选要分析的球员，或点击「跳过自动选择」 → 等待进度（检测… → 择优… → 大模型分析 n/m） → 结果页展示每个动作的三帧拼贴图、动作类型（正手 / 反手 / 发球）、总分与各项分项评分、问题点与改进建议。

## 可调参数

全部集中在 `backend/app/config.py`：

| 参数 | 默认值 | 含义 |
| --- | --- | --- |
| `extract_fps` | 15 | 抽帧帧率 |
| `target_actions` | 3 | 择优保留的动作数（2~3） |
| `rally_gap_seconds` | 6 | 超过该间隔视为不同回合 |
| `speed_smooth_window` | 5 | 速度滑动平均窗口（帧） |
| `peak_prominence_ratio` | 1.8 | 峰值需 ≥ 基线速度的该倍数 |
| `crop_margin_ratio` | 0.15 | 裁剪边距（相对人物框尺寸） |
| `llm_max_retries` / `llm_min_delay_s` / `llm_max_delay_s` | 2 / 2.0 / 5.0 | 大模型请求重试次数与操作间隔 |

## 已知限制

- 仅 CPU 推理，长视频很慢，建议只上传较短的片段。抽出的所有帧都保存在内存中。
- 动作类型完全由通义千问模型判定，**本地没有动作分类器**；如果通义千问不可用或选择器失效，对应动作会被标记为分析失败。
- 浏览器自动化依赖 tongyi.com 的页面结构与已登录的会话，站点改版会导致失效，且可能与站点服务条款冲突——**仅供个人本地使用**。
- 没有数据库，任务产物直接落在 `backend/jobs/<job_id>/` 下（原视频、`montages/`、`result.json`）。

## 开发 / 测试

后端纯逻辑单元测试（离线，不联网、不加载模型）：

```
cd backend && ./.venv/bin/pytest tests/ -q
```

共 34 个用例。YOLO 检测与通义千问浏览器自动化属于集成层，需手动验证，不在 CI 覆盖范围内，详见 `docs/manual-verification-checklist.md`。
