"""Utilities for filtering, formatting, and classifying code symbols."""

from pathlib import Path

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


def _format_full(path: str, _status: str, analysis: FileAnalysis) -> dict | None:
    """Format a file for full_analysis — public symbols only.

    Returns None if the file has no public symbols worth including,
    or if the file is detected as minified/bundled.
    """
    if _is_minified(analysis):
        return None

    symbols_out = []
    for sym in analysis.symbols:
        if not _is_public(sym):
            continue
        if sym.kind == "class":
            entry: dict = {
                "name": sym.name,
                "kind": sym.kind,
                "signature": sym.signature,
                "methods": [
                    s.name for s in analysis.symbols
                    if s.parent == sym.name and s.kind == "method" and _is_public(s)
                ],
            }
            if sym.decorators:
                entry["decorators"] = sym.decorators
            symbols_out.append(entry)
        elif sym.parent is None:
            entry = {
                "name": sym.name,
                "kind": sym.kind,
                "signature": sym.signature,
            }
            if sym.decorators:
                entry["decorators"] = sym.decorators
            symbols_out.append(entry)

    if not symbols_out:
        return None

    return {
        "file": path,
        "language": analysis.language,
        "symbols": symbols_out,
    }


def _summarize_test_files(entries: list[dict]) -> list[dict]:
    """Replace individual test file entries with one summary per directory."""
    by_dir: dict[str, list[dict]] = {}
    for e in entries:
        d = Path(e["file"]).parent.as_posix()
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
