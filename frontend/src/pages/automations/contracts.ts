export interface Target {
  app: string;
  title: string;
}
export type ActionName =
  | "click"
  | "double_click"
  | "right_click"
  | "type_text"
  | "press_key"
  | "hotkey"
  | "scroll"
  | "assert_text"
  | "launch_app";
export interface Step {
  id: string;
  action: ActionName;
  app: string;
  label: string;
  target: Target | null;
  x: number | null;
  y: number | null;
  text: string;
  key: string;
  modifiers: ("ctrl" | "shift" | "alt" | "win")[];
  direction: "up" | "down" | "left" | "right";
  amount: number;
  timeout_seconds: number;
}
export interface Script {
  format: "clawith.cua.v1";
  steps: Step[];
  parameters: Record<string, string>;
  secret_parameters: string[];
}
export interface WorkflowSummary {
  id: string;
  name: string;
  description: string;
  revision: number;
  updated_at: string;
}
export interface Recording {
  id: string;
  workflow_id: string;
  status: string;
  paused: boolean;
  script: Script;
  last_seen: string;
}
export interface Version {
  id: string;
  number: number;
  digest: string;
  note: string;
  tool_id: string | null;
  created_at: string;
  script?: Script;
}
export interface Run {
  id: string;
  workflow_id: string;
  version_id: string | null;
  agent_run_id: string | null;
  status: string;
  digest: string;
  progress: number;
  input_summary: Record<string, string>;
  cancel_requested: boolean;
  created_at: string;
  result: {
    error?: string;
    failed_step?: number | null;
    seconds?: number;
    evidence?: boolean;
    release_confirmed?: boolean;
  };
}
export interface Workflow extends WorkflowSummary {
  draft: Script;
  versions: Version[];
  runs: Run[];
  recording: Recording | null;
  applications: { id: string; label: string }[];
}
export interface DesktopWindow {
  app_name: string;
  title: string;
  pid: number;
  window_id: number;
  z_index: number;
  bounds: { x: number; y: number; width: number; height: number };
}
export interface Frame {
  image: string;
  mime: string;
  width: number;
  height: number;
  windows: DesktopWindow[];
}
export interface ActionResult {
  status: string;
  detail: string;
  recording: Recording;
}
// HTTP LAN deployments lack crypto.randomUUID; getRandomValues remains available.
export function operationId(): string {
  const bytes = crypto.getRandomValues(new Uint8Array(16));
  return Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join("");
}
export function newStep(action: ActionName, changes: Partial<Step> = {}): Step {
  return {
    id: operationId(),
    action,
    app: "",
    label: "",
    target: null,
    x: null,
    y: null,
    text: "",
    key: "",
    modifiers: [],
    direction: "down",
    amount: 3,
    timeout_seconds: 8,
    ...changes,
  };
}
export function reconcileParameters(script: Script): Script {
  const names = new Set(
    script.steps.flatMap((step) =>
      [
        ...`${step.text}\n${step.target?.title || ""}`.matchAll(
          /\$\{([a-zA-Z][a-zA-Z0-9_]{0,39})\}/g,
        ),
      ].map((m) => m[1]),
    ),
  );
  return {
    ...script,
    parameters: Object.fromEntries(
      [...names].map((n) => [n, script.parameters[n] || n]),
    ),
    secret_parameters: script.secret_parameters.filter((n) => names.has(n)),
  };
}
export const actionLabels: Record<ActionName, string> = {
  click: "单击",
  double_click: "双击",
  right_click: "右键",
  type_text: "输入文本",
  press_key: "按键",
  hotkey: "快捷键",
  scroll: "滚动",
  assert_text: "验证结果",
  launch_app: "打开应用",
};
