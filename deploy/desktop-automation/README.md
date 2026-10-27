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
