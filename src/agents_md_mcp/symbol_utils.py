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
    return {
        "name": sym.name,
        "kind": sym.kind,
        "visibility": sym.visibility,
        "signature": sym.signature,
        "decorators": sym.decorators,
    }


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
