// 第 4 步：展示每个动作的拼贴图与通义千问的评分 / 问题 / 建议。
import { montageUrl } from "../api";
import type { ActionRecord, JobResult } from "../types";
import { card, h2, muted } from "./styles";

const STROKE_LABELS: Record<string, string> = {
  forehand: "正手",
  backhand: "反手",
  serve: "发球",
};

/** 动作类型 → 中文；未知值原样展示 */
function strokeLabel(t: string | null): string {
  if (!t) return "未识别";
  return STROKE_LABELS[t] ?? t;
}

function OkBody({ a }: { a: ActionRecord }) {
  const entries = Object.entries(a.scores ?? {});
  return (
    <div>
      <p style={{ margin: "0 0 6px" }}>
        <strong>
          总分：{a.overall != null ? `${a.overall.toFixed(1)} / 10` : "—"}
        </strong>
      </p>
      {entries.length > 0 ? (
        <p style={{ margin: "0 0 6px" }}>
          分项：{entries.map(([k, v]) => `${k} ${v}`).join("，")}
        </p>
      ) : null}
      {a.issues && a.issues.length > 0 ? (
        <div style={{ margin: "0 0 6px" }}>
          主要问题：
          <ul style={{ margin: "4px 0 8px", paddingLeft: 22 }}>
            {a.issues.map((s, i) => (
              <li key={i}>{s}</li>
            ))}
          </ul>
        </div>
      ) : null}
      {a.advice ? (
        <p style={{ margin: "0 0 4px" }}>
          <strong>建议：</strong>
          {a.advice}
        </p>
      ) : null}
    </div>
  );
}

function FailedBody({ a }: { a: ActionRecord }) {
  // parse_failed：模型回复无法解析为结构化结果，但仍展示原文（spec §4）
  const parseFailed = a.status === "parse_failed";
  return (
    <div>
      <p style={{ margin: "0 0 6px", color: "#c0392b" }}>
        {parseFailed
          ? "该动作的模型回复无法解析为结构化结果，以下为原文："
          : "该动作分析失败。"}
      </p>
      {a.raw_reply ? (
        <pre
          style={{
            margin: 0,
            padding: 8,
            background: "#f7f7f5",
            borderRadius: 6,
            fontSize: 13,
            whiteSpace: "pre-wrap",
            wordBreak: "break-word",
          }}
        >
          {a.raw_reply}
        </pre>
      ) : null}
    </div>
  );
}

function ActionCard({ jobId, a }: { jobId: string; a: ActionRecord }) {
  return (
    <div style={card}>
      <img
        src={montageUrl(jobId, a.montage_path)}
        alt={`动作 ${a.action_id + 1} 关键帧拼贴`}
        style={{ width: "100%", borderRadius: 6, display: "block" }}
      />
      <h3 style={{ margin: "12px 0 8px", fontSize: 17 }}>
        动作 {a.action_id + 1}（{a.peak_ts.toFixed(1)}s）· {strokeLabel(a.stroke_type)}
      </h3>
      {a.status === "ok" ? (
        <OkBody a={a} />
      ) : a.status === "pending" ? (
        <p style={{ ...muted, margin: 0 }}>待分析</p>
      ) : (
        <FailedBody a={a} />
      )}
    </div>
  );
}

export default function Results({ job }: { job: JobResult | null }) {
  // 结果可能尚未加载完成（或加载失败），保持健壮
  if (!job) {
    return (
      <div style={{ maxWidth: 860 }}>
        <h2 style={h2}>分析结果</h2>
        <p style={muted}>正在加载结果…</p>
      </div>
    );
  }

  const actions = job.actions ?? [];

  return (
    <div style={{ maxWidth: 860 }}>
      <h2 style={h2}>第 4 步 · 分析结果</h2>
      {job.status === "error" ? (
        <p style={{ margin: "0 0 16px", color: "#c0392b", fontWeight: 600 }}>
          分析出错：{job.message || "未知错误"}
        </p>
      ) : null}
      {actions.length === 0 ? (
        <p style={muted}>没有检测到挥拍动作。</p>
      ) : (
        actions.map((a) => <ActionCard key={a.action_id} jobId={job.job_id} a={a} />)
      )}
    </div>
  );
}
