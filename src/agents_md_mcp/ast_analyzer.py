"""ASTAnalyzer: orchestrates tree-sitter parsing for all supported languages."""

import logging
from pathlib import Path

from .cache import CacheData
from .config import ProjectConfig
from .languages.base import LanguageAnalyzer
from .languages.csharp import CSharpAnalyzer
from .languages.go import GoAnalyzer
from .languages.python import PythonAnalyzer
from .languages.typescript import JavaScriptAnalyzer, TypeScriptAnalyzer
from .models import AnalysisDiff, FileAnalysis, FileChange, SymbolInfo

logger = logging.getLogger(__name__)

# Lazy-loaded analyzers — instantiated once per language
_ANALYZERS: dict[str, LanguageAnalyzer] = {}


def _get_analyzer(language_key: str) -> LanguageAnalyzer | None:
    if language_key not in _ANALYZERS:
        try:
            _ANALYZERS[language_key] = build_analyzer(language_key)
        except Exception as exc:
            logger.warning("Cannot load analyzer for '%s': %s", language_key, exc)
            return None
    return _ANALYZERS[language_key]


def build_analyzer(language_key: str) -> LanguageAnalyzer:
    if language_key == "python":
        return PythonAnalyzer()
    if language_key == "c_sharp":
        return CSharpAnalyzer()
    if language_key in ("typescript", "tsx"):
        return TypeScriptAnalyzer(language_key)
    if language_key == "javascript":
        return JavaScriptAnalyzer()
    if language_key == "go":
        return GoAnalyzer()
    raise ValueError(f"No analyzer for language: {language_key}")


# ── Public API ────────────────────────────────────────────────────────────────

def analyze_changes(
    project_path: str | Path,
    changes: list[FileChange],
    config: ProjectConfig,
    cache: CacheData | None,
) -> dict[str, FileAnalysis]:
    """
    Parse changed files and return a mapping of path → FileAnalysis.

    - "new": full parse
    - "modified": full parse (diff computed separately via diff_analysis)
    - "deleted": skip (caller handles removal from cache)
    """
    root = Path(project_path).resolve()
    results: dict[str, FileAnalysis] = {}

    for change in changes:
        if change.status == "deleted":
            continue

        abs_path = root / change.path
        ext = Path(change.path).suffix
        lang_key = config.language_for_extension(ext)

        if lang_key is None:
            logger.debug("Skipping unsupported extension: %s", change.path)
            continue

        analyzer = _get_analyzer(lang_key)
        if analyzer is None:
            continue

        try:
            source = abs_path.read_bytes()
        except OSError as exc:
            logger.warning("Cannot read %s: %s", change.path, exc)
            continue

        try:
            analysis = analyzer.analyze(Path(change.path), source)
            results[change.path] = analysis
        except Exception as exc:
            logger.warning("AST parse failed for %s: %s", change.path, exc)

    return results


def diff_analysis(old_symbols: list, new_symbols: list) -> AnalysisDiff:
    """Compare two symbol lists and return only what changed.

    Accepts any objects with name/signature/kind/visibility/decorators attributes
    (both SymbolInfo from a fresh analysis and CachedSymbol from cache).
    """
    old_map = {s.name: s for s in old_symbols}
    new_map = {s.name: s for s in new_symbols}

    added = [s for name, s in new_map.items() if name not in old_map]
    removed = [s for name, s in old_map.items() if name not in new_map]
    modified = [
        new_map[name]
        for name in old_map
        if name in new_map
        and old_map[name].signature != new_map[name].signature
    ]

    return AnalysisDiff(added=added, removed=removed, modified=modified)


_HIGH_IMPACT_DECORATORS = {
    # HTTP endpoints
    "HttpGet", "HttpPost", "HttpPut", "HttpDelete", "HttpPatch",
    "Route", "ApiController",
    # Python web frameworks
    "app.route", "router.get", "router.post", "router.put", "router.delete",
    "api_view", "action",
    # NestJS / Angular
    "Controller", "Get", "Post", "Put", "Delete", "Patch",
    "Injectable", "Component", "NgModule",
}


def classify_impact(symbol: SymbolInfo, change_type: str) -> str:
    """Classify a symbol change as 'high', 'medium', or 'low'."""
    decorator_set = set(symbol.decorators)

    # HIGH: HTTP endpoints (any language)
    if decorator_set & _HIGH_IMPACT_DECORATORS:
        return "high"

    # HIGH: Adding/removing a class or interface
    if change_type in ("added", "removed") and symbol.kind in ("class", "interface", "struct"):
        return "high"

    # HIGH: Removing a public method
    if change_type == "removed" and symbol.kind == "method" and symbol.visibility == "public":
        return "high"

    # MEDIUM: Changing a public method's signature
    if change_type == "modified" and symbol.visibility == "public":
        return "medium"

    # MEDIUM: Adding a new public function or method
    if change_type == "added" and symbol.kind in ("function", "method") and symbol.visibility == "public":
        return "medium"

    return "low"
