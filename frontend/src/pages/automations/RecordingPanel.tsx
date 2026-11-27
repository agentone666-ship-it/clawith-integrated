import { useCallback, useEffect, useRef, useState } from "react";
import { automationApi } from "./api";
import { useRecordingFullscreen } from "./useRecordingFullscreen";
import "./recording-fullscreen.css";
import { DesktopSurface } from "./DesktopSurface";
import { DesktopInputQueue } from "./DesktopInputQueue";
import { actionLabels, newStep } from "./contracts";
import type { Frame, Recording, Step, Target, Workflow } from "./contracts";

interface Props {
  workflow: Workflow;
  recording: Recording | null;
  onRecording: (r: Recording | null) => void;
  onSaved: () => Promise<void>;
  onError: (message: string) => void;
}
export function RecordingPanel({
  workflow,
  recording,
  onRecording,
  onSaved,
  onError,
}: Props) {
  const {
    panelRef,
    expanded,
    toggle: toggleFullscreen,
    leave: leaveFullscreen,
  } = useRecordingFullscreen();
  const [frame, setFrame] = useState<Frame | null>(null);
  const [transitioning, setTransitioning] = useState(false);
  const [inputBusy, setInputBusy] = useState(false);
  const busy = transitioning || inputBusy;
  const transition = useRef(false);
  const mounted = useRef(true);
  const dispatching = useRef(false);
  const [expected, setExpected] = useState("");
  const [targetKey, setTargetKey] = useState("");
  const [notice, setNotice] = useState("");
  const [frameError, setFrameError] = useState("");
  const connectionError = useRef("");
  const [inputReset, setInputReset] = useState(0);
  const [inputInterrupted, setInputInterrupted] = useState(false);
  const current = useRef(recording);
  useEffect(() => {
    current.current = recording;
  }, [recording]);
  const refresh = useCallback(
    async (afterInput = false) => {
      const id = current.current?.id;
      if (!id || (dispatching.current && !afterInput)) return;
      try {
        const f = await automationApi.frame(id);
        if (
          !mounted.current ||
          current.current?.id !== id ||
          (dispatching.current && !afterInput)
        )
          return;
        setFrame(f);
        connectionError.current = "";
        setFrameError("");
      } catch (error) {
        if (!mounted.current || current.current?.id !== id) return;
        const message = error instanceof Error ? error.message : "无法获取桌面";
        connectionError.current = message;
        setInputReset((value) => value + 1);
        setFrameError(message);
        onError(message);
        if (message.includes("Recording is no longer active")) {
          current.current = null;
          onRecording(null);
          await onSaved();
        }
      }
    },
    [onError, onRecording, onSaved],
  );
  const recordingId = recording?.id;
  useEffect(() => {
    if (!recordingId) return;
    let disposed = false;
    let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      if (disposed) return;
      await refresh();
      if (!disposed) timer = setTimeout(poll, 1200);
    };
    void poll();
    return () => {
      disposed = true;
      clearTimeout(timer);
    };
  }, [recordingId, refresh]);
  const execute = useCallback(
    async (step: Step) => {
      const r = current.current;
      if (!r || !mounted.current) return false;
      if (connectionError.current) {
        setNotice("画面尚未恢复，暂不发送操作；请核对画面再继续。");
        return false;
      }
      dispatching.current = true;
      let accepted = false;
      try {
        const result = await automationApi.action(r.id, step);
        if (!mounted.current || current.current?.id !== r.id) return false;
        current.current = result.recording;
        onRecording(result.recording);
        accepted = result.status === "recorded";
        if (
          accepted &&
          step.action === "assert_text" &&
          !result.recording.paused
        )
          setInputInterrupted(false);
        const detail =
          result.status === "unknown"
            ? "操作结果需要确认，后续输入未发送。请核对画面再继续。"
            : result.detail;
        if (!accepted) {
          setInputInterrupted(true);
          setInputReset((value) => value + 1);
          onError(detail);
        }
        setNotice(detail);
      } catch (error) {
        if (mounted.current && current.current?.id === r.id) {
          const message =
            error instanceof Error ? error.message : "桌面操作失败";
          setInputInterrupted(true);
          setInputReset((value) => value + 1);
          onError(message);
          setNotice(message + "；后续输入未发送，请核对画面。");
        }
      } finally {
        if (mounted.current && current.current?.id === r.id)
          await refresh(true);
        dispatching.current = false;
      }
      return accepted;
    },
    [onRecording, onError, refresh],
  );
  const executeRef = useRef(execute);
  useEffect(() => {
    executeRef.current = execute;
  }, [execute]);
  const queue = useRef<DesktopInputQueue | null>(null);
  useEffect(() => {
    const owner = new DesktopInputQueue(
      (step) => executeRef.current(step),
      (value) => {
        if (mounted.current) setInputBusy(value);
      },
      (message) => {
        if (mounted.current) setNotice(message);
      },
    );
    queue.current = owner;
    mounted.current = true;
    return () => {
      mounted.current = false;
      owner.clear();
      queue.current = null;
    };
  }, []);
  useEffect(() => {
    queue.current?.clear();
  }, [recordingId]);
  const send = useCallback((step: Step) => {
    if (!transition.current) queue.current?.enqueue(step);
  }, []);
  const selectedWindow =
    frame?.windows.find((w) => `${w.app_name}|${w.title}` === targetKey) ||
    [...(frame?.windows || [])].sort((a, b) => b.z_index - a.z_index)[0];
  const selectedTarget: Target | null = selectedWindow
    ? { app: selectedWindow.app_name, title: selectedWindow.title }
    : null;
  const handleStart = async () => {
    if (
      (workflow.draft.format === "clawith.cua.v1" ? workflow.draft.steps : [])
        .length &&
      !window.confirm("重新录制会替换当前草稿，已发布的版本会保留。继续吗？")
    )
      return;
    transition.current = true;
    setTransitioning(true);
    setFrame(null);
    try {
      const r = await automationApi.record(workflow);
      current.current = r;
      onRecording(r);
      setInputInterrupted(false);
      setNotice("录制已开始，点击云电脑画面即可操作。");
    } catch (error) {
      onError(error instanceof Error ? error.message : "无法开始录制");
    } finally {
      transition.current = false;
      setTransitioning(false);
    }
  };
  const handleStop = async () => {
    if (!recording || transition.current) return;
    transition.current = true;
    setTransitioning(true);
    try {
      await queue.current?.settled();
      await automationApi.stop(recording.id);
      current.current = null;
      onRecording(null);
      await onSaved();
      setNotice("录制已保存到草稿。可继续设置参数、验证和试运行。");
    } catch (error) {
      onError(error instanceof Error ? error.message : "停止录制失败");
    } finally {
      transition.current = false;
      setTransitioning(false);
    }
  };
  const handlePause = async () => {
    if (!current.current || transition.current) return;
    transition.current = true;
    setTransitioning(true);
    try {
      await queue.current?.settled();
      if (!current.current) return;
      if (inputInterrupted) {
        const latest = await automationApi.detail(workflow.id);
        const active = latest.recording;
        if (!active) {
          current.current = null;
          onRecording(null);
          await onSaved();
          return;
        }
        const r = active.paused ? await automationApi.pause(active) : active;
        current.current = r;
        onRecording(r);
        await refresh();
        if (!connectionError.current) setInputInterrupted(false);
      } else {
        const r = await automationApi.pause(current.current);
        current.current = r;
        onRecording(r);
      }
    } catch (error) {
      onError(error instanceof Error ? error.message : "无法切换录制状态");
    } finally {
      transition.current = false;
      setTransitioning(false);
    }
  };
  return (
    <section
      ref={panelRef}
      className={"auto-recording" + (expanded ? " is-fullscreen" : "")}
      onKeyDownCapture={(event) => {
        if (
          expanded &&
          event.key === "Escape" &&
          !(event.target as HTMLElement).closest(".auto-direct-desktop")
        ) {
          event.preventDefault();
          event.stopPropagation();
          void leaveFullscreen();
        }
      }}
    >
      <div className="auto-toolbar">
        <button
          className="btn btn-secondary"
          onClick={() => void toggleFullscreen()}
        >
          {expanded ? "退出全屏" : "全屏"}
        </button>
        {!recording ? (
          <button
            className="btn btn-primary"
            onClick={() => void handleStart()}
            disabled={busy}
          >
            ●{" "}
            {transitioning
              ? "正在准备云电脑…"
              : (workflow.draft.format === "clawith.cua.v1"
                    ? workflow.draft.steps
                    : []
                  ).length
                ? "重新录制"
                : "开始录制"}
          </button>
        ) : (
          <>
            <span
              className={
                "auto-record-state " + (recording.paused ? "paused" : "")
              }
            >
              {recording.paused ? "Ⅱ 已暂停记录" : "● 正在录制"} ·{" "}
              {recording.script.steps.length} 步
            </span>
            <button
              className="btn btn-secondary"
              onClick={() => void handlePause()}
              disabled={transitioning}
            >
              {inputInterrupted
                ? "核对后继续"
                : recording.paused
                  ? "继续录制"
                  : "暂停录制"}
            </button>
            <button
              className="btn btn-primary"
              onClick={() => void handleStop()}
              disabled={transitioning}
            >
              停止并保存
            </button>
          </>
        )}
      </div>
      <p className="auto-hint">
        点击云电脑后直接使用鼠标和键盘，支持中文输入与粘贴。登录时可先暂停记录。
      </p>
      {notice && (
        <div className="auto-notice" role="status">
          {notice}
        </div>
      )}
      {frameError && (
        <div className="auto-error-banner" role="alert">
          画面连接异常：{frameError}
        </div>
      )}
      {frame && recording ? (
        <DesktopSurface
          key={recording.id}
          frame={frame}
          busy={inputBusy}
          blocked={!!frameError || transitioning || inputInterrupted}
          resetToken={inputReset}
          onInput={send}
          onNotice={setNotice}
        />
      ) : (
        <div className="auto-desktop auto-desktop-empty">
          <span>▣</span>
          <strong>
            {recording
              ? "正在连接独立桌面…"
              : transitioning
                ? "正在启动 Windows 云电脑…"
                : "准备录制一个可复用的桌面流程"}
          </strong>
          <p>
            {transitioning && !recording
              ? "首次启动需要数分钟，请保持页面打开。桌面就绪后会自动进入录制。"
              : "开始录制后，桌面画面将在这里显示。"}
          </p>
        </div>
      )}
      {recording && (
        <details className="auto-inputs auto-record-validation">
          <summary>结果验证</summary>
          <div className="auto-card">
            <h3>记录成功条件</h3>
            <select
              aria-label="验证目标窗口"
              value={targetKey}
              onChange={(e) => setTargetKey(e.target.value)}
            >
              <option value="">当前前台窗口</option>
              {frame?.windows
                .filter((w) => w.title)
                .map((w) => (
                  <option key={w.window_id} value={`${w.app_name}|${w.title}`}>
                    {w.title}
                  </option>
                ))}
            </select>
            <input
              aria-label="窗口应包含的结果文本"
              value={expected}
              onChange={(e) => setExpected(e.target.value)}
              placeholder="如 保存成功、草稿编号或 ${order_id}"
            />
            <button
              className="btn btn-secondary"
              disabled={busy || !expected || !selectedTarget}
              onClick={() =>
                void send(
                  newStep("assert_text", {
                    text: expected,
                    target: selectedTarget,
                    label: "验证窗口结果",
                  }),
                )
              }
            >
              {recording.paused ? "验证结果并继续录制" : "添加并检查结果"}
            </button>
            <p className="auto-hint">
              发布前至少有一个结果验证，避免只执行操作却没有完成业务。
            </p>
          </div>
        </details>
      )}
      {recording && (
        <div className="auto-step-strip">
          {recording.script.steps.slice(-8).map((step, i) => (
            <span key={step.id}>
              {Math.max(1, recording.script.steps.length - 7) + i}.{" "}
              {step.label || actionLabels[step.action]}
            </span>
          ))}
        </div>
      )}
    </section>
  );
}
