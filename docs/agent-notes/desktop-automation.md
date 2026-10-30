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


### Product UI and composer handoff correction (2026-10-28)

The extra business field and repeated banner are removed. The compact entry has
Start and Copy actions; Copy uses the exact server Markdown, with feedback. Start
passes specification/context via generic `composerHandoff` route state to the
existing chat composer, without a clipboard dependency or auto-send. The generic
chat hook appends to existing text, consumes once, clears route state and rejects
wrong-agent, older-than-five-minutes or over-24-KiB drafts. No server conversation
state, credential transfer or new runtime was added.

Desktop automation now uses the product accent/background/text/border tokens
and existing global button styles, including its source editor and allocation
dialog. Duplicate promotional chrome is removed. Component choices and official
source links are recorded in `docs/interaction-patterns.md`.

Verification for this correction: focused composer/prompt tests (3), frontend
TypeScript, automation and handoff-hook ESLint, and the production overlay build
passed. Live server headless acceptance verified no business field, exact spec
copy with feedback, real chat textarea population, one-time route-state
consumption, no automatic network/WebSocket submission, short labels, Escape
close, removal of the duplicate CTA, and light/dark/narrow rendering. Screenshots
were inspected. Only the frontend was updated; no Runtime or desktop execution
was started for this UI task.


### Markdown card, adaptive composer and playback review (2026-10-28)

The composer handoff now carries a read-only `AUTOMATION_AGENT.md` document using
the existing attachment card and send packaging. Editable text is only a short
business template with explicit unfilled fields. Placeholder text is not valid
business data. Remove the superseded combined prompt helper; the server Markdown
remains authoritative. The complete encoded handoff is limited to 24 KiB, its
document to 16 KiB. Programmatic changes resize the textarea like typed input,
up to min(320px, 40vh), after which content scrolls.

Playback, shared by Python and RPA, now captures completed-step desktop frames
using its existing provider session and lock. At most 32 screenshots/32 MiB and
120 metadata entries per run are retained, in addition to the existing final
evidence. No typed text is copied into trace metadata. Capture failures do not
retry actions or claim business success. Permission-checked frame reads and an
owner/tenant-scoped latest-Agent-run projection feed the shared viewer; observers
never invoke the provider or steal its lease. The studio shows active frames and
step replay, while chat polls the same receipts every two seconds. Frames are
step samples, not continuous video.

Real specification evaluation used the existing configured Qwen coding employee
in isolated Windows, without authored business source from Codex. Initial run
c0bc8501-ff9c-4827-a6e0-53cf69e60205 failed with no business record: the Windows
Start menu blocked foreground activation. The provider explicitly reported no
mouse input; classify that evidence as a known rejected dispatch rather than an
unknown write. The spec now limits repeated foreground failures and describes
observed Start-menu Escape recovery, while retaining the unknown-write ban.

Second run 9817f603-c5c9-415d-8c13-be6192efb912 completed after autonomous repair.
Workflow b80fbc93-a008-4200-9c23-bc3585c12c7a revision 4 published v1 Tool
c1f44354-4e92-477d-bdd3-474c2f32476a. Successful trial
83dc1c3f-a68d-478f-960e-26983242f68b executed 19 steps in 18.978s with 19 frames.
Independent stored-record grading verified exactly one purchase, supplier,
quantity 940, amount 109526.60, reference, date and reason. A separate real UI
RPA run ec0f0afd-9885-4f3d-b363-193405d5a548 passed all business checks using new
data, 18 steps/18 frames in 19.366s; the UI displayed live frames and navigated
back to step 1. This is one synthetic business family with a failed first
evaluation and a successful iteration, not a general benchmark success rate.

59 focused backend cases, two composer contract tests, Ruff, targeted Pyright,
frontend TypeScript/ESLint and the conservative production build passed. Real
headless UI verified the MD card, short template, textarea height growing from
28px to 204px, live Agent frames, RPA live/replay frames, and no page errors.
Windows and the main Runtime were not replaced; no Mac foreground was used.


### Mounted-composer sizing correction (2026-10-28)

A live reproduction found a four-line programmatic draft rendered in a 28px
textarea with 94px scroll height. The prior value effect could run before the
textarea mounted; manual-fill tests did not exercise that path. Auto-growth now
measures in a callback ref on DOM attachment, a layout effect for controlled
value changes, and a width ResizeObserver/window-resize callback. CSS owns the
viewport cap; the input and its block cannot flex-shrink. The input keeps a 50px
minimum and uses internal scrolling after min(320px,32vh).

The desktop preview is a separate shrinking sibling of the input area, bounded
to min(260px,28vh). It cannot consume the composer's reserved space. No desktop
provider calls or automatic chat sends are introduced by this correction.

Live development readback after deployment measured the initial handed-off draft
at 94px with 94px scroll height (previously 28/94), short content at 50px, nine
lines at 204px and a long draft capped at 288px with internal scrolling. Deleting
text shrank the field back to 50px. In a 780x650 viewport the wrapped template
fully fit at 116px; opening the desktop preview preserved input bounds and the
send button remained inside the viewport. Initial-mount, typing, deletion,
wrapping, scrolling and preview-layout checks passed with no page errors.
TypeScript, targeted hook ESLint and the conservative production build passed;
only frontend assets were replaced. Screenshots were visually inspected.


### Business-language kickoff copy (2026-10-28)

The editable kickoff now asks for one repeated daily task in ordinary business
language: system, usual operations and desired result, with a purchase-draft
example. Only one placeholder remains. Technical choices, test-environment
configuration and Tool publication terminology are removed from the user-facing
template; the read-only Agent specification retains those delivery obligations.

Scoped ESLint and the production TypeScript/build passed. A server headless
readback verified the actual composer text has one placeholder, everyday business
wording and no old script/test-environment/Tool-publication headings; the complete
new draft fits its auto-grown input. No chat message or desktop task was sent.


### Explicit fill-in kickoff (2026-10-28)

The business kickoff uses inline slots for system, recurring work and expected
result, plus one optional business-requirements slot. The example and descriptive
tutorial are removed. The user edits the slots directly; the read-only spec
continues to own implementation and verified delivery.

Scoped ESLint and the production build passed. Live headless readback confirmed
the system/work/result and optional business slots appear in the actual
composer, examples are absent and the complete draft fits its auto-grown area.


### Uncropped desktop viewer (2026-10-28)

User screenshots showed that the fixed-height footer clipped the desktop image.
The monitor now belongs to the normal scrollable chat history, with no internal
fixed-height clipping. The shared Python/RPA frame view scales the entire image
with contain fitting and opens a body portal for a viewport-filling viewer.
Fit/1:1 modes allow whole-desktop overview or native-pixel detail with scrolling;
step selection and follow-latest use the same image state as the inline view.
Escape closes, focus returns, and the business draft remains untouched.
No new provider calls, desktop sessions or automatic messages are introduced.

TypeScript, scoped viewer ESLint and production overlay build passed. Live
server acceptance found the inline monitor at client/scroll height 729/729
(no internal crop), opened a 1416x876 viewer in a 1440x900 viewport, verified
contain fitting and exact 1280x800 native-pixel mode, switched actual stored
step frames, and checked 1017x390 / 780x650 layouts. Escape preserved the
unsent business draft and left the input inside the viewport; no page errors.
Screenshots were inspected. No new desktop operation was executed.


### Current-session desktop activity (2026-10-28)

The chat monitor reads the latest AgentRun for the exact tenant, origin user,
Agent and selected session, then reads only that Run's Tool receipts and
Playback. It must not substitute a previous Run's screenshots when the current
Run has no trial. The read-only activity projection does not change Runtime
state or reserve a desktop; lane_held is only a scheduling fact, not success.
A Run without desktop execution explains that no new frames were produced.
Failed/unknown/cancelled trials without a frame show their actual outcome and
execution error rather than waiting indefinitely for a first frame.

Live log diagnosis found the latest user Run made zero Tool calls and no trial;
its answer repeated previous failures. The preceding Run exhausted its model
step budget after failed trials including unavailable windows, invalid click
coordinates and an unsupported DesktopPlan.sleep call. This monitor correction
does not establish that the user's business script is fixed or executed.

Verification: five focused trace/permission tests, TypeScript, scoped ESLint,
Ruff and the conservative production build passed. The standalone capability
and frontend were deployed; the main Runtime container ID stayed unchanged.
A headless browser under the affected user's identity read the actual current
session and confirmed zero Tools/no trial/no stale frame. A separately marked
observer-response fixture using the real previous compile failure confirmed
terminal errors display without infinite waiting. No chat message, trial or
computer input was dispatched; the business workflow remains unverified.


### Repair execution and application preparation (2026-10-29)

The management Tool now exposes launch(application_id) for applications listed
by sdk. It validates real active Runtime identity and assignment before the
operation, rejects arbitrary paths, and reuses observe's desktop-idle check,
lock, provider identity and finally-release lifecycle. This prepares an
application without constructing a business trial just to launch it. Launch
and observe screenshots are MCP image blocks, not base64 in the bounded JSON
text. The additive operation changes neither published workflow versions nor
the main Runtime or compiler.

The authoring specification requires current-run sdk/observe/get receipts for
repair requests; historical failures cannot substantiate current checks. Reuse
verified action paths, focus each field, keep modal confirmation and final
saved-state assertions, calculate with Decimal, and report exclusion reasons.
ui.window describes a target; ui.launch returns no window object; ui.sleep is
not in the SDK. This guidance improves authoring but does not enforce a model
completion guarantee.

Live checkpoint inspection confirmed the full Markdown reached the model. The
user's latest zero-Tool answer repeated history; revision 8 contained guessed
coordinates, unfocused inputs, no confirmation save and a not-saved assertion.
The existing Qwen3.5-Flash repaired that same user-owned workflow through the
existing Runtime with a supplied read-only verified RPA reference. Run
c5a404a9-18b8-4071-90e4-02590c9fafb6 used 14 Tool calls in 107.835s. Its
20-step trial saved exactly one PR-0088-027 purchase; independent persisted
record checks verified supplier, quantity960, amount110769.60, reference and
date. Revision9/v1 succeeded, but its reason omitted exclusions. The same Qwen model
then updated revision10 and published v2 after a separate PR-0089-027 fixture
test: 970 units, amount113018.30, exactly one saved record and both explicit
exclusion reasons verified independently. Run
e43406bf-4878-4a7b-902e-ff0d498438bc used 8 Tool calls in 72.22s; trial
1664e9fd-ebb8-49c6-aad4-5d49fced925a completed20 steps/20 frames. The original
PR-0088-027 dataset was restored and its record retained; no duplicate save of
that request was performed. Published v2 Tool is
ed321e51-f19d-43fd-906d-1792c5cd25be, with assignment left to the existing guide.
This is assisted repair of a synthetic case, not an unguided success rate.

Ruff, targeted Pyright and 25 focused registry/trace tests passed; five focused
authorization/launch/transport tests passed after adding failure-release
coverage. A headless browser using the affected caller's identity read the
actual workflow and successful v2 trial, displayed its 20 stored frames, opened
the large viewer, switched to step1 and verified the 1017x390 viewport with no
page errors. The capability was replaced while idle; main Runtime and model
were unchanged. No Mac screen control was used.


### Long-message composer space (2026-10-29)

The deployed auto-growth hook was still active: initial handoff measured72px,
pasted business content hit the old288px cap, and a390px viewport reduced the
cap to125px. This reproduced inadequate editing space, not a missing auto-growth
handler. The current inline cap is min(560px,60dvh,actual available chat-panel
space). Available space subtracts attachment/toolbar chrome and reserves up to
96px of message history. Mount, content, container size, visual viewport and
font loading remeasure; observers and listeners are released on unmount.

ComposerInput owns the inline input and optional viewport editor of one
controlled draft. The viewport editor uses Enter for newlines, Escape/Done to
return, retains the text/selection and Markdown card, restores input focus and
never calls send. It does not create a second persistent draft or change chat
intake. The production overlay must copy the hook, component, stylesheet and
AgentDetail wiring together. This change applies to Agent chat authoring.

Verification: TypeScript, scoped ESLint and the production overlay build passed.
Live headless acceptance under the affected user's identity measured the
100-character handoff at72px without scrolling and an810-character pasted task
at314px fully visible (previously clipped at288px). A60-line draft grew to540px
and then scrolled internally. In1017x390 and780x650 viewports the textarea was
173px and390px, with input and Send inside the viewport. The large editor used
a993x366 dialog with a959x256.5 text area on the short viewport. Enter inserted a
newline; Escape/Done preserved content, focus and the Markdown card. Session
switching retained the controlled draft and auto-growth. No messages were sent
and no page errors occurred; screenshots were visually inspected.


### Fresh authoring session after model truncation (2026-10-29)

Run31e06edd-5afd-49b7-89d7-daf5139bccd1 used MiniMax-M3 with a16384-token
output cap and failed after two length responses before any Tool execution.
Read-only reconstruction of its prepared input found84 messages/107463 chars.
A provider-only comparison retained the same model, Tool schema and output cap:
fresh system/current-user inputs (2 messages/10820 chars) emitted valid sdk/list
Tool calls in1.79s with61 output tokens. The historical request with thinking
disabled emitted valid sdk/get/observe calls in2.94s/130 output tokens. These
probes executed no Tools; they implicate history/thinking interaction, not an
inability to call Tools or a demonstrated need for a larger cap. No production
reasoning policy, output cap, retry count or Runtime core was changed.

Previously Start authoring navigated into whichever old chat loaded first,
reusing failed test history and repeated business requests. It now creates an
empty current-user native session via the existing authenticated API before
navigation, includes its ID in the route, and stages the same Markdown card and
business draft without auto-send. The chat owner selects the requested ID from its authorized session list.
The native list intentionally omits empty conversations, so a newly returned
POST receipt is carried as navigation metadata; before using it the client
validates recipient fields and asks the native runtime-state endpoint to
re-authorize that exact tenant/user/Agent/session. The receipt alone cannot
authorize access. Invalid/missing IDs show an error rather than selecting a
different conversation. Manual selection keeps an explicit
session route aligned. Request failure leaves the guide open; closing during
creation does not navigate afterward (a completed API creation may leave an
empty session). Native session APIs remain the permission/persistence owner.

The affected script employee still had Qwen as its default, despite the user's
per-chat override to MiniMax-M3. Its primary model was aligned through the
normal Agent API with the model selected in the failed Run. Other employees
and the company model pool were left unchanged. Old chats/checkpoints were
preserved. This prevents this new-session entry from returning to the known
Arrearage configuration; it does not promise zero model failures.

Verification: TypeScript, scoped guide/resolver ESLint and the conservative
production build passed. Live headless acceptance verified creation failure
stays in the guide, successful startup opens the exact new session with its
Markdown card and auto-grown draft, and no message is sent until Send. A forged
empty-session navigation receipt was rejected by the native owner endpoint and
did not fall back to historical chat. From that real composer, MiniMax-M3 Run
5ea2f689-fbb6-4541-8a25-0f3ebe340523 completed9 read-only sdk/get/version/run_status
Tool calls; exact RunStateReader reported completed/error_code=null. Some
queries encountered a missing-version parameter or read failed historical
trials; the model corrected the parameter and finished. No new Playback or
business write was produced. This verifies the model/Tool/entry path, not a
new successful purchase trial. The original business draft had since become
revision13 and still has separate business-state trial failures. Screenshots
were inspected; main Runtime/provider policy was not replaced.


### Execution-time cloud desktop view (2026-10-29)

Playback now owns a latest-frame sampler for the duration of execution, using
its existing provider identity and lock. The first frame is stored before the
running reservation commits; the sampler refreshes around0.8s between provider
actions and assertion polls. Slow provider calls can delay captures; timestamps
are displayed instead of implying continuous video. Only one bounded8MiB PNG
is retained (atomic replacement); the existing bounded step/final evidence
remains for historical replay. The sampler is cancelled and joined before
final evidence and lease release on success, failure and cancellation.

The authenticated live-frame endpoint checks existing tenant/workflow authority
and reads a file descriptor/mtime pair, never calls the driver or takes a
desktop session. Agent and manual trial viewers share the same default running
view: poll the current frame approximately once per second, keep the viewport
viewer updating, and expose the capture time. Selecting a historical step
pauses follow mode; returning to live resumes it. Terminal runs use stored
playback. The Agent activity observer refreshes every1s and remains scoped to
the current exact session/Run. A read-only model task without desktop execution
still produces no live desktop stream.

Verification:26 focused executor/trace tests, scoped Pyright, ESLint and the
production TypeScript/build passed. The blocked-executor regression reads the
first frame while the task remains unfinished, rejects a different owner and
confirms no sampler/file updates after completion/release. Live acceptance used
the existing MiniMax Agent/Runtime on isolated Windows: Run
41311252-3138-4613-b160-bda15eb65b14 completed2 management Tool calls in42.507s.
The prepared diagnostic workflow checks the application header and cycles focus
without entering or saving business data. A real browser in that exact chat
observed4 changing images while the Playback API still reported running, with
continued updates in the large viewer, a1017x390 check and automatic transition
to stored replay afterward. No page errors. The independent capability and
frontend were updated while idle; the main Runtime container was unchanged.
This proves execution-time visibility, not a business-task success rate.


### Intermediate-state precheck false positive (2026-10-29)

The executor previously prechecked every assertion immediately following any
input and rejected the input if that text already existed. This incorrectly
blocked repeatable intermediate lookups/window preparation, e.g. data-loaded
and preview states. Scope that operation-transition guard to the verification
suffix at the end of a plan: only when all remaining steps are assertions.
Intermediate UI checks still execute and can poll for actual presence. This
retains the preceding final-commit input's precheck and exact request-ID
idempotency; it is not a business-record deduplication engine and does not
guarantee idempotency for arbitrary multi-write scripts. Business systems must
retain their own record uniqueness checks. Script formats/digests and compiler
identity remain unchanged, so fixed published versions are not invalidated.

Unknown intermediate inputs no longer reconcile using a pre-existing UI state.
Only a terminal postcondition proven absent before dispatch can reconcile an
unknown input; otherwise stop unknown without resending input. The final
verification's unreadable precondition still fails closed.

The authoring spec forbids PROBE sentinel assertions as a debugging stop. Use
observe for UI text/screenshots, or a clearly named diagnostic draft that first
checks the window/header, performs read/query actions, ends normally and is
followed by observe. A diagnostic trial is not a successful business delivery
and must not replace/publish the main business draft. Historical failed rows
are preserved rather than reclassified as success.

Regression coverage: already-present intermediate state permits progress;
already-present final saved state prevents commit input; unknown intermediate
dispatch cannot use an old state as reconciliation. Fifty focused executor,
trace and registry tests passed, plus Ruff and targeted Pyright.

PROBE sentinel assertions are also rejected at the trial boundary before
physical desktop claim: RPA returns actionable422, and compiled Python records
invalid_probe_assertion with its source line and desktop_started=false. This
only rejects the reserved debug sentinel prefix, not arbitrary legitimate UI
text. It does not revalidate/erase historical receipts or change serialization
and digests. Fifty-two focused tests and targeted static checks passed.

An attempted autonomous MiniMax repair (Run9f384477-b032-4657-b7eb-051997c9c8bd)
did not converge on the requested business draft and was explicitly cancelled
after17 Tool calls; cancellation was independently observed applied with the
lane released. No successful business trial was produced by that attempt.
The subsequent controlled repair uses the existing validated v2 action path
through the normal authenticated workflow API, with independent business
record validation on a separate synthetic dataset. Do not attribute that
controlled repair to autonomous model success.

Controlled acceptance completed on the isolated Windows desktop. An initial
trial stopped unknown at reason entry because old Confirm Purchase / duplicate
save dialogs blocked the parent window. No new record was saved for that
dataset; the remainder was not resent. After reading and closing those exact
dialogs, a fresh independent dataset succeeded through all22 steps: Playback
252a7d5a-2b4a-4a98-aff7-d831f84423fb, request PR-0093-027. Independent persisted
record checks confirmed exactly1 purchase, supplier华东液压, quantity1010,
amount115391.30, date2026-11-10, drawing reference and both exclusion reasons.
The business workflow3b71d39e-6dfb-4fbe-ab8a-3bec4b2da502 revision4 was published
as v1 (42102e6b-cb4b-4372-8f90-6c60aa0ef657); a fresh API read confirmed its
source matches the validated draft. The diagnostic60782028-8135-4b88-93d9-d0c711f3dc79
was separately repaired to a normally terminating read/query workflow and
passed Playback a138c8e7-cf1a-4086-bb84-6de3e19b7d8a without adding records.
Original fixture bytes were restored, saved test evidence retained. Only the
capability container was replaced; main Runtime was unchanged. This proves
this controlled task, not autonomous model repair reliability or recovery from
arbitrary leftover modals. Historical failures remain unchanged.

### Direct Computer Use live preview (2026-10-29)

The selected desktop execution provider remains pinned MIT-licensed Cua Driver
0.37.0. UI-TARS SDK/Qwen Windows research in the separate thread completed168
real GUI trials; the primary confirmation SDK score was15/36, precise feedback
12/36, JSON+feedback13/36. These are task-success scores and cannot be compared
with the earlier Cua28/28 and UI-TARS21/28 input-primitive checks. No evidence
establishes a universal autonomous winner. Cua fits the current product contract:
atomic Tools, existing Clawith model/Runtime, one shared isolated Windows desktop.

`computer.py` owns the authenticated proxy for the existing Windows Computer
Tool and its Run-bound screenshot sampler. Validate a live genuine Run, tenant,
Agent, enabled Tool assignment and active origin user before provider access.
Runtime supplies identity; arguments cannot supply sessions. Preserve native
request-ID write receipts and never replay uncertain writes. The native bridge
remains the physical lease owner. The sampler shares its Runtime/provider
identity, serializes captures with existing capability work, and stops/joins
before release on explicit release, lane termination or capability shutdown.
Capture errors are logged without changing action receipts. Latest captures
are private bounded8MiB atomic PNG replacements under computer/<Run>/live.png.

The chat monitor selects only the current session's latest authorized Run.
Direct Computer Use reads a private HTTP frame endpoint checked against the
Run tenant and origin user. The observer never acquires a desktop session.
Refresh approximately every1s, show capture time, retain last frame after
completion, and reuse the fit/1:1 viewport viewer. This is sampled live preview,
not a video stream or a task-success assertion. Place the literal computer MCP
route before the published-version UUID wildcard; assembled-app regression
must exercise that order.

Current UI demonstration recorded genuine Code22-step and RPA18-step purchase
runs, independently verified exactly one correct persisted record each (separate
synthetic datasets191/192). The narrated72.56s video shows editing/parameters,
actual running desktop updates and completion; it is not an autonomous coding
or fresh RPA recording success claim. Prior recorded-source history is reused.
The natural preset voice is Qwen3-TTS Serena, disclosed as synthetic.

Direct-tool live acceptance used the existing MiniMax-M3 model through the real
Native Runtime: Run61dc8dd0-b8e5-45d5-8133-45cbee64f9bc completed15 Tool calls
in83.804s, with14 succeeded and1 rejected help(release) schema lookup corrected
by the model. The headless actual chat observed64 fresh frame sequences while
the Run still held its lane, including the expanded viewer;1017x390 fit and
Escape checks passed without page errors. The model navigated purchase/history
pages, queried records and read the same PR-0192-027 fields as the independently
verified RPA result, without saving another record. Explicit release succeeded;
lane_held=false, no unknown/started receipts, and file mtime remained unchanged
after sampler termination. Do not equate64 refreshed captures with64 distinct
visual states or a full-motion video. The dedicated demo Agent uses the shared
Tool; it is not a required or exclusive binding. Existing business Agent's
newly added raw Tool binding was withdrawn because it also reserved the desktop
for a pre-existing user task; that task was preserved. Failed transport and
onboarding acceptance attempts remain excluded from the successful proof.

Verification:60 focused automation tests passed, then8 direct-tool tests passed
after origin-user validation was added. Ruff, targeted Pyright, ESLint and both
source/conservative deployment frontend production builds passed. The main
Runtime container was unchanged; only the capability and frontend assets changed.

### Human publication confirmation and same-page handoff (2026-10-29)

Agent authoring ends with a saved, successfully tested draft. The management
Tool's publish operation validates readiness and returns
awaiting_user_confirmation; it never creates a Version or Tool. This boundary
is enforced by the registry operation, not just authoring prompt wording.
The chat's latest successful trial offers Confirm publication, scoped to that
trial's digest. The authenticated user publication endpoint checks both the
revision and expected digest under the workflow lock and reuses an existing
same-digest version for repeated confirmations. Manual version management
retains explicit human publication. No additional publication state machine or
persisted pending flag is introduced: eligibility is derived from existing
exact-source successful trials and immutable versions.

Clicking confirmation publishes and navigates with the SPA router to the same
workflow's versions tab. View workflow/diagnostics routes to its runs tab in
that same page. Employee allocation links also stay in the SPA. Preserve the
chat session in browser history; do not open a new browser tab/window for
these internal actions. The authoring spec and model-visible readiness receipt
must say saved/tested/pending confirmation, never published before user action.

The revised tutorial must show the actual user entry, Markdown attachment,
business request, model-authored source submission, live execution, user
confirmation and same-page version view. Exclude development logs, prompt
tuning and failed recording attempts from the usage tutorial. Preserve those
attempts separately as evidence; do not represent manual source insertion or
a prebuilt workflow as fresh model-authored delivery.

Acceptance for this interaction used a fresh real MiniMax-M3 authoring Run
20f215cd-f00e-41c5-a8af-61f868b184ab. The Agent created the Python workflow
761848fd-a000-4b9e-bcc2-6a09be6bcec6, verified budget rejection before desktop
input, and passed a22-step real purchase trial with independent field/unique
record readback (PR-0203-027,2110 units,245702.90). Before the recorded user
click there were no published versions. Confirm publication created v1
583ca636-9e25-4969-a472-a92a88c4f3c9 and navigated to ?tab=versions with exactly
one browser page. Fresh API readback and hashes verified the submitted, stored
and published source match. A separate read-only actual-browser check clicked
View workflow/diagnostics into ?tab=runs and returned to the originating chat
with browser Back, still exactly one page and no page errors. The teaching
video crops irrelevant technical context and omits failed recording attempts;
its source footage and audits remain separately retained.

Verification:53 focused publication/registry/executor/trace tests passed;23
publication/registry tests passed after the final typed helper/description
update. Ruff, scoped Pyright, ESLint and production builds passed. The capability
and conservative frontend assets were deployed; the primary Runtime was not
restarted. Previous already-published versions remain unchanged.

### Persistent account/Agent Windows sandboxes (2026-10-30)

The user's accepted contract replaces the shared desktop for managed execution:
account owns data; each `(tenant, origin user, Agent)` owns an independent,
persistent Windows VM. Personal login state, installed software, application
state and files survive compute reclamation. The clean image is used only at
first creation. A used/personalized VM never becomes another account's pool
member. Multiple Agents of one account run separate guest processes/disks and
browser profiles. Sharing a published Tool or workflow shares source, not a VM
or its creator's login state. No writable browser profile is concurrently mounted.

The host service `sandbox_host` is the sole lifecycle/lease authority. It owns
private SQLite identity records, independent qcow2 overlays, NVRAM/vTPM state,
libvirt domains and operation leases. Only this service has hypervisor access;
the capability/Runtime have neither a hypervisor socket nor Windows credentials.
The capability resolves actual Run origin/tenant/Agent after existing authority
checks; model arguments cannot select an owner or VM. Manual-only recording and
trials use an account-private studio desktop; Agent-created workflows remember
their originating Agent for later manual trials. Published invocation always
uses the invoking Run's account and Agent, never the publisher's environment.

`AUTOMATION_SANDBOX_URL` plus a private token file explicitly selects the managed
provider. No managed action silently falls back to the former shared desktop.
The unconfigured legacy route remains solely for existing single-desktop installs
and regression compatibility; remove it when those installs migrate. Private
inventory/actions are transported through existing Clawith authentication under
`/automations/desktops`; even tenant administrators see only their own desktops
there. Guest tokens/passwords and provider addresses never appear in inventory.

The host admits at most two computed desktops initially, configured as two vCPUs
and 4 GiB guest memory each, with storage reserve and account instance limits.
Capacity reservations include failed VMs whose compute release is unconfirmed.
The desktop can only have one operation lease; sessions belonging to the same
Run share a lease and release it only after their last consumer. Heartbeats
follow genuine active Runs, running playbacks or active recordings, not keyboard
input. Ninety seconds without heartbeat fences the old nonce; later commands
cannot resurrect it. In-flight dispatch and startup are protected from sweeping.
Backend heartbeat loss does not replay business input or claim business success.

After ten minutes without an active lease, libvirt managed-save stops the domain
and releases memory/CPU while retaining its disk and state. Plain suspend/pause
is not compute release. A save failure remains error/compute-held, not saved.
Manual save is denied while occupied. Restoring reuses only that account/Agent's
own matched memory/device/disk state. Never restore a saved RAM state against
modified disks, and never clone a personalized RAM state to another identity.
New templates must be versioned and immutable; do not overwrite a backing image
already referenced by existing overlays. Backups and retained user-data deletion
are separate administrative policies, not task completion side effects.

Cold startup runs as a host-owned job. A Tool waits up to8 seconds before an
actionable preparing response with no input dispatched; the startup continues
without a blind business retry. Readiness requires an authenticated real guest
screenshot, not a running container. Restore compatibility pins virtual hardware;
upgrades need save/restore and GUI tests before image rollout. Libvirt isolated
guest ports plus host firewall rules block guest-to-guest and host-management
access while allowing DNS/DHCP and business-network egress.

The management entry uses existing product styles and same-page navigation.
It exposes state, configured resources, occupied status, start/restore and save.
Creation is automatic at authorized first use; users do not configure VM images,
ports, CPU or routing. Existing direct and playback live previews remain private
Run-owned evidence and never acquire another desktop just to observe it.

Cold-start preparing is a no-input acknowledgement, not a failed business
execution. Computer/registry MCP normalize it without claiming task completion.
Manual recording/tests retry only HTTP425 with the identical operation request
ID within600s; connection failures and uncertain inputs are never auto-replayed.

Cutover preserves explicitly configured, already-active legacy Run IDs on the
old desktop and application paths. This is an operator-generated immutable Run
allowlist, not model input or a general fallback. All new Runs use managed
desktops. Remove the allowlist after those Runs end; keep the old VM until its
remaining owners are reconciled. Updating the capability requires no active
recordings/playbacks or in-flight desktop Tool receipts. Main Runtime stays up.

The cloud-desktop recording shortcut creates a workflow associated with that
selected Agent in one transaction, then opens its recording tab in the same
SPA. It does not assign or alter any employee Tool binding.

Template preparation must run Sysprep in an elevated administrator session,
never as Local System (QGA itself runs as System). Microsoft documents missing
XAML registrations after System-context Sysprep on modern Windows. The sealed
development template records its actual non-System principal and image state.
Disable only the first-logon animation; retain app-readiness/update services.
The one-time instance password change occurs before personal use and includes
a new interactive logon, so subsequent personal credentials are created under
the permanent instance identity. Restores never reset that password.
See https://learn.microsoft.com/en-us/troubleshoot/windows-client/setup-upgrade-and-drivers/sysprep-as-system-windows-11.

The current provider also owns the pinned `windows_bridge.py.in` guest asset.
Only this trusted asset is uploaded (bounded command chunks below Windows'
32 KiB command-line limit); hosted business code never enters this bootstrap.
Read-only native calls idempotently start/renew the same authorized Cua label
after native idle expiry. Released manual labels remain closed. Inputs are
never automatically restarted or replayed after native session failure.
Readiness captures use the ordinary45s screenshot budget and one stable probe
label, avoiding false timeouts that strand successive temporary labels.

Per-instance automatic logon updates the Windows LSA `DefaultPassword` secret
and removes the plaintext registry password, so a stale template LSA secret
cannot override the instance identity. The initial user-scoped XAML registration
is applied by a bounded restart; killing SiHost can log off the desktop. The
hidden controller uses separate native stdout/stderr file redirection so normal
Uvicorn stderr logging cannot terminate a PowerShell wrapper.

The network's permanent DHCP reservation is the IP/MAC authority. Allocation is
host-file locked, excludes live dynamic leases, and refuses pool exhaustion.
Per-port clean-traffic filtering enforces the reserved IP/MAC and ARP identity;
bridge isolation alone does not prevent poisoning the host neighbor table.
The capability forwards only active Run IDs for the same account/Agent in
managed mode; the explicit legacy route retains its former shared scope.

Save returns saved only when a managed image exists; absent/shut-down desktops
return stopped. Unconfirmed/invalid provider outcomes retain compute capacity
and an error state. Zstd snapshot storage is configured only on an owned libvirt
host, with all its registered domains stopped during the initial driver change.
Foreign domains prevent this global configuration change. Existing raw save
images remain readable. The setup script preserves existing private host config.

### Development deployment acceptance, 2026-10-30

The running development capability now uses the private libvirt provider, with
an additive `desktop_automation` migration through003. The main Runtime
container identity stayed unchanged. The pre-cutover Run remains explicitly
pinned to the old desktop; its VM was retained. New Runs have no shared fallback.

Two existing accounts and two Agents produced four distinct persistent VMs.
Live API checks confirmed disjoint account inventories and404 for cross-account
start, save and recording shortcuts, including the second account's org-admin
role. The real guest could not connect to another running guest's8090 port or
the host's SSH/lifecycle ports. Host-to-guest authenticated desktop capture
remained available. This is bounded acceptance, not an isolation penetration test.

A genuine chat Run using the development Agent's existing MiniMax model appended
a unique line through the Computer Tool and saved Notepad. An independent guest
file read verified both the existing text and the appended line on disk. A second
real Run exposed a cached desktop image while its lane was still held. The
actual screenshot was visually checked; it contained the correct private
Notepad window. The model's description of a blank desktop was inaccurate;
this acceptance does not establish the model's screenshot interpretation quality.
Read-only RPA and Python fixture trials both passed on the same Agent desktop,
with live frames observed while running and private results denied to the other
account. Those fixture scripts are infrastructure-authored, not model-authored
business-script evaluations.

Three current Zstd save/restore pairs measured27.6–33.5s to confirmed QEMU exit
and18.8–24.7s through authenticated desktop capture. The same guest PID/window
and unsaved Notepad buffer survived each cycle. A separate earlier raw-format
set also completed three pairs. These shared-host samples overlapped another
VM's initialization and are not a controlled compression performance comparison.
A fresh clone with the final bootstrap initialized automatically in497.19s with
no manual guest repair. A prior incomplete clone recovered automatically in
299.22s; that recovery is not a fresh-provisioning latency sample.

CurrentUser-DPAPI protected synthetic login data and a mock Credential Manager
entry survived restoration. No real business-system SSO renewal was tested.
Idle600s reclamation was observed physically stopping QEMU while retaining disk
and saved memory. Busy save was rejected. All four acceptance desktops were
returned to saved state after testing, retaining data. Initial capacity is two
simultaneous2-vCPU/4-GiB desktops. The development image uses Windows Enterprise
LTSC Evaluation; production Windows licensing and backup retention remain
operator deployment work. The management page was checked at1440px and1024px;
the existing product-wide narrow/mobile sidebar layout remains outside this
capability's acceptance.

Focused backend verification:88 tests passed across desktop/registry/publication,
bridge, scope/privacy and installer-admission suites. TypeScript/build and
scoped Python static checks passed. Installer tests cover owned stopped domains,
foreign/active rejection, idempotence and restoring configuration after a failed
driver restart. Recorded deployment receipts and private screenshots live in
the task-specific server handoff directory, not the Runtime or user memory.
