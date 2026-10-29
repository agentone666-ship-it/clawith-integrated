"""Inline MCP parameters: current customer-size models need explicit object types."""

from copy import deepcopy

from .contracts import Step


def registry_schema() -> dict:
    step = Step.model_json_schema()
    definitions = step.pop("$defs", {})

    def inline(value):
        if isinstance(value, list):
            return [inline(v) for v in value]
        if not isinstance(value, dict):
            return value
        if "$ref" in value:
            return inline(deepcopy(definitions[value["$ref"].split("/")[-1]]))
        result = {k: inline(v) for k, v in value.items() if k not in {"title", "default"}}
        if "anyOf" in result:
            alternatives = [v for v in result.pop("anyOf") if v.get("type") != "null"]
            if len(alternatives) == 1:
                result.update(alternatives[0])
            else:
                result["anyOf"] = alternatives
        return result

    properties = {
        "operation": {
            "type": "string",
            "enum": [
                "sdk",
                "list",
                "get",
                "version",
                "observe",
                "launch",
                "create",
                "update",
                "test",
                "run_status",
                "publish",
                "bind",
                "execute",
            ],
        },
        **{
            k: {"type": "string", "description": "Required only for operations referencing this identifier"}
            for k in ("workflow_id", "version_id", "run_id", "agent_id")
        },
        "application_id": {
            "type": "string",
            "maxLength": 80,
            "description": "For launch only: exact server application ID returned by sdk; never a path",
        },
        "name": {"type": "string", "maxLength": 120},
        "description": {"type": "string", "maxLength": 1000},
        "revision": {
            "type": "integer",
            "minimum": 0,
            "description": "Current revision from get; required for update/publish",
        },
        "note": {"type": "string", "maxLength": 500},
        "request_id": {"type": "string", "minLength": 8, "maxLength": 80},
        "inputs": {
            "type": "object",
            "additionalProperties": {"type": "string"},
            "description": "Native JSON object of input name to string value; do not JSON.stringify",
        },
        "offset": {"type": "integer", "minimum": 0},
        "source_offset": {"type": "integer", "minimum": 0},
        "target": {
            "type": "object",
            "properties": {"app": {"type": "string"}, "title": {"type": "string"}},
            "required": ["app", "title"],
            "additionalProperties": False,
        },
        "script": {
            "type": "object",
            "description": "Native JSON object, never an encoded JSON string. Python example: {format:clawith.python.v1,source:Python code,parameters:{order:单号},secret_parameters:[]}. Python source uses actual newlines.",
            "properties": {
                "format": {"type": "string", "enum": ["clawith.python.v1", "clawith.cua.v1"]},
                "source": {
                    "type": "string",
                    "maxLength": 96000,
                    "description": "Python code, required for clawith.python.v1",
                },
                "steps": {"type": "array", "items": inline(step), "maxItems": 120},
                "parameters": {"type": "object", "additionalProperties": {"type": "string"}},
                "secret_parameters": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["format"],
            "additionalProperties": False,
        },
    }
    return {"type": "object", "properties": properties, "required": ["operation"], "additionalProperties": False}
