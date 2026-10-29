import { RunPlayback } from "./RunPlayback";
import { useEffect, useState } from "react";
import type { Run, Script } from "./contracts";
import { automationApi } from "./api";
interface Props {
  workflowId: string;
  script: Script;
  runs: Run[];
  onChanged: () => Promise<void>;
  onError: (message: string) => void;
}
const labels: Record<string, string> = {
  running: "执行中",
  succeeded: "验证通过",
  failed: "失败",
  unknown: "结果未确认",
  cancelled: "已取消",
};
export function RunPanel({
  workflowId,
  script,
  runs,
  onChanged,
  onError,
}: Props) {
  const [inputs, setInputs] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const [evidence, setEvidence] = useState<Record<string, string>>({});
  const running = runs.some((r) => r.status === "running");
  useEffect(() => {
    if (!running) return;
    let stopped = false;
    let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      try {
        await onChanged();
      } catch (e) {
        if (!stopped)
          onError(e instanceof Error ? e.message : "无法获取运行状态");
      }
      if (!stopped) timer = setTimeout(poll, 1500);
    };
    timer = setTimeout(poll, 1500);
    return () => {
      stopped = true;
      clearTimeout(timer);
    };
  }, [running, onChanged, onError]);
  const test = async () => {
    setBusy(true);
    try {
      await automationApi.test(
        workflowId,
        Object.fromEntries(
          Object.keys(script.parameters).map((k) => [k, inputs[k] || ""]),
        ),
      );
      await onChanged();
    } catch (e) {
      onError(e instanceof Error ? e.message : "无法启动试运行");
    } finally {
      setBusy(false);
    }
  };
  return (
    <section>
      <div className="auto-card">
        <h3>换一组数据试运行</h3>
        <p className="auto-hint">
          先保存草稿并停止录制。试运行会真实操作独立桌面，请使用测试数据。
        </p>
        <div className="auto-parameter-grid">
          {Object.entries(script.parameters).map(([key, description]) => (
            <label key={key}>
              {description}
              <code>{key}</code>
              <input
                aria-label={`试运行参数 ${key}`}
                type={
                  script.secret_parameters.includes(key) ? "password" : "text"
                }
                value={inputs[key] || ""}
                onChange={(e) =>
                  setInputs({ ...inputs, [key]: e.target.value })
                }
              />
            </label>
          ))}
        </div>
        <button
          className="btn btn-primary"
          disabled={
            busy ||
            running ||
            (script.format === "clawith.cua.v1"
              ? !script.steps.length
              : !script.source.trim())
          }
          onClick={() => void test()}
        >
          {busy ? "正在启动…" : "▶ 试运行草稿"}
        </button>
      </div>
      <div className="auto-run-list">
        {!runs.length && (
          <div className="auto-empty">试运行后，在这里查看每一步的结果。</div>
        )}
        {runs.map((run) => (
          <article className="auto-card" key={run.id}>
            <div className="auto-row">
              <span className={"auto-badge " + run.status}>
                {labels[run.status] || run.status}
              </span>
              <strong>{run.version_id ? "发布版本调用" : "草稿验证"}</strong>
              <span className="auto-spacer" />
              <time>{new Date(run.created_at).toLocaleString()}</time>
            </div>
            <p className="auto-hint">
              {run.id} · 已完成 {run.progress} 步 · 脚本{" "}
              {run.digest.slice(0, 12)}{" "}
              {run.result.seconds !== undefined &&
                `· ${run.result.seconds.toFixed(2)} 秒`}
            </p>
            {(run.status === "running" || !!run.result.trace?.length) && (
              <RunPlayback run={run} />
            )}
            {run.agent_run_id && (
              <p className="auto-hint">Agent Run：{run.agent_run_id}</p>
            )}
            {run.result.error && (
              <p className="auto-error">
                {(run.result.diagnostic?.line ||
                  run.result.failed_source_line) &&
                  `源码第 ${run.result.diagnostic?.line || run.result.failed_source_line} 行 · `}
                {run.result.failed_step && `步骤 ${run.result.failed_step}：`}
                {run.result.error}
              </p>
            )}
            {run.result.compiler_stdout && (
              <details>
                <summary>脚本诊断输出</summary>
                <pre>{run.result.compiler_stdout}</pre>
              </details>
            )}
            {Object.keys(run.input_summary || {}).length > 0 && (
              <details>
                <summary>输入参数</summary>
                <pre>{JSON.stringify(run.input_summary, null, 2)}</pre>
              </details>
            )}
            <div className="auto-row">
              {run.status === "running" && (
                <button
                  className="btn btn-secondary"
                  disabled={run.cancel_requested}
                  onClick={() => {
                    void automationApi
                      .cancel(run.id)
                      .then(onChanged)
                      .catch((e) =>
                        onError(e instanceof Error ? e.message : "取消失败"),
                      );
                  }}
                >
                  {run.cancel_requested
                    ? "正在等待当前动作结束…"
                    : "取消后续步骤"}
                </button>
              )}
              {run.result.evidence && (
                <button
                  className="btn btn-secondary"
                  onClick={() => {
                    void automationApi
                      .evidence(run.id)
                      .then((f) =>
                        setEvidence({
                          ...evidence,
                          [run.id]: `data:${f.mime};base64,${f.image}`,
                        }),
                      )
                      .catch((e) =>
                        onError(
                          e instanceof Error ? e.message : "无法读取证据",
                        ),
                      );
                  }}
                >
                  查看桌面结果截图
                </button>
              )}
            </div>
            {evidence[run.id] && (
              <img
                className="auto-evidence"
                alt="运行后的桌面结果"
                src={evidence[run.id]}
              />
            )}
          </article>
        ))}
      </div>
    </section>
  );
}
