// 后端 API 封装。后端固定跑在 http://localhost:8000（本地单用户工具，CORS 全开）。
import type { JobResult, ProgressEvent } from "./types";

export const BASE = "http://localhost:8000";

/** POST /api/jobs：上传视频（可选球员点选，cx/cy 为视频像素坐标），返回 job_id。 */
export async function createJob(
  file: File,
  cx?: number,
  cy?: number,
): Promise<string> {
  const form = new FormData();
  form.append("video", file);
  if (cx !== undefined) form.append("cx", String(cx));
  if (cy !== undefined) form.append("cy", String(cy));
  const res = await fetch(`${BASE}/api/jobs`, { method: "POST", body: form });
  if (!res.ok) {
    throw new Error(`上传失败（HTTP ${res.status}）`);
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

/** GET /api/llm/login-status：通义千问是否已登录。 */
export async function getLoginStatus(): Promise<boolean> {
  const res = await fetch(`${BASE}/api/llm/login-status`);
  if (!res.ok) {
    throw new Error(`查询登录状态失败（HTTP ${res.status}）`);
  }
  const data = (await res.json()) as { logged_in: boolean };
  return data.logged_in;
}

/** POST /api/llm/login：在服务端弹出浏览器窗口供用户登录。 */
export async function login(): Promise<void> {
  const res = await fetch(`${BASE}/api/llm/login`, { method: "POST" });
  if (!res.ok) {
    throw new Error(`打开登录窗口失败（HTTP ${res.status}）`);
  }
}
