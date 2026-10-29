import { useCallback, useEffect, useState } from "react";
import type { Run } from "./contracts";
import { automationApi } from "./api";
import "./playback.css";
import { DesktopViewer } from "./DesktopViewer";
const statusLabels: Record<string, string> = {
  running: "正在操作电脑",
  succeeded: "操作回放",
  failed: "试运行失败",
  unknown: "结果未确认",
  cancelled: "已取消",
};
const actionLabels: Record<string, string> = {
  click: "点击",
  double_click: "双击",
  right_click: "右键",
  type_text: "输入",
  press_key: "按键",
  hotkey: "快捷键",
  scroll: "滚动",
  assert_text: "校验",
  launch_app: "启动应用",
};
export function RunPlayback({ run }: { run: Run }) {
  const [expanded, setExpanded] = useState(false);
  const closeViewer = useCallback(() => setExpanded(false), []);
  const [selected, setSelected] = useState<number | null>(null);
  const [image, setImage] = useState("");
  const [error, setError] = useState("");
  const live = run.status === "running" && selected === null;
  const [capturedAt, setCapturedAt] = useState("");
  useEffect(() => {
    if (!live) return;
    let disposed = false;
    let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      if (!document.hidden) {
        try {
          const frame = await automationApi.liveFrame(run.id);
          if (!disposed) {
            setImage(`data:${frame.mime};base64,${frame.image}`);
            setCapturedAt(frame.captured_at);
            setError("");
          }
        } catch {
          if (!disposed) setError("实时画面更新暂时延迟，正在重新连接…");
        }
      }
      if (!disposed) timer = setTimeout(poll, 1000);
    };
    void poll();
    return () => {
      disposed = true;
      clearTimeout(timer);
    };
  }, [run.id, live]);
  const trace = run.result.trace || [];
  const frames = trace.filter((s) => s.frame);
  const step =
    selected ??
    (run.status !== "running" && run.result.evidence
      ? 0
      : frames[frames.length - 1]?.step);
  useEffect(() => {
    if (live || step === undefined) return;
    let disposed = false;
    void (
      step === 0
        ? automationApi.evidence(run.id)
        : automationApi.runFrame(run.id, step)
    )
      .then((f) => {
        if (!disposed) {
          setImage(`data:${f.mime};base64,${f.image}`);
          setError("");
        }
      })
      .catch(() => {
        if (!disposed) setError("画面暂不可用");
      });
    return () => {
      disposed = true;
    };
  }, [run.id, step, live]);
  const caption = live
    ? "云电脑实时画面"
    : step === 0
      ? "最终操作画面"
      : `第 ${step ?? 0} 步 · 已完成 ${run.progress} 步`;
  const steps = (
    <div className="auto-playback-steps">
      {run.result.evidence && (
        <button onClick={() => setSelected(0)}>最终画面</button>
      )}
      {trace.map((s) => (
        <button
          key={s.step}
          disabled={!s.frame}
          aria-pressed={step === s.step}
          onClick={() => setSelected(s.step)}
        >
          {s.step}. {actionLabels[s.action] || s.action}
          {s.x != null ? ` (${s.x}, ${s.y})` : ""}
        </button>
      ))}
    </div>
  );
  return (
    <section className="auto-playback" aria-label="操作画面">
      <div className="auto-row">
        <strong>
          {live
            ? "运行中 · 云电脑实时画面"
            : statusLabels[run.status] || run.status}
        </strong>
        {live && capturedAt && (
          <time>更新于 {new Date(capturedAt).toLocaleTimeString()}</time>
        )}
        <span>已完成 {run.progress} 步</span>
        <button
          className="btn btn-secondary"
          disabled={!image}
          onClick={() => setExpanded(true)}
        >
          放大
        </button>
        {selected !== null && (
          <button
            className="btn btn-secondary"
            onClick={() => setSelected(null)}
          >
            {run.status === "running" ? "返回实时" : "跟随最新"}
          </button>
        )}
      </div>
      {image ? (
        <button
          className="auto-playback-frame"
          aria-label="放大桌面画面"
          onClick={() => setExpanded(true)}
        >
          <img src={image} alt={caption} />
        </button>
      ) : (
        <p role="status">
          {run.status === "running"
            ? "试运行已启动，等待首帧…"
            : "本次未生成操作画面。"}
        </p>
      )}
      {run.result.error && (
        <p role="alert" className="auto-error">
          {run.result.error}
        </p>
      )}
      {error && <p role="status">{error}</p>}
      {steps}

      {expanded && image && (
        <DesktopViewer
          image={image}
          caption={caption}
          steps={steps}
          onClose={closeViewer}
          onFollow={() => setSelected(null)}
        />
      )}
      <small>
        {run.status === "running"
          ? "运行中自动刷新云电脑画面；可放大查看，选择历史步骤后可返回实时。"
          : "操作已结束，可逐步查看回放。截图不代替业务结果校验。"}
      </small>
    </section>
  );
}
