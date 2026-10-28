import assert from "node:assert/strict";
import test from "node:test";
import { buildAuthoringPrompt as build } from "../src/pages/automations/authoringPrompt.ts";

test("authoring handoff requires actual submission and explicit trial scope", () => {
  const brief = {
    name: "采购草稿",
    goal: "计算并保存",
    parameters: "订单号",
    steps: "",
    success: "编号和金额正确",
    testData: "",
    testAndPublish: false,
  };
  const draft = build(brief, "http://dev", null);
  assert.match(draft, /本次只编写并提交草稿/);
  assert.match(draft, /operation=create，name/);
  assert.match(draft, /原生对象 script=/);
  assert.match(draft, /http:\/\/dev\/automations\?workflow=<实际workflow_id>/);
  assert.match(draft, /ui\.assert_text/);
  assert.match(draft, /不算提交/);
  const noData = build({ ...brief, testAndPublish: true }, "http://dev", null);
  assert.match(noData, /本次只编写并提交草稿/);
  const withData = build(
    { ...brief, testData: "订单 TEST-1", testAndPublish: true },
    "http://dev",
    { id: "source-id", name: "原录制" },
  );
  assert.match(withData, /已授权用上述测试数据试运行/);
  assert.match(withData, /真实 test 成功才可 publish/);
  assert.match(withData, /最多三轮/);
  assert.match(withData, /不自动绑定/);
  assert.match(withData, /source-id/);
  assert.match(withData, /禁止修改或覆盖/);
});
