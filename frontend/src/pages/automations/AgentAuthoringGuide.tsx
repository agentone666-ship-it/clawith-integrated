import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { copyToClipboard } from "../../utils/clipboard";
import { automationApi } from "./api";
import type { AuthoringReadiness, Workflow } from "./contracts";
import { buildAuthoringPrompt } from "./authoringPrompt";
import "./authoring.css";

interface Props {
  workflow: Workflow | null;
  onClose: () => void;
  onManual: () => void;
}

export function AgentAuthoringGuide({ workflow, onClose, onManual }: Props) {
  const navigate = useNavigate();
  const [page, setPage] = useState<AuthoringReadiness | null>(null);
  const [task, setTask] = useState("");
  const [error, setError] = useState("");
  const [copied, setCopied] = useState(false);
  useEffect(() => {
    let disposed = false;
    void automationApi
      .authoring("", 0)
      .then((value) => {
        if (!disposed) setPage(value);
      })
      .catch((e: unknown) => {
        if (!disposed)
          setError(
            e instanceof Error
              ? e.message
              : "暂时无法读取编写规范，请稍后重试。",
          );
      });
    return () => {
      disposed = true;
    };
  }, []);
  useEffect(() => {
    const close = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", close);
    return () => document.removeEventListener("keydown", close);
  }, [onClose]);
  // The capability sorts enabled manager assignments first; no grant is inferred.
  const ready = page?.items.filter((a) => a.ready) || [];
  const agent = ready.find((a) => a.name.includes("脚本工程师")) || ready[0];
  const handleCopy = async (openChat = false) => {
    if (!page) return;
    const prompt = buildAuthoringPrompt(
      task,
      page.spec_markdown,
      window.location.origin,
      workflow ? { id: workflow.id, name: workflow.name } : null,
    );
    if (!(await copyToClipboard(prompt))) {
      setError("复制未成功，请下载规范后交给 Agent。");
      return;
    }
    setCopied(true);
    setError("");
    if (openChat && agent) navigate(`/agents/${agent.id}/chat`);
  };
  const handleDownload = () => {
    if (!page) return;
    const url = URL.createObjectURL(
      new Blob([page.spec_markdown], { type: "text/markdown;charset=utf-8" }),
    );
    const a = document.createElement("a");
    a.href = url;
    a.download = "AUTOMATION_AGENT.md";
    a.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
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
          <h2 id="authoring-title">把流程交给 Agent</h2>
          <span className="auto-spacer" />
          <button
            className="btn"
            aria-label="关闭脚本编写入口"
            onClick={onClose}
          >
            ×
          </button>
        </div>
        <p className="auto-authoring-lead">
          说清楚要完成什么就行。Agent 按规范负责写脚本、入库、试跑修复和发布。
        </p>
        <label>
          你想固定下来哪个业务流程？
          <textarea
            aria-label="业务任务"
            maxLength={4000}
            value={task}
            onChange={(e) => {
              setTask(e.target.value);
              setCopied(false);
            }}
            placeholder="例如：把采购申请生成草稿的操作做成可复用 Tool。订单号和数量每次会变，用测试申请 TEST-001 验证，通过后发布。"
          />
        </label>
        <p className="auto-hint">
          流程名、参数和实现方式由 Agent 整理。缺关键业务信息时，它再问你。
        </p>
        {error && (
          <p className="auto-error" role="alert">
            {error}
          </p>
        )}
        {!page && !error && <p>正在读取 Agent 工作规范…</p>}
        <div className="auto-row">
          {agent ? (
            <button
              className="btn btn-primary"
              onClick={() => void handleCopy(true)}
            >
              复制任务并去 Agent 聊天
            </button>
          ) : (
            <button
              className="btn btn-primary"
              disabled={!page}
              onClick={() => void handleCopy()}
            >
              复制任务与规范
            </button>
          )}
          <button className="btn" disabled={!page} onClick={handleDownload}>
            下载规范 MD
          </button>
        </div>
        {agent ? (
          <p className="auto-hint">
            已连接 {agent.name}。点击后在聊天中粘贴发送，无需选 Tool
            或配置参数。
          </p>
        ) : (
          page && (
            <p className="auto-hint">
              当前没有已接入管理 Tool 的可用员工。可先把规范交给已有 coding
              agent；平台接入由管理员处理。
            </p>
          )
        )}
        {copied && (
          <p className="auto-notice" role="status">
            任务与规范已复制，直接发给 coding agent 即可。
          </p>
        )}
        <details className="auto-authoring-details">
          <summary>规范里已经告诉 Agent 怎么交付</summary>
          <p>
            读取 SDK → 自行观察和编写 → 实际提交到流程库 →
            在业务授权范围内试跑修复 →
            成功后发布。不会把聊天里的代码当作已入库，也不会让你填技术配置。
          </p>
          <p>
            可查看{" "}
            <Link to="/automations" onClick={onClose}>
              流程库
            </Link>
            中的实际结果。使用外部 coding agent 时，下载规范交给它；未接入管理
            Tool 时可
            <button className="btn" onClick={onManual}>
              手动导入 Python 源码
            </button>
            。
          </p>
        </details>
      </section>
    </div>
  );
}
