import { useEffect, useState } from "react";
import { agentApi } from "../../services/api";
import type { Agent } from "../../types";
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
  const [agents, setAgents] = useState<Agent[]>([]);
  const [agent, setAgent] = useState("");
  const [selected, setSelected] = useState<Version | null>(null);
  const [notice, setNotice] = useState("");
  useEffect(() => {
    let stopped = false;
    void agentApi
      .list()
      .then((a) => {
        if (!stopped) setAgents(a);
      })
      .catch((e) => {
        if (!stopped) onError(e instanceof Error ? e.message : "无法读取员工");
      });
    return () => {
      stopped = true;
    };
  }, [onError]);
  const perform = async (action: () => Promise<unknown>, message: string) => {
    setBusy(true);
    onError('');
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
        <h3>发布为 Agent Tool</h3>
        <p className="auto-hint">
          当前草稿必须完成结果验证并试运行通过。每个发布版本保持不变，发布新版不会自动升级已有员工绑定。
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
                "版本已发布，可绑定给员工调用。",
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
        <span className="auto-spacer" />
        <select
          aria-label="绑定版本的员工"
          value={agent}
          onChange={(e) => setAgent(e.target.value)}
        >
          <option value="">选择要绑定的员工…</option>
          {agents
            .filter((a) => a.agent_type === "native")
            .map((a) => (
              <option key={a.id} value={a.id}>
                {a.name}
              </option>
            ))}
        </select>
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
            <button
              className="btn"
              disabled={busy || !agent}
              onClick={() =>
                void perform(
                  () => automationApi.bind(workflow.id, v.id, agent),
                  `员工已绑定 v${v.number}，其他工具不受影响。`,
                )
              }
            >
              绑定给所选员工
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
