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
    validComposerHandoff({ ...v, text: "界".repeat(8192) }, "agent", 1000),
    true,
  );
  assert.equal(validComposerHandoff(v, "agent", 301000), true);
  assert.equal(validComposerHandoff(v, "agent", 301001), false);
});
