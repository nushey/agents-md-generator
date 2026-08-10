"""Filesystem scanners: project structure, env vars, and entry points."""

import re
from pathlib import Path

from .change_detector import (
    _NOT_A_REPO_MSG,
    NotAGitRepositoryError,
    _is_excluded,
    git_list_all_files,
)
from .config import EXTENSION_TO_LANGUAGE, ProjectConfig, SizeProfile
from .models import FileAnalysis, FileChange
from .path_utils import rel_posix
from .symbol_utils import _is_test_file

# ── Project structure ─────────────────────────────────────────────────────────

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

_BOILERPLATE_DIR_NAMES = {
    "Migrations", "Properties", "bin", "obj", "dist", "out", "target", "vendor",
    "node_modules", ".idea", ".vscode", ".pytest_cache", "__pycache__"
}


def _walk_files(root: Path, config: ProjectConfig) -> list[tuple[Path, str]]:
    """List project files via git instead of walking the filesystem.

    Shared by `_scan_project_structure` and `_detect_entry_points` so a single
    `build_payload` lists files once. Returns (absolute_path, relative_posix_path)
    pairs, sorted for deterministic output. Git already honors .gitignore, so no
    pathspec matching is needed; config excludes still apply (vendored trees can
    be committed).
    """
    rels = git_list_all_files(root)
    if rels is None:
        raise NotAGitRepositoryError(f"'{root}' {_NOT_A_REPO_MSG}")
    files: list[tuple[Path, str]] = []
    for rel in sorted(rels):
        if _is_excluded(rel, config):
            continue
        item = root / rel
        # ls-files also reports worktree-deleted entries; skip anything unreadable
        if not item.is_file():
            continue
        files.append((item, rel))
    return files


def _scan_project_structure(
    root: Path, config: ProjectConfig, files: list[tuple[Path, str]] | None = None,
) -> dict:
    """Scan directories and root files (no AST, pure filesystem).

    *files* is the shared single-walk result from `_walk_files`. When omitted
    (e.g. in isolated tests) the walk is performed internally.
    """
    if files is None:
        files = _walk_files(root, config)

    root_files = [
        f.name for f in root.iterdir()
        if f.is_file() and not f.name.startswith(".")
    ][:30]

    max_dir_depth = config.profile.max_dir_depth
    dir_summary: dict[str, dict] = {}
    for item, _rel in files:
        parent_rel = rel_posix(item.parent, root)
        if parent_rel == ".":
            continue
        # Cap depth: "a/b/c/d" → "a/b/c" when depth > max_dir_depth
        parts = parent_rel.split("/")
        capped = "/".join(parts[:max_dir_depth])
        if capped not in dir_summary:
            dir_summary[capped] = {"file_count": 0, "languages": set()}
        dir_summary[capped]["file_count"] += 1
        lang = EXTENSION_TO_LANGUAGE.get(item.suffix.lower())
        if lang:
            dir_summary[capped]["languages"].add(lang)

    dirs_out: dict[str, dict] = {}
    for d, info in dir_summary.items():
        rel_path = d + "/"
        entry = {
            "file_count": info["file_count"],
            "languages": ", ".join(sorted(info["languages"])) or None,
        }
        if any(part in _BOILERPLATE_DIR_NAMES for part in d.split("/")):
            entry["kind"] = "boilerplate"
        dirs_out[rel_path] = entry

    # Config files present at root
    config_found = []
    for pattern in _CONFIG_FILES:
        matches = list(root.glob(pattern))
        config_found.extend(rel_posix(m, root) for m in matches)

    # CI files
    ci_found = []
    for pattern in _CI_PATTERNS:
        matches = list(root.glob(pattern))
        ci_found.extend(rel_posix(m, root) for m in matches)

    # Test directories
    test_dirs = []
    for pattern in _TEST_DIR_PATTERNS:
        for d in root.glob(pattern):
            if d.is_dir():
                test_dirs.append(rel_posix(d, root) + "/")
    # Also *.Tests style (case insensitive check)
    for d in root.glob("*"):
        if d.is_dir() and any(
            d.name.lower().endswith(suf)
            for suf in (".tests", ".test", ".specs", ".spec")
        ):
            rel = rel_posix(d, root) + "/"
            if rel not in test_dirs:
                test_dirs.append(rel)

    # Top-level projects: directories with no nested path separator.
    # e.g. "Zureo.Common/" is top-level; "Zureo.Common/Entities/" is not.
    top_level_dirs = {
        k: v for k, v in dirs_out.items()
        if "/" not in k.rstrip("/")
    }

    return {
        "root_files": root_files,
        "top_level_dirs": top_level_dirs,
        "directories": dirs_out,
        "config_files_found": list(dict.fromkeys(config_found)),
        "ci_files_found": list(dict.fromkeys(ci_found)),
        "test_directories": list(dict.fromkeys(test_dirs)),
    }


# ── Environment variable detection ────────────────────────────────────────────

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

# Literal anchors per language: the regex can only match if one of these
# substrings appears, so files without them skip the regex entirely. Rust needs
# "var(" as well — its `var\s*\(` branch contains no "env" literal.
_ENV_GUARDS: dict[str, tuple[str, ...]] = {
    "javascript": ("env",),
    "typescript": ("env",),
    "python":     ("environ", "getenv"),
    "go":         ("Getenv",),
    "ruby":       ("ENV",),
    "rust":       ("env", "var"),
}


def _scan_file_env_vars(item: Path, lang: str, config: ProjectConfig) -> set[str]:
    """Extract env var names referenced in a single source file."""
    pattern = _ENV_PATTERNS.get(lang)
    if pattern is None:
        return set()
    found: set[str] = set()
    try:
        if item.stat().st_size > config.max_file_size_bytes:
            return set()
        content = item.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return set()
    guards = _ENV_GUARDS.get(lang)
    if guards and not any(g in content for g in guards):
        return set()
    for match in pattern.finditer(content):
        # rust pattern has two groups; take whichever matched
        var = next((g for g in match.groups() if g), None) if match.lastindex and match.lastindex > 1 else match.group(1)
        if var:
            found.add(var)
    return found


def detect_env_vars_for_changes(
    root: Path, config: ProjectConfig, changes: list[FileChange],
) -> dict[str, list[str]]:
    """Scan ONLY changed files for env var references — path → sorted var names.

    Unchanged files contribute their cached env_vars instead (merged by the
    caller), so incremental scans never re-read the whole codebase.
    """
    env_map: dict[str, list[str]] = {}
    for change in changes:
        if change.status == "deleted":
            continue
        lang = EXTENSION_TO_LANGUAGE.get(Path(change.path).suffix.lower())
        if lang is None:
            continue
        found = _scan_file_env_vars(root / change.path, lang, config)
        if found:
            env_map[change.path] = sorted(found)
    return env_map


def detect_root_env_vars(root: Path) -> set[str]:
    """Scan .env example files at root — most reliable source of truth."""
    found: set[str] = set()
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
    return found


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


def _detect_entry_points(
    root: Path, config: ProjectConfig, files: list[tuple[Path, str]] | None = None,
) -> list[dict]:
    """Detect bootstrap / entry-point files (index, main, app, server, …)."""
    if files is None:
        files = _walk_files(root, config)
    entries = []
    seen_dirs: set[str] = set()

    for item, rel in files:
        if not config.is_extension_supported(item.suffix.lower()):
            continue
        if _is_test_file(rel):
            continue
        stem = item.stem.lower()
        if stem not in _ENTRY_STEMS:
            continue
        # One entry per directory — avoid index.js + index.ts duplicates
        parent = rel_posix(item.parent, root)
        dir_key = f"{parent}/{stem}"
        if dir_key in seen_dirs:
            continue
        seen_dirs.add(dir_key)
        entries.append({
            "file": rel,
            "role": _infer_entry_role(rel, stem),
        })

    return sorted(entries, key=lambda e: e["file"])


# ── Wiring detection ─────────────────────────────────────────────────────────

# HTTP method decorators per language
_CS_HTTP_METHODS = {"HttpGet": "GET", "HttpPost": "POST", "HttpPut": "PUT", "HttpDelete": "DELETE", "HttpPatch": "PATCH"}
_TS_HTTP_METHODS = {"Get": "GET", "Post": "POST", "Put": "PUT", "Delete": "DELETE", "Patch": "PATCH"}
_PY_HTTP_METHODS = {"get": "GET", "post": "POST", "put": "PUT", "delete": "DELETE", "patch": "PATCH", "route": "ANY"}

_ROUTE_ARG_RE = re.compile(r"""\(\s*['"](.+?)['"]\s*\)""")

def _extract_route_arg(decorator_text: str) -> str | None:
    """Extract the route path from a decorator string like Controller('/api/users')."""
    m = _ROUTE_ARG_RE.search(decorator_text)
    return m.group(1) if m else None


def _cap_routes(routes: list[dict], cap: int) -> list[dict]:
    """Select up to `cap` routes, prioritising one of each HTTP method first.

    Strategy: pick one representative per unique HTTP method, then fill remaining
    slots from whichever method has extras — gives a complete picture of the
    controller's surface without dumping every endpoint.
    """
    if len(routes) <= cap:
        return routes

    by_method: dict[str, list[dict]] = {}
    for r in routes:
        by_method.setdefault(r.get("method", "ANY"), []).append(r)

    selected: list[dict] = []
    seen: set[int] = set()

    # Phase 1: one of each method type
    for method, method_routes in by_method.items():
        if len(selected) >= cap:
            break
        idx = id(method_routes[0])
        selected.append(method_routes[0])
        seen.add(idx)

    # Phase 2: fill remaining slots round-robin from methods with extras
    remaining = cap - len(selected)
    if remaining > 0:
        extras = [r for r in routes if id(r) not in seen]
        selected.extend(extras[:remaining])

    return selected


def _detect_wiring(analyses: dict[str, FileAnalysis], profile: SizeProfile) -> dict:
    """Post-process parsed FileAnalysis objects to extract wiring information.

    Detects route maps for all languages. Caps are controlled by *profile*.
    """
    route_map: list[dict] = []

    for path, analysis in analyses.items():
        lang = analysis.language

        if lang == "c_sharp":
            _detect_csharp_routes(path, analysis, route_map)
        elif lang in ("typescript", "tsx", "javascript"):
            _detect_ts_routes(path, analysis, route_map)
        elif lang == "python":
            _detect_python_routes(path, analysis, route_map)
        elif lang == "go":
            _detect_go_routes(path, analysis, route_map)

    # Apply caps
    for entry in route_map:
        if "routes" in entry:
            all_routes = entry["routes"]
            entry["routes"] = _cap_routes(all_routes, profile.max_routes_per_controller)
            if len(all_routes) > profile.max_routes_per_controller:
                entry["total_routes"] = len(all_routes)
        if "handlers" in entry:
            all_handlers = entry["handlers"]
            entry["handlers"] = all_handlers[:profile.max_go_handlers]
            if len(all_handlers) > profile.max_go_handlers:
                entry["total_handlers"] = len(all_handlers)

    total_controllers = len(route_map)
    if total_controllers > profile.max_route_controllers:
        route_map = route_map[:profile.max_route_controllers]

    result: dict = {}
    if route_map:
        result["route_map"] = route_map
        if total_controllers > profile.max_route_controllers:
            result["total_route_files"] = total_controllers
    return result


def _index_methods_by_parent(analysis: FileAnalysis) -> dict[str, list]:
    """Group method symbols by their parent class name in a single pass.

    Lets route detectors look up a class's methods in O(1) instead of
    re-scanning every symbol per class (was O(classes × symbols)).
    """
    by_parent: dict[str, list] = {}
    for s in analysis.symbols:
        if s.kind == "method" and s.parent:
            by_parent.setdefault(s.parent, []).append(s)
    return by_parent


def _detect_csharp_routes(
    path: str, analysis: FileAnalysis, route_map: list[dict],
) -> None:
    """Detect ASP.NET controller routes from [Route], [HttpGet], etc. decorators."""
    methods_by_parent = _index_methods_by_parent(analysis)
    # Find controller classes
    for sym in analysis.symbols:
        if sym.kind != "class":
            continue
        is_controller = any(
            d in ("ApiController", "Controller") or d.startswith("Route(")
            for d in sym.decorators
        )
        if not is_controller:
            continue

        # Extract class-level route prefix
        prefix = ""
        for d in sym.decorators:
            if d.startswith("Route("):
                arg = _extract_route_arg(d)
                if arg:
                    prefix = arg.rstrip("/")
                    break

        # Extract method-level routes
        routes: list[dict] = []
        for method_sym in methods_by_parent.get(sym.name, ()):
            for dec in method_sym.decorators:
                for cs_attr, http_method in _CS_HTTP_METHODS.items():
                    if dec == cs_attr or dec.startswith(f"{cs_attr}("):
                        method_path = _extract_route_arg(dec) or ""
                        full_path = f"{prefix}/{method_path}".strip("/") if prefix else method_path
                        routes.append({
                            "method": http_method,
                            "path": full_path,
                            "handler": method_sym.name,
                        })
                        break

        if routes:
            route_map.append({"file": path, "class": sym.name, "routes": routes})


def _detect_ts_routes(
    path: str, analysis: FileAnalysis, route_map: list[dict],
) -> None:
    """Detect NestJS-style @Controller/@Get/@Post routes."""
    methods_by_parent = _index_methods_by_parent(analysis)
    for sym in analysis.symbols:
        if sym.kind != "class":
            continue
        # Find @Controller('/path') decorator
        prefix = ""
        is_controller = False
        for d in sym.decorators:
            if d.startswith("Controller(") or d == "Controller()":
                is_controller = True
                arg = _extract_route_arg(d)
                if arg:
                    prefix = arg.strip("/")
                break

        if not is_controller:
            continue

        routes: list[dict] = []
        for method_sym in methods_by_parent.get(sym.name, ()):
            for dec in method_sym.decorators:
                for ts_dec, http_method in _TS_HTTP_METHODS.items():
                    if dec == f"{ts_dec}()" or dec.startswith(f"{ts_dec}("):
                        method_path = _extract_route_arg(dec) or ""
                        full_path = f"{prefix}/{method_path}".strip("/") if prefix else method_path
                        routes.append({
                            "method": http_method,
                            "path": full_path,
                            "handler": method_sym.name,
                        })
                        break

        if routes:
            route_map.append({"file": path, "class": sym.name, "routes": routes})


def _detect_python_routes(
    path: str, analysis: FileAnalysis, route_map: list[dict],
) -> None:
    """Detect FastAPI/Flask route decorators like @app.get('/path')."""
    routes: list[dict] = []
    for sym in analysis.symbols:
        if sym.kind not in ("method", "function"):
            continue
        for dec in sym.decorators:
            # Match patterns like app.get('/path'), router.post('/path'), app.route('/path')
            for py_suffix, http_method in _PY_HTTP_METHODS.items():
                if f".{py_suffix}(" in dec:
                    route_path = _extract_route_arg(dec) or ""
                    routes.append({
                        "method": http_method,
                        "path": route_path,
                        "handler": sym.name,
                    })
                    break

    if routes:
        route_map.append({"file": path, "routes": routes})


def _detect_go_routes(
    path: str, analysis: FileAnalysis, route_map: list[dict],
) -> None:
    """Detect Go HTTP route registrations from imports and handler function signatures.

    Looks for functions matching common handler signatures:
    - net/http: func(w http.ResponseWriter, r *http.Request)
    - gin: func(c *gin.Context)
    - echo: func(c echo.Context)
    """
    _GO_HANDLER_PATTERNS = [
        re.compile(r"http\.ResponseWriter"),
        re.compile(r"\*gin\.Context"),
        re.compile(r"echo\.Context"),
    ]

    handlers: list[dict] = []
    for sym in analysis.symbols:
        if sym.kind not in ("function", "method") or not sym.signature:
            continue
        for pattern in _GO_HANDLER_PATTERNS:
            if pattern.search(sym.signature):
                handlers.append({"handler": sym.name})
                break

    if handlers:
        route_map.append({"file": path, "handlers": handlers})
