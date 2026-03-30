"""Tests for connectors.py — agent connector file mapping."""

from pathlib import Path

from agents_md_mcp.connectors import (
    ConnectorSpec,
    build_connector_instruction,
    get_connector_spec,
)
from agents_md_mcp.server import _build_response


# ── get_connector_spec ────────────────────────────────────────────────────────


def test_get_connector_spec_claude() -> None:
    spec = get_connector_spec("claude-code")
    assert spec is not None
    assert spec.file_path == "CLAUDE.md"
    assert "@AGENTS.md" in spec.reference_line


def test_get_connector_spec_gemini() -> None:
    spec = get_connector_spec("gemini-cli")
    assert spec is not None
    assert spec.file_path == ".gemini/GEMINI.md"
    assert spec.dir_path == ".gemini"


def test_get_connector_spec_case_insensitive() -> None:
    assert get_connector_spec("Claude-Code") is not None
    assert get_connector_spec("CLAUDE-CODE") is not None


def test_get_connector_spec_unknown_returns_none() -> None:
    assert get_connector_spec("unknown-agent") is None


def test_get_connector_spec_none_returns_none() -> None:
    assert get_connector_spec(None) is None


# ── build_connector_instruction ───────────────────────────────────────────────


def test_build_connector_instruction_contains_path() -> None:
    spec = ConnectorSpec(
        file_path="CLAUDE.md",
        dir_path=None,
        reference_line="@AGENTS.md",
        comment_prefix="<!--",
    )
    result = build_connector_instruction(
        spec,
        agents_md_path=Path("/project/AGENTS.md"),
        project_path=Path("/project"),
    )
    assert "CLAUDE.md" in result
    assert "@AGENTS.md" in result
    assert "STEP 5" in result


def test_build_connector_instruction_mentions_existing_file() -> None:
    spec = get_connector_spec("claude-code")
    result = build_connector_instruction(
        spec,
        agents_md_path=Path("/project/AGENTS.md"),
        project_path=Path("/project"),
    )
    assert "ALREADY exists" in result
    assert "prepend" in result
    assert "Do NOT remove" in result


# ── _build_response integration ───────────────────────────────────────────────


def test_build_response_without_client_has_4_steps() -> None:
    response = _build_response(
        payload_path=Path("/cache/payload.json"),
        num_chunks=1,
        agents_md_path=Path("/project/AGENTS.md"),
        project_path=Path("/project"),
        client_name=None,
    )
    assert "STEP 5" not in response["instructions"]
    assert "all 4 steps" in response["instructions"]


def test_build_response_with_unknown_client_has_4_steps() -> None:
    response = _build_response(
        payload_path=Path("/cache/payload.json"),
        num_chunks=1,
        agents_md_path=Path("/project/AGENTS.md"),
        project_path=Path("/project"),
        client_name="unknown-agent",
    )
    assert "STEP 5" not in response["instructions"]
    assert "all 4 steps" in response["instructions"]


def test_build_response_with_claude_has_5_steps() -> None:
    response = _build_response(
        payload_path=Path("/cache/payload.json"),
        num_chunks=1,
        agents_md_path=Path("/project/AGENTS.md"),
        project_path=Path("/project"),
        client_name="claude-code",
    )
    assert "STEP 5" in response["instructions"]
    assert "CLAUDE.md" in response["instructions"]
    assert "@AGENTS.md" in response["instructions"]
    assert "all 5 steps" in response["instructions"]


def test_build_response_with_gemini_has_5_steps() -> None:
    response = _build_response(
        payload_path=Path("/cache/payload.json"),
        num_chunks=1,
        agents_md_path=Path("/project/AGENTS.md"),
        project_path=Path("/project"),
        client_name="gemini-cli",
    )
    assert "STEP 5" in response["instructions"]
    assert ".gemini/GEMINI.md" in response["instructions"]
    assert "all 5 steps" in response["instructions"]
