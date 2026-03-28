"""Tests for context_builder.py."""

import json
from pathlib import Path

import pytest

from agents_md_mcp.cache import make_empty_cache
from agents_md_mcp.config import load_config
from agents_md_mcp.aggregator import _aggregate_by_directory, _extract_class_pattern, _is_dto_directory
from agents_md_mcp.build_system import _detect_build_systems
from agents_md_mcp.context_builder import build_payload
from agents_md_mcp.project_scanner import _scan_project_structure
from agents_md_mcp.symbol_utils import _passes_threshold
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


def _csproj(target: str = "net8.0", output_type: str | None = None, packages: list[tuple[str, str]] = [], proj_refs: list[str] = []) -> str:
    pkg_lines = "\n".join(
        f'    <PackageReference Include="{n}" Version="{v}" />' for n, v in packages
    )
    ref_lines = "\n".join(
        f'    <ProjectReference Include="{r}" />' for r in proj_refs
    )
    output_el = f"  <OutputType>{output_type}</OutputType>" if output_type else ""
    return f"""<Project Sdk="Microsoft.NET.Sdk">
  <PropertyGroup>
    <TargetFramework>{target}</TargetFramework>
    {output_el}
  </PropertyGroup>
  <ItemGroup>
{pkg_lines}
{ref_lines}
  </ItemGroup>
</Project>"""


def test_dotnet_parses_target_framework(tmp_path: Path) -> None:
    _write(tmp_path / "MyApp" / "MyApp.csproj", _csproj(target="net8.0"))
    result = _detect_build_systems(tmp_path)
    assert "dotnet" in result["detected"]
    projects = result.get("dotnet_projects", [])
    assert len(projects) == 1
    assert projects[0]["target_framework"] == "net8.0"


def test_dotnet_parses_output_type(tmp_path: Path) -> None:
    _write(tmp_path / "MyApi" / "MyApi.csproj", _csproj(output_type="Exe"))
    result = _detect_build_systems(tmp_path)
    assert result["dotnet_projects"][0]["output_type"] == "Exe"


def test_dotnet_parses_packages(tmp_path: Path) -> None:
    pkgs = [("MediatR", "12.0.0"), ("AutoMapper", "13.0.1")]
    _write(tmp_path / "App" / "App.csproj", _csproj(packages=pkgs))
    result = _detect_build_systems(tmp_path)
    packages = result["dotnet_projects"][0]["packages"]
    assert "MediatR@12.0.0" in packages
    assert "AutoMapper@13.0.1" in packages


def test_dotnet_caps_packages_at_15(tmp_path: Path) -> None:
    pkgs = [(f"Package{i}", f"1.0.{i}") for i in range(20)]
    _write(tmp_path / "App" / "App.csproj", _csproj(packages=pkgs))
    result = _detect_build_systems(tmp_path)
    assert len(result["dotnet_projects"][0]["packages"]) == 15


def test_dotnet_parses_project_references(tmp_path: Path) -> None:
    refs = ["../MyDomain/MyDomain.csproj", "../MyInfra/MyInfra.csproj"]
    _write(tmp_path / "MyApi" / "MyApi.csproj", _csproj(proj_refs=refs))
    result = _detect_build_systems(tmp_path)
    proj_refs = result["dotnet_projects"][0]["project_references"]
    assert "../MyDomain/MyDomain.csproj" in proj_refs
    assert "../MyInfra/MyInfra.csproj" in proj_refs


def test_dotnet_no_projects_key_when_no_csproj(tmp_path: Path) -> None:
    _write(tmp_path / "MyApp.sln", "")
    result = _detect_build_systems(tmp_path)
    assert "dotnet" in result["detected"]
    assert "dotnet_projects" not in result


def test_dotnet_framework_style_csproj(tmp_path: Path) -> None:
    content = """<?xml version="1.0" encoding="utf-8"?>
<Project ToolsVersion="14.0" xmlns="http://schemas.microsoft.com/developer/msbuild/2003">
  <PropertyGroup>
    <OutputType>Library</OutputType>
    <TargetFrameworkVersion>v4.8</TargetFrameworkVersion>
  </PropertyGroup>
  <ItemGroup>
    <Reference Include="System" />
    <Reference Include="MyCustomLib">
      <HintPath>../packages/MyCustomLib.dll</HintPath>
    </Reference>
    <Reference Include="AnotherLib">
      <HintPath>../packages/AnotherLib.dll</HintPath>
    </Reference>
  </ItemGroup>
  <ItemGroup>
    <ProjectReference Include="../OtherProject/OtherProject.csproj">
      <Project>{abc}</Project>
      <Name>OtherProject</Name>
    </ProjectReference>
  </ItemGroup>
</Project>"""
    _write(tmp_path / "App" / "App.csproj", content)
    result = _detect_build_systems(tmp_path)
    proj = result["dotnet_projects"][0]
    assert proj["target_framework"] == "v4.8"
    assert proj["output_type"] == "Library"
    assert "MyCustomLib" in proj["packages"]
    assert "AnotherLib" in proj["packages"]
    assert "System" not in proj["packages"]
    assert "../OtherProject/OtherProject.csproj" in proj["project_references"]


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
    assert src_entry["languages"] == "python"


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


# ── _aggregate_by_directory ────────────────────────────────────────────────────

def _file_entry(file: str, lang: str, symbols: list[dict] | None = None) -> dict:
    return {"file": file, "language": lang, "symbols": symbols or []}


def _sym_dict(name: str, kind: str = "function") -> dict:
    return {"name": name, "kind": kind, "visibility": "public"}


def test_aggregate_below_threshold_keeps_individual() -> None:
    entries = [
        _file_entry("src/a.py", "python"),
        _file_entry("src/b.py", "python"),
    ]
    result = _aggregate_by_directory(entries, threshold=8)
    # Below threshold — must remain as individual file entries
    assert len(result) == 2
    assert all(e.get("kind") != "directory_summary" for e in result)


def test_aggregate_above_threshold_produces_summary() -> None:
    shared_syms = [_sym_dict("get"), _sym_dict("save"), _sym_dict("delete")]
    entries = [
        _file_entry(f"src/repo{i}.py", "python", shared_syms)
        for i in range(8)
    ]
    result = _aggregate_by_directory(entries, threshold=8)
    assert len(result) == 1
    summary = result[0]
    assert summary["kind"] == "directory_summary"
    assert summary["file_count"] == 8
    assert summary["language"] == "python"
    assert "get" in summary["common_methods"]


def test_aggregate_weak_pattern_keeps_individual() -> None:
    # Each file has completely different symbols — no common methods
    entries = [
        _file_entry(f"src/f{i}.py", "python", [_sym_dict(f"unique_{i}")])
        for i in range(8)
    ]
    result = _aggregate_by_directory(entries, threshold=8)
    assert all(e.get("kind") != "directory_summary" for e in result)


def test_aggregate_minority_language_kept_individual() -> None:
    shared_syms = [_sym_dict("get"), _sym_dict("save"), _sym_dict("delete")]
    py_entries = [_file_entry(f"src/repo{i}.py", "python", shared_syms) for i in range(8)]
    ts_entry = _file_entry("src/utils.ts", "typescript", [_sym_dict("helper")])
    result = _aggregate_by_directory(py_entries + [ts_entry], threshold=8)

    kinds = [e.get("kind") for e in result]
    assert "directory_summary" in kinds
    # The TypeScript file must remain as an individual entry
    ts_result = [e for e in result if e.get("file") == "src/utils.ts"]
    assert len(ts_result) == 1


def test_aggregate_different_dirs_are_independent() -> None:
    shared_syms = [_sym_dict("get"), _sym_dict("save"), _sym_dict("delete")]
    entries = (
        [_file_entry(f"services/s{i}.py", "python", shared_syms) for i in range(8)]
        + [_file_entry(f"models/m{i}.py", "python", shared_syms) for i in range(8)]
    )
    result = _aggregate_by_directory(entries, threshold=8)
    summaries = [e for e in result if e.get("kind") == "directory_summary"]
    assert len(summaries) == 2
    dirs = {s["directory"] for s in summaries}
    assert any("services" in d for d in dirs)
    assert any("models" in d for d in dirs)


# ── _extract_class_pattern ────────────────────────────────────────────────────

def test_extract_class_pattern_common_suffix() -> None:
    entries = [
        _file_entry("a.py", "python", [_sym_dict("OrderService", "class")]),
        _file_entry("b.py", "python", [_sym_dict("UserService", "class")]),
        _file_entry("c.py", "python", [_sym_dict("PaymentService", "class")]),
    ]
    pattern = _extract_class_pattern(entries)
    assert pattern is not None
    assert pattern["pattern"] == "*Service"
    assert pattern["total"] == 3
    assert len(pattern["examples"]) == 3
    assert "OrderService" in pattern["examples"]


def test_extract_class_pattern_common_prefix() -> None:
    entries = [
        _file_entry("a.py", "python", [_sym_dict("AbstractOrder", "class")]),
        _file_entry("b.py", "python", [_sym_dict("AbstractUser", "class")]),
        _file_entry("c.py", "python", [_sym_dict("AbstractPayment", "class")]),
    ]
    pattern = _extract_class_pattern(entries)
    assert pattern is not None
    assert pattern["pattern"] == "Abstract*"
    assert pattern["total"] == 3


def test_extract_class_pattern_no_pattern() -> None:
    entries = [
        _file_entry("a.py", "python", [_sym_dict("Foo", "class")]),
        _file_entry("b.py", "python", [_sym_dict("Bar", "class")]),
    ]
    pattern = _extract_class_pattern(entries)
    assert pattern is None


def test_extract_class_pattern_too_few_classes() -> None:
    entries = [_file_entry("a.py", "python", [_sym_dict("OnlyOne", "class")])]
    pattern = _extract_class_pattern(entries)
    assert pattern is None


# ── _is_dto_directory ─────────────────────────────────────────────────────────

def _dto_entry(file: str, class_name: str) -> dict:
    """A file entry with one class and no methods — canonical DTO shape."""
    return {"file": file, "language": "c_sharp", "symbols": [
        {"name": class_name, "kind": "class", "signature": f"public class {class_name}", "methods": []}
    ]}


def test_is_dto_directory_pure_dtos() -> None:
    entries = [_dto_entry(f"Entities/Dto{i}.cs", f"Dto{i}") for i in range(8)]
    assert _is_dto_directory(entries)


def test_is_dto_directory_not_dtos_with_methods() -> None:
    entries = [
        {"file": f"src/svc{i}.cs", "language": "c_sharp", "symbols": [
            {"name": f"Service{i}", "kind": "class", "methods": ["Get", "Save"]}
        ]}
        for i in range(8)
    ]
    assert not _is_dto_directory(entries)


def test_is_dto_directory_mixed_mostly_dtos() -> None:
    """80% DTOs + 20% with methods → still a DTO directory."""
    entries = [_dto_entry(f"Entities/Dto{i}.cs", f"Dto{i}") for i in range(8)]
    entries.append({"file": "Entities/Special.cs", "language": "c_sharp", "symbols": [
        {"name": "Special", "kind": "class", "methods": ["Compute"]}
    ]})
    entries.append({"file": "Entities/Other.cs", "language": "c_sharp", "symbols": [
        {"name": "Other", "kind": "class", "methods": ["Run"]}
    ]})
    # 8/10 = 80% → exactly at threshold
    assert _is_dto_directory(entries)


def test_is_dto_directory_mixed_too_many_with_methods() -> None:
    """Less than 80% DTOs → not a DTO directory."""
    entries = [_dto_entry(f"Entities/Dto{i}.cs", f"Dto{i}") for i in range(6)]
    for i in range(4):
        entries.append({"file": f"src/svc{i}.cs", "language": "c_sharp", "symbols": [
            {"name": f"Service{i}", "kind": "class", "methods": ["Get"]}
        ]})
    # 6/10 = 60% → below threshold
    assert not _is_dto_directory(entries)


def test_is_dto_directory_empty_entries() -> None:
    assert not _is_dto_directory([])


# ── _aggregate_by_directory: DTO directories ─────────────────────────────────

def test_aggregate_dto_directory_produces_summary() -> None:
    """A directory of DTO classes (no methods) above threshold → directory_summary."""
    entries = [_dto_entry(f"Entities/Dto{i}.cs", f"OrderDto{i}") for i in range(8)]
    result = _aggregate_by_directory(entries, threshold=8)
    assert len(result) == 1
    summary = result[0]
    assert summary["kind"] == "directory_summary"
    assert summary["file_count"] == 8
    assert summary["note"] == "DTO/entity classes — data containers with no methods"


def test_aggregate_dto_directory_includes_naming_pattern() -> None:
    entries = [_dto_entry(f"Entities/f{i}.cs", f"OrderDto{i}") for i in range(8)]
    result = _aggregate_by_directory(entries, threshold=8)
    summary = result[0]
    assert "naming_pattern" in summary
    assert "Dto" in summary["naming_pattern"]["pattern"]
    assert summary["naming_pattern"]["total"] == 8


def test_aggregate_dto_directory_includes_sample_files() -> None:
    entries = [_dto_entry(f"Entities/Dto{i}.cs", f"Dto{i}") for i in range(8)]
    result = _aggregate_by_directory(entries, threshold=8)
    assert "sample_files" in result[0]
    assert len(result[0]["sample_files"]) <= 3


def test_aggregate_dto_below_threshold_keeps_individual() -> None:
    """DTO directory below threshold → individual files, no summary."""
    entries = [_dto_entry(f"Entities/Dto{i}.cs", f"Dto{i}") for i in range(4)]
    result = _aggregate_by_directory(entries, threshold=8)
    assert all(e.get("kind") != "directory_summary" for e in result)
