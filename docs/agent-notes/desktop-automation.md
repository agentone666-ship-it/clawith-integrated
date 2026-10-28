# Recorded desktop workflows in Clawith

The native `/automations` page owns the workflow library, isolated desktop recording, editable drafts, parameter declarations, trial executions and immutable published versions. Cua Driver is an input and observation provider; the existing Clawith Runtime remains the only agent scheduler and model owner. Recording captures actions through this panel, not global OS events on the user's workstation. Login may be performed with capture paused. Mouse dragging and semantic control selectors are not supported in this first version.

Scripts use the bounded declarative `clawith.cua.v1` contract. Text placeholders are literal substitutions, never executable code. Configured application launchers are server-owned. Clicks store window-relative coordinates and an app/title identity. Each execution resolves the current window, checks bounds and reads that window’s own screenshot before foreground delivery. The adapter converts the provider’s observed frame margin, refusing unknown geometry. This tolerates window movement; layout or DPI changes require revalidation. A missing or ambiguous window fails before input. No persisted HWND/PID is reused.

The additive single-worker capability process shares existing Clawith authentication, tenant authorization, PostgreSQL and Tool/AgentTool records. It owns only the `desktop_automation` schema and its independent Alembic version table. Its Docker network endpoint is exposed through the existing frontend nginx. It does not start an agent scheduler or migrate unrelated Runtime tables. Do not run multiple replicas until desktop reservation ownership is coordinated across workers.

A manual recording and a playback reserve the same physical Cua desktop used by the existing raw Tool. The provider lease is authoritative. The capability also checks active recordings, playbacks and raw-Tool Agent Runs. Manual work never fabricates Runtime identity. Published Tools require a genuine held AgentRun, matching tenant and agent, enabled Tool binding and the existing opt-in Runtime MCP metadata. Model arguments cannot establish this identity.

Recording writes get durable request receipts before dispatch. Identical request IDs return the receipt; conflicting inputs reject. An uncertain input pauses capture and preserves the attempted step for inspection. An explicit verification may confirm the result and resume capture. Adjacent plain text is merged; parameter sample values are RAM-only. Secret parameters are masked in history, though the target application and screenshot may visibly contain submitted values.

Playback pins the entire script, digest and supplied input summary before execution. Inputs are sent once. Only read-only assertions poll. An uncertain write may be reconciled by the explicitly authored following assertion only when that assertion was observed absent immediately before dispatch and becomes present afterwards; the input is never repeated. Otherwise the result is unknown. Evidence storage and resource release are independent terminal facts. Cancellation stops subsequent steps. Restarted running reservations become unknown. Idle manual capture expires after 90 seconds and autosaves only if its original draft revision still matches. Concurrent draft edits never silently overwrite each other.

Publication requires an explicit result assertion and a successful trial for the exact current content digest. Published versions cannot be edited. Restore copies a version into a new draft revision. Each version is an ordinary scoped MCP Tool; binding a different version changes only this workflow's assignment on the selected employee. Publication does not automatically upgrade existing assignments. A successful UI assertion is not sufficient evidence of business correctness; benchmark graders independently inspect stored business records.

Validation commands and deployment evidence are in the task handoff and backend test file. The development deployment overlays the older running frontend baseline to avoid replacing unrelated UI behavior, while the review branch targets upstream a1740a7. Nginx uses a graceful reload and retains old hashed assets; the existing backend container is not restarted.


## Agent-authored Python and management Tool

The same workflow library now owns `clawith.python.v1` source alongside recorded
`clawith.cua.v1` steps. The type is derived from its persisted source contract.
The browser selects RPA recording or Python editing at creation. Recording cannot
replace a Python draft. Draft revision, trial history, immutable releases,
and version restore share the automation lifecycle. Publication first registers an
independent Tool, without selecting or mutating an employee. A dismissible
post-publication guide offers search, pagination, multi-selection and optional
batch allocation; version history provides the same entry later. Full per-employee
Tool configuration remains in the employee Tool tab. No default employee is
selected, and closing the guide does not undo publication.
The management Tool is listed as 桌面自动化管理, and execution Tools
use the workflow name and immutable version. Existing programmatic bindings and
execution authorization remain supported.

`AutomationRegistry` owns manager operations. Its opt-in `automation_registry`
MCP Tool supports `sdk`, `list`, `get`, `version`, `observe`, `create`, `update`,
`test`, `run_status`, `publish`, `bind` and `execute`. The registry bootstrap and programmatic assignment endpoints remain capability
integration APIs; the employee Tool tab uses the shared `/api/tools/agents/{id}` Tool API. The
post-publication shortcut uses `VersionAssignments` to write the same central
AgentTool records, never a second assignment store. Candidate pages contain at
most 50 manageable native employees; a submission contains 1–100 distinct IDs.
All selected employees must still satisfy the human configuration policy and
same-tenant/native checks before any writes. One invalid target rejects the
whole batch. Agent rows are locked in UUID order, repeat submissions are
idempotent, and each selected employee switches only this workflow's version.
Unselected employees and unrelated Tools are untouched. New publication never
automatically upgrades existing assignments. The legacy single bind endpoint
and management-Tool caller delegate to this same mutation boundary. Never enable it
by default on business employees. A management call verifies an actual held Run,
matching Agent/tenant, enabled Tool/assignment, and active `origin_user_id`.
Workflow access and Agent configuration use that origin user's existing policy,
never the workflow owner's identity. A manager calling `execute` must also have
the particular published version Tool assigned. Playback enforces assignment at
its own boundary so bypassing an MCP preflight does not bypass authorization.

Python is a bounded planning language, not host code execution. The `automation`
SDK exposes `ui` and string `inputs`; pure computation/loops/branches generate at
most 120 literal actions. It does not read live GUI state inside Python. Agents
observe through the management Tool first, or adapt validated recorded steps.
RPA `get`/`version` also returns `python_template`: a mechanical translation
that preserves action order, window identities, coordinates, input references
and result checks. Agents add derived values to their local `inputs` dictionary
before this sequence. Oversized templates or mixed secret interpolation are
explicitly omitted; paginated RPA reads remain available. This scaffold does
not choose business values or invent controls; the Agent authors calculations
and must run a real trial.
Configured applications, fresh window lookup, relative coordinates, assertions,
uncertain input reconciliation and cleanup are shared with RPA playback.
Literal Python output is never interpreted as RPA `${parameter}` placeholders.
Secret inputs stay out of the compiler: opaque references can only be passed
straight to `ui.type_text`; the executor substitutes actual values in memory.
Submitted values may still be visible in the target application/screenshots.

`compiler_gateway` is a host-only authenticated provider bound to the private
Docker bridge. It resolves an immutable Python image ID and compiles in temporary
containers: no network, no host mounts/credentials, read-only root, UID65534,
128MiB memory, 0.5 CPU, PID16, 3 CPU-second and 10 wall-second bounds, 8MiB tmpfs,
256KiB output limit and two concurrent slots. The gateway alone has Docker
access; never mount that socket into the capability or user containers. AST
restrictions provide SDK feedback; the container is the execution isolation
boundary. Docker containers share the host kernel; this is not a hostile
multi-tenant VM isolation claim. Stop/reconcile a compile container if provider
cleanup is ever unconfirmed. A compiler service restart while compiling can
leave a bounded container to be reclaimed by its provider operator.

The capability sends non-secret inputs and source to `AUTOMATION_COMPILER_URL`,
authenticating with `AUTOMATION_COMPILER_TOKEN_FILE`. The image ID and worker
source hash form `compiler_fingerprint`. Publication records that fingerprint
and `validation_run_id` using the independent `002_script_publication_proof`
migration. Old RPA releases need neither field. Source/schema changes require a
new successful draft test. Published Python execution refuses a changed compiler
fingerprint; revalidate/publish instead of silently changing the SDK. A version
pins source and SDK identity; each call recomputes its plan for current inputs.
A passing input does not establish all possible branches or business correctness.

Compile failures produce durable failed trial receipts before any desktop
claim, with diagnostic code/message/source line and `desktop_started=false`.
Runtime failures identify the action and Python source line, with evidence and
release status independent. Trial responses omit the persisted compiled plan;
it is retained internally without secret values for diagnosis. Source and RPA
step reads are paginated for model context. The advertised MCP schema in
`registry_schema` explicitly types objects and inlines step definitions. A real
Qwen3.5-flash trial repeatedly encoded nested `$ref`/union script parameters as
strings; the inline contract fixes that integration failure without changing
the Runtime. Backend Pydantic validation remains authoritative, and field
errors omit raw submitted source. Do not reintroduce opaque references into the
model-facing schema without a real Runtime regression trial. Test and execute calls wait for the
shared executor and also expose run IDs for status lookup. A lost MCP response
must be reconciled using the same request ID, never a fresh business write.

Focused verification:

```sh
PYTHONPATH=.:../../test-deps .venv/bin/python -m pytest -q tests/test_desktop_automation.py tests/test_automation_registry.py
.venv/bin/ruff check app/services/desktop_automation app/api/desktop_automation.py tests/test_desktop_automation.py tests/test_automation_registry.py
.venv/bin/pyright --pythonpath .venv/bin/python --pythonversion 3.12 app/services/desktop_automation app/api/desktop_automation.py
npx tsc --noEmit
npx eslint src/pages/automations --max-warnings 0
```

The local `test-deps` path supplies SQLite support in the task checkout; normal
`uv sync --extra dev` installs the declared `aiosqlite` dev dependency. Production
still uses PostgreSQL. Runtime GUI proof requires the actual isolated Windows
provider and independent fixture record grader, not these unit fixtures.


### Development deployment evidence (2026-10-28 UTC)

The capability and conservative frontend overlay are deployed on development
port 3009. Live Runtime migration remains `f061_enterprise_info_tenant_id`;
feature migration is `002_script_publication_proof`. The review checkout's
unmodified main migration head is `f066_employee_blueprints`. Existing backend
container `d4a1332f5e62` started on October 26 and was not restarted. The compiler
is an enabled host systemd service; its token is a private file, never committed.
Backend capability/API file hashes were compared against the deployed container.

The real model was the development pool's `qwen3.5-flash`, not a Codex-generated
business script. Two initial 30-call trials did not complete: nested source
arguments were encoded as strings, followed by code and coordinate mistakes.
The inline schema fixed native object submission; source-line feedback let the
model repair a real `NameError` at line 30. That alone did not prevent guessed
coordinates or omitted modal confirmation. With the mechanical RPA template,
the model authored supplier filtering, Decimal tax/freight calculation and reason
text, retained 18 verified GUI actions, tested, published and bound the version.
This final authoring trial completed in 7 calls/93.165 seconds (one bind argument
error corrected). Its GUI execution took 18.582 seconds; the independent fixture
verified every saved record field. This is one synthetic business scenario,
not a benchmark-wide success rate or proof of unattended general code ability.

Reviewable example:
- Workflow `360176b8-19b5-4ec9-a24a-958e8e2ff1c3`
- Version `8c423a0e-5f33-40e6-97b6-62df7bdff509` (v1)
- Published Tool `a9de5be6-42e8-4c06-9df0-3f440e7d2705`
- Successful author trial `47c7d96a-c82a-4975-98e0-5470c7e88336`
- Coding Agent Run `b633130d-848b-409e-86ce-2378d7dd658e`
- Business Agent Run `5b5e15e5-0042-46d8-ae4d-ee6a35b2ab85`

A separate Qwen business Agent, with only the version execution Tool, used fresh
quantity/unit-price inputs and called twice with one operation ID. Both calls
succeeded with one playback `157d9f2a-7e2d-4c72-8127-22b98ab0c99e` and exactly one
saved business record. Independent grading verified the new 60642.80 total,
supplier, quantity, reference, date and reason. The physical desktop was released.
After final backend replacement, both an existing RPA workflow and the published
Python version passed another fresh-input GUI/business-record regression.

Headless browser verification covered Python creation/editing, failed source
line display, refusal to publish untested source, RPA/Python library filters,
published version display and management Tool assignment. No page errors were
observed. All GUI/provider tests ran on the server's isolated Windows desktop;
the user's Mac foreground screen was untouched. Server sandbox tests covered
valid compilation, syntax-line feedback, denied unsupported imports, a bounded
infinite loop and removal of temporary containers. Final audit found no active
recordings/playbacks or leftover compiler/test-browser containers.

Focused local verification passed 36 tests (20 existing, 16 new), Ruff, targeted
Pyright, frontend TypeScript/ESLint and the deployment-baseline production build.
A pre-existing Pydantic deprecation warning remains in sandbox config. Raw
non-credential evidence is retained in the task's `registry-*.json` and screenshots,
with server copies under its existing studio deployment directory.


### Tool UI ownership correction

The desktop automation page now owns source/recording, trials, evidence and
version publication only. Tool assignment controls have been removed from both
the page header and version history. The unused Agent access component and its
frontend assignment clients are deleted. Publication continues registering an
ordinary Tool, so the existing digital employee Tool tab can discover, enable,
disable and configure both the registry Tool and every released execution Tool.
The UI change does not alter current assignments or remove Agent-driven
programmatic publication/assignment consumers.

The correction was deployed to the conservative development frontend overlay.
TypeScript, automation-page ESLint and the production build passed. A headless
browser verified the absence of binding controls and then searched, toggled and
reloaded both the management Tool and a published execution Tool in the existing
employee Tool tab. Both assignments persisted through the shared Tool API, with
no page errors. The temporary verification employee and browser were removed.


### Optional allocation after publication (2026-10-28)

The human publication flow now offers a dismissible multi-employee allocation
guide instead of a fixed employee selector. The same dialog is reachable from
each published version. Candidate search is literal and paginated, selection
is explicit and bounded, and already-enabled targets show their actual state.
The old single-bind integration path delegates to the same transactional owner.
Twelve assignment tests cover multi-target switching, unrelated Tool/config
preservation, duplicate submission, whole-batch denial, permissions and paging;
all 48 focused automation/registry/assignment tests passed. Actual development
UI acceptance published a Tool without an employee, skipped the guide, reopened
it and enabled the Tool for two isolated test employees. Independent AgentTool
readback confirmed both assignments, the third employee retaining v1, unchanged
unrelated Tools, no extra rows on replay, and no partial changes for a mixed
invalid batch. Runtime backend container was not replaced.


### Coding-Agent authoring handoff (2026-10-28, superseded below)

A persistent library entry and the Python creation dialog open a three-step guide:
check a manageable native employee's actual `automation_registry` readiness,
structure a business brief, then copy an explicit creation task and open that
employee's chat. Readiness uses the same central SQL management scope as version
allocation, filters native employees, and bounds/literal-searches each page. It
is read-only: no installation, permission grants, chat sends, desktop dispatches,
or script mutations occur when using this guide. Tool configuration remains in
the employee Tool tab.

The generated task requires the current SDK and an actual `create` operation with
a native script object, name and description, and a real workflow/revision/link
receipt. Chat-only code is not submission. The default scope is draft-only;
explicit optional trial/publication requires test data, real verification and a
bounded repair loop, without automatic employee assignment. An existing workflow
can be read as a reference but must not be overwritten. External Codex/Cursor
users receive the separate manual Python-editor route: their chat does not
possess a Clawith Run identity.

Verification: 53 focused backend tests passed (including five guide cases),
plus the generated-task contract test, Ruff, targeted Pyright, frontend
TypeScript/ESLint and the conservative frontend production build. Live server
headless acceptance checked readiness denial/refresh, employee Tool/chat links,
business example/required fields, draft-only native-create prompt, read-only
reference, LAN HTTP copy, explicit test-data guard, library return and external
manual Python entry. Wide/narrow screenshots were inspected. No automation
mutation or chat send occurred during the guide acceptance, and the main Runtime
container remained unchanged. This proves the guide and handoff contract, not a
new model-authored business execution. Previously-ready coding employees sort
first so a new user can discover them without knowing their names.


### Agent-owned authoring specification (2026-10-28, current)

User feedback rejected the multi-step configuration guide. Its employee picker,
readiness refresh controls, separate business-field form and test/publication
checkboxes are removed. The current entry accepts one natural-language business
task, reads actual readiness and chooses an already-enabled coding employee
(prefer a named script engineer, otherwise the first enabled manager assignment).
No new grant or fixed workflow binding occurs. The action copies the task and
specification and opens that employee's existing chat; the human pastes/sends.
A Markdown download supports external coding agents. This preserves existing
chat delivery semantics without a second Agent scheduler or task state machine.

`backend/app/services/desktop_automation/AUTOMATION_AGENT.md` is the single
agent-facing source of truth for authoring workflow and current SDK. Both the
management Tool's `sdk` operation and the authenticated authoring projection
serve this exact file. The Agent owns discovery, input design, code, actual
`create/update`, authorized trial/repair and publication when a reusable Tool
is requested. Missing test conditions yield a saved draft and one business
question; they never justify invented data in a real system, fake results or
permission bypass. Business constraints override defaults. References remain
read-only unless explicitly selected for repair. Publication stays independent
of optional employee allocation.

Verification: 54 focused backend cases passed, including SDK/readiness serving
the same Markdown contract, plus two natural-task prompt tests, Ruff, targeted
Pyright, frontend TypeScript/ESLint and overlay build. Real server headless UI
acceptance confirmed one business textbox, no configuration selectors, exact MD
download content, real LAN HTTP clipboard copy containing the spec and task,
automatic ready-employee resolution, existing chat navigation, no auto-send or
automation mutations, and wide/narrow layout. Screenshots were inspected. The
main Runtime and isolated Windows/compile provider were not replaced. This
validates spec delivery and UI simplification; no new model/business run was
claimed for this change.
