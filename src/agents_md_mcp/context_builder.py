"""Assembles the structured JSON payload from all project scanners."""

import logging
from pathlib import Path

from .aggregator import _aggregate_by_directory
from .ast_analyzer import classify_impact, diff_analysis
from .build_system import _detect_build_systems
from .cache import CacheData
from .config import ProjectConfig
from .instructions import _build_instructions
from .models import FileAnalysis, FileChange
from .project_scanner import _detect_entry_points, _detect_env_vars, _detect_wiring, _scan_project_structure
from .symbol_utils import (
    _THRESHOLD_ORDER,
    _format_full,
    _is_public,
    _is_test_file,
    _passes_threshold,
    _slim_symbol,
    _summarize_test_files,
)

logger = logging.getLogger(__name__)


def _build_interface_impl_map(analyses: dict[str, FileAnalysis]) -> dict[str, list[str]]:
    """Build a project-wide interface → implementors map.

    Sources:
    - SymbolInfo.implements (populated by language analyzers)
    - Go convention fallback: I{Name} interface → {Name} struct
    """
    all_interfaces: set[str] = set()
    for analysis in analyses.values():
        for sym in analysis.symbols:
            if sym.kind == "interface":
                all_interfaces.add(sym.name)

    impl_map: dict[str, list[str]] = {}
    for analysis in analyses.values():
        for sym in analysis.symbols:
            if sym.kind in ("class", "struct") and sym.implements:
                for iface in sym.implements:
                    if iface in all_interfaces:
                        impl_map.setdefault(iface, []).append(sym.name)

    # Go convention fallback: I{Name} → {Name}
    for analysis in analyses.values():
        if analysis.language != "go":
            continue
        struct_names = {s.name for s in analysis.symbols if s.kind == "struct"}
        for iface in all_interfaces:
            if iface.startswith("I") and iface[1:] in struct_names:
                impl = iface[1:]
                if impl not in impl_map.get(iface, []):
                    impl_map.setdefault(iface, []).append(impl)

    return impl_map


def build_payload(
    project_path: str | Path,
    config: ProjectConfig,
    changes: list[FileChange],
    new_analyses: dict[str, FileAnalysis],
    cache: CacheData | None,
    scan_type: str = "full",
) -> dict:
    """
    Assemble the complete JSON payload to return from the MCP tool.

    Args:
        project_path: Root of the project.
        config: Resolved config.
        changes: All detected FileChange objects.
        new_analyses: path → FileAnalysis for new/modified files.
        cache: Previous cache (for diff against modified files).
        scan_type: "full" or "incremental".

    Returns:
        A dict ready to be JSON-serialized.
    """
    root = Path(project_path).resolve()
    project_name = root.name

    structure = _scan_project_structure(root, config)
    build_system = _detect_build_systems(root)

    # Read existing AGENTS.md if present
    agents_md_path = root / config.agents_md_path.lstrip("./")
    existing_agents_md = None
    if agents_md_path.exists():
        try:
            existing_agents_md = agents_md_path.read_text(encoding="utf-8")
        except OSError:
            pass

    threshold = config.impact_threshold
    changes_payload = []
    full_analysis_payload = []
    test_analysis_payload = []

    for change in changes:
        if change.status == "deleted":
            changes_payload.append({
                "file": change.path,
                "status": "deleted",
                "impact": "high",  # Deletion is always notable
            })
            continue

        analysis = new_analyses.get(change.path)
        if analysis is None:
            continue

        if change.status == "modified":
            # Compute diff against cached version
            old_symbols = None
            if cache and change.path in cache.files:
                old_symbols = cache.files[change.path].symbols

            if old_symbols is not None:
                diff = diff_analysis(old_symbols, [s for s in analysis.symbols if _is_public(s)])

                filtered_added = [
                    _slim_symbol(s) for s in diff.added
                    if _passes_threshold(classify_impact(s, "added"), threshold)
                ]
                filtered_removed = [
                    _slim_symbol(s) for s in diff.removed
                    if _passes_threshold(classify_impact(s, "removed"), threshold)
                ]
                filtered_modified = [
                    _slim_symbol(s) for s in diff.modified
                    if _passes_threshold(classify_impact(s, "modified"), threshold)
                ]

                if not (filtered_added or filtered_removed or filtered_modified):
                    continue  # Below threshold, skip

                # Overall impact = highest of all changes
                all_impacts = (
                    [classify_impact(s, "added") for s in diff.added]
                    + [classify_impact(s, "removed") for s in diff.removed]
                    + [classify_impact(s, "modified") for s in diff.modified]
                )
                overall = min(all_impacts, key=lambda x: _THRESHOLD_ORDER.get(x, 2)) if all_impacts else "low"

                changes_payload.append({
                    "file": change.path,
                    "status": "modified",
                    "language": analysis.language,
                    "impact": overall,
                    "diff": {
                        "added_symbols": filtered_added,
                        "removed_symbols": filtered_removed,
                        "modified_symbols": filtered_modified,
                    },
                })
            else:
                # No old analysis → treat as new
                entry = _format_full(change.path, "modified", analysis)
                if entry is None:
                    continue
                if _is_test_file(change.path):
                    test_analysis_payload.append(entry)
                else:
                    full_analysis_payload.append(entry)

        elif change.status == "new":
            entry = _format_full(change.path, "new", analysis)
            if entry is None:
                continue
            if _is_test_file(change.path):
                test_analysis_payload.append(entry)
            else:
                full_analysis_payload.append(entry)

    # Aggregate production dirs FIRST (before test summaries are mixed in)
    # _aggregate_by_directory expects entries with a "file" key; test_directory_summary
    # entries only have "directory", so they must be added afterwards.
    full_analysis_payload = _aggregate_by_directory(
        full_analysis_payload, config.dir_aggregation_threshold
    )

    # Collapse test files into per-directory summaries and append at the end
    if test_analysis_payload:
        full_analysis_payload.extend(_summarize_test_files(test_analysis_payload))

    env_vars = _detect_env_vars(root, config)
    entry_points = _detect_entry_points(root, config)
    wiring = _detect_wiring(new_analyses)
    interface_impl_map = _build_interface_impl_map(new_analyses)

    payload: dict = {
        "metadata": {
            "project_name": project_name,
            "languages_detected": list({a.language for a in new_analyses.values()}),
        },
        "project_structure": structure,
        "build_system": build_system,
        "entry_points": entry_points,
        "env_vars": env_vars,
        "changes": changes_payload,
        "full_analysis": full_analysis_payload,
        "existing_agents_md": existing_agents_md,
        "instructions": _build_instructions(existing_agents_md is not None),
    }
    if wiring:
        payload["wiring"] = wiring
    if interface_impl_map:
        payload["interface_impl_map"] = interface_impl_map
    return payload
