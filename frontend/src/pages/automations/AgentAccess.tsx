import { useEffect, useState } from "react";
import { agentApi } from "../../services/api";
import type { Agent } from "../../types";
import type { RegistryStatus } from "./contracts";
import { automationApi } from "./api";
interface Props {
  onClose: () => void;
  onError: (message: string) => void;
}
export function AgentAccess({ onClose, onError }: Props) {
  const [status, setStatus] = useState<RegistryStatus | null>(null);
  const [agents, setAgents] = useState<Agent[]>([]);
  const [agent, setAgent] = useState("");
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState("");
  useEffect(() => {
    let disposed = false;
    void Promise.all([automationApi.registry(), agentApi.list()])
      .then(([s, a]) => {
        if (!disposed) {
          setStatus(s);
          setAgents(a);
        }
      })
      .catch((e: unknown) => {
        if (!disposed)
          onError(e instanceof Error ? e.message : "无法读取 Agent 接入信息");
      });
    return () => {
      disposed = true;
    };
  }, [onError]);
  const perform = async (bind: boolean) => {
    setBusy(true);
    try {
      if (bind) {
        await automationApi.bindManager(agent);
        setNotice("管理 Tool 已分配。可让该 Agent 编写、测试并发布自动化。");
      } else {
        setStatus(await automationApi.registerManager());
        setNotice("管理 Tool 已启用，请分配给 coding Agent。");
      }
    } catch (e) {
      onError(e instanceof Error ? e.message : "接入失败");
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="auto-modal-backdrop" onClick={onClose}>
      <section
        className="auto-modal"
        role="dialog"
        aria-modal="true"
        aria-label="Agent 接入"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="auto-row">
          <h2>Agent 接入</h2>
          <span className="auto-spacer" />
          <button className="btn" onClick={onClose}>
            关闭
          </button>
        </div>
        <p>
          给 coding Agent
          分配“桌面自动化管理”Tool，即可让它编写脚本、根据失败反馈修复、测试后自行发布，再把版本
          Tool 交给业务 Agent。
        </p>
        <p className="auto-hint">
          管理操作沿用任务发起人的流程和员工配置权限。只有管理员可启用和分配管理
          Tool。业务员工只需绑定已发布版本。
        </p>
        <p>管理 Tool：{status?.enabled ? "已启用" : "尚未启用"}</p>
        {!status?.enabled && (
          <button
            className="btn btn-primary"
            disabled={busy || !status}
            onClick={() => void perform(false)}
          >
            启用管理 Tool
          </button>
        )}
        <label>
          选择 coding Agent
          <select
            aria-label="管理 Tool 的 coding Agent"
            value={agent}
            onChange={(e) => setAgent(e.target.value)}
          >
            <option value="">选择员工…</option>
            {agents
              .filter((a) => a.agent_type === "native")
              .map((a) => (
                <option key={a.id} value={a.id}>
                  {a.name}
                </option>
              ))}
          </select>
        </label>
        <button
          className="btn btn-primary"
          disabled={busy || !status?.enabled || !agent}
          onClick={() => void perform(true)}
        >
          分配管理 Tool
        </button>
        {notice && (
          <p className="auto-notice" role="status">
            {notice}
          </p>
        )}
        <details>
          <summary>Agent 编写与发布说明</summary>
          <pre className="auto-sdk">{status?.sdk || "加载中…"}</pre>
        </details>
      </section>
    </div>
  );
}
