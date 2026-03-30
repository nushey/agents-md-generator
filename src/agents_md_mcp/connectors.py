"""Agent connector file mapping.

Maps MCP client names to their native instruction file paths and content,
so each agent reads AGENTS.md through its own convention.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class ConnectorSpec:
    """Defines how to create a connector file for a specific agent."""

    file_path: str  # Relative to project root (e.g. "CLAUDE.md")
    dir_path: str | None  # Directory to create if needed (e.g. ".gemini")
    reference_line: str  # The import/reference line (e.g. "@AGENTS.md")
    comment_prefix: str  # For preserving user content (e.g. "<!--" or "#")


# Known MCP client names → connector specs
# Client names come from clientInfo.name in the MCP initialize handshake.
CONNECTORS: dict[str, ConnectorSpec] = {
    "claude-code": ConnectorSpec(
        file_path="CLAUDE.md",
        dir_path=None,
        reference_line="@AGENTS.md",
        comment_prefix="<!--",
    ),
    "gemini-cli": ConnectorSpec(
        file_path=".gemini/GEMINI.md",
        dir_path=".gemini",
        reference_line="@AGENTS.md",
        comment_prefix="<!--",
    ),
}


def get_connector_spec(client_name: str | None) -> ConnectorSpec | None:
    """Return the connector spec for a known client, or None."""
    if not client_name:
        return None
    return CONNECTORS.get(client_name.lower())


def build_connector_instruction(
    spec: ConnectorSpec,
    agents_md_path: Path,
    project_path: Path,
) -> str:
    """Build the instruction text telling the agent to create/update its connector file."""
    connector_path = project_path / spec.file_path

    return (
        f"STEP 5 -- Ensure your agent reads AGENTS.md by creating or updating "
        f"the connector file at: {connector_path}\n"
        f"  - If the file does NOT exist: create it with this single line:\n"
        f"    {spec.reference_line}\n"
        f"  - If the file ALREADY exists: check whether it already contains "
        f"'{spec.reference_line}'. If it does, do nothing. If it does NOT, "
        f"prepend '{spec.reference_line}' as the FIRST line of the file, "
        f"preserving all existing content below it.\n"
        f"  - Do NOT remove or modify any existing content in this file."
    )
