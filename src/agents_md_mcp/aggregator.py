"""Collapses large sets of similar files into directory-level summaries."""

from pathlib import Path

_COMMON_METHOD_FREQUENCY = 0.6  # method must appear in >= 60% of files to be "common"
_AGGREGATION_SAMPLE_SIZE = 3    # number of sample files to include in directory summary
_PATTERN_COVERAGE_THRESHOLD = 0.4  # common methods must cover >= 40% of avg symbols per file
_DTO_METHOD_RATIO_THRESHOLD = 0.8  # >= 80% of files must have zero methods to be a DTO dir
_MAX_FILES_PER_LAYER = 5        # cap unaggregated files per directory


def _extract_common_methods(entries: list[dict]) -> list[str]:
    """Return method signatures that appear in >= 60% of the given file entries."""
    if not entries:
        return []
    method_counts: dict[str, int] = {}
    for entry in entries:
        seen: set[str] = set()
        for sym in entry.get("symbols", []):
            for method in sym.get("methods", []):
                seen.add(method)
        for sig in seen:
            method_counts[sig] = method_counts.get(sig, 0) + 1
    cutoff = len(entries) * _COMMON_METHOD_FREQUENCY
    return sorted(sig for sig, count in method_counts.items() if count >= cutoff)


def _extract_class_pattern(entries: list[dict]) -> dict | None:
    """Detect a common suffix or prefix in class names and return pattern with examples.

    Returns: {"pattern": "*Service", "examples": ["UserService", ...], "total": 47}
    """
    class_names = [
        s["name"]
        for entry in entries
        for s in entry.get("symbols", [])
        if s.get("kind") in ("class", "struct", "record")
    ]
    if len(class_names) < 2:
        return None

    pattern: str | None = None
    threshold = max(2, int(len(class_names) * 0.8))
    matching_examples: list[str] = []

    # Check common suffix (most frequent in real codebases) — longest match first
    for length in range(12, 2, -1):
        counts: dict[str, int] = {}
        for name in class_names:
            if len(name) >= length:
                suf = name[-length:]
                counts[suf] = counts.get(suf, 0) + 1
        
        # Suffix should ideally start with an uppercase letter to be a semantic unit (e.g. 'Service')
        best_suffix = None
        for suf, count in counts.items():
            if count >= threshold and suf[0].isupper():
                best_suffix = suf
                break
        
        if best_suffix:
            pattern = f"*{best_suffix}"
            matching_examples = [n for n in class_names if n.endswith(best_suffix)]
            break

    # Check common prefix — longest match first
    if not pattern:
        for length in range(12, 2, -1):
            counts: dict[str, int] = {}
            for name in class_names:
                if len(name) >= length:
                    pref = name[:length]
                    counts[pref] = counts.get(pref, 0) + 1
            
            best_prefix = None
            for pref, count in counts.items():
                if count >= threshold:
                    best_prefix = pref
                    break
            
            if best_prefix:
                pattern = f"{best_prefix}*"
                matching_examples = [n for n in class_names if n.startswith(best_prefix)]
                break

    if not pattern:
        return None

    return {
        "pattern": pattern,
        "examples": matching_examples[:3],
        "total": len(matching_examples),
    }


def _is_dto_directory(entries: list[dict]) -> bool:
    """Return True if entries look like a DTO/entity directory.

    Heuristic: >= 80% of files have only class symbols with no methods.
    These directories have no "common methods" pattern but are still worth
    collapsing — they're pure data containers, one class per file.
    """
    if not entries:
        return False
    methodless = sum(
        1 for e in entries
        if all(
            s.get("kind") == "class" and not s.get("methods")
            for s in e.get("symbols", [])
            if s.get("kind") == "class"
        )
        and any(s.get("kind") == "class" for s in e.get("symbols", []))
    )
    return (methodless / len(entries)) >= _DTO_METHOD_RATIO_THRESHOLD


def _aggregate_by_directory(entries: list[dict], threshold: int) -> list[dict]:
    """
    Group full_analysis entries by directory. Directories with >= threshold files
    of the same dominant language are collapsed into a single directory summary.
    Directories below threshold, or where no meaningful common pattern exists,
    are kept as individual file entries.
    """
    # Group by parent directory
    by_dir: dict[str, list[dict]] = {}
    for entry in entries:
        parent = Path(entry["file"]).parent.as_posix()
        by_dir.setdefault(parent, []).append(entry)

    result: list[dict] = []

    for directory, dir_entries in sorted(by_dir.items()):
        # Group entries within this directory by language
        by_lang: dict[str, list[dict]] = {}
        for entry in dir_entries:
            by_lang.setdefault(entry["language"], []).append(entry)

        # Find the dominant language group
        dominant_lang, dominant_entries = max(by_lang.items(), key=lambda kv: len(kv[1]))
        minority_entries = [e for lang, entries in by_lang.items() for e in entries if lang != dominant_lang]

        if len(dominant_entries) < threshold:
            # Not enough files to aggregate — keep individual, capped
            if len(dir_entries) > _MAX_FILES_PER_LAYER:
                result.extend(dir_entries[:_MAX_FILES_PER_LAYER])
                result.append({
                    "directory": (directory + "/").replace("//", "/"),
                    "kind": "overflow",
                    "remaining_files": len(dir_entries) - _MAX_FILES_PER_LAYER,
                })
            else:
                result.extend(dir_entries)
            continue

        common_methods = _extract_common_methods(dominant_entries)

        avg_methods = sum(
            sum(len(s.get("methods", [])) for s in e.get("symbols", []))
            for e in dominant_entries
        ) / len(dominant_entries)
        coverage = len(common_methods) / avg_methods if avg_methods > 0 else 0

        # Special Case: Directory of DTO Containers (Minified)
        if all(e.get("kind") == "dto_container" for e in dominant_entries):
            n = len(dominant_entries)
            indices = sorted({0, n // 2, n - 1})
            result.append({
                "directory": (directory + "/").replace("//", "/"),
                "kind": "directory_summary",
                "file_count": n,
                "language": dominant_lang,
                "note": f"Contains {n} DTO/Entity classes with no logic methods",
                "sample_files": [dominant_entries[i]["file"] for i in indices],
            })
            result.extend(minority_entries)
            continue

        if len(common_methods) < 2 or coverage < _PATTERN_COVERAGE_THRESHOLD:
            # No shared method pattern — check for DTO/entity directory before giving up
            if _is_dto_directory(dominant_entries):
                n = len(dominant_entries)
                indices = sorted({0, n // 2, n - 1})
                dto_summary: dict = {
                    "directory": (directory + "/").replace("//", "/"),
                    "kind": "directory_summary",
                    "file_count": len(dominant_entries),
                    "language": dominant_lang,
                    "common_methods": [],
                    "note": "DTO/entity classes — data containers with no methods",
                    "sample_files": [dominant_entries[i]["file"] for i in indices],
                }
                class_pattern = _extract_class_pattern(dominant_entries)
                if class_pattern:
                    dto_summary["naming_pattern"] = class_pattern
                result.append(dto_summary)
                result.extend(minority_entries)
            else:
                # Generic fallback — collapse into summary to avoid payload bloat
                n = len(dominant_entries)
                indices = sorted({0, n // 2, n - 1})
                fallback: dict = {
                    "directory": (directory + "/").replace("//", "/"),
                    "kind": "directory_summary",
                    "file_count": n,
                    "language": dominant_lang,
                    "note": "No common method pattern detected",
                    "sample_files": [dominant_entries[i]["file"] for i in indices],
                }
                class_pattern = _extract_class_pattern(dominant_entries)
                if class_pattern:
                    fallback["naming_pattern"] = class_pattern
                result.append(fallback)
                result.extend(minority_entries)
            continue

        common_method_set = set(common_methods)
        class_pattern = _extract_class_pattern(dominant_entries)

        # Outliers: files that have methods NOT in common_methods (unique behavior)
        outliers = []
        for entry in dominant_entries:
            unique_methods: list[str] = []
            for sym in entry.get("symbols", []):
                for method in sym.get("methods", []):
                    if method not in common_method_set:
                        unique_methods.append(method)
            if unique_methods:
                outliers.append({
                    "file": entry["file"],
                    "unique_methods": unique_methods[:5],
                })

        # Sample files: first, middle, last for representativeness
        n = len(dominant_entries)
        indices = sorted({0, n // 2, n - 1})
        sample_files = [dominant_entries[i]["file"] for i in indices]

        summary: dict = {
            "directory": (directory + "/").replace("//", "/"),
            "kind": "directory_summary",
            "file_count": len(dominant_entries),
            "language": dominant_lang,
            "common_methods": common_methods,
        }
        if class_pattern:
            summary["naming_pattern"] = class_pattern
        if outliers:
            summary["outliers"] = outliers[:5]  # cap at 5 to control size
        summary["sample_files"] = sample_files

        result.append(summary)

        # Minority language files in the same dir are always kept individual
        result.extend(minority_entries)

    return result
