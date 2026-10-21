# HR recruitment and interview ownership

## Product contract

The Talent Market starts HR recruitment, either from a role template or an open
conversation. The business user describes work, reviews an employee resume,
selects capabilities, observes real interview tasks and supplies a human review.
There is no technical test-case authoring prerequisite. Advanced manual creation
and external Agent connection remain available from the market footer; the old
standalone wizard is at `/agents/configure`.

Company settings are also a fixed main-sidebar destination for the same
administrators already authorized by the native settings route. The existing
workspace-menu shortcut remains available. Recruitment's missing-model notice
links directly to `/enterprise#llm`; ordinary users are asked to contact their
administrator instead of being sent into administrator settings.
The administrator notice explicitly names the persistent path, "Company
settings → Model pool", so the shortcut also teaches where to return later.
The native sidebar active state remains visible after navigating to settings.

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
The provider gets one request with a 90-second limit and a 6,500-token output
ceiling. Input context is capped at 240,000 UTF-8 bytes; provider text at 70,000
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

The five new Backend modules pass focused Pyright. Including the existing
`app/api/agents.py` also reports three unchanged baseline errors: its unread
counter helper accepts `list` while the caller supplies `Sequence`, and its
permission-list sorting lambda dereferences a potentially missing User twice.
These are outside the recruitment diff; no repository-wide type-check pass is
claimed.
