import json
from pathlib import Path

from agents_md_mcp.connectors import (
    ConnectorSpec,
    get_connector_spec,
    setup_connectors,
)
from agents_md_mcp.server import _build_response


# ── get_connector_spec ────────────────────────────────────────────────────────


def test_get_connector_spec_claude() -> None:
    spec = get_connector_spec("claude-code")
    assert spec is not None
    assert spec.file_path == "CLAUDE.md"
    assert "{file}" in spec.reference_template


def test_get_connector_spec_cursor() -> None:
    spec = get_connector_spec("cursor")
    assert spec is not None
    assert spec.file_path == ".cursorrules"
    assert "{file}" in spec.reference_template


def test_get_connector_spec_case_insensitive() -> None:
    assert get_connector_spec("Claude-Code") is not None
    assert get_connector_spec("CLAUDE-CODE") is not None


def test_get_connector_spec_unknown_returns_none() -> None:
    assert get_connector_spec("unknown-agent") is None


def test_get_connector_spec_none_returns_none() -> None:
    assert get_connector_spec(None) is None


# ── setup_connectors ─────────────────────────────────────────────────────────


def test_setup_connectors_creates_file_for_known_client(tmp_path: Path) -> None:
    agents_md = tmp_path / "AGENTS.md"
    setup_connectors(tmp_path, agents_md, client_name="claude-code")
    claude_md = tmp_path / "CLAUDE.md"
    assert claude_md.exists()
    assert "@AGENTS.md" in claude_md.read_text()


def test_setup_connectors_creates_file_for_cursor(tmp_path: Path) -> None:
    agents_md = tmp_path / "AGENTS.md"
    setup_connectors(tmp_path, agents_md, client_name="cursor")
    cursorrules = tmp_path / ".cursorrules"
    assert cursorrules.exists()
    assert "AGENTS.md" in cursorrules.read_text()


def test_setup_connectors_creates_dir_and_file_for_copilot(tmp_path: Path) -> None:
    agents_md = tmp_path / "AGENTS.md"
    setup_connectors(tmp_path, agents_md, client_name="copilot")
    copilot_md = tmp_path / ".github" / "copilot-instructions.md"
    assert copilot_md.parent.is_dir()
    assert copilot_md.exists()
    assert "AGENTS.md" in copilot_md.read_text()


def test_setup_connectors_prepends_to_existing_file(tmp_path: Path) -> None:
    agents_md = tmp_path / "AGENTS.md"
    claude_md = tmp_path / "CLAUDE.md"
    claude_md.write_text("Existing content here.", encoding="utf-8")
    
    setup_connectors(tmp_path, agents_md, client_name="claude-code")
    
    content = claude_md.read_text(encoding="utf-8")
    assert "@AGENTS.md" in content
    assert "Existing content here." in content
    assert content.startswith("@AGENTS.md")


def test_setup_connectors_uses_custom_agents_md_filename(tmp_path: Path) -> None:
    custom_md = tmp_path / "CUSTOM_RULES.md"
    setup_connectors(tmp_path, custom_md, client_name="claude-code")
    claude_md = tmp_path / "CLAUDE.md"
    assert "@CUSTOM_RULES.md" in claude_md.read_text()


def test_setup_connectors_does_not_duplicate_reference(tmp_path: Path) -> None:
    agents_md = tmp_path / "AGENTS.md"
    cursorrules = tmp_path / ".cursorrules"
    ref = "See AGENTS.md for project context and rules."
    cursorrules.write_text(f"{ref}\nExisting content.", encoding="utf-8")
    
    setup_connectors(tmp_path, agents_md, client_name="cursor")
    
    content = cursorrules.read_text(encoding="utf-8")
    # Should only appear once
    assert content.count("AGENTS.md") == 1


def test_setup_connectors_auto_detects_multiple_agents(tmp_path: Path) -> None:
    agents_md = tmp_path / "AGENTS.md"
    # Set up multiple project structures
    (tmp_path / "CLAUDE.md").write_text("Old stuff", encoding="utf-8")
    (tmp_path / ".cursorrules").write_text("Old cursor rules", encoding="utf-8")
    (tmp_path / ".gemini").mkdir()
    
    # Run without a specific client name
    setup_connectors(tmp_path, agents_md, client_name=None)
    
    # All should be updated if their files or directories existed
    assert "@AGENTS.md" in (tmp_path / "CLAUDE.md").read_text(encoding="utf-8")
    assert "AGENTS.md" in (tmp_path / ".cursorrules").read_text(encoding="utf-8")
    assert "@AGENTS.md" in (tmp_path / ".gemini" / "GEMINI.md").read_text(encoding="utf-8")


# ── _build_response (integration) ─────────────────────────────────────────────


def test_build_response_returns_neutral_response(tmp_path: Path) -> None:
    response = _build_response(num_chunks=2, project_path=tmp_path)

    assert response["status"] == "ready"
    assert response["total_chunks"] == 2
    assert "read_payload_chunk" in response["instructions"]
