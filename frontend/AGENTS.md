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

The native workflow page is owned by [desktop automation](../docs/agent-notes/desktop-automation.md). Keep recorded RPA and Python source, parameters, executions and immutable version management in the same workflow context. The employee Tool tab remains the owner of full per-employee Tool configuration. Automation publication is independent of assignment; after publication an optional guide may batch-assign a fixed version to selected employees, and the version history must offer the same allocation entry. Do not require or preselect a fixed employee to publish. Python source editing must show actionable compiler and execution line feedback. Use the existing authenticated request wrapper. Record only actions sent through the isolated desktop panel; do not imply that global desktop hooks or semantic layout recovery exist.

The authoring entry has no business form. Start carries a bounded read-only Markdown attachment plus a short business template into the existing composer, without auto-send. The spec must not be inserted into editable message text. Reuse the existing file-card/send packaging so the model actually receives document content. Resize the composer on programmatic and typed content changes, with a viewport-bound scrolling cap. RunPanel and the Agent chat share the read-only RunPlayback viewer; observers read executor-owned captures and never acquire a desktop session. Preserve product tokens and follow [interaction patterns](../docs/interaction-patterns.md).

Composer auto-growth must measure on textarea mount as well as value/width changes; drafts may arrive before the chat UI loads. Keep preview panels in scrollable chat history and reserve composer space without clipping images. Verify the initial handed-off draft without typing, shrink-back, wrapped text, capped scrolling and input/send-button visibility in a short viewport with the preview open.

Desktop monitoring belongs in the scrollable chat content, not in a short clipped footer. Show the entire image with contain scaling and offer a portal-based viewport viewer with fit/1:1 modes, step navigation and Escape/focus restoration. Never crop the desktop to reserve composer space.

Scope the chat monitor to the selected session and latest AgentRun. Explain
when that Run has no desktop trial; terminal trials without frames must show
the actual failure instead of an indefinite first-frame waiting message.
