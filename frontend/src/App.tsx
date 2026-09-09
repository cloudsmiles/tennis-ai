// 顶层状态机：source（上传 / B站链接）→ pick → progress → results。
//
// 开始分析前先查通义千问登录态；未登录则弹出站内登录框（手机号+验证码，
// 浏览器在后端无头运行、用户无感），登录成功后自动续跑。任务通过 SSE 跟踪
// 进度，终结 stage（done / error / login_required / captcha_required）分别
// 落到结果页 / 结果页（错误条）/ 登录框 / 风控提示。
import { useEffect, useRef, useState } from "react";
import type { CSSProperties } from "react";
import {
  createJob,
  getLoginStatus,
  getResult,
  sourceVideoUrl,
  streamEvents,
} from "./api";
import type { JobResult, ProgressEvent } from "./types";
import AccountPanel from "./components/AccountPanel";
import PlayerPicker, { type AnalyzeOpts } from "./components/PlayerPicker";
import Progress from "./components/Progress";
import QianwenLogin from "./components/QianwenLogin";
import Results from "./components/Results";
import SourcePicker from "./components/SourcePicker";
import {
  appSubtitle,
  appTitle,
  banner,
  button,
  card,
  colors,
  page,
  shell,
} from "./components/styles";

type Screen = "source" | "pick" | "progress" | "results";

/** 千问登录态：unknown=尚未确知（后端浏览器可能还没起，不代表未登录） */
type LoginState = "unknown" | "in" | "out";

function AccountChip({ state, onClick }: { state: LoginState; onClick: () => void }) {
  const map = {
    unknown: { dot: "#9ca3af", text: "千问账号", border: "#d1d5db", fg: colors.muted },
    in: { dot: "#16a34a", text: "千问已登录", border: "#bbf7d0", fg: "#166534" },
    out: { dot: "#d97706", text: "千问未登录", border: "#fde68a", fg: "#92400e" },
  }[state];
  return (
    <button
      type="button"
      onClick={onClick}
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: 7,
        padding: "6px 13px",
        fontSize: 13,
        fontWeight: 600,
        borderRadius: 999,
        border: `1px solid ${map.border}`,
        background: "#fff",
        color: map.fg,
        cursor: "pointer",
        whiteSpace: "nowrap",
        flexShrink: 0,
      }}
    >
      <span style={{ width: 8, height: 8, borderRadius: "50%", background: map.dot }} />
      {map.text}
    </button>
  );
}

type MediaRef =
  | { kind: "file"; file: File }
  | { kind: "source"; sourceId: string }
  | null;

const EMPTY_EVENT: ProgressEvent = { progress: 0, stage: "", message: "" };

const STEPS = ["选择视频", "选择动作与球员", "分析中", "查看结果"];

const noticeStyle: CSSProperties = {
  ...banner,
  background: "#fffbeb",
  border: "1px solid #fde68a",
  color: "#92400e",
};

const errorStyle: CSSProperties = {
  ...banner,
  background: "#fef2f2",
  border: "1px solid #fecaca",
  color: "#b91c1c",
};

const retryButton: CSSProperties = {
  marginLeft: 12,
  padding: "4px 10px",
  fontSize: 13,
  border: "1px solid #b91c1c",
  borderRadius: 6,
  background: "transparent",
  color: "#b91c1c",
  cursor: "pointer",
};

function errText(e: unknown): string {
  return e instanceof Error ? e.message : String(e);
}

function StepIndicator({ active }: { active: number }) {
  return (
    <div style={{ display: "flex", alignItems: "center", marginBottom: 20 }}>
      {STEPS.map((label, i) => {
        const done = i < active;
        const on = i === active;
        return (
          <div key={label} style={{ display: "flex", alignItems: "center", flex: i < STEPS.length - 1 ? 1 : 0 }}>
            <div
              style={{
                width: 30,
                height: 30,
                borderRadius: "50%",
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                fontSize: 13,
                fontWeight: 700,
                flexShrink: 0,
                background: on ? colors.primary : done ? "#93c5fd" : "#e5e7eb",
                color: on || done ? "#fff" : colors.muted,
              }}
            >
              {i + 1}
            </div>
            <span
              style={{
                fontSize: 13,
                marginLeft: 8,
                whiteSpace: "nowrap",
                color: on ? colors.text : colors.muted,
                fontWeight: on ? 600 : 400,
              }}
            >
              {label}
            </span>
            {i < STEPS.length - 1 ? (
              <div
                style={{
                  flex: 1,
                  height: 2,
                  background: i < active ? "#93c5fd" : colors.border,
                  margin: "0 12px",
                }}
              />
            ) : null}
          </div>
        );
      })}
    </div>
  );
}

export default function App() {
  const [screen, setScreen] = useState<Screen>("source");
  const [media, setMedia] = useState<MediaRef>(null);
  const [videoSrc, setVideoSrc] = useState<string | null>(null);
  const [jobId, setJobId] = useState<string | null>(null);
  const [job, setJob] = useState<JobResult | null>(null);
  const [evt, setEvt] = useState<ProgressEvent>(EMPTY_EVENT);
  const [notice, setNotice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loginOpen, setLoginOpen] = useState(false);
  const [accountOpen, setAccountOpen] = useState(false);
  const [loginState, setLoginState] = useState<LoginState>("unknown");

  // SSE 关闭函数；卸载组件时确保断流
  const closeRef = useRef<(() => void) | null>(null);
  // 登录成功后要自动续跑的那次分析参数（未登录预检拦截 / 任务中途要求登录）
  const pendingOptsRef = useRef<AnalyzeOpts | null>(null);
  useEffect(() => {
    return () => {
      closeRef.current?.();
      closeRef.current = null;
    };
  }, []);

  // 由 media 派生可播放地址：本地文件用 blob URL，B站 source 用后端 mp4
  useEffect(() => {
    if (media?.kind === "file") {
      const url = URL.createObjectURL(media.file);
      setVideoSrc(url);
      return () => URL.revokeObjectURL(url);
    }
    if (media?.kind === "source") {
      setVideoSrc(sourceVideoUrl(media.sourceId));
      return;
    }
    setVideoSrc(null);
  }, [media]);

  const closeStream = () => {
    closeRef.current?.();
    closeRef.current = null;
  };

  const reset = () => {
    closeStream();
    setScreen("source");
    setMedia(null);
    setVideoSrc(null);
    setJobId(null);
    setJob(null);
    setEvt(EMPTY_EVENT);
    setNotice(null);
    setError(null);
  };

  const resetJobState = () => {
    setJobId(null);
    setJob(null);
    setEvt(EMPTY_EVENT);
    setNotice(null);
    setError(null);
  };

  const loadResult = async (jid: string) => {
    try {
      const r = await getResult(jid);
      setJob(r);
      setError(null);
      setScreen("results");
    } catch (e) {
      setError(`获取结果失败：${errText(e)}`);
      setScreen("results");
    }
  };

  // 建任务并订阅进度（登录预检通过 / 登录成功后续跑都走这里）。
  const runJob = async (o: AnalyzeOpts) => {
    if (!media) return;
    const source =
      media.kind === "file"
        ? { file: media.file }
        : { sourceId: media.sourceId };
    const jid = await createJob(source, {
      cx: o.cx,
      cy: o.cy,
      clickTs: o.clickTs,
      startTs: o.startTs,
      endTs: o.endTs,
      strokeType: o.strokeType,
      skipLlm: o.preview,
    });
    setJobId(jid);
    setJob(null);
    setEvt({ progress: 0, stage: "queued", message: "任务已创建，等待分析…" });
    setScreen("progress");

    const close = streamEvents(jid, (e) => {
      setEvt(e);
      if (e.stage === "done" || e.stage === "error") {
        close();
        closeRef.current = null;
        void loadResult(jid);
      } else if (e.stage === "login_required" || e.stage === "captcha_required") {
        close();
        closeRef.current = null;
        if (e.stage === "captcha_required") {
          // 第三方风控：登录态可能仍有效，不弹登录框，提示稍后在本页重跑
          setNotice(e.message || "通义千问要求安全验证，请稍后重试");
          setScreen("pick");
        } else {
          setLoginState("out");
          setLoginOpen(true);
          setScreen("pick");
        }
      }
    });
    closeRef.current = close;
  };

  // 第 2 步确认后开始分析；完整分析需先登录千问（预览关键帧不需要）。
  const startAnalysis = async (o: AnalyzeOpts) => {
    if (!media) return;
    setNotice(null);
    setError(null);
    pendingOptsRef.current = o;
    try {
      if (!o.preview) {
        // ensure=true：服务刚启动、浏览器未起时也能按持久 cookie 得到真实状态
        let loggedIn = false;
        try {
          const st = await getLoginStatus(true);
          // busy（浏览器正忙，能分析即说明登录有效）时按已登录放行
          loggedIn = st.logged_in || st.busy;
        } catch {
          loggedIn = false;
        }
        setLoginState(loggedIn ? "in" : "out");
        if (!loggedIn) {
          setLoginOpen(true); // 登录成功后 onLoginSuccess 自动续跑
          return;
        }
      }
      await runJob(o);
    } catch (e) {
      setError(`无法开始分析：${errText(e)}`);
      setScreen("pick");
    }
  };

  // 站内登录成功：关闭模态，若有一次待分析任务则自动续跑。
  const onLoginSuccess = async () => {
    setLoginOpen(false);
    setLoginState("in");
    setNotice(null);
    const o = pendingOptsRef.current;
    if (o) {
      try {
        await runJob(o);
      } catch (e) {
        setError(`无法开始分析：${errText(e)}`);
        setScreen("pick");
      }
    }
  };

  const handleFile = (f: File) => {
    resetJobState();
    setMedia({ kind: "file", file: f });
    setScreen("pick");
  };

  const handleSource = (sourceId: string) => {
    resetJobState();
    setMedia({ kind: "source", sourceId });
    setScreen("pick");
  };

  const stepIndex = { source: 0, pick: 1, progress: 2, results: 3 }[screen];
  // pick 页必须有可播放地址；异常情况下退回来源页
  const effScreen: Screen = screen === "pick" && !videoSrc ? "source" : screen;

  return (
    <div style={page}>
      <div style={shell}>
        <div style={{ display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap" }}>
          <h1 style={appTitle}>网球 AI 视频分析</h1>
          <div style={{ marginLeft: "auto" }}>
            <AccountChip state={loginState} onClick={() => setAccountOpen(true)} />
          </div>
        </div>
        <p style={appSubtitle}>
          上传网球视频，框出一次挥拍，AI 自动截取关键帧，并由通义千问点评。
        </p>
        <div style={{ ...card, marginTop: 20 }}>
          <StepIndicator active={stepIndex} />
        </div>

        {notice ? <div style={noticeStyle}>{notice}</div> : null}
        {error ? (
          <div style={errorStyle}>
            {error}
            {effScreen === "results" && jobId ? (
              <button
                type="button"
                style={retryButton}
                onClick={() => void loadResult(jobId)}
              >
                重试获取结果
              </button>
            ) : null}
          </div>
        ) : null}

        {effScreen === "source" ? (
          <SourcePicker onFile={handleFile} onSource={handleSource} />
        ) : null}

        {effScreen === "pick" && videoSrc ? (
          <PlayerPicker src={videoSrc} onConfirm={(o) => void startAnalysis(o)} />
        ) : null}

        {effScreen === "progress" ? (
          <div style={card}>
            <Progress
              progress={evt.progress ?? 0}
              stage={evt.stage}
              message={evt.message}
            />
          </div>
        ) : null}

        {effScreen === "results" ? (
          <div style={card}>
            <Results job={job} />
            <button type="button" style={button} onClick={reset}>
              分析另一个视频
            </button>
          </div>
        ) : null}
      </div>

      {loginOpen ? (
        <QianwenLogin
          onClose={() => setLoginOpen(false)}
          onSuccess={() => void onLoginSuccess()}
        />
      ) : null}

      {accountOpen ? (
        <AccountPanel
          onClose={() => setAccountOpen(false)}
          onStatusChange={(s) => setLoginState(s)}
        />
      ) : null}
    </div>
  );
}
