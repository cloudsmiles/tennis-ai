// 后端 API 封装。后端固定跑在 http://localhost:8000（本地单用户工具，CORS 全开）。
import type { JobResult, ProgressEvent } from "./types";

export const BASE = "http://localhost:8000";

/** POST /api/sources：提交 B站链接，后端下载后返回 source_id 与可播放地址。 */
export async function createSource(
  url: string,
): Promise<{ source_id: string; video_url: string }> {
  const form = new FormData();
  form.append("url", url);
  const res = await fetch(`${BASE}/api/sources`, { method: "POST", body: form });
  if (!res.ok) {
    let msg = `视频提取失败（HTTP ${res.status}）`;
    try {
      const d = (await res.json()) as { detail?: string };
      if (d.detail) msg = d.detail;
    } catch {
      // 忽略解析失败，回退到通用提示
    }
    throw new Error(msg);
  }
  return (await res.json()) as { source_id: string; video_url: string };
}

/** 后端 source 视频的可播放地址（供 <video> 拖动定位）。 */
export function sourceVideoUrl(sourceId: string): string {
  return `${BASE}/api/sources/${sourceId}/video`;
}

/** POST /api/jobs：建分析任务，返回 job_id。
 *  视频来源二选一：file（本地上传）或 sourceId（B站链接已下载的 source）。
 *  cx/cy 为球员点选的视频像素坐标，clickTs 为点选时的时间戳（后端在该帧锁定
 *  并全程跟踪该球员）；startTs/endTs+strokeType 为手动模式（用户用进度条框出
 *  单个动作的时间范围：起=准备/引拍开始，止=随挥结束；后端在范围内自动找击球
 *  帧、按姿态差异选关键帧，正反手/发球均 6 帧）；skipLlm=true 只出拼贴图。 */
export async function createJob(
  source: { file?: File; sourceId?: string },
  opts: {
    cx?: number;
    cy?: number;
    clickTs?: number;
    skipLlm?: boolean;
    startTs?: number;
    endTs?: number;
    strokeType?: string;
  } = {},
): Promise<string> {
  const { cx, cy, clickTs, skipLlm = false, startTs, endTs, strokeType } = opts;
  const form = new FormData();
  if (source.file) form.append("video", source.file);
  if (source.sourceId) form.append("source_id", source.sourceId);
  if (cx !== undefined) form.append("cx", String(cx));
  if (cy !== undefined) form.append("cy", String(cy));
  if (clickTs !== undefined) form.append("click_ts", String(clickTs));
  if (startTs !== undefined) form.append("start_ts", String(startTs));
  if (endTs !== undefined) form.append("end_ts", String(endTs));
  if (strokeType !== undefined) form.append("stroke_type", strokeType);
  form.append("skip_llm", skipLlm ? "true" : "false");
  const res = await fetch(`${BASE}/api/jobs`, { method: "POST", body: form });
  if (!res.ok) {
    throw new Error(`创建任务失败（HTTP ${res.status}）`);
  }
  const data = (await res.json()) as { job_id: string };
  return data.job_id;
}

/** 订阅 GET /api/jobs/{job_id}/events 的 SSE 进度流；返回关闭函数。 */
export function streamEvents(
  jobId: string,
  cb: (e: ProgressEvent) => void,
): () => void {
  const es = new EventSource(`${BASE}/api/jobs/${jobId}/events`);
  es.onmessage = (ev: MessageEvent<string>) => {
    try {
      cb(JSON.parse(ev.data) as ProgressEvent);
    } catch {
      // 忽略无法解析的消息，保持流打开
    }
  };
  return () => es.close();
}

/** GET /api/jobs/{job_id}/result：拉取完整结果。 */
export async function getResult(jobId: string): Promise<JobResult> {
  const res = await fetch(`${BASE}/api/jobs/${jobId}/result`);
  if (!res.ok) {
    throw new Error(`获取结果失败（HTTP ${res.status}）`);
  }
  return (await res.json()) as JobResult;
}

/** 拼贴图完整 URL（montage_path 形如 "montages/action_0.jpg"）。 */
export function montageUrl(jobId: string, path: string): string {
  return `${BASE}/api/jobs/${jobId}/${path}`;
}

/** GET /api/llm/login-status：通义千问是否已登录。
 *  ensure=true 时后端会先拉起无头浏览器、依据持久 cookie 给真实状态。 */
export interface LoginStatusResult {
  logged_in: boolean;
  /** 浏览器正忙于分析等长任务、状态暂不可查（logged_in 为缓存值） */
  busy: boolean;
}

export async function getLoginStatus(ensure = false): Promise<LoginStatusResult> {
  const res = await fetch(
    `${BASE}/api/llm/login-status${ensure ? "?ensure=true" : ""}`,
  );
  if (!res.ok) {
    let msg = `查询登录状态失败（HTTP ${res.status}）`;
    try {
      const d = (await res.json()) as { detail?: string };
      if (d.detail) msg = d.detail;
    } catch {
      // 忽略解析失败，回退到通用提示
    }
    throw new Error(msg);
  }
  return (await res.json()) as LoginStatusResult;
}

export type LoginStatus =
  | "code_sent"
  | "already_logged_in"
  | "captcha"
  | "error"
  | "ok";

export interface LoginResult {
  status: LoginStatus;
  message?: string;
}

/** POST /api/llm/login/start：后端无头页面填手机号并请求短信验证码。 */
export async function loginStart(phone: string): Promise<LoginResult> {
  const res = await fetch(`${BASE}/api/llm/login/start`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ phone }),
  });
  if (!res.ok) {
    throw new Error(`请求验证码失败（HTTP ${res.status}）`);
  }
  return (await res.json()) as LoginResult;
}

/** POST /api/llm/login/verify：提交短信验证码完成登录。 */
export async function loginVerify(code: string): Promise<LoginResult> {
  const res = await fetch(`${BASE}/api/llm/login/verify`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ code }),
  });
  if (!res.ok) {
    throw new Error(`登录失败（HTTP ${res.status}）`);
  }
  return (await res.json()) as LoginResult;
}
