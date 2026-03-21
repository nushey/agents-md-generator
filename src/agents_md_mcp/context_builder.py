"""ContextBuilder: assembles the structured JSON payload for Claude Code."""

import fnmatch
import json
import logging
import re
import tomllib
from pathlib import Path

from .ast_analyzer import classify_impact, diff_analysis
from .cache import CacheData
from .change_detector import _is_excluded
from .config import EXTENSION_TO_LANGUAGE, ProjectConfig
from .gitignore import is_gitignored, load_gitignore_spec
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

    # Parse pyproject.toml — entry points, test runner, package manager
    pyproject = root / "pyproject.toml"
    if pyproject.exists():
        try:
            with open(pyproject, "rb") as f:
                toml = tomllib.load(f)

            py_scripts: dict[str, str] = {}

            # Detect package manager from lock file presence
            runner = "python"
            if (root / "uv.lock").exists():
                runner = "uv run"
                if "uv" not in detected:
                    detected.append("uv")
            elif (root / "poetry.lock").exists():
                runner = "poetry run"
                if "poetry" not in detected:
                    detected.append("poetry")

            # Install command
            if runner == "uv run":
                py_scripts["install"] = "uv sync"
            elif runner == "poetry run":
                py_scripts["install"] = "poetry install"

            # [project.scripts] → CLI entry points
            project_scripts = toml.get("project", {}).get("scripts", {})
            for name, target in project_scripts.items():
                py_scripts[name] = f"{runner} {name}" if runner != "python" else name

            # Detect test runner from dependencies
            all_deps = (
                toml.get("project", {}).get("dependencies", [])
                + [d for deps in toml.get("project", {}).get("optional-dependencies", {}).values() for d in deps]
            )
            dep_names = [d.split(">=")[0].split("==")[0].split("[")[0].strip().lower() for d in all_deps]
            if "pytest" in dep_names:
                py_scripts["test"] = f"{runner} pytest"
            elif "unittest" in dep_names:
                py_scripts["test"] = f"{runner} python -m unittest"

            if py_scripts:
                scripts["python"] = py_scripts
        except (OSError, tomllib.TOMLDecodeError):
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
    gitignore_spec = load_gitignore_spec(root)

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
            if is_gitignored(rel, gitignore_spec):
                continue
            if _is_excluded(rel, config):
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


# ── Environment variable detection ───────────────────────────────────────────

_ENV_PATTERNS: dict[str, re.Pattern] = {
    "javascript": re.compile(r'process\.env\.([A-Z][A-Z0-9_]+)'),
    "typescript": re.compile(r'process\.env\.([A-Z][A-Z0-9_]+)'),
    "python":     re.compile(r'os\.(?:environ(?:\.get)?\s*\(\s*[\'"]|getenv\s*\(\s*[\'"])([A-Z][A-Z0-9_]+)'),
    "go":         re.compile(r'os\.Getenv\(\s*"([A-Z][A-Z0-9_]+)'),
    "ruby":       re.compile(r'ENV\s*\[\s*[\'"]([A-Z][A-Z0-9_]+)'),
    "rust":       re.compile(r'env!\s*\(\s*"([A-Z][A-Z0-9_]+)|var\s*\(\s*"([A-Z][A-Z0-9_]+)'),
}

_ENV_DOTFILES = (".env.example", ".env.template", ".env.sample", ".env.test")
_ENV_VAR_RE = re.compile(r'^([A-Z][A-Z0-9_]+)\s*=')


def _detect_env_vars(root: Path, config: ProjectConfig) -> list[str]:
    """Scan source files and .env examples for environment variable names."""
    gitignore_spec = load_gitignore_spec(root)
    found: set[str] = set()

    # Scan source files for process.env.X / os.environ / etc.
    try:
        for item in root.rglob("*"):
            if not item.is_file():
                continue
            rel = str(item.relative_to(root))
            if is_gitignored(rel, gitignore_spec) or _is_excluded(rel, config):
                continue
            lang = EXTENSION_TO_LANGUAGE.get(item.suffix.lower())
            pattern = _ENV_PATTERNS.get(lang) if lang else None
            if pattern is None:
                continue
            if item.stat().st_size > config.max_file_size_bytes:
                continue
            try:
                content = item.read_text(encoding="utf-8", errors="replace")
                for match in pattern.finditer(content):
                    # rust pattern has two groups; take whichever matched
                    var = next((g for g in match.groups() if g), None) if match.lastindex and match.lastindex > 1 else match.group(1)
                    if var:
                        found.add(var)
            except OSError:
                continue
    except OSError:
        pass

    # Scan .env example files at root — most reliable source of truth
    for name in _ENV_DOTFILES:
        env_file = root / name
        if not env_file.exists():
            continue
        try:
            for line in env_file.read_text(encoding="utf-8", errors="replace").splitlines():
                m = _ENV_VAR_RE.match(line.strip())
                if m:
                    found.add(m.group(1))
        except OSError:
            continue

    return sorted(found)


# ── Entry point detection ─────────────────────────────────────────────────────

_ENTRY_STEMS = {"index", "main", "app", "server", "program", "bootstrap", "startup"}

_ROLE_HINTS: list[tuple[str, str]] = [
    ("electron",   "Electron main process"),
    ("preload",    "Electron preload script"),
    ("routes",     "Route definitions"),
    ("api",        "API module index"),
    ("server",     "HTTP server bootstrap"),
    ("backend",    "Backend entry point"),
    ("frontend",   "Frontend entry point"),
]


def _infer_entry_role(rel: str, stem: str) -> str:
    lower = rel.lower()
    for hint, label in _ROLE_HINTS:
        if hint in lower:
            return label
    if stem == "main":
        return "Application entry point"
    if stem == "app":
        return "Application setup"
    if stem == "server":
        return "HTTP server bootstrap"
    return "Module index"


def _detect_entry_points(root: Path, config: ProjectConfig) -> list[dict]:
    """Detect bootstrap / entry-point files (index, main, app, server, …)."""
    gitignore_spec = load_gitignore_spec(root)
    entries = []
    seen_dirs: set[str] = set()

    try:
        for item in root.rglob("*"):
            if not item.is_file():
                continue
            rel = str(item.relative_to(root))
            if is_gitignored(rel, gitignore_spec) or _is_excluded(rel, config):
                continue
            if not config.is_extension_supported(item.suffix.lower()):
                continue
            if _is_test_file(rel):
                continue
            stem = item.stem.lower()
            if stem not in _ENTRY_STEMS:
                continue
            # One entry per directory — avoid index.js + index.ts duplicates
            parent = str(item.parent.relative_to(root))
            dir_key = f"{parent}/{stem}"
            if dir_key in seen_dirs:
                continue
            seen_dirs.add(dir_key)
            entries.append({
                "file": rel,
                "role": _infer_entry_role(rel, stem),
            })
    except OSError:
        pass

    return sorted(entries, key=lambda e: e["file"])


# ── Impact threshold filtering ────────────────────────────────────────────────

_THRESHOLD_ORDER = {"high": 0, "medium": 1, "low": 2}


def _passes_threshold(impact: str, threshold: str) -> bool:
    return _THRESHOLD_ORDER.get(impact, 2) <= _THRESHOLD_ORDER.get(threshold, 1)


# ── Main builder ──────────────────────────────────────────────────────────────

def _build_instructions(has_existing: bool) -> str:
    """Build the instruction string embedded in the payload."""
    action = "UPDATE the existing" if has_existing else "CREATE a new"
    update_note = (
        "The existing AGENTS.md content is provided in 'existing_agents_md'. "
        "Preserve sections that are not affected by the detected changes. "
        "Only rewrite sections where the analysis shows something changed."
        if has_existing
        else "Write the complete file from scratch using the analysis data."
    )

    return f"""
TASK: {action} AGENTS.md file at the project root.

## ABSOLUTE RULES — NEVER BREAK THESE

1. DO NOT read any source files. Do not call Read, Glob, Grep, Bash, or any
   file-reading tool. ALL information needed is already in this payload.

2. DO NOT call generate_agents_md again.

3. DO NOT enumerate files. Never write tables or bullet lists of filenames with
   their exports. If you find yourself writing "| clients.api.js | getClients, addClient |"
   — STOP. That is wrong. AGENTS.md is not a file index.

4. DO NOT invent commands, tools, or conventions absent from this payload.
   If a script is not in build_system.scripts, do not mention it.
   If a linter is not in config_files_found, do not claim it exists.

5. USE ONLY the data in this payload:
   - metadata → project name, detected languages
   - project_structure → directories, config files, CI files, test directories
   - build_system → detected tools, package files, parsed scripts
   - entry_points → bootstrap/main files per package with their role
   - env_vars → environment variables referenced in source or .env.example files
   - full_analysis → public symbols per file (use to INFER patterns)
   - changes → semantic diffs (incremental scans only)
   - existing_agents_md → current content to preserve or update ({update_note})

## WHAT AGENTS.MD IS — READ THIS BEFORE WRITING ANYTHING

AGENTS.md is a "README for AI coding agents." It gives agents the architectural
context and operational rules they need to contribute effectively WITHOUT
exploring the codebase themselves.

It answers:
  - How is this system structured and why?
  - What conventions must I follow when adding code?
  - Where exactly do I put a new file of type X?
  - What commands do I run to build, test, lint?
  - What must I never break?

It is NOT documentation. It is NOT a changelog. It is NOT a file index.

## HOW TO USE THE PAYLOAD DATA

### `full_analysis` — SYNTHESIZE patterns, never list files

Examine the file paths and symbol names to detect recurring patterns, then
document those patterns as RULES.

Examples of synthesis (infer these from the data, do not hard-code them):
- Naming convention: if you see `clients.api.js`, `orders.api.js`, `transports.api.js`
  → rule: "API clients follow the pattern `<entity>.api.js` in `src/api/`"
- Export convention: if every *.api.js exports getX, addX, modifyX, deleteX
  → rule: "API modules export CRUD functions named getX / addX / modifyX / deleteX"
- Layer pattern: if api/ → services/ → hooks/ → context/ → pages/ appears
  → document the data flow as a pipeline, not as individual files
- Domain grouping: if clients.*, orders.*, quotations.* appear across layers
  → the project is domain-oriented; list the domains, not the files

If you cannot detect a pattern, omit that convention. Never invent one.

### `project_structure.directories` — describe architecture, not a tree

Write what each directory layer IS and DOES, not a directory listing.
"src/api/ contains one HTTP client module per business entity" is good.
A table of directory paths with file counts is useless to an agent.

### `build_system.scripts` — exact commands only

Copy them verbatim. Use fenced code blocks. Never paraphrase.
`scripts.python` contains install, test, and CLI entry point commands derived
from `pyproject.toml` and the detected package manager (uv, poetry, pip).
`scripts.npm` contains scripts from `package.json`.
`scripts.make` contains Makefile targets.

## FORMAT (include only sections with real data)

### Project Overview
2–4 sentences: what the system does, the tech stack, and the top-level
architectural shape (e.g., layered, domain-driven, monorepo). No file lists.

### Architecture & Data Flow
The most important narrative section. Describe the architectural layers or
domains detected from the directory structure and file analysis.
For a layered architecture: name each layer, its responsibility, and the
direction data flows (e.g., Page → Context → Service → API → Backend).
For a domain architecture: name the domains and their boundaries.
This section replaces any need to enumerate files.

### Conventions & Patterns
THE most actionable section for AI agents. Synthesize from full_analysis:
- File naming rules per layer/type (exact pattern, exact directory)
- Export contract per file type (what every file of that type must export)
- Import rules (which layers may import from which — e.g., "pages import
  only from Context, never directly from api/")
- How to add a new entity end-to-end (step-by-step, referencing the detected
  pattern — e.g., "1. Create <entity>.api.js in src/api/ with CRUD exports.
  2. Create <entity>Service.js in src/services/. 3. Add hook in src/hooks/.
  4. Register in DataContext.")

### Environment Variables
Only if env_vars is non-empty. List each variable with a one-line description
of its purpose inferred from its name and the files it appears in.
If a .env.example is present, mention it explicitly.

### Setup Commands
Exact install and environment commands from build_system. Fenced code blocks.
Reference entry_points to explain where bootstrap happens.

### Development Workflow
Run/build/watch commands from build_system.scripts. Fenced code blocks.
Skip if no scripts detected.

### Testing Instructions
From test_directories + config_files_found (jest/pytest/vitest) +
build_system.scripts test entries. Skip entirely if nothing detected.

### Code Style
Only if linting/formatting config files appear in config_files_found.
Include the exact lint/format commands. Omit if nothing detected.

### Build and Deployment
Build commands and CI pipeline info from ci_files_found. Omit if empty.

### Keeping AGENTS.md Up to Date
ALWAYS include this section verbatim at the end of every AGENTS.md, regardless
of the project:

```
## Keeping AGENTS.md Up to Date

This file is generated and maintained by the `agents-md-generator` MCP tool.
**Never edit it manually.** To regenerate after code changes, ask Claude Code:

> "Update the AGENTS.md for this project"

Claude will invoke the `generate_agents_md` tool automatically, perform an
incremental scan of changed files, and rewrite only the affected sections.
To force a full rescan from scratch: "Regenerate the AGENTS.md from scratch".
```

## QUALITY BAR

- Conventions section must be actionable: an agent reading it should know
  exactly what file to create, where, and what to export — with zero guessing.
- Every command must be exact and runnable. No placeholders like <your-value>.
- Omit any section with zero real data from the payload.
- Zero file enumeration tables or lists anywhere in the document.
""".strip()


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
                # Filter by impact threshold
                def impact_entry(sym, ctype):
                    imp = classify_impact(sym, ctype)
                    return imp, sym

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
                if _is_test_file(change.path):
                    test_analysis_payload.append(entry)
                else:
                    full_analysis_payload.append(entry)

        elif change.status == "new":
            entry = _format_full(change.path, "new", analysis)
            if _is_test_file(change.path):
                test_analysis_payload.append(entry)
            else:
                full_analysis_payload.append(entry)

    # Collapse test files into per-directory summaries
    if test_analysis_payload:
        full_analysis_payload.extend(_summarize_test_files(test_analysis_payload))

    env_vars = _detect_env_vars(root, config)
    entry_points = _detect_entry_points(root, config)

    return {
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


_TEST_PATH_MARKERS = ("/tests/", "/test/", "/__tests__/", "/spec/", "/specs/")
_TEST_NAME_PATTERNS = ("test_", "_test.", ".spec.", ".test.")


def _is_test_file(path: str) -> bool:
    name = Path(path).name
    padded = f"/{path}/"
    return (
        name.startswith("test_")
        or any(name.endswith(p) for p in ("_test.py", "_test.go", ".spec.ts", ".spec.js", ".test.ts", ".test.js"))
        or any(marker in padded for marker in _TEST_PATH_MARKERS)
    )


def _slim_symbol(sym) -> dict:
    """Return only the fields Claude needs — no line numbers, no parent."""
    return {
        "name": sym.name,
        "kind": sym.kind,
        "visibility": sym.visibility,
        "signature": sym.signature,
        "decorators": sym.decorators,
    }


def _is_public(sym) -> bool:
    """Exclude private symbols — not useful for AGENTS.md."""
    if sym.visibility in ("private", "protected"):
        return False
    if sym.name.startswith("_"):
        return False
    return True


def _format_full(path: str, _status: str, analysis: FileAnalysis) -> dict:
    """Format a file for full_analysis — public symbols only."""
    symbols_out = []
    for sym in analysis.symbols:
        if not _is_public(sym):
            continue
        if sym.kind == "class":
            symbols_out.append({
                "name": sym.name,
                "kind": sym.kind,
                "signature": sym.signature,
                "decorators": sym.decorators,
                "methods": [
                    s.name for s in analysis.symbols
                    if s.parent == sym.name and s.kind == "method" and _is_public(s)
                ],
            })
        elif sym.parent is None:
            symbols_out.append({
                "name": sym.name,
                "kind": sym.kind,
                "signature": sym.signature,
                "decorators": sym.decorators,
            })

    return {
        "file": path,
        "language": analysis.language,
        "symbols": symbols_out,
    }


def _summarize_test_files(entries: list[dict]) -> list[dict]:
    """Replace individual test file entries with one summary per directory."""
    by_dir: dict[str, list[dict]] = {}
    for e in entries:
        d = str(Path(e["file"]).parent)
        by_dir.setdefault(d, []).append(e)

    summaries = []
    for d, files in sorted(by_dir.items()):
        total_fns = sum(len(f.get("symbols", [])) for f in files)
        languages = list({f["language"] for f in files})
        summaries.append({
            "directory": d + "/",
            "kind": "test_directory_summary",
            "file_count": len(files),
            "test_function_count": total_fns,
            "languages": languages,
            "files": [f["file"] for f in files],
        })
    return summaries
