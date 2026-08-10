from pathlib import Path

from agents_md_mcp.context_builder import build_payload
from agents_md_mcp.config import ProjectConfig, DEFAULT_CONFIG

from tests.conftest import git_init


def _payload(tmp_path, include_agents_md_context):
    root = tmp_path / "myproj"
    root.mkdir()
    git_init(root)
    (root / "AGENTS.md").write_text("existing agents content")
    config = ProjectConfig(DEFAULT_CONFIG)
    return build_payload(
        project_path=root,
        config=config,
        changes=[],
        new_analyses={},
        cache=None,
        include_agents_md_context=include_agents_md_context,
    )


def test_scan_payload_order(tmp_path):
    payload = _payload(tmp_path, include_agents_md_context=False)
    keys = list(payload.keys())

    assert keys[0] == "metadata"
    # Scan mode never carries AGENTS.md generation fields.
    assert "instructions" not in keys
    assert "existing_agents_md" not in keys
    assert "mode" not in keys

    # Interpretation tables are always present and precede full_analysis so the
    # agent can resolve aliases while reading it, not after.
    for table in ("method_patterns", "interface_impl_map", "wiring"):
        assert table in keys, table
        assert keys.index(table) < keys.index("full_analysis"), table


def test_generate_payload_puts_mode_and_existing_up_front(tmp_path):
    payload = _payload(tmp_path, include_agents_md_context=True)
    keys = list(payload.keys())

    assert payload["mode"] == "update"  # AGENTS.md exists -> update
    # mode + existing content arrive before the bulky full_analysis section.
    for early in ("instructions", "mode", "existing_agents_md", "method_patterns"):
        assert keys.index(early) < keys.index("full_analysis"), early
