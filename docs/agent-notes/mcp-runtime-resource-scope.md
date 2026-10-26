# MCP resource leases bound to Runtime identity

The MCP execution adapter may opt in through `Tool.config.runtime_context_meta`.
For those tools only, the adapter reads the authoritative current Run from the
existing execution scope, verifies its assigned agent, and sends MCP `_meta`
under `io.clawith/runtime`. The metadata contains tenant, Run and agent UUIDs,
plus at most 256 held lane identities in that tenant, including the current
Run. Missing identity, wrong ownership or an oversized snapshot fails before
dispatch. Model arguments cannot supply or replace this metadata. Other MCP
tools retain their existing wire requests.

AgentRun remains the owner of scheduling state. The metadata is a bounded
point-in-time projection for provider resource reconciliation, not a second
Run lifecycle, model prompt, authorization token or cancellation command.

The current consumer is the isolated Cua desktop adapter. It derives its native
session label from the Run UUID, ignoring model-supplied session labels. One
active Run retains the desktop; another active Run cannot steal it. A new Run
in the same tenant can close the old native session only after the authoritative
lane snapshot shows that the old owner no longer holds its execution lane.
Another tenant's snapshot never proves the old owner ended. Existing inactivity
expiry remains the bound for abandoned or diagnostic sessions. Application
state remains on the isolated desktop when a session is ended.

An explicit release drops the native session and lease. If completion repair
needs a fresh observation within the same Run, the adapter starts that native
session again before dispatch; this does not replay a previous write. Provider
write request IDs and private idempotency receipts remain separate from Run
identity. Lease handoffs are logged with their reason and timestamp.

The opt-in is currently supported by the direct HTTP MCP transport. It is not
enabled for other registered tools or Smithery connections. The development
desktop is single-resource and is not a multi-tenant VM isolation guarantee.

Verification covers metadata placement outside model arguments, Run ownership,
bounded lane reads, failure before dispatch without identity, session-label
changes within a Run, active-owner fencing, ended-owner handoff, tenant fencing,
release/reopen for verification, and missing write-ID rejection without lease
acquisition. Live deployment evidence is recorded separately from these tests.
