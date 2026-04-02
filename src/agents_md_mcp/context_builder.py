"""Assembles the structured JSON payload from all project scanners."""

import logging
from collections import Counter
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

_METHOD_DEDUP_MIN_OCCURRENCES = 3  # signature must appear >= 3 times to be deduplicated


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


def _deduplicate_methods(entries: list[dict]) -> dict[str, str]:
    """Extract repeated method signatures into a lookup registry.

    Scans all entries for method signatures appearing >= _METHOD_DEDUP_MIN_OCCURRENCES
    times. Returns a dict mapping short keys ("m0", "m1", ...) to full signatures.
    Modifies entries IN PLACE, replacing inline signatures with their short keys.
    """
    # Count all method signature occurrences
    sig_counts: Counter[str] = Counter()
    for entry in entries:
        for sym in entry.get("symbols", []):
            for method in sym.get("methods", []):
                sig_counts[method] += 1
        # Also check common_methods in directory summaries
        for method in entry.get("common_methods", []):
            sig_counts[method] += 1

    # Build the registry for frequently repeated signatures
    registry: dict[str, str] = {}
    reverse: dict[str, str] = {}  # signature → key
    idx = 0
    for sig, count in sig_counts.most_common():
        if count < _METHOD_DEDUP_MIN_OCCURRENCES:
            break
        key = f"m{idx}"
        registry[key] = sig
        reverse[sig] = key
        idx += 1

    if not registry:
        return {}

    # Replace inline signatures with keys
    for entry in entries:
        for sym in entry.get("symbols", []):
            if "methods" in sym:
                sym["methods"] = [reverse.get(m, m) for m in sym["methods"]]
        if "common_methods" in entry:
            entry["common_methods"] = [reverse.get(m, m) for m in entry["common_methods"]]

    return registry


def _strip_language_from_file_entries(entries: list[dict]) -> None:
    """Remove 'language' from individual file entries (not directory summaries).

    Language is already in metadata.languages_detected. Directory summaries
    keep their language field since they distinguish mixed-language directories.
    """
    for entry in entries:
        if "file" in entry and "language" in entry:
            del entry["language"]


def build_payload(
    project_path: str | Path,
    config: ProjectConfig,
    changes: list[FileChange],
    new_analyses: dict[str, FileAnalysis],
    cache: CacheData | None,
    scan_type: str = "full",
    include_agents_md_context: bool = False,
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

    existing_agents_md: str | None = None
    if include_agents_md_context:
        agents_md_path = root / config.agents_md_path.lstrip("./")
        if agents_md_path.exists():
            try:
                existing_agents_md = agents_md_path.read_text(encoding="utf-8")
            except OSError:
                pass

    profile = config.profile
    threshold = profile.impact_filter
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
                entry = _format_full(change.path, "modified", analysis, profile)
                if entry is None:
                    continue
                if _is_test_file(change.path):
                    test_analysis_payload.append(entry)
                else:
                    full_analysis_payload.append(entry)

        elif change.status == "new":
            entry = _format_full(change.path, "new", analysis, profile)
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
        full_analysis_payload, profile.dir_aggregation_threshold, profile
    )

    # Collapse test files into per-directory summaries and append at the end
    if test_analysis_payload:
        full_analysis_payload.extend(_summarize_test_files(test_analysis_payload))

    # Post-processing: deduplicate method signatures and strip per-entry language
    method_patterns = _deduplicate_methods(full_analysis_payload)
    _strip_language_from_file_entries(full_analysis_payload)

    env_vars = _detect_env_vars(root, config)
    entry_points = _detect_entry_points(root, config)
    wiring = _detect_wiring(new_analyses, profile)
    interface_impl_map = _build_interface_impl_map(new_analyses)

    payload: dict = {
        "metadata": {
            "project_name": project_name,
            "languages_detected": list({a.language for a in new_analyses.values()}),
        },
    }
    if include_agents_md_context:
        payload["instructions"] = _build_instructions(existing_agents_md is not None)
    payload["project_structure"] = structure
    payload["build_system"] = build_system
    payload["entry_points"] = entry_points
    payload["env_vars"] = env_vars
    payload["changes"] = changes_payload
    payload["full_analysis"] = full_analysis_payload
    if include_agents_md_context:
        payload["existing_agents_md"] = existing_agents_md
    if method_patterns:
        payload["method_patterns"] = method_patterns
    if wiring:
        payload["wiring"] = wiring
    if interface_impl_map:
        payload["interface_impl_map"] = interface_impl_map
    return payload
