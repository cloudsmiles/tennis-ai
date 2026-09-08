// 第 2 步：在视频画面上点选要分析的球员（换算为视频像素坐标）。
import { useEffect, useMemo } from "react";
import type { CSSProperties, MouseEvent } from "react";
import { buttonSecondary, h2, muted } from "./styles";

interface PlayerPickerProps {
  file: File;
  /** 点击点选，cx/cy 为视频像素坐标 */
  onPick: (cx: number, cy: number) => void;
  /** 跳过点选，交给后端自动选择 */
  onSkip: () => void;
}

const videoStyle: CSSProperties = {
  maxWidth: "100%",
  cursor: "crosshair",
  display: "block",
  marginBottom: 12,
  border: "1px solid #e0e0e0",
  borderRadius: 8,
  background: "#000",
};

export default function PlayerPicker({ file, onPick, onSkip }: PlayerPickerProps) {
  const videoUrl = useMemo(() => URL.createObjectURL(file), [file]);

  // 卸载或换文件时释放 blob URL
  useEffect(() => {
    return () => URL.revokeObjectURL(videoUrl);
  }, [videoUrl]);

  const handleClick = (e: MouseEvent<HTMLVideoElement>) => {
    const video = e.currentTarget;
    // 元数据未就绪或尺寸异常时无法换算，忽略本次点击
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
    // 点击位置（控件内偏移）→ 视频像素坐标
    const cx = (e.nativeEvent.offsetX / video.clientWidth) * video.videoWidth;
    const cy = (e.nativeEvent.offsetY / video.clientHeight) * video.videoHeight;
    onPick(cx, cy);
  };

  return (
    <div style={{ maxWidth: 720 }}>
      <h2 style={h2}>第 2 步 · 选择要分析的球员</h2>
      <p style={muted}>
        拖动进度条到能同时看清双方球员的画面，然后点击画面中要分析的那位
        球员（点击位置会换算成视频像素坐标）。画面中只有一个人时可直接跳过。
      </p>
      <video controls src={videoUrl} onClick={handleClick} style={videoStyle} />
      <button type="button" onClick={onSkip} style={buttonSecondary}>
        跳过，自动选择
      </button>
    </div>
  );
}
