"""Fresh and historical schema contracts for Feishu delivery targets."""

import importlib.util
from pathlib import Path
from unittest.mock import Mock

import pytest
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


def _load(monkeypatch, columns):
    path = Path(__file__).resolve().parents[1] / "alembic/versions/202608181600_schedule_trigger_feishu_group_target.py"
    spec = importlib.util.spec_from_file_location("feishu_target_migration", path)
    assert spec is not None and spec.loader is not None
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    inspector = Mock()
    inspector.get_columns.side_effect = lambda table: columns.get(table, [])
    monkeypatch.setattr(migration.sa, "inspect", lambda _bind: inspector)
    monkeypatch.setattr(migration.op, "get_bind", lambda: object())
    calls = []
    monkeypatch.setattr(migration.op, "add_column", lambda table, column: calls.append(("add", table, column.name)))
    monkeypatch.setattr(migration.op, "drop_column", lambda table, column: calls.append(("drop", table, column)))
    return migration, calls


def _column(kind=None, nullable=True):
    return {"name": "delivery_target_id", "type": kind if kind is not None else postgresql.UUID(), "nullable": nullable}


def test_fresh_metadata_columns_are_preserved(monkeypatch):
    migration, calls = _load(monkeypatch, {table: [_column()] for table in ("agent_schedules", "agent_triggers")})
    migration.upgrade()
    assert calls == []


def test_historical_tables_receive_missing_columns(monkeypatch):
    migration, calls = _load(monkeypatch, {})
    migration.upgrade()
    assert calls == [("add", "agent_schedules", "delivery_target_id"), ("add", "agent_triggers", "delivery_target_id")]


def test_partial_schema_only_receives_missing_column(monkeypatch):
    migration, calls = _load(monkeypatch, {"agent_schedules": [_column()]})
    migration.upgrade()
    assert calls == [("add", "agent_triggers", "delivery_target_id")]


@pytest.mark.parametrize("column", [_column(sa.String()), _column(nullable=False)])
def test_incompatible_column_is_rejected_before_any_ddl(monkeypatch, column):
    migration, calls = _load(monkeypatch, {"agent_triggers": [column]})
    with pytest.raises(RuntimeError, match="Expected nullable UUID agent_triggers"):
        migration.upgrade()
    assert calls == []


def test_downgrade_removes_present_columns_in_reverse_order(monkeypatch):
    migration, calls = _load(monkeypatch, {table: [_column()] for table in ("agent_schedules", "agent_triggers")})
    migration.downgrade()
    assert calls == [("drop", "agent_triggers", "delivery_target_id"), ("drop", "agent_schedules", "delivery_target_id")]


def test_downgrade_skips_absent_columns(monkeypatch):
    migration, calls = _load(monkeypatch, {})
    migration.downgrade()
    assert calls == []
