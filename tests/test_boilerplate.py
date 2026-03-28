import pytest
from pathlib import Path
from agents_md_mcp.project_scanner import _scan_project_structure
from agents_md_mcp.config import ProjectConfig, DEFAULT_CONFIG

def test_boilerplate_directory_flag(tmp_path):
    # Setup project with a boilerplate directory
    root = tmp_path / "myproj"
    root.mkdir()
    migrations = root / "Migrations"
    migrations.mkdir()
    (migrations / "001_initial.cs").write_text("// dummy")
    
    config = ProjectConfig(DEFAULT_CONFIG)
    structure = _scan_project_structure(root, config)
    
    # Verify Migrations/ is flagged as boilerplate
    assert "Migrations/" in structure["directories"]
    assert structure["directories"]["Migrations/"]["kind"] == "boilerplate"
    
    # Verify non-boilerplate is NOT flagged
    src = root / "src"
    src.mkdir()
    (src / "app.cs").write_text("// logic")
    
    structure = _scan_project_structure(root, config)
    assert "src/" in structure["directories"]
    assert "kind" not in structure["directories"]["src/"]
