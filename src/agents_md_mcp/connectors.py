"""Agent connector file mapping.

Maps MCP client names to their native instruction file paths and content,
and automatically modifies them so each agent reads AGENTS.md through its own convention.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ConnectorSpec:
    """Defines how to create a connector file for a specific agent."""

    agent_id: str  # Internal identifier (used for fuzzy matching)
    file_path: str  # Relative to project root (e.g. "CLAUDE.md")
    reference_template: str
    # Optional: Directories that, if present, suggest this agent is used in the project
    detection_markers: list[str] = field(default_factory=list)
    # Optional: Directory that must exist for the file_path (e.g. ".github" for .github/rules.md)
    ensure_dir: str | None = None


# Known Agent Configurations
CONNECTORS: list[ConnectorSpec] = [
    ConnectorSpec(
        agent_id="claude",
        file_path="CLAUDE.md",
        reference_template="@{file}",
        detection_markers=[".claude"],
    ),
    ConnectorSpec(
        agent_id="gemini",
        file_path=".gemini/GEMINI.md",
        ensure_dir=".gemini",
        reference_template="@{file}",
        detection_markers=[".gemini"],
    ),
    ConnectorSpec(
        agent_id="cursor",
        file_path=".cursorrules",
        reference_template="See {file} for project context and rules.",
        detection_markers=[".cursor"],
    ),
    ConnectorSpec(
        agent_id="windsurf",
        file_path=".windsurfrules",
        reference_template="See {file} for project context and rules.",
        detection_markers=[".windsurf"],
    ),
    ConnectorSpec(
        agent_id="copilot",
        file_path=".github/copilot-instructions.md",
        ensure_dir=".github",
        reference_template="Always refer to {file} for codebase rules and architecture.",
        detection_markers=[".github"],
    ),
    ConnectorSpec(
        agent_id="codex",
        file_path=".github/copilot-instructions.md",
        ensure_dir=".github",
        reference_template="Always refer to {file} for codebase rules and architecture.",
    ),
    ConnectorSpec(
        agent_id="cline",
        file_path=".clinerules",
        reference_template="See {file} for project context and rules.",
    ),
    ConnectorSpec(
        agent_id="roo-code",
        file_path=".clinerules",
        reference_template="See {file} for project context and rules.",
    ),
    ConnectorSpec(
        agent_id="codeium",
        file_path=".codeiumrules",
        reference_template="See {file} for project context and rules.",
    ),
]


def get_connector_spec(client_name: str | None) -> ConnectorSpec | None:
    """Return the connector spec for a known client, or None."""
    if not client_name:
        return None
    name = client_name.lower()
    for spec in CONNECTORS:
        if spec.agent_id in name:
            return spec
    return None


def setup_connectors(
    project_path: Path, 
    agents_md_path: Path,
    client_name: str | None = None
) -> None:
    """Automatically create or update connector files based on client or project structure."""
    specs_to_apply: list[ConnectorSpec] = []
    agents_md_name = agents_md_path.name

    # 1. Active client match
    client_spec = get_connector_spec(client_name)
    if client_spec:
        specs_to_apply.append(client_spec)

    # 2. Heuristic detection
    for spec in CONNECTORS:
        # Check if file already exists
        if (project_path / spec.file_path).exists():
            specs_to_apply.append(spec)
            continue
            
        # Check markers (directories/files that hint at agent usage)
        for marker in spec.detection_markers:
            if (project_path / marker).exists():
                specs_to_apply.append(spec)
                break

    # De-duplicate
    unique_specs = {s.agent_id: s for s in specs_to_apply}.values()

    for spec in unique_specs:
        try:
            _apply_connector_spec(spec, project_path, agents_md_name)
        except Exception as exc:
            logger.warning("Failed to auto-modify connector %s: %s", spec.file_path, exc)


def _apply_connector_spec(spec: ConnectorSpec, project_path: Path, agents_md_name: str) -> None:
    """Creates or updates the connector file directly."""
    connector_path = project_path / spec.file_path
    reference_line = spec.reference_template.format(file=agents_md_name)

    # Ensure parent directory exists for the file being created
    if spec.ensure_dir:
        (project_path / spec.ensure_dir).mkdir(parents=True, exist_ok=True)
    else:
        connector_path.parent.mkdir(parents=True, exist_ok=True)

    if not connector_path.exists():
        connector_path.write_text(f"{reference_line}\n", encoding="utf-8")
        logger.info("Created connector file for %s: %s", spec.agent_id, connector_path)
        return

    content = connector_path.read_text(encoding="utf-8")
    if reference_line not in content:
        connector_path.write_text(f"{reference_line}\n{content}", encoding="utf-8")
        logger.info("Updated connector file for %s: %s", spec.agent_id, connector_path)
