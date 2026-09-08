// 第 2 步：自定义播放器——独立进度条/播放控制（脱离视频原生控制条），
// 动作类型分段选择，按钮点选球员并在画面标记，确认后开始分析。
import { useEffect, useRef, useState } from "react";
import type { CSSProperties, MouseEvent } from "react";
import {
  button,
  buttonGhost,
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
  /** 用户标注的动作"大致开始"时间（视频秒）；后端在其后自动定位击球帧 */
  startTs: number;
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
  marginBottom: 8,
};

const sliderStyle: CSSProperties = { flex: 1, accentColor: colors.primary };

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

const timeLabel: CSSProperties = {
  fontVariantNumeric: "tabular-nums",
  fontSize: 13,
  color: colors.muted,
  whiteSpace: "nowrap",
};

const segRow: CSSProperties = {
  display: "flex",
  gap: 8,
  margin: "14px 0 6px",
};

function segBtn(active: boolean): CSSProperties {
  return {
    flex: 1,
    padding: "11px 0",
    fontSize: 15,
    fontWeight: 600,
    borderRadius: 10,
    border: `1px solid ${active ? colors.primary : colors.border}`,
    background: active ? colors.primary : "#fff",
    color: active ? "#fff" : colors.text,
    cursor: "pointer",
  };
}

const fieldLabel: CSSProperties = {
  fontSize: 13,
  fontWeight: 600,
  color: colors.muted,
  margin: "12px 0 6px",
};

function fmt(t: number): string {
  if (!isFinite(t)) t = 0;
  const m = Math.floor(t / 60);
  const s = Math.floor(t % 60);
  return `${m}:${s.toString().padStart(2, "0")}`;
}

export default function PlayerPicker({ src, onConfirm }: PlayerPickerProps) {
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const [playing, setPlaying] = useState(false);
  const [current, setCurrent] = useState(0);
  const [duration, setDuration] = useState(0);
  const [strokeType, setStrokeType] = useState("forehand");
  const [picked, setPicked] = useState<Picked | null>(null);
  const [arming, setArming] = useState(false);
  const [preview, setPreview] = useState(true);

  useEffect(() => {
    setPicked(null);
    setCurrent(0);
    setPlaying(false);
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
    v.currentTime = Math.max(0, Math.min((duration || 0), v.currentTime + delta));
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
    if (v && !v.paused) v.pause(); // 点选前暂停，便于精确点击
    setArming((a) => !a);
  };

  const handleConfirm = () => {
    onConfirm({
      cx: picked?.cx,
      cy: picked?.cy,
      clickTs: picked?.ts,
      startTs: videoRef.current?.currentTime ?? 0,
      strokeType,
      preview,
    });
  };

  return (
    <div style={card}>
      <p style={stepHint}>第 2 步</p>
      <h2 style={h2}>选择动作类型、定位动作并点选球员</h2>
      <p style={muted}>
        先选动作类型；用下方进度条拖到动作<b>大致开始</b>的位置（发球即抛球前后、
        正反手即开始引拍处），<b>无需对准击球瞬间</b>。画面有多人时点"选择球员"
        标出要分析的人（会自动跟踪其移动），单人可跳过。
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

      {/* 脱离视频的独立控制条 */}
      <div style={controlBar}>
        <button type="button" style={iconBtn} onClick={togglePlay} aria-label="播放/暂停">
          {playing ? "❚❚" : "►"}
        </button>
        <input
          type="range"
          min={0}
          max={duration || 0}
          step={0.01}
          value={Math.min(current, duration || 0)}
          style={sliderStyle}
          onChange={(e) => {
            const t = Number(e.target.value);
            if (videoRef.current) videoRef.current.currentTime = t;
            setCurrent(t);
          }}
        />
        <span style={timeLabel}>
          {fmt(current)} / {fmt(duration)}
        </span>
      </div>
      <div style={{ display: "flex", gap: 8, marginBottom: 4 }}>
        <button type="button" style={iconBtn} onClick={() => nudge(-1)}>-1s</button>
        <button type="button" style={iconBtn} onClick={() => nudge(-0.1)}>-0.1</button>
        <button type="button" style={iconBtn} onClick={() => nudge(0.1)}>+0.1</button>
        <button type="button" style={iconBtn} onClick={() => nudge(1)}>+1s</button>
        <span style={{ ...muted, margin: "auto 0 0 8px", fontSize: 12 }}>
          微调进度，精确定位动作开始处
        </span>
      </div>

      <p style={fieldLabel}>动作类型</p>
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

      <p style={fieldLabel}>要分析的球员（多人时选择）</p>
      <div style={{ display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap" }}>
        <button type="button" style={buttonGhost} onClick={armSelection}>
          {arming ? "请点击画面中的球员…" : picked ? "重新选择球员" : "选择球员"}
        </button>
        <span style={{ ...muted, margin: 0, fontSize: 13 }}>
          {picked
            ? `已在 ${fmt(picked.ts)} 处标记球员，分析时自动跟踪其移动`
            : arming
              ? "在画面中点击要分析的那位球员（红圈标记）"
              : "未选择时自动选取画面中的球员"}
        </span>
      </div>

      <label
        style={{ display: "flex", alignItems: "center", gap: 8, margin: "18px 0 14px", cursor: "pointer" }}
      >
        <input type="checkbox" checked={preview} onChange={(e) => setPreview(e.target.checked)} />
        <span style={{ fontSize: 14 }}>
          仅生成动作帧拼贴图（预览，暂不调用通义千问）——先确认截取效果
        </span>
      </label>

      <button type="button" style={button} onClick={handleConfirm}>
        动作从这里开始，自动定位击球点并分析
      </button>
      <p style={{ ...muted, marginTop: 10, marginBottom: 0, fontSize: 13 }}>
        {preview
          ? "预览模式：只截取动作四联帧，不打开通义千问。满意后取消勾选再跑一次即可得到大模型分析。"
          : "完整分析：截取四联帧后会自动打开通义千问分析（需先登录）。"}
      </p>
    </div>
  );
}
