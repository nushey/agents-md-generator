"""Tests for ast_analyzer.py and language analyzers."""

from pathlib import Path

import pytest

from agents_md_mcp.ast_analyzer import classify_impact, diff_analysis
from agents_md_mcp.languages.python import PythonAnalyzer
from agents_md_mcp.languages.csharp import CSharpAnalyzer
from agents_md_mcp.languages.typescript import TypeScriptAnalyzer, JavaScriptAnalyzer
from agents_md_mcp.languages.go import GoAnalyzer
from agents_md_mcp.models import FileAnalysis, SymbolInfo

FIXTURES = Path(__file__).parent / "fixtures"


def _names(analysis: FileAnalysis) -> set[str]:
    return {s.name for s in analysis.symbols}


def _by_name(analysis: FileAnalysis, name: str) -> SymbolInfo:
    return next(s for s in analysis.symbols if s.name == name)


# ── Python ────────────────────────────────────────────────────────────────────

def test_python_classes_and_methods() -> None:
    src = (FIXTURES / "sample.py").read_bytes()
    result = PythonAnalyzer().analyze(Path("sample.py"), src)

    assert "UserService" in _names(result)
    assert "get_user" in _names(result)
    assert "_internal_helper" in _names(result)
    assert "create_order" in _names(result)


def test_python_visibility() -> None:
    src = (FIXTURES / "sample.py").read_bytes()
    result = PythonAnalyzer().analyze(Path("sample.py"), src)

    assert _by_name(result, "UserService").visibility == "public"
    assert _by_name(result, "_validate").visibility == "protected"
    assert _by_name(result, "_internal_helper").visibility == "protected"


def test_python_method_has_parent() -> None:
    src = (FIXTURES / "sample.py").read_bytes()
    result = PythonAnalyzer().analyze(Path("sample.py"), src)

    get_user = _by_name(result, "get_user")
    assert get_user.parent == "UserService"
    assert get_user.kind == "method"


def test_python_top_level_function() -> None:
    src = (FIXTURES / "sample.py").read_bytes()
    result = PythonAnalyzer().analyze(Path("sample.py"), src)

    create_order = _by_name(result, "create_order")
    assert create_order.kind == "function"
    assert create_order.parent is None


def test_python_imports() -> None:
    src = (FIXTURES / "sample.py").read_bytes()
    result = PythonAnalyzer().analyze(Path("sample.py"), src)

    assert any("os" in imp for imp in result.imports)
    assert any("Optional" in imp for imp in result.imports)


# ── C# ────────────────────────────────────────────────────────────────────────

def test_csharp_classes_and_interface() -> None:
    src = (FIXTURES / "sample.cs").read_bytes()
    result = CSharpAnalyzer().analyze(Path("sample.cs"), src)

    assert "OrderService" in _names(result)
    assert "IRepository" in _names(result)


def test_csharp_methods() -> None:
    src = (FIXTURES / "sample.cs").read_bytes()
    result = CSharpAnalyzer().analyze(Path("sample.cs"), src)

    method_names = {s.name for s in result.symbols if s.kind == "method"}
    assert "GetOrder" in method_names
    assert "CancelOrder" in method_names


def test_csharp_imports() -> None:
    src = (FIXTURES / "sample.cs").read_bytes()
    result = CSharpAnalyzer().analyze(Path("sample.cs"), src)

    assert any("System" in imp for imp in result.imports)


# ── TypeScript ────────────────────────────────────────────────────────────────

def test_typescript_class_and_interface() -> None:
    src = (FIXTURES / "sample.ts").read_bytes()
    result = TypeScriptAnalyzer().analyze(Path("sample.ts"), src)

    assert "UserService" in _names(result)
    assert "User" in _names(result)


def test_typescript_exports() -> None:
    src = (FIXTURES / "sample.ts").read_bytes()
    result = TypeScriptAnalyzer().analyze(Path("sample.ts"), src)

    assert "UserService" in result.exports or "formatName" in result.exports


def test_typescript_imports() -> None:
    src = (FIXTURES / "sample.ts").read_bytes()
    result = TypeScriptAnalyzer().analyze(Path("sample.ts"), src)

    assert any("angular" in imp for imp in result.imports)


# ── Go ────────────────────────────────────────────────────────────────────────

def test_go_struct_and_functions() -> None:
    src = (FIXTURES / "sample.go").read_bytes()
    result = GoAnalyzer().analyze(Path("sample.go"), src)

    assert "OrderService" in _names(result)
    assert "NewOrderService" in _names(result)
    assert "HealthCheck" in _names(result)


def test_go_method_parent() -> None:
    src = (FIXTURES / "sample.go").read_bytes()
    result = GoAnalyzer().analyze(Path("sample.go"), src)

    get_order = _by_name(result, "GetOrder")
    assert get_order.kind == "method"
    assert get_order.parent == "OrderService"


def test_go_visibility() -> None:
    src = (FIXTURES / "sample.go").read_bytes()
    result = GoAnalyzer().analyze(Path("sample.go"), src)

    assert _by_name(result, "HealthCheck").visibility == "public"
    assert _by_name(result, "cancelOrder").visibility == "private"


def test_go_imports() -> None:
    src = (FIXTURES / "sample.go").read_bytes()
    result = GoAnalyzer().analyze(Path("sample.go"), src)

    assert any("fmt" in imp for imp in result.imports)


# ── diff_analysis ─────────────────────────────────────────────────────────────

def _make_symbol(name: str, sig: str = "sig") -> SymbolInfo:
    return SymbolInfo(name=name, kind="method", visibility="public", signature=sig)


def test_diff_added() -> None:
    old = FileAnalysis(path="f.py", language="python", symbols=[_make_symbol("foo")])
    new = FileAnalysis(path="f.py", language="python", symbols=[_make_symbol("foo"), _make_symbol("bar")])
    diff = diff_analysis(old, new)
    assert len(diff.added) == 1
    assert diff.added[0].name == "bar"
    assert diff.removed == []


def test_diff_removed() -> None:
    old = FileAnalysis(path="f.py", language="python", symbols=[_make_symbol("foo"), _make_symbol("bar")])
    new = FileAnalysis(path="f.py", language="python", symbols=[_make_symbol("foo")])
    diff = diff_analysis(old, new)
    assert len(diff.removed) == 1
    assert diff.removed[0].name == "bar"


def test_diff_modified_signature() -> None:
    old = FileAnalysis(path="f.py", language="python", symbols=[_make_symbol("foo", "def foo()")])
    new = FileAnalysis(path="f.py", language="python", symbols=[_make_symbol("foo", "def foo(x: int)")])
    diff = diff_analysis(old, new)
    assert len(diff.modified) == 1
    assert diff.modified[0].signature == "def foo(x: int)"


def test_diff_no_changes() -> None:
    sym = _make_symbol("foo", "def foo()")
    old = FileAnalysis(path="f.py", language="python", symbols=[sym])
    new = FileAnalysis(path="f.py", language="python", symbols=[_make_symbol("foo", "def foo()")])
    diff = diff_analysis(old, new)
    assert diff.added == []
    assert diff.removed == []
    assert diff.modified == []


# ── classify_impact ───────────────────────────────────────────────────────────

def test_impact_endpoint_decorator_is_high() -> None:
    sym = SymbolInfo(name="GetOrder", kind="method", visibility="public",
                     signature="...", decorators=["HttpGet"])
    assert classify_impact(sym, "added") == "high"


def test_impact_removing_public_class_is_high() -> None:
    sym = SymbolInfo(name="OrderService", kind="class", visibility="public", signature="...")
    assert classify_impact(sym, "removed") == "high"


def test_impact_modifying_public_method_is_medium() -> None:
    sym = SymbolInfo(name="GetUser", kind="method", visibility="public", signature="...")
    assert classify_impact(sym, "modified") == "medium"


def test_impact_private_change_is_low() -> None:
    sym = SymbolInfo(name="_validate", kind="method", visibility="private", signature="...")
    assert classify_impact(sym, "modified") == "low"
