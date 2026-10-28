import assert from "node:assert/strict";
import test from "node:test";
import { buildAuthoringPrompt as build } from "../src/pages/automations/authoringPrompt.ts";

test("one business task carries the actual specification without configuration questions", () => {
  const prompt = build(
    "核对采购金额，用测试申请 TEST-001 验证后发布",
    "# 实际 Agent 规范\n必须实际提交",
    "http://dev",
    { id: "source-id", name: "采购录制" },
  );
  assert.ok(prompt.startsWith("# 实际 Agent 规范"));
  assert.match(prompt, /TEST-001/);
  assert.match(prompt, /实际提交/);
  assert.match(prompt, /不要让我选 Tool/);
  assert.match(prompt, /只在缺少关键业务信息时提问/);
  assert.match(prompt, /source-id/);
  assert.match(prompt, /不得覆盖/);
  assert.match(prompt, /http:\/\/dev\/automations\?workflow=<真实workflow_id>/);
  assert.ok(!prompt.includes("testAndPublish"));
});

test("blank request asks only the business goal rather than configuration", () => {
  const prompt = build("", "# 工作规范", "http://dev", null);
  assert.match(prompt, /先问我想固化哪个业务流程/);
  assert.ok(!prompt.includes("可只读参考"));
});
