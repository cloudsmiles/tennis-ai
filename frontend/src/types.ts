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
  /** 本地检测疑似发球 */
  suspected_serve: boolean;
  status: ActionStatus;
  /** forehand | backhand | serve | null（未知） */
  stroke_type: string | null;
  /** 分项得分，键为中文维度名（"准备"/"击球点"/"随挥"…） */
  scores: Record<string, number> | null;
  /** 总分（0-10） */
  overall: number | null;
  issues: string[] | null;
  advice: string | null;
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
