// 顶层状态机：upload → pick → progress → results。
//
// 开始分析前先查通义千问登录态；未登录则弹提示、打开登录窗口并回到选人
// 页面（不建任务）。任务通过 SSE 跟踪进度，终结 stage（done / error /
// login_required）后分别落到结果页 / 结果页（红色错误信息）/ 登录提示。
import { useEffect, useRef, useState } from "react";
import type { CSSProperties } from "react";
import { createJob, getLoginStatus, getResult, login, streamEvents } from "./api";
import type { JobResult, ProgressEvent } from "./types";
import PlayerPicker from "./components/PlayerPicker";
import Progress from "./components/Progress";
import Results from "./components/Results";
import Uploader from "./components/Uploader";
import { button } from "./components/styles";

type Screen = "upload" | "pick" | "progress" | "results";

const LOGIN_ALERT =
  "通义千问未登录，点击确定后在弹出的浏览器中登录，登录完成后请重新点击分析";

const EMPTY_EVENT: ProgressEvent = { progress: 0, stage: "", message: "" };

const page: CSSProperties = {
  maxWidth: 960,
  margin: "0 auto",
  padding: "32px 20px",
  fontFamily:
    "-apple-system, BlinkMacSystemFont, 'Segoe UI', 'PingFang SC', 'Hiragino Sans GB', sans-serif",
  color: "#222",
};

const banner: CSSProperties = {
  padding: "10px 14px",
  borderRadius: 8,
  marginBottom: 16,
  lineHeight: 1.6,
};

const noticeStyle: CSSProperties = {
  ...banner,
  background: "#fdf6e3",
  border: "1px solid #e6d8a8",
  color: "#7a5c00",
};

const errorStyle: CSSProperties = {
  ...banner,
  background: "#fdecea",
  border: "1px solid #f2b8b5",
  color: "#b3261e",
};

const retryButton: CSSProperties = {
  marginLeft: 12,
  padding: "4px 10px",
  fontSize: 13,
  border: "1px solid #b3261e",
  borderRadius: 6,
  background: "transparent",
  color: "#b3261e",
  cursor: "pointer",
};

function errText(e: unknown): string {
  return e instanceof Error ? e.message : String(e);
}

export default function App() {
  const [screen, setScreen] = useState<Screen>("upload");
  const [file, setFile] = useState<File | null>(null);
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

  const closeStream = () => {
    closeRef.current?.();
    closeRef.current = null;
  };

  const reset = () => {
    closeStream();
    setScreen("upload");
    setFile(null);
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
      // 结果页对 null job 健壮；顶部横幅提供重试
      setError(`获取结果失败：${errText(e)}`);
      setScreen("results");
    }
  };

  // SSE 收到 login_required：重新打开登录窗口并提示用户重新分析
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

  // 第 2 步确认后开始分析。startTs 为用户标注的动作"大致开始"（视频秒，后端
  // 自动定位击球帧），strokeType 为动作类型，cx/cy 为球员点选坐标（可空）。
  // preview=true：只跑到生成动作帧拼贴图，不检查登录、不调用通义千问。
  const startAnalysis = async (opts: {
    cx?: number;
    cy?: number;
    startTs?: number;
    strokeType?: string;
    preview?: boolean;
  }) => {
    if (!file) return;
    const { cx, cy, startTs, strokeType, preview = false } = opts;
    setNotice(null);
    setError(null);
    try {
      // 完整分析才需要先检查登录态；预览模式不碰浏览器/大模型
      if (!preview) {
        const loggedIn = await getLoginStatus();
        if (!loggedIn) {
          window.alert(LOGIN_ALERT);
          await login();
          setScreen("pick");
          return;
        }
      }

      const jid = await createJob(file, {
        cx,
        cy,
        startTs,
        strokeType,
        skipLlm: preview,
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
    setFile(f);
    setJobId(null);
    setJob(null);
    setEvt(EMPTY_EVENT);
    setNotice(null);
    setError(null);
    setScreen("pick");
  };

  // pick 页面必须有文件；异常情况下退回上传页
  const effScreen: Screen = screen === "pick" && !file ? "upload" : screen;

  return (
    <div style={page}>
      <h1 style={{ fontSize: 24, margin: "0 0 20px" }}>网球 AI 视频分析</h1>

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

      {effScreen === "upload" ? <Uploader onFile={handleFile} /> : null}

      {effScreen === "pick" && file ? (
        <PlayerPicker file={file} onConfirm={(o) => void startAnalysis(o)} />
      ) : null}

      {effScreen === "progress" ? (
        <Progress
          progress={evt.progress ?? 0}
          stage={evt.stage}
          message={evt.message}
        />
      ) : null}

      {effScreen === "results" ? (
        <>
          <Results job={job} />
          <button type="button" style={button} onClick={reset}>
            分析另一个视频
          </button>
        </>
      ) : null}
    </div>
  );
}
