# Employee studio first version

## Product scope

The studio at `/employee-studio` turns a job requirement into an editable job
specification. Users can start manually, choose one of three business templates,
or generate a configuration using an enabled tenant model. The dashboard links
to this page. Existing agent creation remains available.

The implemented path is requirement, saved draft, human review of test cases,
server readiness check, native agent creation, and the existing agent workspace.
Human review is not an executed test or a claim of business acceptance.

Employee kinds cover personal, team, application, enterprise and subsidiary jobs.
These are classifications, not new authorization modes. Studio-created agents
start private. Connection notes cover MCP, SDK/CLI and RPA requirements; recording
a note does not connect a system. Users may bind existing registered tenant or
global skills and tools. Credentials and runtime permissions remain owned by the
existing tool and authorization boundaries.

## Authoritative facts

`EmployeeBlueprint` owns the user and tenant, requirement, specification, revision
and one-time agent binding. Every read and mutation is scoped to both the active
tenant and creator. Lists are paginated; the capability picker is bounded to 200
skills and 200 enabled tools and never returns tool configuration or secrets.

Draft updates use a row lock and an expected revision. Job or test-content changes
invalidate previous review flags. The UI instructs users to save content changes
before reviewing cases. Published creation snapshots are read-only, including
after an agent is soft-deleted. They describe the creation configuration, not
subsequent changes made from the existing agent settings or workspace.

`POST /agents/` consumes `employee_blueprint_id` and
`employee_blueprint_revision`. This actual mutation path locks and rechecks the
draft, tests, tenant, enabled model and selected capability IDs. It compiles the
saved job into the existing personality and boundaries fields, copies selected
skills, and binds selected tools. Caller-supplied personality, name, access mode
and template cannot override the saved studio job. Agent creation and snapshot
binding commit in the same transaction. A repeated request returns 409 and does
not create a second agent. Background workspace setup can still fail separately;
the existing Agent status owns that outcome.

No additional execution state machine is introduced. LangGraph checkpoints,
task execution, A2A, approvals and tool receipts retain their existing ownership.

## Generation contract

Generation calls one active model in the user's tenant without tools. Input is
bounded to 6000 characters, output to 5000 tokens and 60000 UTF-8 bytes, and the
provider call to 90 seconds. The result must validate against the specification
schema. Model-supplied capability IDs and review flags are always cleared. No
fallback configuration is invented on model failure. An actionable 502 response
allows the user to retry or enter the job manually. Live provider integration
requires a configured model and credentials; unit coverage uses a stub provider.

## Schema and installation

`f066_employee_blueprints` follows the observed single head
`f065_feishu_group_target`. It creates only the blueprint table and owner index.
Upgrade is idempotent and downgrade removes the new table.

Fresh database validation exposed an upstream issue: `initial_schema` creates
current ORM columns, then F065 attempted to add the existing delivery-target
columns again. F065 now uses `ADD COLUMN IF NOT EXISTS` and symmetric guarded
removal without changing its revision graph. This permits fresh installation.

Apply migrations before running the updated API:

```sh
cd backend
uv run alembic upgrade head
uv run uvicorn app.main:app --host 127.0.0.1 --port 8008
```

In a second terminal:

```sh
cd frontend
BACKEND_PORT=8008 npm run dev -- --host 127.0.0.1 --port 3008
```

Configure PostgreSQL, Redis, secrets and model credentials for the intended
environment before enabling workers or business integrations. For a UI-only
preview, `PROCESS_ROLE=preview` skips workers, connectors and bootstrap seeding;
it does not execute business tasks.

## Verification

Focused backend tests include unit contracts and real PostgreSQL HTTP integration
tests through the Agent creation endpoint. Set `STUDIO_TEST_DATABASE_URL` to an
isolated migrated database to enable them. Each integration test rolls back its
fixture transaction; do not point this workflow at production.

```sh
cd backend
uv run pytest tests/test_employee_studio.py tests/test_task_api_runtime_intake.py tests/test_onboarding.py tests/test_runtime_model_settings_api.py -q
uv run pyright --pythonpath .venv/bin/python --pythonversion 3.12 app/api/employee_studio.py app/services/employee_studio.py app/schemas/employee_studio.py app/models/employee_blueprint.py
```

Run frontend checks with `npm run build`, `npm test`, and focused ESLint on
`src/pages/employee-studio`. Browser verification covers login, template loading,
database-backed save and human review followed by a successful readiness check.
The preview has no model credentials; real generation and business execution
remain unverified.

## Remaining customer requirements

This version does not implement automatic business test execution, Skill/Tool
recommendations, published-version rollback, the complete Case acceptance center,
new system-specific connectors, group/subsidiary data authorization, scoped memory
governance, or additional A2A task handoff contracts. Harness recovery and external
side-effect reliability still require the planned fault-injection exercises.
