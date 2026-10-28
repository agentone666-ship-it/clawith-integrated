import { useState } from "react";
import type { Version, Workflow } from "./contracts";
import { automationApi } from "./api";
interface Props {
  workflow: Workflow;
  onChanged: () => Promise<void>;
  onError: (message: string) => void;
}
export function VersionPanel({ workflow, onChanged, onError }: Props) {
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [selected, setSelected] = useState<Version | null>(null);
  const [notice, setNotice] = useState("");
  const perform = async (action: () => Promise<unknown>, message: string) => {
    setBusy(true);
    onError("");
    try {
      await action();
      setNotice(message);
      await onChanged();
    } catch (e) {
      onError(e instanceof Error ? e.message : "版本操作失败");
    } finally {
      setBusy(false);
    }
  };
  return (
    <section>
      <div className="auto-card">
        <h3>发布版本</h3>
        <p className="auto-hint">
          当前草稿必须完成结果验证并试运行通过。发布后自动注册为
          Tool，请到数字员工的 Tool 中统一管理。每个版本保持不变。
        </p>
        <div className="auto-row">
          <input
            aria-label="版本变更说明"
            value={note}
            onChange={(e) => setNote(e.target.value)}
            placeholder="本次修改了什么"
          />
          <button
            className="btn btn-primary"
            disabled={busy}
            onClick={() =>
              void perform(
                () => automationApi.publish(workflow, note),
                "版本已发布，可在数字员工的 Tool 中启用。",
              )
            }
          >
            发布当前草稿
          </button>
        </div>
      </div>
      {notice && (
        <p className="auto-notice" role="status">
          {notice}
        </p>
      )}
      <div className="auto-toolbar">
        <h3>版本历史</h3>
      </div>
      {!workflow.versions.length && (
        <div className="auto-empty">
          还没有发布版本。录制后先到“试运行与记录”验证。
        </div>
      )}
      {workflow.versions.map((v) => (
        <article className="auto-card" key={v.id}>
          <div className="auto-row">
            <span className="auto-version">v{v.number}</span>
            <strong>{v.note || "首次发布"}</strong>
            <span className="auto-spacer" />
            <time>{new Date(v.created_at).toLocaleString()}</time>
          </div>
          <p className="auto-hint">
            内容摘要 {v.digest.slice(0, 16)} · Tool {v.tool_id}
          </p>
          <div className="auto-row">
            <button
              className="btn"
              onClick={() => {
                void automationApi
                  .version(workflow.id, v.id)
                  .then(setSelected)
                  .catch((e) =>
                    onError(e instanceof Error ? e.message : "读取版本失败"),
                  );
              }}
            >
              与当前草稿对比
            </button>
            <button
              className="btn"
              disabled={busy || !!workflow.recording}
              onClick={() => {
                if (
                  window.confirm(
                    `将 v${v.number} 恢复为草稿？已发布版本和运行中的任务不会改变。`,
                  )
                )
                  void perform(
                    () => automationApi.restore(workflow, v.id),
                    `已从 v${v.number} 恢复草稿`,
                  );
              }}
            >
              恢复为草稿
            </button>
          </div>
        </article>
      ))}
      {selected && (
        <div className="auto-card">
          <div className="auto-row">
            <h3>v{selected.number} 与当前草稿</h3>
            <span className="auto-spacer" />
            <button className="btn" onClick={() => setSelected(null)}>
              关闭
            </button>
          </div>
          <div className="auto-diff">
            <div>
              <h4>已发布 v{selected.number}</h4>
              <pre>{JSON.stringify(selected.script, null, 2)}</pre>
            </div>
            <div>
              <h4>当前草稿</h4>
              <pre>{JSON.stringify(workflow.draft, null, 2)}</pre>
            </div>
          </div>
        </div>
      )}
    </section>
  );
}
