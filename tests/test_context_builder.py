"""Tests for context_builder.py."""

import json
from pathlib import Path

import pytest

from agents_md_mcp.cache import make_empty_cache
from agents_md_mcp.config import load_config
from agents_md_mcp.context_builder import (
    _detect_build_systems,
    _passes_threshold,
    _scan_project_structure,
    build_payload,
)
from agents_md_mcp.models import CachedFile, FileAnalysis, FileChange, SymbolInfo


# ── Helpers ───────────────────────────────────────────────────────────────────

def _write(path: Path, content: str = "") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def _analysis(path: str, lang: str = "python", symbols: list[SymbolInfo] | None = None) -> FileAnalysis:
    return FileAnalysis(path=path, language=lang, symbols=symbols or [])


def _sym(name: str, kind: str = "function", visibility: str = "public", sig: str = "sig") -> SymbolInfo:
    return SymbolInfo(name=name, kind=kind, visibility=visibility, signature=sig)  # type: ignore[arg-type]


# ── _passes_threshold ─────────────────────────────────────────────────────────

def test_threshold_high_passes_all() -> None:
    assert _passes_threshold("high", "low")
    assert _passes_threshold("high", "medium")
    assert _passes_threshold("high", "high")


def test_threshold_low_only_passes_low() -> None:
    assert _passes_threshold("low", "low")
    assert not _passes_threshold("low", "medium")
    assert not _passes_threshold("low", "high")


def test_threshold_medium() -> None:
    assert _passes_threshold("medium", "low")
    assert _passes_threshold("medium", "medium")
    assert not _passes_threshold("medium", "high")


# ── _detect_build_systems ────────────────────────────────────────────────────

def test_detects_npm(tmp_path: Path) -> None:
    _write(tmp_path / "package.json", json.dumps({
        "scripts": {"build": "vite build", "test": "vitest"}
    }))
    result = _detect_build_systems(tmp_path)
    assert "npm" in result["detected"]
    assert "build" in result["scripts"].get("npm", {})


def test_detects_python(tmp_path: Path) -> None:
    _write(tmp_path / "pyproject.toml", "[build-system]\n")
    result = _detect_build_systems(tmp_path)
    assert "python" in result["detected"]


def test_detects_go(tmp_path: Path) -> None:
    _write(tmp_path / "go.mod", "module example.com/app\n")
    result = _detect_build_systems(tmp_path)
    assert "go" in result["detected"]


def test_detects_makefile_targets(tmp_path: Path) -> None:
    _write(tmp_path / "Makefile", "build:\n\tgo build\ntest:\n\tgo test ./...\n")
    result = _detect_build_systems(tmp_path)
    assert "make" in result["detected"]
    assert "build" in result["scripts"].get("make", {})
    assert "test" in result["scripts"].get("make", {})


def test_no_build_system(tmp_path: Path) -> None:
    result = _detect_build_systems(tmp_path)
    assert result["detected"] == []


# ── _scan_project_structure ───────────────────────────────────────────────────

def test_scans_root_files(tmp_path: Path) -> None:
    _write(tmp_path / "README.md")
    _write(tmp_path / "main.py")
    cfg = load_config(tmp_path)
    result = _scan_project_structure(tmp_path, cfg)
    assert "README.md" in result["root_files"] or "main.py" in result["root_files"]


def test_detects_ci_files(tmp_path: Path) -> None:
    ci_file = tmp_path / ".github" / "workflows" / "ci.yml"
    _write(ci_file, "name: CI\n")
    cfg = load_config(tmp_path)
    result = _scan_project_structure(tmp_path, cfg)
    assert any("ci.yml" in f for f in result["ci_files_found"])


def test_detects_test_directories(tmp_path: Path) -> None:
    (tmp_path / "tests").mkdir()
    cfg = load_config(tmp_path)
    result = _scan_project_structure(tmp_path, cfg)
    assert any("tests" in d for d in result["test_directories"])


def test_directory_language_detection(tmp_path: Path) -> None:
    _write(tmp_path / "src" / "app.py", "# python")
    _write(tmp_path / "src" / "utils.py", "# python")
    cfg = load_config(tmp_path)
    result = _scan_project_structure(tmp_path, cfg)
    src_entry = result["directories"].get("src/")
    assert src_entry is not None
    assert src_entry["primary_language"] == "python"


# ── build_payload ─────────────────────────────────────────────────────────────

def test_build_payload_new_files(tmp_path: Path) -> None:
    _write(tmp_path / "src" / "app.py", "def run(): pass")
    cfg = load_config(tmp_path)

    changes = [FileChange(path="src/app.py", status="new", new_hash="abc")]
    analyses = {"src/app.py": _analysis("src/app.py", "python", [_sym("run")])}

    payload = build_payload(tmp_path, cfg, changes, analyses, cache=None)

    assert len(payload["full_analysis"]) == 1
    assert payload["full_analysis"][0]["file"] == "src/app.py"


def test_build_payload_includes_instructions(tmp_path: Path) -> None:
    cfg = load_config(tmp_path)
    payload = build_payload(tmp_path, cfg, [], {}, cache=None)
    assert "AGENTS.md" in payload["instructions"]


def test_build_payload_reads_existing_agents_md(tmp_path: Path) -> None:
    _write(tmp_path / "AGENTS.md", "# Existing content\n")
    cfg = load_config(tmp_path)
    payload = build_payload(tmp_path, cfg, [], {}, cache=None)
    assert payload["existing_agents_md"] == "# Existing content\n"


def test_build_payload_no_agents_md(tmp_path: Path) -> None:
    cfg = load_config(tmp_path)
    payload = build_payload(tmp_path, cfg, [], {}, cache=None)
    assert payload["existing_agents_md"] is None


def test_build_payload_modified_with_diff(tmp_path: Path) -> None:
    _write(tmp_path / "src" / "app.py", "def run(): pass\ndef stop(): pass")
    cfg = load_config(tmp_path)

    old_analysis = _analysis("src/app.py", "python", [_sym("run", sig="def run()")])
    cache = make_empty_cache()
    from agents_md_mcp.models import CachedSymbol
    cache.files["src/app.py"] = CachedFile(
        hash="old",
        symbols=[CachedSymbol(name="run", kind="function", visibility="public", signature="def run()")],
    )

    new_analysis = _analysis("src/app.py", "python", [
        _sym("run", sig="def run()"),
        _sym("stop", sig="def stop()"),
    ])

    changes = [FileChange(path="src/app.py", status="modified", old_hash="old", new_hash="new")]
    analyses = {"src/app.py": new_analysis}

    payload = build_payload(tmp_path, cfg, changes, analyses, cache=cache, scan_type="incremental")

    assert len(payload["changes"]) == 1
    diff_entry = payload["changes"][0]
    assert diff_entry["status"] == "modified"
    assert any(s["name"] == "stop" for s in diff_entry["diff"]["added_symbols"])


def test_build_payload_deleted_file(tmp_path: Path) -> None:
    cfg = load_config(tmp_path)
    changes = [FileChange(path="src/old.py", status="deleted", old_hash="abc")]
    payload = build_payload(tmp_path, cfg, changes, {}, cache=None)
    assert len(payload["changes"]) == 1
    assert payload["changes"][0]["status"] == "deleted"
    assert payload["changes"][0]["impact"] == "high"
