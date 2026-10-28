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
export interface RpaScript {
  format: "clawith.cua.v1";
  steps: Step[];
  parameters: Record<string, string>;
  secret_parameters: string[];
}
export interface PythonScript {
  format: "clawith.python.v1";
  source: string;
  parameters: Record<string, string>;
  secret_parameters: string[];
}
export type Script = RpaScript | PythonScript;
export interface WorkflowSummary {
  kind: "rpa" | "python";
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
  script: RpaScript;
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
    diagnostic?: { code: string; message: string; line?: number };
    failed_source_line?: number;
    compiler_stdout?: string;
    total_steps?: number;
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
export function reconcileParameters(script: RpaScript): RpaScript {
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

export function emptyPython(): PythonScript {
  return {
    format: "clawith.python.v1",
    source:
      '# 先通过 Agent 管理 Tool 观察独立桌面，再编写操作\nfrom automation import ui, inputs\n\n# w = ui.window("notepad.exe", "*Notepad*")\n# ui.type_text(inputs["text"], target=w)\n# ui.assert_text(inputs["text"], target=w)\n',
    parameters: {},
    secret_parameters: [],
  };
}

export interface AssignmentAgent {
  id: string;
  name: string;
  assigned: boolean;
  versions: { id: string; number: number }[];
}
export interface AssignmentPage {
  items: AssignmentAgent[];
  total: number;
  offset: number;
  next_offset: number | null;
}
export interface AssignmentResult {
  version_id: string;
  tool_id: string;
  number: number;
  assigned_count: number;
  changed_count: number;
  unchanged_count: number;
  agents: { id: string; name: string }[];
}

export interface AuthoringAgent {
  id: string;
  name: string;
  assigned: boolean;
  ready: boolean;
}
export interface AuthoringReadiness {
  spec_markdown: string;
  manager: { tool_id: string | null; enabled: boolean; name: string };
  items: AuthoringAgent[];
  total: number;
  offset: number;
  next_offset: number | null;
}
