"""Resolved configuration belongs to this capability, not the Agent Runtime."""

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    tenant_id: str
    driver_url: str
    driver_token: str
    public_mcp_url: str
    signing_key: str
    evidence_dir: Path
    driver_tool_id: str

    @classmethod
    def load(cls) -> "Settings":
        required = [
            "AUTOMATION_TENANT_ID",
            "AUTOMATION_DRIVER_URL",
            "AUTOMATION_DRIVER_TOKEN_FILE",
            "AUTOMATION_MCP_URL",
            "AUTOMATION_SIGNING_KEY_FILE",
            "AUTOMATION_DRIVER_TOOL_ID",
        ]
        if any(not os.environ.get(k) for k in required):
            raise RuntimeError("Desktop automation configuration is incomplete")
        return cls(
            os.environ[required[0]],
            os.environ[required[1]],
            Path(os.environ[required[2]]).read_text().strip(),
            os.environ[required[3]],
            Path(os.environ[required[4]]).read_text().strip(),
            Path(os.getenv("AUTOMATION_EVIDENCE_DIR", "/data/desktop-automation")),
            os.environ[required[5]],
        )
