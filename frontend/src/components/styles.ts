// 共享的内联样式常量（不引 UI 库，保持简单）。统一的专业感配色：
// 中性灰底 + 蓝色主行动色，卡片式布局。
import type { CSSProperties } from "react";

export const colors = {
  primary: "#2563eb",
  primaryHover: "#1d4ed8",
  text: "#111827",
  muted: "#6b7280",
  border: "#e5e7eb",
  pageBg: "#f4f5f7",
  cardBg: "#ffffff",
  danger: "#dc2626",
};

export const page: CSSProperties = {
  minHeight: "100vh",
  background: colors.pageBg,
  padding: "32px 20px 56px",
};

export const shell: CSSProperties = {
  maxWidth: 880,
  margin: "0 auto",
  fontFamily:
    "-apple-system, BlinkMacSystemFont, 'Segoe UI', 'PingFang SC', 'Hiragino Sans GB', sans-serif",
  color: colors.text,
};

export const appTitle: CSSProperties = {
  fontSize: 26,
  fontWeight: 700,
  margin: 0,
  letterSpacing: 0.5,
};

export const appSubtitle: CSSProperties = {
  margin: "6px 0 0",
  color: colors.muted,
  fontSize: 14,
};

export const card: CSSProperties = {
  background: colors.cardBg,
  border: `1px solid ${colors.border}`,
  borderRadius: 14,
  padding: "24px 26px",
  marginBottom: 18,
  boxShadow: "0 1px 3px rgba(16,24,40,0.06)",
};

export const h2: CSSProperties = {
  fontSize: 19,
  fontWeight: 700,
  margin: "0 0 6px",
};

export const stepHint: CSSProperties = {
  color: colors.primary,
  fontSize: 13,
  fontWeight: 600,
  margin: "0 0 4px",
  letterSpacing: 0.3,
};

export const muted: CSSProperties = {
  color: colors.muted,
  margin: "0 0 14px",
  lineHeight: 1.7,
  fontSize: 14,
};

export const button: CSSProperties = {
  padding: "10px 20px",
  fontSize: 15,
  fontWeight: 600,
  border: `1px solid ${colors.primary}`,
  borderRadius: 9,
  background: colors.primary,
  color: "#fff",
  cursor: "pointer",
  transition: "background .15s",
};

export const buttonDisabled: CSSProperties = {
  ...button,
  opacity: 0.45,
  cursor: "not-allowed",
};

/** 次要按钮（白底蓝边） */
export const buttonSecondary: CSSProperties = {
  ...button,
  background: "#fff",
  color: colors.primary,
};

/** 幽灵按钮（灰底，用于工具性操作） */
export const buttonGhost: CSSProperties = {
  ...button,
  background: "#f3f4f6",
  border: `1px solid ${colors.border}`,
  color: colors.text,
  fontWeight: 500,
};

export const textInput: CSSProperties = {
  flex: 1,
  padding: "10px 12px",
  fontSize: 14,
  border: `1px solid ${colors.border}`,
  borderRadius: 9,
  outline: "none",
  minWidth: 0,
};

export const banner: CSSProperties = {
  padding: "12px 16px",
  borderRadius: 10,
  marginBottom: 16,
  lineHeight: 1.6,
  fontSize: 14,
};
