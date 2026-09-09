// 通义千问站内登录模态：手机号 + 短信验证码。
// 浏览器在后端无头运行，用户只在这个框里输入手机号/验证码，看不到任何浏览器窗口。
// 登录态由后端持久化，通常只需登录一次。
import { useEffect, useRef, useState } from "react";
import type { CSSProperties, FormEvent } from "react";
import { loginStart, loginVerify } from "../api";
import { colors } from "./styles";

interface Props {
  onClose?: () => void;
  onSuccess: () => void;
  /** 内嵌模式：不渲染自己的遮罩/标题栏，供账号面板直接嵌入表单 */
  embedded?: boolean;
}

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

const row: CSSProperties = { display: "flex", gap: 10, marginBottom: 12 };

const input: CSSProperties = {
  flex: 1,
  minWidth: 0,
  padding: "11px 12px",
  fontSize: 15,
  border: `1px solid ${colors.border}`,
  borderRadius: 9,
  outline: "none",
};

function sideBtn(disabled: boolean): CSSProperties {
  return {
    padding: "0 16px",
    fontSize: 14,
    fontWeight: 600,
    borderRadius: 9,
    border: `1px solid ${disabled ? colors.border : colors.primary}`,
    background: disabled ? "#f3f4f6" : "#fff",
    color: disabled ? colors.muted : colors.primary,
    cursor: disabled ? "not-allowed" : "pointer",
    whiteSpace: "nowrap",
  };
}

const primaryBtn: CSSProperties = {
  width: "100%",
  padding: "12px 0",
  fontSize: 15,
  fontWeight: 700,
  borderRadius: 9,
  border: "none",
  background: colors.primary,
  color: "#fff",
  cursor: "pointer",
  marginTop: 2,
};

const msg = (color: string): CSSProperties => ({
  fontSize: 13,
  color,
  margin: "0 0 10px",
  lineHeight: 1.6,
});

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

export default function QianwenLogin({ onClose, onSuccess, embedded = false }: Props) {
  const [phone, setPhone] = useState("");
  const [code, setCode] = useState("");
  const [step, setStep] = useState<"phone" | "code">("phone");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [info, setInfo] = useState<string | null>(null);
  const [countdown, setCountdown] = useState(0);
  const timer = useRef<number | undefined>(undefined);

  useEffect(() => () => window.clearInterval(timer.current), []);

  const startCountdown = () => {
    setCountdown(60);
    window.clearInterval(timer.current);
    timer.current = window.setInterval(() => {
      setCountdown((c) => {
        if (c <= 1) {
          window.clearInterval(timer.current);
          return 0;
        }
        return c - 1;
      });
    }, 1000);
  };

  const sendCode = async () => {
    if (!/^1[3-9]\d{9}$/.test(phone)) {
      setError("请输入正确的 11 位手机号");
      return;
    }
    setBusy(true);
    setError(null);
    setInfo(null);
    try {
      const r = await loginStart(phone);
      if (r.status === "already_logged_in") {
        onSuccess();
        return;
      }
      if (r.status === "code_sent") {
        setStep("code");
        startCountdown();
        setInfo("验证码已发送，请查收短信");
      } else if (r.status === "captcha") {
        setError(r.message || "千问要求完成安全验证，请稍后重试");
      } else {
        setError(r.message || "获取验证码失败，请稍后重试");
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const verify = async (e?: FormEvent) => {
    e?.preventDefault();
    if (code.trim().length !== 6) {
      setError("请输入 6 位短信验证码");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const r = await loginVerify(code.trim());
      if (r.status === "ok") {
        onSuccess();
        return;
      }
      setError(
        r.status === "captcha"
          ? r.message || "千问要求完成安全验证，请稍后重试"
          : r.message || "登录失败，请检查验证码",
      );
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const body = (
    <>
      {embedded ? null : (
        <button type="button" style={closeX} onClick={onClose} aria-label="关闭">
          ×
        </button>
      )}
      <h2 style={title}>登录通义千问</h2>
      <p style={sub}>
        动作点评由通义千问完成，请先用手机号登录。浏览器在后台运行、无需你操作，登录状态会保留，通常只需登录一次。
      </p>

      <div style={row}>
        <input
          style={input}
          inputMode="tel"
          maxLength={11}
          placeholder="手机号"
          value={phone}
          disabled={busy}
          onChange={(e) => setPhone(e.target.value.replace(/\D/g, ""))}
        />
        <button
          type="button"
          style={sideBtn(busy || countdown > 0)}
          disabled={busy || countdown > 0}
          onClick={() => void sendCode()}
        >
          {countdown > 0 ? `${countdown}s 后重发` : step === "code" ? "重新获取" : "获取验证码"}
        </button>
      </div>

      {step === "code" ? (
        <form onSubmit={verify}>
          <div style={row}>
            <input
              style={input}
              inputMode="numeric"
              maxLength={6}
              autoFocus
              placeholder="短信验证码"
              value={code}
              disabled={busy}
              onChange={(e) => setCode(e.target.value.replace(/\D/g, ""))}
            />
          </div>
        </form>
      ) : null}

      {error ? <p style={msg(colors.danger)}>{error}</p> : null}
      {info && !error ? <p style={msg(colors.muted)}>{info}</p> : null}

      <button
        type="button"
        style={{ ...primaryBtn, opacity: busy ? 0.6 : 1, cursor: busy ? "wait" : "pointer" }}
        disabled={busy}
        onClick={() => (step === "phone" ? void sendCode() : void verify())}
      >
        {busy ? "请稍候…" : step === "phone" ? "获取验证码" : "登录"}
      </button>
    </>
  );

  if (embedded) return body;

  return (
    <div
      style={overlay}
      onClick={(e) => e.target === e.currentTarget && onClose?.()}
    >
      <div style={modal}>{body}</div>
    </div>
  );
}
