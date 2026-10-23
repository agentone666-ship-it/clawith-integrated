# MCP image evidence for model-owned computer control

The dynamic MCP adapter owns protocol decoding. A synchronous successful MCP
result may contain one PNG, JPEG or WebP image; its decoded image is validated
and handed to the existing private ToolResultStore through `private_binary`.
Malformed, oversized, MIME-mismatched or multiple images return an unknown
outcome so an executed GUI action is not silently replayed. Async completion
and provider-error semantics are unchanged.

ToolResultStore remains the owner of private storage, tenant/run checks,
binary references, replay and reconciliation. Base64 bytes never enter the
tool summary, ledger metadata or checkpoint message. The existing model-step
image resolver accepts privately archived image refs from any tool, retaining
the legacy AgentBay screenshot checks. Pixels are resolved only while building
the outbound multimodal model request. Missing private evidence does not cause
an external screenshot or click to be repeated.

Screenshot resolution retains the current Run and tenant scope. A historical
image outside that scope remains text with a request for fresh screen state;
its pixels are not loaded and it does not prevent a later chat turn. Corrupt or
missing bytes inside the accepted scope still fail evidence preparation.

The deterministic completion verifier recognizes `tool-result-binary://` as a
private ToolResultStore reference. It calls `resolve_binary` with the exact
tenant and Run before accepting it, rather than sending the URI to an external
artifact reader. Missing stores or invalid scope still block completion. This
checks evidence readability; the existing task gate retains responsibility for
whether the evidence proves the user's requested result.

The current consumer is an atomic Cua Driver MCP tool. The model, multi-step
planning, retries and task completion remain owned by Clawith Runtime. Neither
the driver nor its transport adapter invokes an LLM. The integration runs on
an isolated server desktop; it does not target a user's physical desktop.

Verification covers valid/invalid MCP image decoding, private archival and
model-request restoration after restart, existing dynamic MCP and AgentBay
contracts, and historical image scope rejection. Deployment acceptance is
recorded separately with the real chat run and native-app file checks.
