// 顶层状态机：source（上传 / B站链接）→ pick → progress → results。
//
// 开始分析前先查通义千问登录态；未登录则弹提示、打开登录窗口并回到选人
// 页面（不建任务）。任务通过 SSE 跟踪进度，终结 stage（done / error /
// login_required）后分别落到结果页 / 结果页（红色错误信息）/ 登录提示。
import { useEffect, useRef, useState } from "react";
import type { CSSProperties } from "react";
import {
  createJob,
  getLoginStatus,
  getResult,
  login,
  sourceVideoUrl,
  streamEvents,
} from "./api";
import type { JobResult, ProgressEvent } from "./types";
import PlayerPicker, { type AnalyzeOpts } from "./components/PlayerPicker";
import Progress from "./components/Progress";
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

type MediaRef =
  | { kind: "file"; file: File }
  | { kind: "source"; sourceId: string }
  | null;

const LOGIN_ALERT =
  "通义千问未登录，点击确定后在弹出的浏览器中登录，登录完成后请重新点击分析";

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

  // SSE 关闭函数；卸载组件时确保断流
  const closeRef = useRef<(() => void) | null>(null);
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

  const handleLoginRequired = async (msg: string) => {
    try {
      await login();
    } catch (e) {
      setError(`打开登录窗口失败：${errText(e)}`);
    }
    setNotice(
      `${msg || "通义千问未登录"}。已在服务端重新打开登录窗口，` +
        "请完成登录后重新点击分析。",
    );
    setScreen("pick");
  };

  // 第 2 步确认后开始分析。
  const startAnalysis = async (o: AnalyzeOpts) => {
    if (!media) return;
    setNotice(null);
    setError(null);
    try {
      if (!o.preview) {
        const loggedIn = await getLoginStatus();
        if (!loggedIn) {
          window.alert(LOGIN_ALERT);
          await login();
          setScreen("pick");
          return;
        }
      }

      const source =
        media.kind === "file"
          ? { file: media.file }
          : { sourceId: media.sourceId };
      const jid = await createJob(source, {
        cx: o.cx,
        cy: o.cy,
        clickTs: o.clickTs,
        startTs: o.startTs,
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
        } else if (e.stage === "login_required") {
          close();
          closeRef.current = null;
          void handleLoginRequired(e.message);
        }
      });
      closeRef.current = close;
    } catch (e) {
      setError(`无法开始分析：${errText(e)}`);
      setScreen("pick");
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
        <h1 style={appTitle}>网球 AI 视频分析</h1>
        <p style={appSubtitle}>
          上传视频或粘贴 B站链接，选择动作并定位球员，自动截取关键帧，由通义千问给出评分与纠错建议。
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
    </div>
  );
}
