"""Versioned, bounded scripts; only native Cua actions, never evaluated code."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

MAX_STEPS = 120
MAX_SCRIPT_BYTES = 131072
PARAMETER = re.compile(r"\$\{([a-zA-Z][a-zA-Z0-9_]{0,39})\}")


class Target(BaseModel):
    model_config = ConfigDict(extra="forbid")
    app: str = Field(min_length=1, max_length=260)
    title: str = Field(min_length=1, max_length=240)


class Step(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(min_length=1, max_length=80)
    action: Literal[
        "click",
        "double_click",
        "right_click",
        "type_text",
        "press_key",
        "hotkey",
        "scroll",
        "assert_text",
        "launch_app",
    ]
    app: str = Field(default="", max_length=80)
    label: str = Field(default="", max_length=120)
    target: Target | None = None
    x: int | None = Field(default=None, ge=0, le=10000)
    y: int | None = Field(default=None, ge=0, le=10000)
    text: str = Field(default="", max_length=8000)
    key: str = Field(default="", max_length=30)
    modifiers: list[Literal["ctrl", "shift", "alt", "win"]] = Field(default_factory=list, max_length=4)
    direction: Literal["up", "down", "left", "right"] = "down"
    amount: int = Field(default=3, ge=1, le=20)
    timeout_seconds: int = Field(default=8, ge=1, le=20)

    @model_validator(mode="after")
    def action_contract(self) -> Step:
        if self.action in {"click", "double_click", "right_click"} and (self.x is None or self.y is None):
            raise ValueError("Clicks require coordinates")
        if self.action in {"type_text", "assert_text"} and not self.text:
            raise ValueError("Text is required")
        if self.action in {"press_key", "hotkey"} and not self.key:
            raise ValueError("A key is required")
        if self.action == "hotkey" and not self.modifiers:
            raise ValueError("A hotkey requires modifiers")
        if self.action == "launch_app" and not self.app:
            raise ValueError("Select a configured application")
        if self.action == "assert_text" and self.target is None:
            raise ValueError("Assertions require an exact application window")
        return self


class Script(BaseModel):
    model_config = ConfigDict(extra="forbid")
    format: Literal["clawith.cua.v1"] = "clawith.cua.v1"
    steps: list[Step] = Field(default_factory=list, max_length=MAX_STEPS)
    secret_parameters: list[str] = Field(default_factory=list, max_length=40)
    parameters: dict[str, str] = Field(default_factory=dict, max_length=40)

    @model_validator(mode="after")
    def complete_contract(self) -> Script:
        if len(json.dumps(self.model_dump(), ensure_ascii=False).encode()) > MAX_SCRIPT_BYTES:
            raise ValueError("Script exceeds 128 KiB")
        if len({s.id for s in self.steps}) != len(self.steps):
            raise ValueError("Step identifiers must be unique")
        if not set(self.secret_parameters).issubset(self.parameters):
            raise ValueError("Secret parameters must be declared")
        used = set()
        for s in self.steps:
            used.update(PARAMETER.findall(s.text))
            if s.target:
                used.update(PARAMETER.findall(s.target.title))
        if set(self.parameters) != used:
            raise ValueError("Declare exactly the parameters referenced by steps")
        if any(not re.fullmatch(r"[a-zA-Z][a-zA-Z0-9_]{0,39}", k) or len(v) > 120 for k, v in self.parameters.items()):
            raise ValueError("Invalid parameter name or description")
        return self

    def digest(self) -> str:
        return hashlib.sha256(json.dumps(self.model_dump(), sort_keys=True, ensure_ascii=False).encode()).hexdigest()

    def validate_inputs(self, inputs: dict[str, str]) -> dict[str, str]:
        if set(inputs) != set(self.parameters):
            raise ValueError("Inputs must match declared parameters")
        if any(not isinstance(v, str) or len(v) > 8000 for v in inputs.values()):
            raise ValueError("Each input must be a string of at most 8000 characters")
        if len(json.dumps(inputs, ensure_ascii=False).encode()) > 32768:
            raise ValueError("Inputs exceed 32 KiB")
        return inputs

    def input_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                **{k: {"type": "string", "description": v, "maxLength": 8000} for k, v in self.parameters.items()},
                "_operation_id": {
                    "type": "string",
                    "description": "Unique ID for a new operation. Reuse only for the same operation.",
                    "minLength": 8,
                    "maxLength": 80,
                },
            },
            "required": [*self.parameters, "_operation_id"],
            "additionalProperties": False,
        }


def render(value: str, inputs: dict[str, str]) -> str:
    missing = set(PARAMETER.findall(value)) - inputs.keys()
    if missing:
        raise ValueError("Missing parameter values: " + ", ".join(sorted(missing)))
    return PARAMETER.sub(lambda m: inputs[m.group(1)], value)
