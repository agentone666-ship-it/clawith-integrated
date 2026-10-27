"""Feature-owned PostgreSQL schema; central Clawith remains auth/Tool authority."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, UniqueConstraint, Uuid
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def now() -> datetime:
    return datetime.now(UTC)


class AutomationBase(DeclarativeBase):
    pass


class Workflow(AutomationBase):
    __tablename__ = "workflows"
    __table_args__ = ({"schema": "desktop_automation"},)
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, index=True)
    owner_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    name: Mapped[str] = mapped_column(String(120))
    description: Mapped[str] = mapped_column(String(1000), default="")
    draft: Mapped[dict] = mapped_column(JSON, default=dict)
    revision: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Version(AutomationBase):
    __tablename__ = "versions"
    __table_args__ = (UniqueConstraint("workflow_id", "number"), {"schema": "desktop_automation"})
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, index=True)
    workflow_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("desktop_automation.workflows.id"), index=True)
    number: Mapped[int] = mapped_column(Integer)
    script: Mapped[dict] = mapped_column(JSON)
    digest: Mapped[str] = mapped_column(String(64))
    note: Mapped[str] = mapped_column(String(500), default="")
    tool_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Recording(AutomationBase):
    __tablename__ = "recordings"
    __table_args__ = ({"schema": "desktop_automation"},)
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, index=True)
    owner_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    workflow_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("desktop_automation.workflows.id"), index=True)
    status: Mapped[str] = mapped_column(String(24), default="active")
    paused: Mapped[bool] = mapped_column(default=False)
    base_revision: Mapped[int] = mapped_column(Integer)
    script: Mapped[dict] = mapped_column(JSON)
    last_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class RecordingAction(AutomationBase):
    __tablename__ = "recording_actions"
    __table_args__ = (UniqueConstraint("recording_id", "request_id"), {"schema": "desktop_automation"})
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    recording_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("desktop_automation.recordings.id"), index=True)
    request_id: Mapped[str] = mapped_column(String(80))
    fingerprint: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(24))
    result: Mapped[dict] = mapped_column(JSON, default=dict)


class Playback(AutomationBase):
    __tablename__ = "playbacks"
    __table_args__ = (UniqueConstraint("tenant_id", "request_id"), {"schema": "desktop_automation"})
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, index=True)
    owner_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    workflow_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("desktop_automation.workflows.id"), index=True)
    version_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("desktop_automation.versions.id"), nullable=True
    )
    agent_run_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    request_id: Mapped[str] = mapped_column(String(80))
    fingerprint: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(24), default="running")
    script: Mapped[dict] = mapped_column(JSON)
    input_summary: Mapped[dict] = mapped_column(JSON, default=dict)
    digest: Mapped[str] = mapped_column(String(64))
    progress: Mapped[int] = mapped_column(Integer, default=0)
    result: Mapped[dict] = mapped_column(JSON, default=dict)
    cancel_requested: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
