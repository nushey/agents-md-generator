import pytest
from pathlib import Path
from agents_md_mcp.context_builder import build_payload
from agents_md_mcp.config import ProjectConfig, DEFAULT_CONFIG

def test_payload_instruction_order(tmp_path):
    # Setup dummy project
    root = tmp_path / "myproj"
    root.mkdir()
    (root / "AGENTS.md").write_text("existing agents content")
    
    config = ProjectConfig(DEFAULT_CONFIG)
    payload = build_payload(
        project_path=root,
        config=config,
        changes=[],
        new_analyses={},
        cache=None
    )
    
    # Check key order
    keys = list(payload.keys())
    assert keys[0] == "metadata"
    assert keys[1] == "instructions"
    assert "project_structure" in keys
