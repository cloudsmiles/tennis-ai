// 第 2 步：选择动作类型 → 拖到动作大致开始处 → （可选）按钮点选球员 → 确认。
import { useEffect, useRef, useState } from "react";
import type { CSSProperties, MouseEvent } from "react";
import { button, h2, muted } from "./styles";

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
  file: File;
  /** 确认分析 */
  onConfirm: (opts: AnalyzeOpts) => void;
}

interface Picked {
  cx: number;
  cy: number;
  ts: number;
  /** 相对视频显示框的百分比位置，用于在画面上叠标记 */
  leftPct: number;
  topPct: number;
}

const STROKES = [
  { value: "forehand", label: "正手" },
  { value: "backhand", label: "反手" },
  { value: "serve", label: "发球" },
];

const videoWrap: CSSProperties = {
  position: "relative",
  marginBottom: 12,
};

const videoStyle: CSSProperties = {
  maxWidth: "100%",
  display: "block",
  border: "1px solid #e0e0e0",
  borderRadius: 8,
  background: "#000",
};

const videoArmed: CSSProperties = {
  ...videoStyle,
  cursor: "crosshair",
  boxShadow: "0 0 0 3px rgba(66,133,244,0.55)",
};

const markerStyle: CSSProperties = {
  position: "absolute",
  width: 26,
  height: 26,
  marginLeft: -13,
  marginTop: -13,
  borderRadius: "50%",
  border: "3px solid #ff5252",
  background: "rgba(255,82,82,0.18)",
  pointerEvents: "none",
  boxShadow: "0 0 0 2px rgba(255,255,255,0.85)",
};

const radioRow: CSSProperties = {
  display: "flex",
  gap: 16,
  margin: "4px 0 12px",
};

const selectBtn: CSSProperties = {
  ...button,
  marginBottom: 12,
  background: "#fff",
  color: "#1a73e8",
  border: "1px solid #1a73e8",
};

export default function PlayerPicker({ file, onConfirm }: PlayerPickerProps) {
  // 在 effect 内创建/释放 blob URL：StrictMode 二次挂载时也能正确重建
  const [videoUrl, setVideoUrl] = useState<string | null>(null);
  const [strokeType, setStrokeType] = useState("forehand");
  const [picked, setPicked] = useState<Picked | null>(null);
  const [arming, setArming] = useState(false);
  const [preview, setPreview] = useState(true);
  const videoRef = useRef<HTMLVideoElement | null>(null);

  useEffect(() => {
    const url = URL.createObjectURL(file);
    setVideoUrl(url);
    return () => URL.revokeObjectURL(url);
  }, [file]);

  // 仅在"选择球员"武装状态下，点击画面才视为点选（否则交给原生播放控制）
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
    // 点击落在原生控制栏区域（底部一条）时不作为点选
    const controlBar = Math.min(52, video.clientHeight * 0.25);
    if (video.clientHeight - e.nativeEvent.offsetY < controlBar) {
      return;
    }
    e.preventDefault(); // 阻止本次点击触发播放/暂停
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

  const handleConfirm = () => {
    const startTs = videoRef.current?.currentTime ?? 0;
    onConfirm({
      cx: picked?.cx,
      cy: picked?.cy,
      clickTs: picked?.ts,
      startTs,
      strokeType,
      preview,
    });
  };

  return (
    <div style={{ maxWidth: 720 }}>
      <h2 style={h2}>第 2 步 · 选择动作并拖到动作开始处</h2>
      <p style={muted}>
        先选择动作类型，再拖动进度条到动作<b>大致开始</b>的位置
        （发球即抛球前后、正反手即开始引拍处）——<b>不需要对准击球瞬间</b>，
        系统会自动在随后的片段里找到击球点。画面中有多人时，点下方按钮选中要
        分析的球员（会自动跟踪其移动）；只有一个人可跳过。
      </p>

      <div style={radioRow}>
        {STROKES.map((s) => (
          <label
            key={s.value}
            style={{ display: "flex", alignItems: "center", gap: 6, cursor: "pointer" }}
          >
            <input
              type="radio"
              name="stroke"
              value={s.value}
              checked={strokeType === s.value}
              onChange={() => setStrokeType(s.value)}
            />
            <span>{s.label}</span>
          </label>
        ))}
      </div>

      {videoUrl ? (
        <div style={videoWrap}>
          <video
            ref={videoRef}
            controls
            src={videoUrl}
            onClick={handleVideoClick}
            style={arming ? videoArmed : videoStyle}
          />
          {picked ? (
            <div
              style={{ ...markerStyle, left: `${picked.leftPct}%`, top: `${picked.topPct}%` }}
              title={`已选球员 @ ${picked.ts.toFixed(1)}s`}
            />
          ) : null}
        </div>
      ) : null}

      <button type="button" style={selectBtn} onClick={() => setArming((v) => !v)}>
        {arming ? "请点击画面中的球员…" : picked ? "重新选择球员" : "选择球员"}
      </button>
      <p style={{ ...muted, marginTop: 0, fontSize: 13 }}>
        {picked
          ? `已在 ${picked.ts.toFixed(1)}s 处标记球员，分析时会自动跟踪他/她的移动；可拖到别的时间再点"重新选择球员"。`
          : arming
            ? "在画面中点击要分析的那位球员（红圈标记）。"
            : "未选择球员时将自动选择画面中的球员。"}
      </p>

      <label
        style={{
          display: "flex",
          alignItems: "center",
          gap: 8,
          margin: "4px 0 12px",
          cursor: "pointer",
        }}
      >
        <input
          type="checkbox"
          checked={preview}
          onChange={(e) => setPreview(e.target.checked)}
        />
        <span>
          仅生成动作帧拼贴图（预览，暂不调用通义千问）——先确认截取效果
        </span>
      </label>

      <button type="button" style={button} onClick={handleConfirm}>
        动作从这里开始，自动定位击球点并分析
      </button>
      <p style={{ ...muted, marginTop: 12, fontSize: 13 }}>
        {preview
          ? "预览模式：只截取动作四联帧，不打开通义千问。确认拼贴图满意后，取消勾选再跑一次即可得到大模型分析。"
          : "完整分析：截取动作四联帧后会自动打开通义千问分析（需先登录）。"}
      </p>
    </div>
  );
}
