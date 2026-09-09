// 第 3 步：分析进度（进度条 + 最新一条 stage/message）。
import { useEffect, useState } from "react";
import type { CSSProperties } from "react";
import { h2, muted } from "./styles";

interface ProgressProps {
  progress: number; // 0-100
  stage: string;
  message: string;
}

/** 大模型阶段模拟进度的天花板；该动作真正完成后后端会推 95/100 覆盖 */
const LLM_CEIL = 95;

const trackStyle: CSSProperties = {
  width: "100%",
  height: 18,
  borderRadius: 9,
  background: "#ececec",
  overflow: "hidden",
  margin: "16px 0 12px",
};

export default function Progress({ progress, stage, message }: ProgressProps) {
  const [display, setDisplay] = useState(progress);

  // 服务端真实进度：analyzing 阶段只许前进（防止模拟值被旧事件拉回）；
  // 其余阶段直接对齐真实值（done 立即到 100）。
  useEffect(() => {
    setDisplay((d) => (stage === "analyzing" ? Math.max(d, progress) : progress));
  }, [progress, stage]);

  // 单次大模型回复可能耗时数十秒到数分钟，期间后端无任何事件；
  // 在 70%~95% 之间渐近爬升，避免进度条长时间静止（纯展示，不影响真实状态）。
  useEffect(() => {
    if (stage !== "analyzing") return;
    const t = window.setInterval(() => {
      setDisplay((d) => {
        if (d < progress) return progress;
        if (d >= LLM_CEIL) return LLM_CEIL;
        return Math.min(LLM_CEIL, d + Math.max(0.12, (LLM_CEIL - d) * 0.03));
      });
    }, 400);
    return () => window.clearInterval(t);
  }, [stage, progress]);

  const pct = Math.max(0, Math.min(100, Math.round(display)));
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
