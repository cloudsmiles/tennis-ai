// 第 1 步：选择并上传视频文件。
import { useState } from "react";
import { button, buttonDisabled, h2, muted } from "./styles";

interface UploaderProps {
  onFile: (file: File) => void;
}

export default function Uploader({ onFile }: UploaderProps) {
  const [file, setFile] = useState<File | null>(null);

  return (
    <div style={{ maxWidth: 720 }}>
      <h2 style={h2}>第 1 步 · 选择视频</h2>
      <p style={muted}>
        上传一段打网球的视频（MP4 / MOV 等）。系统会自动检测挥拍动作，
        生成关键帧拼贴并由通义千问给出评分与建议。
      </p>
      <input
        type="file"
        accept="video/*"
        onChange={(e) => setFile(e.target.files?.[0] ?? null)}
        style={{ marginBottom: 16 }}
      />
      <div>
        <button
          type="button"
          disabled={!file}
          onClick={() => {
            if (file) onFile(file);
          }}
          style={file ? button : buttonDisabled}
        >
          下一步：选择要分析的球员
        </button>
      </div>
      {file ? <p style={muted}>已选择：{file.name}</p> : null}
    </div>
  );
}
