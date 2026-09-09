// 第 2 步：① 选动作类型 → ② 拖进度条框出一次挥拍的开始/结束 → ③（可选）点选球员。
// 后端在框定范围内自动找击球帧、选 6 张关键帧；「开始 AI 分析」会交给通义千问点评，
// 「预览关键帧」只出拼贴图、不调用大模型。
import { useEffect, useRef, useState } from "react";
import type { CSSProperties, MouseEvent } from "react";
import {
  button,
  buttonGhost,
  buttonSecondary,
  card,
  colors,
  h2,
  muted,
  stepHint,
} from "./styles";

export interface AnalyzeOpts {
  cx?: number;
  cy?: number;
  /** 点选球员时所在的时间（视频秒）；后端在该帧锁定并全程跟踪该球员 */
  clickTs?: number;
  /** 用户框出的动作时间范围（秒）：开始=准备/引拍开始，结束=随挥结束。 */
  startTs: number;
  endTs: number;
  strokeType: string;
  preview: boolean;
}

interface PlayerPickerProps {
  /** 可播放的视频地址（本地 blob URL 或后端 source 的 mp4 URL） */
  src: string;
  onConfirm: (opts: AnalyzeOpts) => void;
}

interface Picked {
  cx: number;
  cy: number;
  ts: number;
  leftPct: number;
  topPct: number;
}

const STROKES = [
  { value: "forehand", label: "正手" },
  { value: "backhand", label: "反手" },
  { value: "serve", label: "发球" },
];

const videoWrap: CSSProperties = { position: "relative", marginBottom: 10 };

const videoStyle: CSSProperties = {
  width: "100%",
  display: "block",
  borderRadius: 10,
  background: "#000",
};

const videoArmed: CSSProperties = {
  ...videoStyle,
  cursor: "crosshair",
  boxShadow: "0 0 0 3px rgba(37,99,235,0.55)",
};

const markerStyle: CSSProperties = {
  position: "absolute",
  width: 28,
  height: 28,
  marginLeft: -14,
  marginTop: -14,
  borderRadius: "50%",
  border: "3px solid #ef4444",
  background: "rgba(239,68,68,0.18)",
  pointerEvents: "none",
  boxShadow: "0 0 0 2px rgba(255,255,255,0.9)",
};

const controlBar: CSSProperties = {
  display: "flex",
  alignItems: "center",
  gap: 10,
  background: "#f9fafb",
  border: `1px solid ${colors.border}`,
  borderRadius: 10,
  padding: "8px 12px",
  marginBottom: 16,
};

const sliderWrap: CSSProperties = {
  position: "relative",
  flex: 1,
  display: "flex",
  alignItems: "center",
};

const sliderStyle: CSSProperties = { width: "100%", accentColor: colors.primary };

const rangeSegment: CSSProperties = {
  position: "absolute",
  top: "50%",
  height: 6,
  marginTop: -3,
  borderRadius: 3,
  background: "rgba(37,99,235,0.35)",
  pointerEvents: "none",
};

function edgeStyle(pct: number): CSSProperties {
  return {
    position: "absolute",
    top: "50%",
    left: `${pct}%`,
    height: 14,
    marginTop: -7,
    width: 2,
    background: colors.primary,
    pointerEvents: "none",
  };
}

const iconBtn: CSSProperties = {
  border: `1px solid ${colors.border}`,
  background: "#fff",
  borderRadius: 8,
  width: 38,
  height: 34,
  fontSize: 14,
  cursor: "pointer",
  color: colors.text,
};

const nudgeBtn: CSSProperties = {
  ...iconBtn,
  width: "auto",
  padding: "0 8px",
  fontSize: 12,
};

const markBtn: CSSProperties = {
  border: `1px solid ${colors.primary}`,
  background: "#fff",
  color: colors.primary,
  borderRadius: 8,
  height: 34,
  padding: "0 14px",
  fontSize: 14,
  fontWeight: 600,
  cursor: "pointer",
};

const timeLabel: CSSProperties = {
  fontVariantNumeric: "tabular-nums",
  fontSize: 13,
  color: colors.muted,
  whiteSpace: "nowrap",
};

// ①②③ 小标题
const sectionLabel: CSSProperties = {
  fontSize: 14,
  fontWeight: 700,
  color: colors.text,
  margin: "16px 0 8px",
  display: "flex",
  alignItems: "center",
  gap: 8,
};

const stepNum: CSSProperties = {
  width: 20,
  height: 20,
  borderRadius: "50%",
  background: colors.primary,
  color: "#fff",
  fontSize: 12,
  fontWeight: 700,
  display: "inline-flex",
  alignItems: "center",
  justifyContent: "center",
  flexShrink: 0,
};

const segRow: CSSProperties = { display: "flex", gap: 8 };

function segBtn(active: boolean): CSSProperties {
  return {
    flex: 1,
    padding: "10px 0",
    fontSize: 15,
    fontWeight: 600,
    borderRadius: 10,
    border: `1px solid ${active ? colors.primary : colors.border}`,
    background: active ? colors.primary : "#fff",
    color: active ? "#fff" : colors.text,
    cursor: "pointer",
  };
}

function fmt(t: number): string {
  if (!isFinite(t)) t = 0;
  const m = Math.floor(t / 60);
  const s = Math.floor(t % 60);
  return `${m}:${s.toString().padStart(2, "0")}`;
}

function fmtT(t: number): string {
  if (!isFinite(t)) t = 0;
  return `${fmt(t)}.${Math.floor((t % 1) * 10 + 1e-6)}`;
}

export default function PlayerPicker({ src, onConfirm }: PlayerPickerProps) {
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const [playing, setPlaying] = useState(false);
  const [current, setCurrent] = useState(0);
  const [duration, setDuration] = useState(0);
  const [strokeType, setStrokeType] = useState("forehand");
  const [picked, setPicked] = useState<Picked | null>(null);
  const [arming, setArming] = useState(false);
  const [rangeStart, setRangeStart] = useState<number | null>(null);
  const [rangeEnd, setRangeEnd] = useState<number | null>(null);

  useEffect(() => {
    setPicked(null);
    setCurrent(0);
    setPlaying(false);
    setRangeStart(null);
    setRangeEnd(null);
  }, [src]);

  const togglePlay = () => {
    const v = videoRef.current;
    if (!v) return;
    if (v.paused) v.play();
    else v.pause();
  };

  const nudge = (delta: number) => {
    const v = videoRef.current;
    if (!v) return;
    v.currentTime = Math.max(0, Math.min(duration || 0, v.currentTime + delta));
  };

  // 仅在"选择球员"武装状态下，点击画面才视为点选
  const handleVideoClick = (e: MouseEvent<HTMLVideoElement>) => {
    if (!arming) return;
    const video = e.currentTarget;
    if (
      video.videoWidth <= 0 ||
      video.videoHeight <= 0 ||
      video.clientWidth <= 0 ||
      video.clientHeight <= 0
    ) {
      return;
    }
    e.preventDefault();
    const cx = (e.nativeEvent.offsetX / video.clientWidth) * video.videoWidth;
    const cy = (e.nativeEvent.offsetY / video.clientHeight) * video.videoHeight;
    setPicked({
      cx,
      cy,
      ts: video.currentTime,
      leftPct: (e.nativeEvent.offsetX / video.clientWidth) * 100,
      topPct: (e.nativeEvent.offsetY / video.clientHeight) * 100,
    });
    setArming(false);
  };

  const armSelection = () => {
    const v = videoRef.current;
    if (v && !v.paused) v.pause();
    setArming((a) => !a);
  };

  const dur = duration || 0;
  const pct = (t: number) => (dur > 0 ? (t / dur) * 100 : 0);
  const rangeValid =
    rangeStart !== null && rangeEnd !== null && rangeEnd > rangeStart;

  const handleConfirm = (preview: boolean) => {
    if (!rangeValid || rangeStart === null || rangeEnd === null) return;
    onConfirm({
      cx: picked?.cx,
      cy: picked?.cy,
      clickTs: picked?.ts,
      startTs: rangeStart,
      endTs: rangeEnd,
      strokeType,
      preview,
    });
  };

  return (
    <div style={card}>
      <p style={stepHint}>第 2 步</p>
      <h2 style={h2}>框出要分析的挥拍</h2>
      <p style={muted}>
        先选动作类型，再拖动进度条，把一次完整挥拍（从准备到随挥结束）的开始与结束框出来；
        画面有多人时点选要分析的球员，单人可跳过。
      </p>

      <div style={videoWrap}>
        <video
          ref={videoRef}
          src={src}
          onClick={handleVideoClick}
          style={arming ? videoArmed : videoStyle}
          onPlay={() => setPlaying(true)}
          onPause={() => setPlaying(false)}
          onTimeUpdate={(e) => setCurrent(e.currentTarget.currentTime)}
          onLoadedMetadata={(e) => setDuration(e.currentTarget.duration)}
          onSeeked={(e) => setCurrent(e.currentTarget.currentTime)}
        />
        {picked ? (
          <div
            style={{ ...markerStyle, left: `${picked.leftPct}%`, top: `${picked.topPct}%` }}
          />
        ) : null}
      </div>

      {/* 播放/进度/微调 */}
      <div style={controlBar}>
        <button type="button" style={iconBtn} onClick={togglePlay} aria-label="播放/暂停">
          {playing ? "❚❚" : "►"}
        </button>
        <div style={sliderWrap}>
          <input
            type="range"
            min={0}
            max={dur}
            step={0.01}
            value={Math.min(current, dur)}
            style={sliderStyle}
            onChange={(e) => {
              const t = Number(e.target.value);
              if (videoRef.current) videoRef.current.currentTime = t;
              setCurrent(t);
            }}
          />
          {rangeValid && rangeStart !== null && rangeEnd !== null ? (
            <>
              <div
                style={{
                  ...rangeSegment,
                  left: `${pct(rangeStart)}%`,
                  width: `${pct(rangeEnd - rangeStart)}%`,
                }}
              />
              <div style={edgeStyle(pct(rangeStart))} />
              <div style={edgeStyle(pct(rangeEnd))} />
            </>
          ) : null}
        </div>
        <button type="button" style={nudgeBtn} title="后退 0.1 秒" onClick={() => nudge(-0.1)}>
          ‒0.1s
        </button>
        <button type="button" style={nudgeBtn} title="前进 0.1 秒" onClick={() => nudge(0.1)}>
          +0.1s
        </button>
        <span style={timeLabel}>
          {fmt(current)} / {fmt(dur)}
        </span>
      </div>

      {/* ① 动作类型 */}
      <p style={sectionLabel}>
        <span style={stepNum}>1</span>动作类型
      </p>
      <div style={segRow}>
        {STROKES.map((s) => (
          <button
            key={s.value}
            type="button"
            style={segBtn(strokeType === s.value)}
            onClick={() => setStrokeType(s.value)}
          >
            {s.label}
          </button>
        ))}
      </div>

      {/* ② 框出时间范围 */}
      <p style={sectionLabel}>
        <span style={stepNum}>2</span>框出这次挥拍
      </p>
      <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
        <button
          type="button"
          style={markBtn}
          onClick={() => setRangeStart(videoRef.current?.currentTime ?? 0)}
        >
          设为开始
        </button>
        <button
          type="button"
          style={markBtn}
          onClick={() => setRangeEnd(videoRef.current?.currentTime ?? 0)}
        >
          设为结束
        </button>
        <button
          type="button"
          style={{ ...iconBtn, width: "auto", padding: "0 12px", whiteSpace: "nowrap" }}
          onClick={() => {
            setRangeStart(null);
            setRangeEnd(null);
          }}
        >
          清除
        </button>
        <span style={{ ...timeLabel, marginLeft: 4 }}>
          {rangeStart !== null || rangeEnd !== null ? (
            <>
              {rangeStart !== null ? fmtT(rangeStart) : "开始"}
              {"　→　"}
              {rangeEnd !== null ? fmtT(rangeEnd) : "结束"}
              {rangeValid && rangeStart !== null && rangeEnd !== null
                ? `（${(rangeEnd - rangeStart).toFixed(1)}s）`
                : ""}
            </>
          ) : (
            "拖到起点设开始、终点设结束"
          )}
        </span>
      </div>
      {rangeStart !== null && rangeEnd !== null && !rangeValid ? (
        <p style={{ ...muted, color: colors.danger, fontSize: 12, margin: "6px 2px 0" }}>
          结束需晚于开始，请重设
        </p>
      ) : null}

      {/* ③ 球员（可选） */}
      <p style={sectionLabel}>
        <span style={stepNum}>3</span>球员（多人时选，单人可跳过）
      </p>
      <div style={{ display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap" }}>
        <button type="button" style={buttonGhost} onClick={armSelection}>
          {arming ? "请点击画面中的球员…" : picked ? "重新选择球员" : "选择球员"}
        </button>
        <span style={{ ...muted, margin: 0, fontSize: 13 }}>
          {picked
            ? `已在 ${fmt(picked.ts)} 标记，将自动跟踪`
            : arming
              ? "在画面中点击要分析的球员"
              : "未选择时自动选取画面中的球员"}
        </span>
      </div>

      {/* 主动作 */}
      <div style={{ display: "flex", gap: 10, marginTop: 22 }}>
        <button
          type="button"
          style={{
            ...button,
            flex: 1,
            opacity: rangeValid ? 1 : 0.5,
            cursor: rangeValid ? "pointer" : "not-allowed",
          }}
          disabled={!rangeValid}
          onClick={() => handleConfirm(false)}
        >
          开始 AI 分析
        </button>
        <button
          type="button"
          style={{
            ...buttonSecondary,
            opacity: rangeValid ? 1 : 0.5,
            cursor: rangeValid ? "pointer" : "not-allowed",
          }}
          disabled={!rangeValid}
          onClick={() => handleConfirm(true)}
        >
          预览关键帧
        </button>
      </div>
      {!rangeValid ? (
        <p style={{ ...muted, marginTop: 10, marginBottom: 0, fontSize: 13 }}>
          先用「设为开始 / 设为结束」框出一次完整挥拍。
        </p>
      ) : null}
    </div>
  );
}
