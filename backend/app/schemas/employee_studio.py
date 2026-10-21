"""Bounded contracts for editable employee job specifications."""

import uuid
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

ShortText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]
EmployeeKind = Literal["personal", "team", "application", "enterprise", "subsidiary"]


class StudioContract(BaseModel):
    model_config = ConfigDict(extra="forbid")


class EmployeeTestCase(StudioContract):
    kind: Literal["normal", "exception", "boundary"]
    input: str = Field(default="", max_length=3000)
    expected: str = Field(default="", max_length=3000)
    reviewed: bool = False


class ConnectionRequirement(StudioContract):
    kind: Literal["mcp", "sdk_cli", "rpa"]
    description: str = Field(default="", max_length=500)


class EmployeeSpecification(StudioContract):
    name: str = Field(default="", max_length=100)
    employee_kind: EmployeeKind = "personal"
    audience: str = Field(default="", max_length=500)
    objective: str = Field(default="", max_length=3000)
    responsibilities: list[ShortText] = Field(default_factory=list, max_length=12)
    boundaries: list[ShortText] = Field(default_factory=list, max_length=12)
    output_format: str = Field(default="", max_length=3000)
    acceptance_criteria: list[ShortText] = Field(default_factory=list, max_length=12)
    connections: list[ConnectionRequirement] = Field(default_factory=list, max_length=6)
    skill_ids: list[uuid.UUID] = Field(default_factory=list, max_length=20)
    tool_ids: list[uuid.UUID] = Field(default_factory=list, max_length=20)
    test_cases: list[EmployeeTestCase] = Field(default_factory=list, max_length=9)


class BlueprintSave(StudioContract):
    requirement: str = Field(default="", max_length=6000)
    specification: EmployeeSpecification
    expected_revision: int = Field(default=0, ge=0)


class BlueprintOut(StudioContract):
    id: uuid.UUID
    requirement: str
    specification: EmployeeSpecification
    revision: int
    published_agent_id: uuid.UUID | None
    published_at: datetime | None
    updated_at: datetime
    model_config = ConfigDict(from_attributes=True, extra="forbid")


class GenerateSpecification(StudioContract):
    requirement: str = Field(min_length=5, max_length=6000)
    employee_kind: EmployeeKind
    model_id: uuid.UUID


class StudioIssue(StudioContract):
    field: str
    message: str


class StudioReadiness(StudioContract):
    ready: bool
    issues: list[StudioIssue]
    warnings: list[str]


class StudioCapability(StudioContract):
    id: uuid.UUID
    name: str
    description: str


class StudioCatalog(StudioContract):
    skills: list[StudioCapability]
    tools: list[StudioCapability]
