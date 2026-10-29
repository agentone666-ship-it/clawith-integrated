import assert from "node:assert/strict";
import test from "node:test";
import { validComposerHandoff } from "../src/pages/agent-detail/hooks/useComposerHandoff.ts";
test("composer handoff validates recipient, freshness and complete encoded size", () => {
  const v = { agentId: "agent", text: "规范", createdAt: 1000 };
  assert.equal(validComposerHandoff(v, "agent", 1000), true);
  for (const bad of [
    null,
    {},
    { ...v, agentId: "other" },
    { ...v, text: "" },
    { ...v, text: "界".repeat(8193) },
    { ...v, createdAt: 1001 },
  ])
    assert.equal(validComposerHandoff(bad, "agent", 1000), false);
  assert.equal(
    validComposerHandoff({ ...v, text: "界".repeat(8100) }, "agent", 1000),
    true,
  );
  assert.equal(validComposerHandoff(v, "agent", 301000), true);
  assert.equal(validComposerHandoff(v, "agent", 301001), false);
});

test("document card preserves content and rejects excessive or invalid document payload", () => {
  const v = {
    agentId: "agent",
    text: "目标：【填写】",
    createdAt: 1000,
    document: { name: "AUTOMATION_AGENT.md", text: "# 规范" },
  };
  assert.equal(validComposerHandoff(v, "agent", 1000), true);
  assert.equal(
    validComposerHandoff(
      { ...v, document: { name: "other.md", text: "# fake" } },
      "agent",
      1000,
    ),
    false,
  );
  assert.equal(
    validComposerHandoff(
      {
        ...v,
        document: { name: "AUTOMATION_AGENT.md", text: "界".repeat(6000) },
      },
      "agent",
      1000,
    ),
    false,
  );
  const base = { agentId: "agent", text: "", createdAt: 1000 };
  const n = 24576 - new TextEncoder().encode(JSON.stringify(base)).length;
  assert.equal(
    validComposerHandoff({ ...base, text: "a".repeat(n) }, "agent", 1000),
    true,
  );
  assert.equal(
    validComposerHandoff({ ...base, text: "a".repeat(n + 1) }, "agent", 1000),
    false,
  );
});
