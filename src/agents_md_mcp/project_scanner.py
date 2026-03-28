"""Filesystem scanners: project structure, env vars, and entry points."""

import re
from pathlib import Path

from .change_detector import _is_excluded
from .config import EXTENSION_TO_LANGUAGE, ProjectConfig
from .gitignore import is_gitignored, load_gitignore_spec
from .models import FileAnalysis
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


def _scan_project_structure(root: Path, config: ProjectConfig) -> dict:
    """Scan directories and root files (no AST, pure filesystem)."""
    gitignore_spec = load_gitignore_spec(root)

    root_files = [
        f.name for f in root.iterdir()
        if f.is_file() and not f.name.startswith(".")
    ][:30]

    # Directory summary: file count + languages (capped at depth 3)
    _MAX_DIR_DEPTH = 2
    dir_summary: dict[str, dict] = {}
    try:
        for item in root.rglob("*"):
            if not item.is_file():
                continue
            rel = rel_posix(item, root)
            if is_gitignored(rel, gitignore_spec):
                continue
            if _is_excluded(rel, config):
                continue
            parent_rel = rel_posix(item.parent, root)
            if parent_rel == ".":
                continue
            # Cap depth: "a/b/c/d" → "a/b/c" when depth > _MAX_DIR_DEPTH
            parts = parent_rel.split("/")
            capped = "/".join(parts[:_MAX_DIR_DEPTH])
            if capped not in dir_summary:
                dir_summary[capped] = {"file_count": 0, "languages": set()}
            dir_summary[capped]["file_count"] += 1
            lang = EXTENSION_TO_LANGUAGE.get(item.suffix.lower())
            if lang:
                dir_summary[capped]["languages"].add(lang)
    except OSError:
        pass

    dirs_out: dict[str, dict] = {}
    for d, info in dir_summary.items():
        dirs_out[d + "/"] = {
            "file_count": info["file_count"],
            "languages": ", ".join(sorted(info["languages"])) or None,
        }

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


def _detect_env_vars(root: Path, config: ProjectConfig) -> list[str]:
    """Scan source files and .env examples for environment variable names."""
    gitignore_spec = load_gitignore_spec(root)
    found: set[str] = set()

    # Scan source files for process.env.X / os.environ / etc.
    try:
        for item in root.rglob("*"):
            if not item.is_file():
                continue
            rel = rel_posix(item, root)
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
            rel = rel_posix(item, root)
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
            parent = rel_posix(item.parent, root)
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


# ── Wiring detection ─────────────────────────────────────────────────────────

# HTTP method decorators per language
_CS_HTTP_METHODS = {"HttpGet": "GET", "HttpPost": "POST", "HttpPut": "PUT", "HttpDelete": "DELETE", "HttpPatch": "PATCH"}
_TS_HTTP_METHODS = {"Get": "GET", "Post": "POST", "Put": "PUT", "Delete": "DELETE", "Patch": "PATCH"}
_PY_HTTP_METHODS = {"get": "GET", "post": "POST", "put": "PUT", "delete": "DELETE", "patch": "PATCH", "route": "ANY"}

_ROUTE_ARG_RE = re.compile(r"""\(\s*['"](.+?)['"]\s*\)""")

_MAX_ROUTE_CONTROLLERS = 10
_MAX_ROUTES_PER_CONTROLLER = 5
_MAX_GO_HANDLERS = 5


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


def _detect_wiring(analyses: dict[str, FileAnalysis]) -> dict:
    """Post-process parsed FileAnalysis objects to extract wiring information.

    Detects route maps for all languages. Applies caps:
    - Max 10 controllers/files in route_map
    - Max 5 routes per controller (one of each HTTP method first, then fill)
    - Max 5 Go handlers per file
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
            entry["routes"] = _cap_routes(all_routes, _MAX_ROUTES_PER_CONTROLLER)
            if len(all_routes) > _MAX_ROUTES_PER_CONTROLLER:
                entry["total_routes"] = len(all_routes)
        if "handlers" in entry:
            all_handlers = entry["handlers"]
            entry["handlers"] = all_handlers[:_MAX_GO_HANDLERS]
            if len(all_handlers) > _MAX_GO_HANDLERS:
                entry["total_handlers"] = len(all_handlers)

    total_controllers = len(route_map)
    if total_controllers > _MAX_ROUTE_CONTROLLERS:
        route_map = route_map[:_MAX_ROUTE_CONTROLLERS]

    result: dict = {}
    if route_map:
        result["route_map"] = route_map
        if total_controllers > _MAX_ROUTE_CONTROLLERS:
            result["total_route_files"] = total_controllers
    return result


def _detect_csharp_routes(
    path: str, analysis: FileAnalysis, route_map: list[dict],
) -> None:
    """Detect ASP.NET controller routes from [Route], [HttpGet], etc. decorators."""
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
        for method_sym in analysis.symbols:
            if method_sym.parent != sym.name or method_sym.kind != "method":
                continue
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
        for method_sym in analysis.symbols:
            if method_sym.parent != sym.name or method_sym.kind != "method":
                continue
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
