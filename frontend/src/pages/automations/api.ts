import { operationId } from "./contracts";
import { request } from "../../api/request";
import type {
  Workflow,
  WorkflowSummary,
  Script,
  Recording,
  Frame,
  Step,
  ActionResult,
  Run,
  Version,
  AssignmentPage,
  AssignmentResult,
  AuthoringReadiness,
  AgentDesktopActivity,
} from "./contracts";
const base = "/automations";
const post = <T>(path: string, value: unknown = {}) =>
  request<T>(base + path, { method: "POST", body: JSON.stringify(value) });
export const automationApi = {
  authoring: (search: string, offset: number) =>
    request<AuthoringReadiness>(
      base +
        "/authoring?" +
        new URLSearchParams({ search, offset: String(offset) }),
    ),
  agentActivity: (agentId: string, sessionId: string) =>
    request<AgentDesktopActivity | null>(
      base +
        "/agent-activity/" +
        agentId +
        "?" +
        new URLSearchParams({ session_id: sessionId }),
    ),
  computerFrame: (id: string) =>
    request<{
      image: string;
      mime: string;
      sequence: string;
      captured_at: string;
    }>(base + "/computer-runs/" + id + "/live"),
  liveFrame: (id: string) =>
    request<{
      image: string;
      mime: string;
      sequence: string;
      captured_at: string;
    }>(base + "/runs/" + id + "/live"),
  latestAgentRun: (agentId: string) =>
    request<Run | null>(base + "/agent-runs/" + agentId),
  runFrame: (id: string, step: number) =>
    request<{ image: string; mime: string }>(
      base + "/runs/" + id + "/frames/" + step,
    ),
  list: () => request<WorkflowSummary[]>(base),
  create: (name: string, description: string, script?: Script) =>
    post<Workflow>("", { name, description, script }),
  detail: (id: string) => request<Workflow>(base + "/" + id),
  save: (w: Workflow, script: Script) =>
    request<Workflow>(base + "/" + w.id, {
      method: "PUT",
      body: JSON.stringify({
        name: w.name,
        description: w.description,
        revision: w.revision,
        script,
      }),
    }),
  record: (w: Workflow) =>
    post<Recording>("/" + w.id + "/recordings", { revision: w.revision }),
  frame: (id: string) => request<Frame>(base + "/recordings/" + id + "/frame"),
  action: (
    id: string,
    step: Step,
    parameter_name = "",
    parameter_label = "",
    secret = false,
  ) =>
    post<ActionResult>("/recordings/" + id + "/actions", {
      request_id: operationId(),
      step,
      parameter_name,
      parameter_label,
      secret,
    }),
  pause: (r: Recording) =>
    post<Recording>("/recordings/" + r.id + "/pause", { paused: !r.paused }),
  stop: (id: string) => post<Recording>("/recordings/" + id + "/stop"),
  test: (
    id: string,
    inputs: Record<string, string>,
    version_id: string | null = null,
  ) =>
    post<Run>("/" + id + "/test", {
      inputs,
      request_id: operationId(),
      version_id,
    }),
  run: (id: string) => request<Run>(base + "/runs/" + id + "/status"),
  evidence: (id: string) =>
    request<{ image: string; mime: string }>(
      base + "/runs/" + id + "/evidence",
    ),
  cancel: (id: string) => post<Run>("/runs/" + id + "/cancel"),
  publish: (w: Workflow, note: string) =>
    post<{ number: number; version_id: string; tool_id: string }>(
      "/" + w.id + "/versions",
      { revision: w.revision, note },
    ),
  version: (id: string, version: string) =>
    request<Version>(base + "/" + id + "/versions/" + version),
  assignmentCandidates: (
    id: string,
    version: string,
    search: string,
    offset: number,
  ) =>
    request<AssignmentPage>(
      base +
        "/" +
        id +
        "/versions/" +
        version +
        "/agents?" +
        new URLSearchParams({ search, offset: String(offset) }),
    ),
  assign: (id: string, version: string, agent_ids: string[]) =>
    post<AssignmentResult>("/" + id + "/versions/" + version + "/assignments", {
      agent_ids,
    }),
  restore: (w: Workflow, version: string) =>
    post("/" + w.id + "/versions/" + version + "/restore", {
      revision: w.revision,
    }),
};
