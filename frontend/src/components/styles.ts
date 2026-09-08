// 共享的内联样式常量（不引 UI 库，保持简单）。
import type { CSSProperties } from "react";

export const h2: CSSProperties = {
  fontSize: 20,
  margin: "0 0 12px",
};

export const muted: CSSProperties = {
  color: "#666",
  margin: "0 0 12px",
  lineHeight: 1.6,
};

export const button: CSSProperties = {
  padding: "10px 18px",
  fontSize: 15,
  border: "1px solid #2f6f3f",
  borderRadius: 6,
  background: "#2f6f3f",
  color: "#fff",
  cursor: "pointer",
};

export const buttonDisabled: CSSProperties = {
  ...button,
  opacity: 0.5,
  cursor: "not-allowed",
};

/** 次要按钮（跳过 / 重新开始） */
export const buttonSecondary: CSSProperties = {
  ...button,
  background: "#fff",
  color: "#2f6f3f",
};

export const card: CSSProperties = {
  border: "1px solid #e0e0e0",
  borderRadius: 8,
  padding: 16,
  marginBottom: 16,
  background: "#fff",
};
