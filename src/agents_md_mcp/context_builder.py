"""ContextBuilder: assembles the structured JSON payload for Claude Code."""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from .ast_analyzer import classify_impact, diff_analysis
from .cache import CacheData
from .config import ProjectConfig
from .models import FileAnalysis, FileChange

logger = logging.getLogger(__name__)

# ── Build system detection ────────────────────────────────────────────────────

_BUILD_MARKERS: dict[str, list[str]] = {
    "dotnet": ["*.sln", "*.csproj", "global.json", "Directory.Build.props"],
    "npm": ["package.json"],
    "go": ["go.mod"],
    "make": ["Makefile", "makefile", "GNUmakefile"],
    "python": ["pyproject.toml", "setup.py", "setup.cfg", "Pipfile"],
    "rust": ["Cargo.toml"],
    "maven": ["pom.xml"],
    "gradle": ["build.gradle", "build.gradle.kts"],
    "ruby": ["Gemfile"],
}

_CI_PATTERNS = [
    ".github/workflows/*.yml",
    ".github/workflows/*.yaml",
    ".gitlab-ci.yml",
    "Jenkinsfile",
    ".circleci/config.yml",
    "azure-pipelines.yml",
    ".travis.yml",
    "bitbucket-pipelines.yml",
]

_CONFIG_FILES = [
    ".editorconfig",
    ".eslintrc*",
    ".eslintrc.json",
    ".eslintrc.js",
    ".eslintrc.yml",
    "eslint.config.*",
    ".prettierrc*",
    ".prettierrc",
    "prettier.config.*",
    "tsconfig.json",
    "tsconfig*.json",
    ".stylelintrc*",
    "jest.config.*",
    "vitest.config.*",
    "pytest.ini",
    "pyproject.toml",
    ".flake8",
    "mypy.ini",
    ".mypy.ini",
    "rustfmt.toml",
    ".rustfmt.toml",
    ".golangci.yml",
    ".golangci.yaml",
]

_TEST_DIR_PATTERNS = [
    "test", "tests", "spec", "specs", "__tests__",
    "*.Tests", "*.Test", "*.Specs",
]


def _glob_first(root: Path, patterns: list[str]) -> list[Path]:
    found = []
    for pattern in patterns:
        found.extend(root.glob(pattern))
    return found


def _detect_build_systems(root: Path) -> dict:
    detected = []
    package_files = []

    for system, markers in _BUILD_MARKERS.items():
        for marker in markers:
            matches = list(root.glob(marker))
            if matches:
                detected.append(system)
                for m in matches:
                    rel = str(m.relative_to(root))
                    if rel not in package_files:
                        package_files.append(rel)
                break  # one match per system is enough

    scripts: dict[str, dict] = {}

    # Parse npm scripts
    pkg_json = root / "package.json"
    if pkg_json.exists():
        try:
            data = json.loads(pkg_json.read_text(encoding="utf-8"))
            if "scripts" in data:
                scripts["npm"] = data["scripts"]
            # Detect package manager
            if "packageManager" in data:
                pm = data["packageManager"].split("@")[0]
                if pm not in detected:
                    detected.append(pm)
        except (json.JSONDecodeError, OSError):
            pass

    # Parse Makefile targets (first word of non-indented lines ending with :)
    makefile = root / "Makefile"
    if not makefile.exists():
        makefile = root / "makefile"
    if makefile.exists():
        try:
            targets = []
            for line in makefile.read_text(encoding="utf-8", errors="replace").splitlines():
                if line and not line.startswith("\t") and not line.startswith("#") and ":" in line:
                    target = line.split(":")[0].strip()
                    if target and not target.startswith(".") and " " not in target:
                        targets.append(target)
            if targets:
                scripts["make"] = {t: f"make {t}" for t in targets[:20]}
        except OSError:
            pass

    return {
        "detected": detected,
        "package_files": package_files,
        "scripts": scripts,
    }


def _scan_project_structure(root: Path, config: ProjectConfig) -> dict:
    """Scan directories and root files (no AST, pure filesystem)."""
    root_files = [
        f.name for f in root.iterdir()
        if f.is_file() and not f.name.startswith(".")
    ][:30]

    # Directory summary: file count + dominant extension
    dir_summary: dict[str, dict] = {}
    try:
        for item in root.rglob("*"):
            if not item.is_file():
                continue
            rel = str(item.relative_to(root))
            # Skip excluded paths
            skip = False
            for excl in config.exclude:
                import fnmatch
                if fnmatch.fnmatch(rel, excl):
                    skip = True
                    break
            if skip:
                continue
            parent_rel = str(item.parent.relative_to(root))
            if parent_rel == ".":
                continue
            if parent_rel not in dir_summary:
                dir_summary[parent_rel] = {"file_count": 0, "extensions": {}}
            dir_summary[parent_rel]["file_count"] += 1
            ext = item.suffix.lower()
            if ext:
                exts = dir_summary[parent_rel]["extensions"]
                exts[ext] = exts.get(ext, 0) + 1
    except OSError:
        pass

    # Pick primary language per directory
    from .config import EXTENSION_TO_LANGUAGE
    dirs_out: dict[str, dict] = {}
    for d, info in dir_summary.items():
        primary = None
        best = 0
        for ext, count in info["extensions"].items():
            lang = EXTENSION_TO_LANGUAGE.get(ext)
            if lang and count > best:
                primary = lang
                best = count
        dirs_out[d + "/"] = {
            "file_count": info["file_count"],
            "primary_language": primary,
        }

    # Config files present at root
    config_found = []
    for pattern in _CONFIG_FILES:
        matches = list(root.glob(pattern))
        config_found.extend(str(m.relative_to(root)) for m in matches)

    # CI files
    ci_found = []
    for pattern in _CI_PATTERNS:
        matches = list(root.glob(pattern))
        ci_found.extend(str(m.relative_to(root)) for m in matches)

    # Test directories
    test_dirs = []
    for pattern in _TEST_DIR_PATTERNS:
        for d in root.glob(pattern):
            if d.is_dir():
                test_dirs.append(str(d.relative_to(root)) + "/")
        # Also *.Tests style (case insensitive check)
        for d in root.glob("*"):
            if d.is_dir() and any(
                d.name.lower().endswith(suf)
                for suf in (".tests", ".test", ".specs", ".spec")
            ):
                rel = str(d.relative_to(root)) + "/"
                if rel not in test_dirs:
                    test_dirs.append(rel)

    return {
        "root_files": root_files,
        "directories": dirs_out,
        "config_files_found": list(dict.fromkeys(config_found)),
        "ci_files_found": list(dict.fromkeys(ci_found)),
        "test_directories": list(dict.fromkeys(test_dirs)),
    }


# ── Impact threshold filtering ────────────────────────────────────────────────

_THRESHOLD_ORDER = {"high": 0, "medium": 1, "low": 2}


def _passes_threshold(impact: str, threshold: str) -> bool:
    return _THRESHOLD_ORDER.get(impact, 2) <= _THRESHOLD_ORDER.get(threshold, 1)


# ── Main builder ──────────────────────────────────────────────────────────────

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
            old_analysis = None
            if cache and change.path in cache.files:
                old_analysis = cache.files[change.path].analysis

            if old_analysis:
                diff = diff_analysis(old_analysis, analysis)
                # Filter by impact threshold
                def impact_entry(sym, ctype):
                    imp = classify_impact(sym, ctype)
                    return imp, sym

                filtered_added = [
                    s.model_dump() for s in diff.added
                    if _passes_threshold(classify_impact(s, "added"), threshold)
                ]
                filtered_removed = [
                    s.model_dump() for s in diff.removed
                    if _passes_threshold(classify_impact(s, "removed"), threshold)
                ]
                filtered_modified = [
                    s.model_dump() for s in diff.modified
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
                full_analysis_payload.append(_format_full(change.path, "modified", analysis))

        elif change.status == "new":
            full_analysis_payload.append(_format_full(change.path, "new", analysis))

    return {
        "metadata": {
            "project_name": project_name,
            "scan_type": scan_type,
            "files_analyzed": len(new_analyses),
            "files_total": len(changes),
            "languages_detected": list({a.language for a in new_analyses.values()}),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        },
        "project_structure": structure,
        "build_system": build_system,
        "changes": changes_payload,
        "full_analysis": full_analysis_payload,
        "existing_agents_md": existing_agents_md,
        "instructions": (
            "Based on this analysis, generate (or update) the AGENTS.md following the agents.md standard. "
            "The file must include: Project Overview, Setup Commands, Development Workflow, Testing Instructions, "
            "Code Style, Build and Deployment, and any additional sections justified by the analysis. "
            "If an AGENTS.md already exists, preserve its structure and only update sections affected by the "
            "detected changes. Prioritize exact, actionable commands."
        ),
    }


def _format_full(path: str, status: str, analysis: FileAnalysis) -> dict:
    """Format a new/untracked file for the full_analysis section."""
    symbols_out = []
    for sym in analysis.symbols:
        if sym.kind == "class":
            # Include method names as a list
            entry = sym.model_dump(exclude={"decorators", "line_start", "line_end", "parent"})
            entry["methods"] = [
                s.name for s in analysis.symbols
                if s.parent == sym.name and s.kind == "method"
            ]
            symbols_out.append(entry)
        elif sym.parent is None:
            # Top-level non-class symbol
            symbols_out.append(sym.model_dump(exclude={"line_start", "line_end"}))

    return {
        "file": path,
        "status": status,
        "language": analysis.language,
        "symbols": symbols_out,
        "imports": analysis.imports[:10],  # Cap for payload size
    }
