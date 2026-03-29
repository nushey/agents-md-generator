"""Utilities for filtering, formatting, and classifying code symbols."""

from __future__ import annotations

from pathlib import Path

from .config import SizeProfile
from .models import FileAnalysis

# ── Impact threshold ──────────────────────────────────────────────────────────

_THRESHOLD_ORDER = {"high": 0, "medium": 1, "low": 2}


def _passes_threshold(impact: str, threshold: str) -> bool:
    return _THRESHOLD_ORDER.get(impact, 2) <= _THRESHOLD_ORDER.get(threshold, 1)


# ── Symbol visibility ─────────────────────────────────────────────────────────

def _is_public(sym) -> bool:
    """Exclude private symbols — not useful for AGENTS.md."""
    if sym.visibility in ("private", "protected"):
        return False
    if sym.name.startswith("_"):
        return False
    return True


# ── Test file detection ───────────────────────────────────────────────────────

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


# ── Symbol formatting ─────────────────────────────────────────────────────────

def _slim_symbol(sym) -> dict:
    """Return only the fields the AI needs — no line numbers, no parent."""
    out = {
        "name": sym.name,
        "kind": sym.kind,
        "visibility": sym.visibility,
        "signature": sym.signature,
    }
    if sym.decorators:
        out["decorators"] = sym.decorators
    return out


_MINIFIED_SHORT_NAME_THRESHOLD = 0.30  # >30% single/double-char names → minified

# ── Generated file detection ─────────────────────────────────────────────────

_GENERATED_PATH_MARKERS = (
    "Connected Services/", "Service References/", "/Generated/",
    "/obj/", "/auto_generated/", "/auto-generated/",
)
_GENERATED_SUFFIXES = (
    ".Designer.cs", ".g.cs", ".g.i.cs", "Reference.cs",
    ".generated.cs", ".designer.cs",
)


def _is_generated(path: str, analysis: FileAnalysis) -> bool:
    """Return True if the file is auto-generated code with no architectural value."""
    # Path-based detection
    if any(marker in path for marker in _GENERATED_PATH_MARKERS):
        return True
    if any(path.endswith(suffix) for suffix in _GENERATED_SUFFIXES):
        return True
    # Decorator-based detection: first few symbols have GeneratedCode attributes
    for sym in analysis.symbols[:3]:
        if sym.decorators:
            for dec in sym.decorators:
                if "GeneratedCode" in dec or "System.CodeDom.Compiler" in dec:
                    return True
    return False


# ── Noise decorator filtering ────────────────────────────────────────────────

_NOISE_DECORATOR_PREFIXES = (
    "System.Runtime.Serialization.",
    "System.CodeDom.Compiler.",
    "System.SerializableAttribute",
    "System.Diagnostics.DebuggerStepThroughAttribute",
    "System.Diagnostics.DebuggerNonUserCode",
    "KnownTypeAttribute",
    "DataContractAttribute",
    "DataMemberAttribute",
    "System.ComponentModel.EditorBrowsable",
)


def _filter_decorators(decorators: list[str]) -> list[str]:
    """Strip noise decorators that add no architectural signal."""
    return [
        d for d in decorators
        if not any(d.startswith(prefix) for prefix in _NOISE_DECORATOR_PREFIXES)
    ]


def _is_minified(analysis: FileAnalysis) -> bool:
    """Return True if the file looks like minified or bundled JS/TS.

    Heuristic: if more than 30% of top-level public symbol names are
    1–2 characters long, the file was likely minified or auto-generated.
    Only applied to JS/TS files where this pattern is meaningful.
    """
    if analysis.language not in ("javascript", "typescript"):
        return False
    public_syms = [s for s in analysis.symbols if _is_public(s) and s.parent is None]
    if len(public_syms) < 5:
        return False
    short = sum(1 for s in public_syms if len(s.name) <= 2)
    return (short / len(public_syms)) > _MINIFIED_SHORT_NAME_THRESHOLD


def _is_low_entropy(analysis: FileAnalysis) -> bool:
    """Return True if the file contains primarily low-logic symbols (DTOs/Entities).

    Heuristic: 100% of symbols are classes or structs with zero public methods.
    Only applied if there are >= 3 such containers, to avoid minifying 
    small logic files that might just be starting out.
    """
    public_syms = [s for s in analysis.symbols if _is_public(s)]
    if not public_syms:
        return False

    containers = [s for s in public_syms if s.kind in _MEMBER_CONTAINER_KINDS]
    if not containers:
        return False

    for container in containers:
        methods = [
            s for s in public_syms
            if s.parent == container.name and s.kind == "method"
        ]
        if methods:
            return False

    return True


_MEMBER_CONTAINER_KINDS = frozenset({"class", "interface", "struct"})


_PRIMITIVE_TYPES = frozenset({
    "string", "int", "long", "float", "double", "bool", "boolean",
    "byte", "char", "decimal", "short", "uint", "ulong", "ushort",
    "object", "void", "number", "any", "str", "None",
})


def _parse_constructor_deps(sig: str) -> list[str]:
    """Extract dependency type names from a constructor signature.

    "(IRepo repo, ILogger<Worker> logger, string name)" → ["IRepo", "ILogger<Worker>"]

    Skips primitive types (string, int, bool...) — those are config values, not DI deps.
    """
    open_p = sig.find("(")
    close_p = sig.rfind(")")
    if open_p == -1 or close_p == -1:
        return []
    inner = sig[open_p + 1:close_p].strip()
    if not inner:
        return []
    deps = []
    for param in inner.split(","):
        param = param.strip()
        if not param:
            continue
        # "Type name" or "Type<Generic> name" — take everything except the last token
        parts = param.rsplit(None, 1)
        if len(parts) == 2:
            type_name = parts[0].strip()
        else:
            type_name = param.strip()
        # Strip primitive types
        base_type = type_name.split("<")[0].split("[")[0].strip()
        if base_type.lower() not in _PRIMITIVE_TYPES:
            deps.append(type_name)
    return deps


def _format_full(path: str, _status: str, analysis: FileAnalysis, profile: SizeProfile) -> dict | None:
    """Format a file for full_analysis — public symbols only.

    Returns None if the file has no public symbols worth including,
    or if the file is detected as minified/bundled.

    Caps (controlled by *profile*):
    - Methods per class/interface/struct: profile.max_methods_per_symbol
    - Symbols per file: profile.max_symbols_per_file
    total_methods / total_symbols are added when truncated.
    """
    if _is_minified(analysis):
        return None

    if _is_generated(path, analysis):
        return None

    if _is_low_entropy(analysis):
        # Minify DTO-only files
        containers = [s for s in analysis.symbols if _is_public(s) and s.kind in _MEMBER_CONTAINER_KINDS]
        if not containers:
            return None
        return {
            "file": path,
            "language": analysis.language,
            "kind": "dto_container",
            "is_dto": True,
            "symbols_count": len(containers),
        }

    symbols_out = []
    for sym in analysis.symbols:
        if not _is_public(sym):
            continue
        if sym.kind in _MEMBER_CONTAINER_KINDS:
            entry: dict = {
                "name": sym.name,
                "kind": sym.kind,
                "signature": sym.signature,
            }

            # Implements — interface→impl relationships
            if sym.implements:
                entry["implements"] = sym.implements

            # Constructor deps — first-class, parsed as type list
            constructor = next(
                (s for s in analysis.symbols
                 if s.parent == sym.name and s.kind == "constructor" and _is_public(s)),
                None,
            )
            if constructor and constructor.signature:
                deps = _parse_constructor_deps(constructor.signature)
                if deps:
                    entry["constructor_deps"] = deps

            # Methods — full signatures, capped
            all_methods = [
                s.signature or s.name
                for s in analysis.symbols
                if s.parent == sym.name and s.kind == "method" and _is_public(s)
            ]
            entry["methods"] = all_methods[:profile.max_methods_per_symbol]
            if len(all_methods) > profile.max_methods_per_symbol:
                entry["total_methods"] = len(all_methods)

            # DTO detection — classes/structs with no methods get is_dto tag, no properties
            if sym.kind in ("class", "struct") and not all_methods:
                entry["is_dto"] = True

            if sym.decorators:
                filtered = _filter_decorators(sym.decorators)
                if filtered:
                    entry["decorators"] = filtered
            symbols_out.append(entry)

        elif sym.parent is None:
            entry = {
                "name": sym.name,
                "kind": sym.kind,
                "signature": sym.signature,
            }
            if sym.decorators:
                filtered = _filter_decorators(sym.decorators)
                if filtered:
                    entry["decorators"] = filtered
            symbols_out.append(entry)

    if not symbols_out:
        return None

    # Strip trivial entries: all symbols have no methods, no deps, no implements,
    # no decorators — these files contribute no architectural signal.
    has_signal = any(
        s.get("methods")
        or s.get("constructor_deps")
        or s.get("decorators")
        or (s.get("implements") and s["implements"] != ["object"])
        for s in symbols_out
    )
    if not has_signal:
        return None

    total = len(symbols_out)
    result: dict = {
        "file": path,
        "language": analysis.language,
        "symbols": symbols_out[:profile.max_symbols_per_file],
    }
    if total > profile.max_symbols_per_file:
        result["total_symbols"] = total
    return result


def _summarize_test_files(entries: list[dict]) -> list[dict]:
    """Replace individual test file entries with one summary per directory."""
    by_dir: dict[str, list[dict]] = {}
    for e in entries:
        d = Path(e["file"]).parent.as_posix()
        by_dir.setdefault(d, []).append(e)

    summaries = []
    for d, files in sorted(by_dir.items()):
        total_fns = sum(len(f.get("symbols", [])) for f in files)
        languages = list({f["language"] for f in files if "language" in f})
        summaries.append({
            "directory": d + "/",
            "kind": "test_directory_summary",
            "file_count": len(files),
            "test_function_count": total_fns,
            "languages": languages,
            "files": [f["file"] for f in files],
        })
    return summaries
