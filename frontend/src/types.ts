// 后端 API 数据结构，与 backend/app/schemas.py 及各路由的 JSON 对齐。

export type JobStatus = "queued" | "running" | "done" | "error";

/** parse_failed：回复无法解析为 JSON，raw_reply 保留模型原文供展示 */
export type ActionStatus = "ok" | "pending" | "parse_failed" | "failed";

/** 单次挥拍动作的记录（含大模型分析结果）。 */
export interface ActionRecord {
  action_id: number;
  /** 挥拍峰值时间戳（秒） */
  peak_ts: number;
  /** 相对 job 目录的拼贴图路径，如 "montages/action_0.jpg" */
  montage_path: string;
  /** 叠加检测标注（球员框/球拍框/手腕/跟踪点）的调试版拼贴 */
  debug_montage_path?: string | null;
  /** 本地检测疑似发球 */
  suspected_serve: boolean;
  status: ActionStatus;
  /** forehand | backhand | serve | null（未知） */
  stroke_type: string | null;
  /** NTRP 风格评级（"2.0"~"5.0"），旧记录可能为空 */
  level?: string | null;
  /** 定级理由 */
  level_note?: string | null;
  /** 优点 */
  strengths?: string[] | null;
  /** 缺点 / 待改进点（旧记录字段名为 issues） */
  weaknesses?: string[] | null;
  advice?: string | null;
  /** 大模型原始回复（失败时展示给用户） */
  raw_reply: string;
}

/** GET /api/jobs/{job_id}/result 的响应。 */
export interface JobResult {
  job_id: string;
  status: JobStatus;
  progress: number;
  stage: string;
  message: string;
  actions: ActionRecord[] | null;
  /** 后端额外字段（本地文件路径），前端不使用 */
  video_path?: string;
}

/** SSE 事件：data: {"progress":0-100,"stage":"...","message":"..."}。
 *  后端异常路径可能省略 progress，故设为可选。 */
export interface ProgressEvent {
  progress?: number;
  stage: string;
  message: string;
}
