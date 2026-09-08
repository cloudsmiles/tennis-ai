// 第 1 步：选择视频来源——本地上传 或 粘贴 B站链接（标签页切换）。
import { useState } from "react";
import type { CSSProperties } from "react";
import { createSource } from "../api";
import {
  button,
  buttonDisabled,
  buttonGhost,
  card,
  colors,
  h2,
  muted,
  stepHint,
  textInput,
} from "./styles";

interface SourcePickerProps {
  onFile: (file: File) => void;
  onSource: (sourceId: string) => void;
}

const tabsWrap: CSSProperties = {
  display: "inline-flex",
  background: "#f3f4f6",
  borderRadius: 10,
  padding: 4,
  marginBottom: 18,
  gap: 4,
};

function tabStyle(active: boolean): CSSProperties {
  return {
    border: "none",
    borderRadius: 8,
    padding: "8px 18px",
    fontSize: 14,
    fontWeight: 600,
    cursor: "pointer",
    background: active ? "#fff" : "transparent",
    color: active ? colors.primary : colors.muted,
    boxShadow: active ? "0 1px 2px rgba(16,24,40,0.12)" : "none",
  };
}

const dropZone: CSSProperties = {
  border: `2px dashed ${colors.border}`,
  borderRadius: 12,
  padding: "36px 20px",
  textAlign: "center",
  color: colors.muted,
  marginBottom: 16,
  background: "#fafbfc",
  cursor: "pointer",
  display: "block",
};

export default function SourcePicker({ onFile, onSource }: SourcePickerProps) {
  const [tab, setTab] = useState<"upload" | "bilibili">("upload");
  const [file, setFile] = useState<File | null>(null);
  const [url, setUrl] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleFetch = async () => {
    if (!url.trim() || loading) return;
    setLoading(true);
    setError(null);
    try {
      const res = await createSource(url.trim());
      onSource(res.source_id);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  };

  return (
    <div style={card}>
      <p style={stepHint}>第 1 步</p>
      <h2 style={h2}>选择要分析的视频</h2>
      <p style={muted}>
        上传本地视频，或粘贴 B站视频链接由系统下载。之后你可以选择动作类型、
        拖动到动作开始处并点选球员，系统会自动截取关键帧并交给通义千问点评。
      </p>

      <div style={tabsWrap}>
        <button type="button" style={tabStyle(tab === "upload")} onClick={() => setTab("upload")}>
          本地上传
        </button>
        <button type="button" style={tabStyle(tab === "bilibili")} onClick={() => setTab("bilibili")}>
          B站链接
        </button>
      </div>

      {tab === "upload" ? (
        <div>
          <label style={dropZone}>
            <input
              type="file"
              accept="video/*"
              style={{ display: "none" }}
              onChange={(e) => setFile(e.target.files?.[0] ?? null)}
            />
            <div style={{ fontSize: 30, lineHeight: 1 }}>⬆</div>
            <div style={{ fontSize: 15, fontWeight: 600, color: colors.text, marginTop: 10 }}>
              点击选择视频文件
            </div>
            <div style={{ fontSize: 13, marginTop: 4 }}>
              支持 MP4 / MOV 等常见格式
            </div>
            {file ? (
              <div
                style={{
                  marginTop: 12,
                  display: "inline-block",
                  padding: "4px 12px",
                  borderRadius: 999,
                  background: "#eff6ff",
                  color: colors.primary,
                  fontSize: 13,
                  fontWeight: 600,
                }}
              >
                已选择：{file.name}
              </div>
            ) : null}
          </label>
          <button
            type="button"
            disabled={!file}
            onClick={() => file && onFile(file)}
            style={file ? button : buttonDisabled}
          >
            下一步：选择动作与球员
          </button>
        </div>
      ) : (
        <div>
          <div style={{ display: "flex", gap: 10, marginBottom: 10 }}>
            <input
              style={textInput}
              placeholder="粘贴 B站视频链接，如 https://www.bilibili.com/video/BV… 或 https://b23.tv/…"
              value={url}
              onChange={(e) => setUrl(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && handleFetch()}
            />
            <button
              type="button"
              style={loading ? buttonDisabled : button}
              disabled={loading}
              onClick={handleFetch}
            >
              {loading ? "下载中…" : "提取视频"}
            </button>
          </div>
          {error ? (
            <p style={{ ...muted, color: colors.danger, marginBottom: 8 }}>{error}</p>
          ) : (
            <p style={{ ...muted, marginBottom: 8 }}>
              免登录提取可用的最高清晰度；下载完成后会自动进入下一步。
            </p>
          )}
          <button type="button" style={buttonGhost} onClick={() => setTab("upload")}>
            改为上传本地文件
          </button>
        </div>
      )}
    </div>
  );
}
