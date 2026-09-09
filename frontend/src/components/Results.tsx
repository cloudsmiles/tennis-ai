// 第 4 步：展示每个动作的拼贴图与通义千问的评分 / 问题 / 建议。
import { useState } from "react";
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

/** 评级徽标配色：等级越高越绿 */
function levelColor(level: string): { bg: string; fg: string } {
  const v = parseFloat(level);
  if (!isFinite(v)) return { bg: "#eef2ff", fg: "#3730a3" };
  if (v >= 4.0) return { bg: "#dcfce7", fg: "#166534" };
  if (v >= 3.0) return { bg: "#dbeafe", fg: "#1e40af" };
  return { bg: "#fef3c7", fg: "#92400e" };
}

function PointList({
  title,
  items,
  color,
}: {
  title: string;
  items: string[];
  color: string;
}) {
  if (!items.length) return null;
  return (
    <div style={{ marginBottom: 10 }}>
      <p style={{ margin: "0 0 4px", fontWeight: 700, color }}>{title}</p>
      <ul style={{ margin: 0, paddingLeft: 20, lineHeight: 1.7 }}>
        {items.map((s, i) => (
          <li key={i}>{s}</li>
        ))}
      </ul>
    </div>
  );
}

function OkBody({ a }: { a: ActionRecord }) {
  const strengths = a.strengths ?? [];
  const weaknesses = a.weaknesses ?? [];
  const lc = a.level ? levelColor(a.level) : null;
  return (
    <div>
      {a.level ? (
        <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 8 }}>
          <span
            style={{
              display: "inline-flex",
              alignItems: "center",
              padding: "4px 14px",
              borderRadius: 999,
              fontSize: 18,
              fontWeight: 800,
              background: lc!.bg,
              color: lc!.fg,
            }}
          >
            {a.level}
          </span>
          <span style={{ fontSize: 13, color: "#6b7280" }}>
            NTRP 风格综合评级
          </span>
        </div>
      ) : null}
      {a.level_note ? (
        <p style={{ margin: "0 0 10px", lineHeight: 1.7 }}>{a.level_note}</p>
      ) : null}
      <PointList title="优点" items={strengths} color="#15803d" />
      <PointList title="缺点与改进点" items={weaknesses} color="#b45309" />
      {a.advice ? (
        <div
          style={{
            background: "#eff6ff",
            border: "1px solid #bfdbfe",
            borderRadius: 10,
            padding: "10px 14px",
            marginTop: 4,
          }}
        >
          <p style={{ margin: "0 0 4px", fontWeight: 700, color: "#1d4ed8" }}>
            训练建议
          </p>
          <p style={{ margin: 0, lineHeight: 1.7 }}>{a.advice}</p>
        </div>
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
  const [showDebug, setShowDebug] = useState(false);
  const debugSrc =
    a.debug_montage_path && showDebug
      ? montageUrl(jobId, a.debug_montage_path)
      : montageUrl(jobId, a.montage_path);
  return (
    <div style={card}>
      <img
        src={debugSrc}
        alt={`动作 ${a.action_id + 1} 关键帧拼贴`}
        style={{ width: "100%", borderRadius: 6, display: "block" }}
      />
      {a.debug_montage_path ? (
        <label
          style={{
            display: "inline-flex",
            alignItems: "center",
            gap: 6,
            margin: "8px 0 0",
            fontSize: 13,
            color: "#555",
            cursor: "pointer",
          }}
        >
          <input
            type="checkbox"
            checked={showDebug}
            onChange={(e) => setShowDebug(e.target.checked)}
          />
          显示识别标注（绿=球员框，橙=球拍，蓝=手腕，红叉=跟踪点）
        </label>
      ) : null}
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
