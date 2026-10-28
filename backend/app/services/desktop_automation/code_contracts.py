"""Hosted Python source and its bounded, literal desktop execution plan."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .contracts import MAX_SCRIPT_BYTES, MAX_STEPS, Script, Step


class PythonScript(BaseModel):
    model_config = ConfigDict(extra="forbid")
    format: Literal["clawith.python.v1"]
    source: str = Field(max_length=96000)
    parameters: dict[str, str] = Field(default_factory=dict, max_length=40)
    secret_parameters: list[str] = Field(default_factory=list, max_length=40)

    @model_validator(mode="after")
    def contract(self) -> PythonScript:
        if len(json.dumps(self.model_dump(), ensure_ascii=False).encode()) > MAX_SCRIPT_BYTES:
            raise ValueError("Script exceeds 128 KiB")
        if not set(self.secret_parameters).issubset(self.parameters):
            raise ValueError("Secret parameters must be declared")
        if any(not re.fullmatch(r"[a-zA-Z][a-zA-Z0-9_]{0,39}", k) or len(v) > 120 for k, v in self.parameters.items()):
            raise ValueError("Invalid parameter declaration")
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


ManagedScript = Annotated[Script | PythonScript, Field(discriminator="format")]


def load_script(value: dict) -> ManagedScript:
    if value.get("format") == "clawith.python.v1":
        return PythonScript.model_validate(value)
    return Script.model_validate(value)


def kind(script: ManagedScript) -> str:
    return "python" if isinstance(script, PythonScript) else "rpa"


class CodePlan(BaseModel):
    model_config = ConfigDict(extra="forbid")
    steps: list[Step] = Field(min_length=1, max_length=MAX_STEPS)
    secret_bindings: dict[str, str] = Field(default_factory=dict, max_length=MAX_STEPS)
    source_lines: dict[str, int] = Field(default_factory=dict, max_length=MAX_STEPS)

    @model_validator(mode="after")
    def bounds(self) -> CodePlan:
        if len(json.dumps(self.model_dump(), ensure_ascii=False).encode()) > MAX_SCRIPT_BYTES:
            raise ValueError("Generated desktop plan exceeds 128 KiB")
        ids = {s.id for s in self.steps}
        if len(ids) != len(self.steps) or set(self.source_lines) - ids or set(self.secret_bindings) - ids:
            raise ValueError("Generated step references are invalid")
        if any(not isinstance(n, int) or not 1 <= n <= 131072 for n in self.source_lines.values()):
            raise ValueError("Invalid Python source line")
        if not any(s.action == "assert_text" for s in self.steps):
            raise ValueError("脚本必须包含 ui.assert_text 结果校验，不能仅执行操作后返回成功")
        if any(s.action != "type_text" for s in self.steps if s.id in self.secret_bindings):
            raise ValueError("Secret references may only be supplied to ui.type_text")
        return self

    def validate_source(self, source: PythonScript) -> None:
        if set(self.secret_bindings.values()) - set(source.secret_parameters):
            raise ValueError("Generated plan references an undeclared secret")

    def execution_steps(self, inputs: dict[str, str]) -> list[Step]:
        return [
            s.model_copy(update={"text": inputs[self.secret_bindings[s.id]]}) if s.id in self.secret_bindings else s
            for s in self.steps
        ]
