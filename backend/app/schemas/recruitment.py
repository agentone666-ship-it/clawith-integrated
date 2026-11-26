"""Human-readable recruitment contracts; runtime configuration stays server-owned."""

import hashlib
import json
import uuid
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, computed_field, model_validator

Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1000)]
Scope = Literal["personal", "team", "application", "enterprise", "subsidiary"]


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Capability(Contract):
    key: str = Field(min_length=1, max_length=80, pattern=r"^[\w-]+$")
    name: str = Field(min_length=1, max_length=100)
    description: str = Field(min_length=1, max_length=1000)
    selected: bool = True
    skill_ids: list[uuid.UUID] = Field(default_factory=list, max_length=12)
    tool_ids: list[uuid.UUID] = Field(default_factory=list, max_length=20)
    needs_setup: list[Text] = Field(default_factory=list, max_length=6)


class InterviewTask(Contract):
    title: str = Field(min_length=1, max_length=100)
    instruction: str = Field(min_length=1, max_length=6000)
    look_for: str = Field(min_length=1, max_length=1000)


class Resume(Contract):
    name: str = Field(min_length=2, max_length=100)
    role: str = Field(min_length=1, max_length=500)
    goal: str = Field(min_length=1, max_length=2000)
    audience: str = Field(min_length=1, max_length=500)
    scope: Scope
    boundaries: list[Text] = Field(min_length=1, max_length=10)
    output: str = Field(min_length=1, max_length=2000)
    work_arrangement: str = Field(min_length=1, max_length=1000)
    memory: str = Field(min_length=1, max_length=1000)
    notification: str = Field(min_length=1, max_length=1000)
    permissions: str = Field(min_length=1, max_length=1000)
    capabilities: list[Capability] = Field(min_length=1, max_length=12)
    interview_tasks: list[InterviewTask] = Field(min_length=1, max_length=5)

    @model_validator(mode="after")
    def unique_capabilities(self):
        if len({item.key for item in self.capabilities}) != len(self.capabilities):
            raise ValueError("Capability keys must be unique")
        return self

    def fingerprint(self) -> str:
        return hashlib.sha256(json.dumps(
            self.model_dump(mode="json"), ensure_ascii=False, sort_keys=True,
        ).encode()).hexdigest()


class HRReply(Contract):
    reply: str = Field(min_length=1, max_length=5000)
    resume: Resume | None


class Revision(Contract):
    revision: int = Field(ge=1)


class Talk(Revision):
    content: str = Field(min_length=1, max_length=6000)
    model_id: uuid.UUID | None = None


class SaveResume(Revision):
    resume: Resume


class StartInterview(Revision):
    request_id: uuid.UUID
    task: InterviewTask


class Review(Revision):
    decision: Literal["pass", "fail"]
    feedback: str = Field(default="", max_length=3000)


class ContinueInterview(Revision):
    request_id: uuid.UUID
    content: str = Field(min_length=1, max_length=6000)


class Resource(Contract):
    id: uuid.UUID
    name: str
    description: str


class Catalog(Contract):
    skills: list[Resource]
    tools: list[Resource]
    truncated: bool


class RecruitmentOut(Contract):
    model_config = ConfigDict(from_attributes=True, extra="forbid")
    id: uuid.UUID
    revision: int
    messages: list[dict]
    resume: dict | None
    candidate_id: uuid.UUID | None
    candidate_hash: str | None
    interviews: list[dict]
    hired_at: datetime | None
    created_at: datetime
    updated_at: datetime

    @computed_field
    @property
    def candidate_current(self) -> bool:
        return bool(self.candidate_id and self.resume and self.candidate_hash == Resume.model_validate(self.resume).fingerprint())

    @computed_field
    @property
    def can_hire(self) -> bool:
        return not self.hired_at and self.candidate_current and reviewed_candidate_ready(self.candidate_id, self.interviews)


def reviewed_candidate_ready(candidate_id: uuid.UUID | None, interviews: list[dict]) -> bool:
    # A later attempt of the same task supersedes its earlier interview decision.
    latest = {i["task"]["instruction"]: i for i in interviews if i["candidate_id"] == str(candidate_id)}
    return bool(latest) and all(i.get("decision") == "pass" for i in latest.values())
