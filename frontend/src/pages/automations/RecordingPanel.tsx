import { useCallback, useEffect, useRef, useState } from "react";
import { automationApi } from "./api";
import { actionLabels, newStep } from "./contracts";
import type {
  ActionName,
  Frame,
  Recording,
  Step,
  Target,
  Workflow,
} from "./contracts";

interface Props {
  workflow: Workflow;
  recording: Recording | null;
  onRecording: (r: Recording | null) => void;
  onSaved: () => Promise<void>;
  onError: (message: string) => void;
}
const keyMap: Record<string, string> = {
  Enter: "return",
  Escape: "escape",
  ArrowDown: "down",
  ArrowUp: "up",
  ArrowLeft: "left",
  ArrowRight: "right",
  " ": "space",
  Backspace: "backspace",
  Delete: "delete",
  Tab: "tab",
};

export function RecordingPanel({
  workflow,
  recording,
  onRecording,
  onSaved,
  onError,
}: Props) {
  const [frame, setFrame] = useState<Frame | null>(null);
  const [mode, setMode] = useState<ActionName>("click");
  const [busy, setBusy] = useState(false);
  const dispatching = useRef(false);
  const [text, setText] = useState("");
  const [parameter, setParameter] = useState("");
  const [secret, setSecret] = useState(false);
  const [expected, setExpected] = useState("");
  const [targetKey, setTargetKey] = useState("");
  const [notice, setNotice] = useState("");
  const current = useRef(recording);
  useEffect(() => {
    current.current = recording;
  }, [recording]);
  const refresh = useCallback(async () => {
    if (!current.current || dispatching.current) return;
    try {
      const f = await automationApi.frame(current.current.id);
      setFrame(f);
    } catch (error) {
      const message = error instanceof Error ? error.message : "无法获取桌面";
      onError(message);
      if (message.includes("Recording is no longer active")) {
        current.current = null;
        onRecording(null);
        await onSaved();
      }
    }
  }, [onError, onRecording, onSaved]);
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
  const send = useCallback(
    async (step: Step, param = "", isSecret = false) => {
      const r = current.current;
      if (!r || dispatching.current) return;
      dispatching.current = true;
      setBusy(true);
      try {
        const result = await automationApi.action(
          r.id,
          step,
          param,
          param,
          isSecret,
        );
        current.current = result.recording;
        onRecording(result.recording);
        setNotice(result.detail);
      } catch (error) {
        onError(error instanceof Error ? error.message : "桌面操作失败");
      } finally {
        dispatching.current = false;
        setBusy(false);
        await refresh();
      }
    },
    [onRecording, onError, refresh],
  );
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
    setBusy(true);
    try {
      const r = await automationApi.record(workflow);
      current.current = r;
      onRecording(r);
      setNotice("录制已开始，请在下方独立桌面操作。");
    } catch (error) {
      onError(error instanceof Error ? error.message : "无法开始录制");
    } finally {
      setBusy(false);
    }
  };
  const handleStop = async () => {
    if (!recording || dispatching.current) return;
    setBusy(true);
    try {
      await automationApi.stop(recording.id);
      current.current = null;
      onRecording(null);
      await onSaved();
      setNotice("录制已保存到草稿。可继续设置参数、验证和试运行。");
    } catch (error) {
      onError(error instanceof Error ? error.message : "停止录制失败");
    } finally {
      setBusy(false);
    }
  };
  const handlePause = async () => {
    if (!recording) return;
    try {
      const r = await automationApi.pause(recording);
      current.current = r;
      onRecording(r);
    } catch (error) {
      onError(error instanceof Error ? error.message : "无法切换录制状态");
    }
  };
  return (
    <section className="auto-recording">
      <div className="auto-toolbar">
        {!recording ? (
          <button
            className="btn btn-primary"
            onClick={() => void handleStart()}
            disabled={busy}
          >
            ●{" "}
            {(workflow.draft.format === "clawith.cua.v1"
              ? workflow.draft.steps
              : []
            ).length
              ? "重新录制"
              : "开始录制桌面流程"}
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
              className="btn"
              onClick={() => void handlePause()}
              disabled={busy}
            >
              {recording.paused ? "核对桌面后继续录制" : "暂停记录"}
            </button>
            <button
              className="btn btn-primary"
              onClick={() => void handleStop()}
              disabled={busy}
            >
              停止并保存草稿
            </button>
          </>
        )}
        {recording && (
          <>
            <select
              aria-label="鼠标操作模式"
              value={mode}
              onChange={(e) => setMode(e.target.value as ActionName)}
            >
              <option value="click">单击</option>
              <option value="double_click">双击</option>
              <option value="right_click">右键</option>
            </select>
            <select
              aria-label="打开桌面应用"
              value=""
              disabled={busy}
              onChange={(e) => {
                if (e.target.value)
                  void send(
                    newStep("launch_app", {
                      app: e.target.value,
                      label: "打开应用",
                    }),
                  );
              }}
            >
              <option value="">打开应用…</option>
              {workflow.applications.map((a) => (
                <option key={a.id} value={a.id}>
                  {a.label}
                </option>
              ))}
            </select>
          </>
        )}
      </div>
      <p className="auto-hint">
        这里是服务器独立 Windows
        桌面。登录时可暂停记录；支持点击、快捷键、中文文本和结果验证。停止录制后请换数据试运行。
      </p>
      {notice && (
        <div className="auto-notice" role="status">
          {notice}
        </div>
      )}
      <div
        className={"auto-desktop " + (busy ? "busy" : "")}
        tabIndex={0}
        aria-label="独立 Windows 桌面"
        onKeyDown={(e) => {
          if (
            !recording ||
            busy ||
            ["Control", "Shift", "Alt", "Meta"].includes(e.key)
          )
            return;
          e.preventDefault();
          const modifiers: Step["modifiers"] = [];
          if (e.ctrlKey || e.metaKey) modifiers.push("ctrl");
          if (e.altKey) modifiers.push("alt");
          if (e.shiftKey) modifiers.push("shift");
          if (e.key.length === 1 && modifiers.length === 0)
            void send(newStep("type_text", { text: e.key }));
          else
            void send(
              newStep(modifiers.length ? "hotkey" : "press_key", {
                key: keyMap[e.key] || e.key.toLowerCase(),
                modifiers,
              }),
            );
        }}
        onPaste={(e) => {
          e.preventDefault();
          const value = e.clipboardData.getData("text");
          if (value) void send(newStep("type_text", { text: value }));
        }}
      >
        {frame ? (
          <img
            alt="Windows 桌面实时画面"
            draggable={false}
            src={`data:${frame.mime};base64,${frame.image}`}
            onClick={(e) => {
              const rect = e.currentTarget.getBoundingClientRect();
              e.currentTarget.parentElement?.focus({ preventScroll: true });
              void send(
                newStep(mode, {
                  x: Math.floor(
                    ((e.clientX - rect.left) * frame.width) / rect.width,
                  ),
                  y: Math.floor(
                    ((e.clientY - rect.top) * frame.height) / rect.height,
                  ),
                }),
              );
            }}
            onContextMenu={(e) => {
              e.preventDefault();
              const rect = e.currentTarget.getBoundingClientRect();
              void send(
                newStep("right_click", {
                  x: Math.floor(
                    ((e.clientX - rect.left) * frame.width) / rect.width,
                  ),
                  y: Math.floor(
                    ((e.clientY - rect.top) * frame.height) / rect.height,
                  ),
                }),
              );
            }}
          />
        ) : (
          <div className="auto-desktop-empty">
            <span>▣</span>
            <strong>
              {recording ? "正在连接独立桌面…" : "准备录制一个可复用的桌面流程"}
            </strong>
            <p>开始录制后，桌面画面将在这里显示。</p>
          </div>
        )}
      </div>
      {recording && (
        <div className="auto-inputs">
          <div className="auto-card">
            <h3>输入文字</h3>
            <textarea
              aria-label="发送到桌面的文本"
              value={text}
              onChange={(e) => setText(e.target.value)}
              placeholder="先点击桌面输入框，再输入或粘贴中文内容"
            />
            <div className="auto-row">
              <input
                aria-label="文本参数名"
                value={parameter}
                onChange={(e) => setParameter(e.target.value)}
                placeholder="参数名，可选，如 order_id"
              />
              <label>
                <input
                  type="checkbox"
                  checked={secret}
                  onChange={(e) => setSecret(e.target.checked)}
                />
                敏感参数
              </label>
              <button
                className="btn"
                disabled={busy || !text || (secret && !parameter)}
                onClick={() => {
                  void send(
                    newStep("type_text", {
                      text,
                      label: parameter ? `输入参数 ${parameter}` : "输入文本",
                    }),
                    parameter,
                    secret,
                  );
                  setText("");
                }}
              >
                发送文本
              </button>
            </div>
            <div className="auto-row">
              {["return", "tab", "escape", "backspace"].map((key) => (
                <button
                  className="btn auto-small"
                  key={key}
                  disabled={busy}
                  onClick={() => void send(newStep("press_key", { key }))}
                >
                  {key}
                </button>
              ))}
              <button
                className="btn auto-small"
                disabled={busy}
                onClick={() =>
                  void send(
                    newStep("hotkey", { key: "a", modifiers: ["ctrl"] }),
                  )
                }
              >
                Ctrl+A
              </button>
              <button
                className="btn auto-small"
                disabled={busy}
                onClick={() =>
                  void send(
                    newStep("hotkey", { key: "s", modifiers: ["ctrl"] }),
                  )
                }
              >
                Ctrl+S
              </button>
              {(["up", "down"] as const).map((direction) => (
                <button
                  className="btn auto-small"
                  key={direction}
                  disabled={busy}
                  onClick={() =>
                    void send(newStep("scroll", { direction, amount: 3 }))
                  }
                >
                  {direction === "up" ? "向上滚动" : "向下滚动"}
                </button>
              ))}
            </div>
          </div>
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
              className="btn"
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
        </div>
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
