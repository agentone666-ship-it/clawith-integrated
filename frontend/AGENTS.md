# Frontend AGENTS.md — Clawith Frontend Guidelines

---

## 1. Subsystem Overview

**Stack**: React 18, TypeScript, Vite, Tailwind CSS, shadcn/ui.
**Root Spec**: Extended from root [`AGENTS.md`](file:///Users/alex/Documents/Code/dataelem/Clawith/AGENTS.md).

---

## 2. Common Commands

From `frontend/` directory:

| Action | Command |
|---|---|
| Run Dev Server | `npm run dev` |
| Type Check | `npx tsc --noEmit` |
| Run Linter | `npm run lint` |
| Build Production Bundle | `npm run build` |

---

## 3. Frontend Hard Rules (P0)

- **TypeScript Only**: Functional components only. Class components are strictly prohibited.
- **Single File Line Limit**: File length MUST NOT exceed 600 lines. Split into sub-components or custom hooks when approaching limit.
- **Interface vs Type**: Use `interface` for component Props and public API structures; use `type` for internal unions/tuples.
- **Naming Conventions**:
  - Components: `PascalCase`
  - Utilities & Hooks: `camelCase` (hooks MUST start with `use`)
  - Event Handlers: Internal handler functions `handle<Event>` (e.g., `handleSubmit`), prop callbacks `on<Event>` (e.g., `onSubmit`).
- **Export Style**: Named exports ONLY (`export function ComponentName`). Default exports (`export default`) are forbidden.
- **HTTP Client Wrapper (C4)**: NEVER `import axios` directly in UI components or pages. Always use the unified request module (`src/api/request.ts`).
- **No Unexplained `any`**: Avoid `any`. If unavoidable due to external library constraints, append `// eslint-disable-next-line @typescript-scope` with a explicit reason on the preceding line.
- **Comment Language**: Write all code comments in clear English.

---

## 4. UI & Aesthetics Guidelines

- **Design System**: Use Tailwind CSS and shadcn/ui components for consistent design tokens.
- **Responsive Layout**: Ensure layouts adapt gracefully to desktop and mobile viewports.
- **Micro-Interactions**: Use smooth CSS transitions and hover states for interactive elements.

---

## 5. Lifecycle Ownership

Frontend-specific lifecycle ownership and cleanup rules will be defined here.

## Desktop automation

The Cloud desktops entry in the existing automation page lists only the current
account's persistent environments. Creation follows the first authenticated
Tool/recording call; do not add per-task VM configuration. Start/restore and
save stay in the same page, and active tasks prohibit manual saving. Show saved
compute separately from retained files and login state; never imply deletion.

The native workflow page is owned by [desktop automation](../docs/agent-notes/desktop-automation.md). Keep recorded RPA and Python source, parameters, executions and immutable version management in the same workflow context. The employee Tool tab remains the owner of full per-employee Tool configuration. Automation publication is independent of assignment; after publication an optional guide may batch-assign a fixed version to selected employees, and the version history must offer the same allocation entry. Do not require or preselect a fixed employee to publish. Python source editing must show actionable compiler and execution line feedback. Use the existing authenticated request wrapper. Record only actions sent through the isolated desktop panel; do not imply that global desktop hooks or semantic layout recovery exist.

The authoring entry has no business form. Start carries a bounded read-only Markdown attachment plus a short business template into the existing composer, without auto-send. The spec must not be inserted into editable message text. Reuse the existing file-card/send packaging so the model actually receives document content. Resize the composer on programmatic and typed content changes, with a viewport-bound scrolling cap. RunPanel and the Agent chat share the read-only RunPlayback viewer; observers read executor-owned captures and never acquire a desktop session. Preserve product tokens and follow [interaction patterns](../docs/interaction-patterns.md).

Composer auto-growth must measure on textarea mount as well as value/width changes; drafts may arrive before the chat UI loads. Keep preview panels in scrollable chat history and reserve composer space without clipping images. Verify the initial handed-off draft without typing, shrink-back, wrapped text, capped scrolling and input/send-button visibility in a short viewport with the preview open.

Desktop monitoring belongs in the scrollable chat content, not in a short clipped footer. Show the entire image with contain scaling and offer a portal-based viewport viewer with fit/1:1 modes, step navigation and Escape/focus restoration. Never crop the desktop to reserve composer space.

Scope the chat monitor to the selected session and latest AgentRun. Explain
when that Run has no desktop trial; terminal trials without frames must show
the actual failure instead of an indefinite first-frame waiting message.

ComposerInput owns inline auto-growth and viewport editing of the same controlled
draft. Use the available chat-panel height minus attachments, toolbar and a
small history reserve; do not restore the old 32vh cap. Large editing preserves
text, selection, focus and attachment cards and never dispatches a message.

Starting a new automation authoring task creates an empty native chat session
before navigation and targets it explicitly with ?session=. The chat owner
resolves that ID from the current user's authorized session list, or hydrates a
new empty POST receipt after the native runtime-state API re-authorizes it;
missing IDs must not fall back to a different conversation. Creation failure stays in
the guide, and startup never sends the staged business draft automatically.

A running desktop trial defaults to the live latest-frame endpoint, with capture
time and continued updates in the large viewer. Do not wait for Tool completion
or substitute final evidence while running. Historical step selection can pause
live following; the explicit return-to-live control restores it.

Direct Computer Use uses the current session/Run's private cached frame and
capture time in AgentRunMonitor, with the same viewport DesktopViewer as fixed
scripts. Polling observers never call a desktop Tool or acquire a session. Keep
terminal last-frame state distinct from ongoing execution and business success.

After Agent authoring/testing, show a concise Confirm publication action. Publish
that displayed trial digest and navigate in the SPA to the same workflow's
versions tab. Workflow diagnostics and employee Tool links stay in the current
page; do not use target=_blank. Preserve the originating chat in browser history.

The recording workspace uses same-page maximization so Escape can reach Windows
while the desktop keyboard has focus; the exit button remains available. Keep
only recording lifecycle and view controls in its toolbar. DesktopSurface owns
click/double-click/right-click, browser text/IME/paste and keyboard capture;
DesktopInputQueue owns a bounded, ordered queue of unsent manual input. Flush
pending text before navigation keys or pointer actions, and drain accepted input
before pause/save. Failed/uncertain writes clear later pending input without
replay. Neither an observer nor a rerender may claim a desktop session. Maintain
whole-image fitting, IME focus and coordinate mapping from the actual image.

Cloud desktop login sharing uses the managed Business Browser and the current
account. Show the host-owned browser sync projection without exposing secrets or
adding per-Agent credential configuration. Saved desktops sync on restore; do
not present an old saved snapshot as currently synchronized. Keep instance/file
isolation distinct from browser login sharing.

The HR recruitment UI lives in `src/pages/recruitment/` and uses the shared
request wrapper in `src/services/api.ts`. Dossiers and interview execution are
Backend-owned; the UI polls native Run projections and never invents completion
or pass status. See `docs/agent-notes/recruitment.md` for its contract.
