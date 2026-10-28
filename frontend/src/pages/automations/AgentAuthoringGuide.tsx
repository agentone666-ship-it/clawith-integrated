import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { copyToClipboard } from "../../utils/clipboard";
import { automationApi } from "./api";
import type { AuthoringAgent, AuthoringReadiness, Workflow } from "./contracts";
import { buildAuthoringPrompt, type AuthoringBrief } from "./authoringPrompt";
import "./authoring.css";

interface Props {
  workflow: Workflow | null;
  onClose: () => void;
  onFind: (name: string) => Promise<void>;
  onManual: () => void;
}
const initial: AuthoringBrief = {
  name: "",
  goal: "",
  parameters: "",
  steps: "",
  success: "",
  testData: "",
  testAndPublish: false,
};

export function AgentAuthoringGuide({
  workflow,
  onClose,
  onFind,
  onManual,
}: Props) {
  const [step, setStep] = useState(1);
  const [search, setSearch] = useState("");
  const [offset, setOffset] = useState(0);
  const [page, setPage] = useState<AuthoringReadiness | null>(null);
  const [agent, setAgent] = useState<AuthoringAgent | null>(null);
  const [loading, setLoading] = useState(true);
  const [refresh, setRefresh] = useState(0);
  const [error, setError] = useState("");
  const [copied, setCopied] = useState(false);
  const [brief, setBrief] = useState<AuthoringBrief>(initial);
  const [reference, setReference] = useState(!!workflow);
  useEffect(() => {
    let disposed = false;
    const timer = setTimeout(() => {
      void automationApi
        .authoring(search, offset)
        .then((value) => {
          if (!disposed) {
            setPage(value);
            setLoading(false);
            setAgent((previous) =>
              previous
                ? value.items.find((a) => a.id === previous.id) || null
                : null,
            );
          }
        })
        .catch((e: unknown) => {
          if (!disposed) {
            setError(e instanceof Error ? e.message : "无法检查工具接入状态");
            setLoading(false);
            setPage(null);
            setAgent(null);
          }
        });
    }, 200);
    return () => {
      disposed = true;
      clearTimeout(timer);
    };
  }, [search, offset, refresh]);
  useEffect(() => {
    const close = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", close);
    return () => document.removeEventListener("keydown", close);
  }, [onClose]);
  const prompt = useMemo(
    () =>
      buildAuthoringPrompt(
        brief,
        window.location.origin,
        reference && workflow ? { id: workflow.id, name: workflow.name } : null,
      ),
    [brief, reference, workflow],
  );
  const valid =
    brief.name.trim() &&
    brief.goal.trim() &&
    brief.success.trim() &&
    (!brief.testAndPublish || brief.testData.trim());
  const handleChange = (key: keyof AuthoringBrief, value: string | boolean) => {
    setBrief((previous) => ({ ...previous, [key]: value }));
    setCopied(false);
  };
  const handleCopy = async () => {
    const ok = await copyToClipboard(prompt);
    setCopied(ok);
    if (!ok) setError("自动复制未成功，请选中下方任务文本后手动复制。");
  };
  const handleExample = () => {
    setBrief({
      name: "创建采购草稿（请改成你的流程名）",
      goal: "根据采购申请资料选择合规供应商，计算含税到货金额，只保存采购草稿。",
      parameters:
        "申请编号、采购数量、交付日期；金额按当前报价和业务规则计算。",
      steps:
        "打开采购系统，查询申请，核对供应商资格和交期，填写草稿，检查确认弹窗并保存。请以实际界面为准。",
      success:
        "核对保存后的申请编号、供应商、数量和含税金额，并确认只生成一条草稿。",
      testData: "",
      testAndPublish: false,
    });
    setCopied(false);
  };
  return (
    <div className="auto-modal-backdrop" onClick={onClose}>
      <section
        className="auto-modal auto-authoring-modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby="authoring-title"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="auto-row">
          <h2 id="authoring-title">让 coding agent 编写并提交脚本</h2>
          <span className="auto-spacer" />
          <button
            className="btn"
            aria-label="关闭脚本编写引导"
            onClick={onClose}
          >
            ×
          </button>
        </div>
        <p className="auto-authoring-lead">
          Agent 通过管理 Tool
          提交后，草稿才会进入这里。只在聊天里贴代码，不算提交。
        </p>
        <ol className="auto-authoring-progress">
          {["准备 coding agent", "描述固定流程", "发送任务并验收"].map(
            (title, i) => (
              <li
                key={title}
                className={
                  step === i + 1 ? "active" : step > i + 1 ? "done" : ""
                }
              >
                {i + 1}. {title}
              </li>
            ),
          )}
        </ol>
        {error && (
          <p className="auto-error" role="alert">
            {error}
          </p>
        )}
        {step === 1 && (
          <div>
            <div className="auto-authoring-explainer">
              <strong>两个 Tool，两个用途</strong>
              <p>
                <b>coding agent：</b>
                启用「桌面自动化管理」（automation_registry），用它创建、修改和提交脚本。
              </p>
              <p>
                <b>业务 agent：</b>脚本测试并发布后，只分配对应的版本
                Tool，用固定流程处理业务。
              </p>
            </div>
            {!loading && !page?.manager.enabled && (
              <p className="auto-notice">
                {page?.manager.tool_id
                  ? "管理 Tool 尚未启用，请管理员在员工 Tool 配置中检查全局状态。"
                  : "平台尚未注册管理 Tool，请联系管理员开通此能力。此引导不会自动安装工具或授予权限。"}
              </p>
            )}
            <label>
              选择 Clawith 中的 coding agent
              <input
                aria-label="搜索 coding agent"
                value={search}
                maxLength={120}
                placeholder="按员工名称搜索，如脚本工程师"
                onChange={(e) => {
                  setSearch(e.target.value);
                  setOffset(0);
                  setAgent(null);
                  setLoading(true);
                  setError("");
                }}
              />
            </label>
            <div className="auto-authoring-agents" aria-busy={loading}>
              {loading ? (
                <p>正在检查工具接入状态…</p>
              ) : !page?.items.length ? (
                <p>
                  没有匹配的可管理员工。可换个名称，或先创建一个有编程能力的原生员工。
                </p>
              ) : (
                page.items.map((a) => (
                  <button
                    key={a.id}
                    className={agent?.id === a.id ? "selected" : ""}
                    aria-pressed={agent?.id === a.id}
                    onClick={() => setAgent(a)}
                  >
                    <span>{a.name}</span>
                    <small>
                      {a.ready ? "管理 Tool 已就绪" : "尚未启用管理 Tool"}
                    </small>
                  </button>
                ))
              )}
            </div>
            <div className="auto-row">
              <span className="auto-hint">仅显示你有权配置的原生员工</span>
              <span className="auto-spacer" />
              <button
                className="btn"
                disabled={loading || offset === 0}
                onClick={() => {
                  setOffset(Math.max(0, offset - 50));
                  setAgent(null);
                  setLoading(true);
                }}
              >
                上一页
              </button>
              <button
                className="btn"
                disabled={loading || page?.next_offset == null}
                onClick={() => {
                  if (page?.next_offset != null) {
                    setOffset(page.next_offset);
                    setAgent(null);
                    setLoading(true);
                  }
                }}
              >
                下一页
              </button>
            </div>
            {agent && (
              <div className="auto-authoring-setup">
                <strong>{agent.name}</strong>
                <p>
                  打开员工「Tool」页，搜索并启用「桌面自动化管理」，再回这里重新检查。凭据由平台管理，不需要发给
                  Agent。
                </p>
                <div className="auto-row">
                  <Link
                    className="btn"
                    to={`/agents/${agent.id}/settings#tools`}
                    target="_blank"
                    rel="noreferrer"
                  >
                    打开员工 Tool 配置 ↗
                  </Link>
                  <button
                    className="btn"
                    disabled={loading}
                    onClick={() => {
                      setLoading(true);
                      setError("");
                      setRefresh((n) => n + 1);
                    }}
                  >
                    重新检查接入
                  </button>
                </div>
              </div>
            )}
            <details className="auto-authoring-external">
              <summary>如果使用 Codex、Cursor 等外部 coding agent</summary>
              <p>
                外部聊天没有当前 Clawith 员工的 Runtime
                身份，不能仅凭一段代码自动提交。让它按下方 Python 编辑器的桌面
                SDK 输出源码与参数说明，再新建「Python
                脚本」粘贴保存、试跑。不要把平台凭据复制给外部客户端。
              </p>
              <button className="btn" onClick={onManual}>
                打开手动提交 Python 脚本入口
              </button>
            </details>
            <div className="auto-authoring-footer">
              <span className="auto-hint">管理 Tool 就绪后即可继续</span>
              <button
                className="btn btn-primary"
                disabled={loading || !agent?.ready}
                onClick={() => {
                  setStep(2);
                  setError("");
                }}
              >
                下一步：描述任务
              </button>
            </div>
          </div>
        )}
        {step === 2 && (
          <div className="auto-authoring-brief">
            <div className="auto-row">
              <p className="auto-hint">
                描述业务，让 Agent
                编写参数化的固定脚本。之后复用同一版本，不需要每次重新规划。
              </p>
              <button className="btn" onClick={handleExample}>
                填入采购示例
              </button>
            </div>
            <label>
              流程名称
              <input
                aria-label="编写任务流程名称"
                maxLength={120}
                value={brief.name}
                onChange={(e) => handleChange("name", e.target.value)}
                placeholder="例如：核对发票并保存核验方案"
              />
            </label>
            <label>
              要完成什么
              <textarea
                aria-label="脚本业务目标"
                maxLength={2000}
                value={brief.goal}
                onChange={(e) => handleChange("goal", e.target.value)}
                placeholder="说明系统、规则和最终要保存的结果"
              />
            </label>
            <div className="auto-authoring-grid">
              <label>
                每次变化的输入
                <textarea
                  aria-label="脚本输入参数说明"
                  maxLength={1000}
                  value={brief.parameters}
                  onChange={(e) => handleChange("parameters", e.target.value)}
                  placeholder="订单号、日期、数量等；账号密码用敏感参数占位"
                />
              </label>
              <label>
                已知界面步骤
                <textarea
                  aria-label="已知业务操作步骤"
                  maxLength={2000}
                  value={brief.steps}
                  onChange={(e) => handleChange("steps", e.target.value)}
                  placeholder="可描述你的操作，Agent 仍需观察真实界面或沿用已验证录制"
                />
              </label>
            </div>
            <label>
              怎样才算成功
              <textarea
                aria-label="脚本成功条件"
                maxLength={1000}
                value={brief.success}
                onChange={(e) => handleChange("success", e.target.value)}
                placeholder="例如：编号与金额正确、显示保存成功，且记录没有重复"
              />
            </label>
            {workflow && (
              <label className="auto-authoring-checkbox">
                <input
                  type="checkbox"
                  checked={reference}
                  onChange={(e) => setReference(e.target.checked)}
                />
                参考当前流程「{workflow.name}」，新建副本，不覆盖原流程
              </label>
            )}
            <label className="auto-authoring-checkbox">
              <input
                type="checkbox"
                checked={brief.testAndPublish}
                onChange={(e) =>
                  handleChange("testAndPublish", e.target.checked)
                }
              />
              同时用给定测试数据试跑，通过后发布（不自动分配）
            </label>
            {brief.testAndPublish ? (
              <label>
                可用于试跑的测试数据
                <textarea
                  aria-label="授权试跑测试数据"
                  maxLength={1000}
                  value={brief.testData}
                  onChange={(e) => handleChange("testData", e.target.value)}
                  placeholder="填写已准备好的测试编号和参数，不填凭据"
                />
              </label>
            ) : (
              <p className="auto-hint">
                默认只提交草稿。你可以先在流程库检查，再决定何时试运行和发布。
              </p>
            )}
            <div className="auto-authoring-footer">
              <button className="btn" onClick={() => setStep(1)}>
                上一步
              </button>
              <button
                className="btn btn-primary"
                disabled={!valid}
                onClick={() => {
                  setStep(3);
                  setError("");
                }}
              >
                生成给 Agent 的任务
              </button>
            </div>
          </div>
        )}
        {step === 3 && (
          <div>
            <div className="auto-authoring-explainer">
              <strong>复制后，发给 {agent?.name}</strong>
              <p>
                这份任务明确要求调用管理 Tool 的 create
                提交。没有调用提交操作，聊天里的代码不会出现在流程库。
              </p>
            </div>
            <textarea
              className="auto-authoring-prompt"
              aria-label="给 coding agent 的完整任务"
              readOnly
              value={prompt}
              onFocus={(e) => e.currentTarget.select()}
            />
            <div className="auto-row">
              <button
                className="btn btn-primary"
                onClick={() => void handleCopy()}
              >
                复制任务
              </button>
              {agent && (
                <Link
                  className="btn"
                  to={`/agents/${agent.id}/chat`}
                  target="_blank"
                  rel="noreferrer"
                >
                  去 coding agent 聊天 ↗
                </Link>
              )}
            </div>
            {copied && (
              <p className="auto-notice" role="status">
                任务已复制。去员工聊天粘贴并发送；这里不会替你自动发消息。
              </p>
            )}
            <div className="auto-authoring-checklist">
              <h3>提交后，到哪里看</h3>
              <ol>
                <li>
                  Agent 应返回
                  workflow_id、草稿链接和参数说明；不是只回复一段代码。
                </li>
                <li>
                  点返回的链接，或回流程库按名称查找，检查「Python
                  脚本」源码与参数。
                </li>
                <li>
                  到「试运行与记录」换数据验证；失败时把运行 ID 和诊断发回 Agent
                  修复。
                </li>
                <li>验证成功后发布 Tool，再按需批量分配给业务员工。</li>
              </ol>
            </div>
            <div className="auto-authoring-footer">
              <button className="btn" onClick={() => setStep(2)}>
                修改需求
              </button>
              <button className="btn" onClick={() => void onFind(brief.name)}>
                返回流程库查找草稿
              </button>
            </div>
          </div>
        )}
      </section>
    </div>
  );
}
