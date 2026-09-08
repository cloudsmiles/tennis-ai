// 第 2 步：选择动作类型 → 拖动进度条到击球瞬间 → （可选）点选球员 → 确认。
import { useEffect, useRef, useState } from "react";
import type { CSSProperties, MouseEvent } from "react";
import { button, h2, muted } from "./styles";

export interface AnalyzeOpts {
  cx?: number;
  cy?: number;
  hitTs: number;
  strokeType: string;
  preview: boolean;
}

interface PlayerPickerProps {
  file: File;
  /** 确认分析：hitTs 为击球瞬间（视频秒），strokeType 为动作类型，cx/cy 为球员像素坐标（可空） */
  onConfirm: (opts: AnalyzeOpts) => void;
}

const STROKES = [
  { value: "forehand", label: "正手" },
  { value: "backhand", label: "反手" },
  { value: "serve", label: "发球" },
];

const videoStyle: CSSProperties = {
  maxWidth: "100%",
  cursor: "crosshair",
  display: "block",
  marginBottom: 12,
  border: "1px solid #e0e0e0",
  borderRadius: 8,
  background: "#000",
};

const radioRow: CSSProperties = {
  display: "flex",
  gap: 16,
  margin: "4px 0 12px",
};

export default function PlayerPicker({ file, onConfirm }: PlayerPickerProps) {
  // 在 effect 内创建/释放 blob URL：StrictMode 二次挂载时也能正确重建
  const [videoUrl, setVideoUrl] = useState<string | null>(null);
  const [strokeType, setStrokeType] = useState("forehand");
  const [picked, setPicked] = useState<{ cx: number; cy: number } | null>(null);
  const [preview, setPreview] = useState(true);
  const videoRef = useRef<HTMLVideoElement | null>(null);

  useEffect(() => {
    const url = URL.createObjectURL(file);
    setVideoUrl(url);
    return () => URL.revokeObjectURL(url);
  }, [file]);

  const handleClick = (e: MouseEvent<HTMLVideoElement>) => {
    const video = e.currentTarget;
    if (
      video.videoWidth <= 0 ||
      video.videoHeight <= 0 ||
      video.clientWidth <= 0 ||
      video.clientHeight <= 0
    ) {
      return;
    }
    // 点击落在原生控制栏区域（底部一条）时视为播放/进度条操作，不作为点选
    const controlBar = Math.min(52, video.clientHeight * 0.25);
    if (video.clientHeight - e.nativeEvent.offsetY < controlBar) {
      return;
    }
    const cx = (e.nativeEvent.offsetX / video.clientWidth) * video.videoWidth;
    const cy = (e.nativeEvent.offsetY / video.clientHeight) * video.videoHeight;
    setPicked({ cx, cy });
  };

  const handleConfirm = () => {
    const hitTs = videoRef.current?.currentTime ?? 0;
    onConfirm({
      cx: picked?.cx,
      cy: picked?.cy,
      hitTs,
      strokeType,
      preview,
    });
  };

  return (
    <div style={{ maxWidth: 720 }}>
      <h2 style={h2}>第 2 步 · 选择动作并定位击球瞬间</h2>
      <p style={muted}>
        先选择动作类型，再拖动进度条到<b>击球瞬间</b>，然后点击画面中要分析的球员
        （多人时；只有一个人可跳过点选），最后点确认。
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
        <video
          ref={videoRef}
          controls
          src={videoUrl}
          onClick={handleClick}
          style={videoStyle}
        />
      ) : null}

      <p style={{ ...muted, marginTop: 0, fontSize: 13 }}>
        {picked
          ? "已记录球员位置；如需改选可直接点击画面中另一位球员。"
          : "未点选球员时将自动选择画面中的球员。"}
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
        确认当前画面为击球瞬间，开始分析
      </button>
      <p style={{ ...muted, marginTop: 12, fontSize: 13 }}>
        {preview
          ? "预览模式：只截取动作三联帧，不打开通义千问。确认拼贴图满意后，取消勾选再跑一次即可得到大模型分析。"
          : "完整分析：截取动作三联帧后会自动打开通义千问分析（需先登录）。"}
      </p>
    </div>
  );
}
