// 第 3 步：分析进度（进度条 + 最新一条 stage/message）。
import type { CSSProperties } from "react";
import { h2, muted } from "./styles";

interface ProgressProps {
  progress: number; // 0-100
  stage: string;
  message: string;
}

const trackStyle: CSSProperties = {
  width: "100%",
  height: 18,
  borderRadius: 9,
  background: "#ececec",
  overflow: "hidden",
  margin: "16px 0 12px",
};

export default function Progress({ progress, stage, message }: ProgressProps) {
  const pct = Math.max(0, Math.min(100, Math.round(progress)));
  return (
    <div style={{ maxWidth: 720 }}>
      <h2 style={h2}>第 3 步 · 分析中…</h2>
      <div style={trackStyle} role="progressbar" aria-valuenow={pct} aria-valuemin={0} aria-valuemax={100}>
        <div
          style={{
            width: `${pct}%`,
            height: "100%",
            background: "#2f6f3f",
            borderRadius: 9,
            transition: "width 0.3s ease",
          }}
        />
      </div>
      <p style={{ margin: "0 0 8px", fontSize: 15 }}>
        {pct}%{message ? ` — ${message}` : ""}
        {stage ? <span style={{ color: "#999" }}>（{stage}）</span> : null}
      </p>
      <p style={muted}>
        视频检测与大模型分析可能需要几分钟，请保持本页面打开。登录窗口若在服务端弹出，请完成登录后重新分析。
      </p>
    </div>
  );
}
