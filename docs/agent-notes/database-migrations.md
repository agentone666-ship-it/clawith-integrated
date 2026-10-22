# Database migration bootstrap

Alembic owns the application schema. `initial_schema` creates the current ORM
metadata for an empty database; later historical migrations must therefore
accept their already-present target schema. A successful health endpoint alone
does not establish that migrations or the runtime are ready.

`f065_feishu_group_target` adds nullable UUID `delivery_target_id` columns to
`agent_schedules` and `agent_triggers`. It adds missing columns, preserves matching
existing columns, and rejects incompatible types or nullability before any DDL.
Its revision and parent remain unchanged. Databases that already applied this
revision require no new migration. Downgrade removes only columns that exist.

Verify the positive, partial and incompatible schema cases with
`tests/test_feishu_group_target_migration.py`. Deployment verification must also
run the complete migration chain on an empty PostgreSQL database and exercise
the `f065` downgrade/upgrade path. Never stamp a failed migration as successful
or allow startup to continue past a migration failure.
