# Desktop workflow capability

Build from the repository root with the same backend image that owns the current Clawith database and authentication contract:

```sh
docker build --build-arg BASE_IMAGE=your-clawith-backend-image -f deploy/desktop-automation/Dockerfile -t clawith-desktop-automation:local .
```

Provision a private signing key file and evidence directory. Keep credentials out of source control. Set `AUTOMATION_ENV_FILE`, `CUA_DRIVER_TOKEN_PATH`, `AUTOMATION_SIGNING_KEY_PATH`, `AUTOMATION_EVIDENCE_PATH`, and the existing external `CLAWITH_NETWORK` when it differs. The private env file contains the existing backend's `DATABASE_URL`, `SECRET_KEY` and any explicit JWT settings, plus:

- `AUTOMATION_TENANT_ID`: company owning this isolated desktop.
- `AUTOMATION_DRIVER_URL`: existing authenticated Cua bridge MCP endpoint.
- `AUTOMATION_DRIVER_TOOL_ID`: existing raw desktop Tool used for preflight reservation checks.
- `AUTOMATION_MCP_URL=http://clawith-desktop-automation:8080/api/automation-mcp`.
- `AUTOMATION_APPLICATIONS`: JSON map of launcher IDs to server-owned `label`, `path`, optional `args`.

The Compose file sets token, signing key and evidence paths inside the container. Before startup, apply only this capability's schema:

```sh
docker compose -f deploy/desktop-automation/compose.yml run --rm --entrypoint python desktop-automation -m app.services.desktop_automation.migrate
docker compose -f deploy/desktop-automation/compose.yml up -d desktop-automation
```

The existing frontend nginx template routes the capability's API prefixes to the service alias. Build the frontend normally. For Vite development, `AUTOMATION_DEV_URL` defaults to `http://127.0.0.1:18128`. Existing backend API and WebSocket routes remain unchanged. Nginx configuration testing and frontend acceptance must precede rollout.

Use exactly one feature worker/replica. Before an update, verify no recording, release-pending session or playback is active. Do not restart the main Runtime to update this capability. An interrupted playback is unknown, never automatically repeated. Back up the feature schema, signing key and private evidence together. Rotating the signing key invalidates published Tool credentials and requires controlled republishing.

Development acceptance: [`docs/agent-notes/desktop-automation.md`](../../docs/agent-notes/desktop-automation.md) and `backend/tests/test_desktop_automation.py`. Business benchmark fixtures and deployment-specific artifacts belong in the task handoff, not in the Runtime core.

## Persistent Windows host

The Windows host owns libvirt, writable overlays, separate NVRAM/TPM state,
leases and idle managed-save. The Runtime/capability receive no hypervisor or
Docker socket. Prepare a generalized clean Windows image with QEMU Guest Agent,
virtio drivers, the interactive Clawith account, Cua bridge and application
catalog. Keep the sealed backing image immutable while any overlay exists.
Run Sysprep in an elevated administrator session, never the System/QGA session.
The development acceptance found that System-context sealing breaks XAML shell
registration on modern Windows. Record the sealing principal and verify a fresh
clone before rollout. Set `WINDOWS_SANDBOX_TEMPLATE` to an immutable versioned
backing image path; existing overlays retain their original backing reference.
Production images need the operator's Windows licensing; the development
acceptance uses a Windows evaluation image.

Install the host package `backend/app/services/desktop_automation/sandbox_host`
and run `setup-windows-host.py` on the designated KVM host. Inspect its explicit
network, bind address, storage and quota settings before reuse on another host.
Place a pinned Python environment beside the package (FastAPI 0.115.12,
uvicorn 0.34.2, httpx 0.28.1), then start/enable
`clawith-windows-sandbox.service` after sealing the template.

Set `AUTOMATION_SANDBOX_URL` to the private host endpoint and
`AUTOMATION_SANDBOX_TOKEN_PATH` to its private gateway-token file. The separate
`AUTOMATION_MANAGED_APPLICATIONS` catalog uses installed guest-local paths.
The existing catalog remains only for explicitly pinned pre-cutover Runs.
`AUTOMATION_LEGACY_RUN_IDS` may contain only genuine already-running Run IDs;
remove each entry once the Run ends. Never use a blanket shared-desktop fallback.

Before capability replacement, inspect active/release-pending recordings,
running playback and in-flight desktop Tool receipts; do not cut over mid-input.
Retain existing keys, compiler configuration and evidence mounts. Apply only
this capability's migration head. Start/restore uses a bounded HTTP 425 response
while initialization continues; the response guarantees no input was sent.
The client may retry that response, never an uncertain write.

Back up host private state (encrypted by the operator's backup service), VM
overlays, NVRAM, TPM state and managed-save memory together. A saved desktop
releases guest CPU/RAM and retains disk/memory state; it is not deletion or a
backup. Migrating saved memory requires compatible pinned CPU/device layout.
Do not transfer a used overlay to another account.
