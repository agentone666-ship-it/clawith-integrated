# HR recruitment and interview ownership

## Product contract

The Talent Market starts HR recruitment, either from a role template or an open
conversation. The business user describes work, reviews an employee resume,
selects capabilities, observes real interview tasks and supplies a human review.
There is no technical test-case authoring prerequisite. Advanced manual creation
and external Agent connection remain available from the market footer; the old
standalone wizard is at `/agents/configure`.

Company settings retain their original workspace-menu entry; no extra sidebar
destination is added. Recruitment's administrator-only "Configure model" button
starts a click-through walkthrough: company-name button, the original Company
settings menu item, then the Model pool tab. Each highlight advances only after
the user operates the actual control; no automatic menu opening or route jump
substitutes for discovering the entry. The Layout owns the temporary walkthrough
flag across child-route changes. Closing, Escape, completion or navigation away
from recruitment/settings ends it; it can be started again. Keyboard listeners
clean up when the guide ends. The active step tracks its target's viewport
rectangle each animation frame, including ancestor transforms
from the workspace menu's opening animation; target size observations alone miss
these movements. Unchanged geometry does not update React state, and the frame
loop is cancelled when the step changes or the guide ends.
The final hint repeats the original path. Ordinary users are asked to contact
their administrator; native settings authorization remains unchanged.

`Recruitment` owns one tenant/creator-private dossier: HR messages, the current
resume, its optimistic revision, the current candidate identity and immutable
interview input/version references with editable human reviews. It does not own
Run execution state. APIs scope every read and mutation by tenant and owner.
Already-hired dossiers are read-only; native Agent settings own later changes.

## HR and capability compilation

`services/recruitment.py` owns the bounded, structured HR completion. HR sees the
conversation, current resume, interview feedback and up to 200 visible skills
and 200 enabled built-in/admin tools (catalog truncation is explicit). Output
IDs are revalidated against actual tenant-visible resources before persistence.
Pure instruction-based capabilities are distinguished from marketplace
bindings. Missing systems, knowledge or authorization are listed as preparation
requirements, never claimed to be connected.

HR generation is an application configuration completion, not an employee task
Run. Every applied completion records its exact messages, pinned model,
dossier revision and structured answer in `AuditLog` (`recruitment.hr_turn`).
The provider gets one request using the selected model's configured timeout
and output allowance (or its native defaults). HR bounds the complete completion
operation at 180 seconds; it must not interrupt a model at the former fixed
90-second deadline or replace its output allowance with 6,500 tokens. The prompt
asks for concise, non-repetitive resumes and uses provided interview samples;
market bindings require a clear need, and simple conversation-only jobs should
not acquire unrelated workflow Skills, file creation or Focus planning.
`complete_llm_once(stream_response=True)` receives and aggregates provider chunks
without forwarding partial JSON to the UI. This avoids waiting for an entire
long answer before any provider data arrives; model idle timeouts and the HR
total deadline still apply. There are no hidden retries or provider fallbacks.
Timeouts return an actionable 504, preserve the dossier revision and cancel the
completion; the same input/revision can be retried. Logs record dossier/model,
elapsed time, finish reason and bounded validation locations/types, never raw
provider responses or credentials. Input context is capped at 240,000 UTF-8 bytes; provider text at 70,000
bytes; resumes at 60,000 bytes. Failed/invalid/stale completions do not add a
conversation turn. A missing model is an actionable failure, with no simulated
candidate or execution result. The dossier supports at most 20 HR turns and
30 interview attempts; listings paginate. Interview results bound both row
counts and displayed content and explicitly report truncation.

The existing native `POST /agents/` owns creation, quotas, model checks,
workspace initialization and setup failure handling. When a recruitment
reference is supplied, the locked saved resume overrides client names,
instructions, skills, template, autonomy overrides and visibility. Only selected
capabilities are compiled. Tool assignments explicitly enable selected tools
and disable other currently visible tools; recruitment setup skips automatic
default skills. Native protocol capabilities remain governed by the Runtime.
Creation and candidate linkage commit together. The setup task still owns
readiness (`creating`/`idle`/`error`). Creation errors or negative reviews allow
reassembly from the same resume. Superseded candidates and their evidence remain
private and accessible; they have no recruitment-enabled heartbeat.

Agent manager start uses the existing Runtime rollout decision: a native Agent
with v2 chat enabled and no existing gateway container becomes idle after file
and Skill setup, without attempting to pull/start an OpenClaw gateway image.
Existing containers and other start paths retain their gateway lifecycle.
Deleted Agents cannot be started. Idle means available for intake, not proof
that the shared worker is healthy; only an actual Run establishes execution.

## Interviews and reviews

`services/recruitment_interviews.py` creates a real native direct session and
uses `enqueue_chat_runtime` to persist the user input and durable Run command.
It uses `source_type=chat`; no alternative execution engine or state machine is
introduced. Native quota checks apply, and accepted interview/HR inputs count
against ordinary users' conversation allowance. Each interview records a
client request UUID, candidate ID, resume fingerprint, task input, Run and
session IDs. Retrying a start UUID returns the original interview. A dossier
permits only one nonterminal interview at a time, including waits. Reassembly
and hiring reject active interviews; cancellation only submits a native cancel
command and does not claim immediate termination.

The result view reads execution status through `RunStateReader` (the exact
Run/Command/checkpoint), messages from its session, and tool results from its
Run ledger. It never infers success from a saved message or an elapsed timer.
Recruitment projects the native finalizer's serialized `summary` field into
human-readable delivery text; verification internals and reference envelopes
are not shown as raw JSON. Plain-text summaries remain supported; unknown
structured envelopes stay in the native workbench. Display limits apply after
projection and summary truncation is explicit. An identical final message is
shown only once. The UI names the verifying phase and scrolls a newly selected
interview into view. Unavailable candidates cannot start UI trials; failed HR
adjustment offers a retry against the already-saved review without discarding
an unsent composer draft.
Waiting-user input resumes the same Run with the native correlation identity;
other approvals and complete files remain accessible in the native workbench.

Human pass/fail is independent of execution completion: only a completed Run
can receive a pass. Failure requires written feedback. The frontend saves that
review before asking HR to revise the resume, so provider failure cannot lose
the user's review. Changed resumes require new candidates and new interviews.
For the current candidate, the latest attempt of each exact task input must
have a human pass before hiring; previous failed attempts remain visible.
Hiring validates the current fingerprint and absence of active Runs again.

## Present scope and operational limits

The first version creates private, manually invoked candidates and disables
proactive heartbeat. The five organization levels are recorded as job scope,
not new authorization grants. Work schedules, message/event triggers, shared
memory and external-system access remain explicit job agreements/pending setup;
the resume explains that their native settings/integrations still need to be
configured. Hiring does not broaden data access or silently enable schedules.
Reassembly creates a new native Agent, so native creation quotas still apply.

The recruitment UI reuses Clawith CSS variables, native button/input classes,
Tabler icons and Markdown rendering. Its scoped styles support light/dark
themes, reduced motion and stacked narrow-screen layouts.

## Verification

- `frontend`: `npm run build`; focused ESLint for new recruitment components
  and API client; existing `npm test`.
- `backend`: focused Ruff and Pyright; `tests/test_recruitment.py` covers
  generation failures, exact UTF-8 bounds, stale updates, tenant/owner denial at
  reads/mutations/native creation/interview submission, capability visibility,
  native creation, real chat command intake, idempotent retry, human-review
  gates, changed-resume invalidation and hiring. Provider output and completed
  execution are mocked where explicitly indicated in the test.
- Transactional PostgreSQL integration tests require
  `RECRUITMENT_TEST_DATABASE_URL`; all writes roll back, including native
  creation commits via externally-owned connection savepoints. They do not
  require credentials or call a live provider. Ordinary unit tests run without
  that opt-in database variable.
- Migration `f066_recruitment` follows `f065_feishu_group_target`; verify one
  Alembic head and exercise downgrade/upgrade on an isolated local database.
- Browser checks verify the market entry, editable resume, interview screen,
  native visual style and honest missing-model notice. A live configured model
  is required for actual HR conversations and completed employee work; automated
  checks do not establish business acceptance.
- Guide positioning fix: focused ESLint and `npx tsc --noEmit` pass. Browser
  rectangle measurements verify 5px highlight padding at all three targets,
  including after the workspace menu animation finishes; the original settings
  entry, model-pool completion and guide dismissal remain functional.
- HR reliability checks (2026-10-21): 70 focused tests pass across
  `test_llm_single_step.py`, `test_recruitment.py`,
  `test_agent_manager_native_start.py`, `test_agent_manager_soul.py` and
  `test_onboarding.py`, with the transactional PostgreSQL opt-in enabled.
  Subsequent focused recruitment/native-start checks also cover decoded summary
  truncation below, at and above 12,000 characters. Focused Ruff, frontend ESLint,
  frontend production build and TypeScript pass; focused HR-service Pyright passes.
- Live local MiniMax-M3.1-Flash evidence is separate from mocked tests: the
  customer-service recruitment reproduced a 90-second completion timeout and a
  122.6-second non-streaming ReadTimeout. After correction, streamed HR adjustment
  completed in 96 seconds. The initial interview was cancelled after unnecessary
  Focus/file work and received a failed human review; HR removed generic Skills,
  kept the four customer-service capabilities and assembled a fresh native
  candidate without a gateway image. Its combined return/logistics/fault-complaint
  trial completed with no tool calls and three replies of 75, 74 and 60 characters.
  The review passed, hiring completed, and the native workbench opened with the
  actual interview messages and an enabled composer. High local host/DB load still
  caused visible delays; these observations do not establish production latency.

The five new Backend modules pass focused Pyright. Including the existing
`app/api/agents.py` also reports three unchanged baseline errors: its unread
counter helper accepts `list` while the caller supplies `Sequence`, and its
permission-list sorting lambda dereferences a potentially missing User twice.
These are outside the recruitment diff; no repository-wide type-check pass is
claimed.

Additional static-check baselines observed in this fix: `agent_manager.py` has
two unchanged Docker SDK overload/restart-policy errors (also reproduced against
its HEAD source), and `llm/single_step.py` has the pre-existing `LLMClient.close`
declaration error. All concrete provider clients implement cleanup and the
one-call tests verify closure on completion, failure and streaming paths. No
repository-wide Pyright pass is claimed.
