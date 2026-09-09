// 通义千问账号面板：随时自查登录态；未登录可直接在面板内完成手机号+验证码登录。
// 打开面板时用 ensure=true 让后端拉起无头浏览器按持久 cookie 查真实状态。
import { useCallback, useEffect, useState } from "react";
import type { CSSProperties } from "react";
import { getLoginStatus } from "../api";
import QianwenLogin from "./QianwenLogin";
import { colors } from "./styles";

interface Props {
  onClose: () => void;
  onStatusChange: (s: "in" | "out") => void;
}

type State = "checking" | "in" | "out" | "error";

const overlay: CSSProperties = {
  position: "fixed",
  inset: 0,
  background: "rgba(17,24,39,0.45)",
  display: "flex",
  alignItems: "center",
  justifyContent: "center",
  zIndex: 1000,
  padding: 20,
};

const modal: CSSProperties = {
  background: "#fff",
  borderRadius: 14,
  padding: "26px 26px 22px",
  width: 400,
  maxWidth: "92vw",
  boxShadow: "0 12px 40px rgba(16,24,40,0.25)",
};

const title: CSSProperties = { fontSize: 19, fontWeight: 700, margin: 0 };
const sub: CSSProperties = {
  fontSize: 13,
  color: colors.muted,
  margin: "6px 0 18px",
  lineHeight: 1.6,
};

const closeX: CSSProperties = {
  float: "right",
  border: "none",
  background: "transparent",
  fontSize: 20,
  lineHeight: 1,
  color: colors.muted,
  cursor: "pointer",
  padding: 0,
};

const statusRow: CSSProperties = {
  display: "flex",
  alignItems: "center",
  gap: 10,
  fontSize: 16,
  fontWeight: 700,
  margin: "2px 0 8px",
};

const dot: CSSProperties = {
  width: 12,
  height: 12,
  borderRadius: "50%",
  flexShrink: 0,
};

const closeBtn: CSSProperties = {
  width: "100%",
  padding: "11px 0",
  fontSize: 15,
  fontWeight: 700,
  borderRadius: 9,
  border: "none",
  background: colors.primary,
  color: "#fff",
  cursor: "pointer",
  marginTop: 6,
};

const retryBtn: CSSProperties = {
  padding: "6px 14px",
  fontSize: 13,
  fontWeight: 600,
  borderRadius: 8,
  border: `1px solid ${colors.primary}`,
  background: "#fff",
  color: colors.primary,
  cursor: "pointer",
};

export default function AccountPanel({ onClose, onStatusChange }: Props) {
  const [state, setState] = useState<State>("checking");
  const [errMsg, setErrMsg] = useState<string | null>(null);

  const check = useCallback(async () => {
    setState("checking");
    setErrMsg(null);
    try {
      const r = await getLoginStatus(true);
      // 分析等长任务占用浏览器时状态暂不可查：稍后自动重试，不打扰用户
      if (r.busy) {
        return "busy";
      }
      setState(r.logged_in ? "in" : "out");
      onStatusChange(r.logged_in ? "in" : "out");
      return "done";
    } catch (e) {
      setErrMsg(e instanceof Error ? e.message : String(e));
      setState("error");
      return "error";
    }
  }, [onStatusChange]);

  useEffect(() => {
    let cancelled = false;
    let timer: number | undefined;
    const tick = async () => {
      const r = await check();
      if (!cancelled && r === "busy") {
        timer = window.setTimeout(tick, 2000);
      }
    };
    void tick();
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [check]);

  const handleLoggedIn = () => {
    setState("in");
    onStatusChange("in");
  };

  return (
    <div style={overlay} onClick={(e) => e.target === e.currentTarget && onClose()}>
      <div style={modal}>
        <button type="button" style={closeX} onClick={onClose} aria-label="关闭">
          ×
        </button>

        {state === "checking" ? (
          <>
            <h2 style={title}>通义千问账号</h2>
            <p style={sub}>
              正在检查登录状态（首次会在后台启动浏览器；若正在分析动作会稍候自动重试）…
            </p>
          </>
        ) : null}

        {state === "error" ? (
          <>
            <h2 style={title}>通义千问账号</h2>
            <p style={{ ...sub, color: colors.danger }}>
              检查失败：{errMsg}
            </p>
            <button type="button" style={retryBtn} onClick={() => void check()}>
              重新检查
            </button>
          </>
        ) : null}

        {state === "in" ? (
          <>
            <h2 style={title}>通义千问账号</h2>
            <div style={statusRow}>
              <span style={{ ...dot, background: "#16a34a" }} />
              已登录
            </div>
            <p style={sub}>
              登录状态有效，可以直接开始 AI 动作点评。登录态由后端持久保存，通常只需登录一次。
            </p>
            <button type="button" style={closeBtn} onClick={onClose}>
              完成
            </button>
          </>
        ) : null}

        {state === "out" ? (
          <div>
            <div style={statusRow}>
              <span style={{ ...dot, background: "#d97706" }} />
              <span style={{ fontSize: 15 }}>未登录</span>
            </div>
            <QianwenLogin embedded onSuccess={handleLoggedIn} />
          </div>
        ) : null}
      </div>
    </div>
  );
}
