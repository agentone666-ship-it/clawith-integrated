export interface AuthoringReference {
  id: string;
  name: string;
}

export function buildAuthoringPrompt(
  task: string,
  spec: string,
  origin: string,
  reference: AuthoringReference | null,
): string {
  return `${spec}

## 本次业务任务
${task.trim() || "请先问我想固化哪个业务流程，然后按上述规范自主完成。"}

${reference ? `可只读参考当前流程 ${reference.id}（${reference.name}），不得覆盖该流程。` : ""}
Clawith 地址：${origin}。提交后返回 ${origin}/automations?workflow=<真实workflow_id>。
先读取当前 SDK，再由你设计参数、编写、实际提交、按业务授权试跑修复并发布。只在缺少关键业务信息时提问，不要让我选 Tool 或填写技术配置。`;
}
