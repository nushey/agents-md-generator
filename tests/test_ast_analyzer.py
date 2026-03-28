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


def test_csharp_constructor_has_own_kind() -> None:
    """Constructor must be kind='constructor', not 'method'."""
    src = (FIXTURES / "sample.cs").read_bytes()
    result = CSharpAnalyzer().analyze(Path("sample.cs"), src)

    constructors = [s for s in result.symbols if s.kind == "constructor"]
    assert any(s.name == "OrderService" for s in constructors)


def test_csharp_constructor_signature_has_no_void() -> None:
    """Constructor signature must not include a 'void' return type."""
    src = (FIXTURES / "sample.cs").read_bytes()
    result = CSharpAnalyzer().analyze(Path("sample.cs"), src)

    ctor = next(s for s in result.symbols if s.kind == "constructor" and s.name == "OrderService")
    assert "void" not in (ctor.signature or "")
    assert "IRepository" in (ctor.signature or "")


def test_csharp_interface_methods_are_public() -> None:
    """Interface methods without explicit modifier are implicitly public."""
    src = (FIXTURES / "sample.cs").read_bytes()
    result = CSharpAnalyzer().analyze(Path("sample.cs"), src)

    interface_methods = [
        s for s in result.symbols
        if s.parent == "IRepository" and s.kind == "method"
    ]
    assert len(interface_methods) == 2
    assert all(s.visibility == "public" for s in interface_methods)


def test_csharp_class_members_default_private() -> None:
    """Class members without modifier default to private."""
    src = (FIXTURES / "sample.cs").read_bytes()
    result = CSharpAnalyzer().analyze(Path("sample.cs"), src)

    validate = next(s for s in result.symbols if s.name == "Validate")
    assert validate.visibility == "private"


def test_csharp_class_implements_interfaces() -> None:
    """Class inheriting interfaces populates the implements field."""
    src = (FIXTURES / "sample.cs").read_bytes()
    result = CSharpAnalyzer().analyze(Path("sample.cs"), src)

    sql_repo = _by_name(result, "SqlRepository")
    assert sql_repo.kind == "class"
    assert "IRepository" in sql_repo.implements
    assert "IDisposable" in sql_repo.implements


def test_csharp_class_without_bases_has_empty_implements() -> None:
    """Class without base list has empty implements."""
    src = (FIXTURES / "sample.cs").read_bytes()
    result = CSharpAnalyzer().analyze(Path("sample.cs"), src)

    entity = _by_name(result, "SimpleEntity")
    assert entity.implements == []


def test_csharp_attributes_include_arguments() -> None:
    """Attributes with arguments include the full text: HttpGet("{id}")."""
    src = (FIXTURES / "sample.cs").read_bytes()
    result = CSharpAnalyzer().analyze(Path("sample.cs"), src)

    controller = _by_name(result, "OrderController")
    assert any("api/orders" in d for d in controller.decorators)

    get_method = next(s for s in result.symbols if s.name == "Get" and s.parent == "OrderController")
    assert any("{id}" in d for d in get_method.decorators)


def test_csharp_attributes_without_args_are_plain_names() -> None:
    """Attributes without arguments are just names: HttpPost (no parens)."""
    src = (FIXTURES / "sample.cs").read_bytes()
    result = CSharpAnalyzer().analyze(Path("sample.cs"), src)

    create = next(s for s in result.symbols if s.name == "Create" and s.parent == "OrderController")
    assert "HttpPost" in create.decorators


def test_csharp_toplevel_class_without_modifier_is_internal() -> None:
    """Top-level class without access modifier defaults to internal."""
    src = (FIXTURES / "sample.cs").read_bytes()
    result = CSharpAnalyzer().analyze(Path("sample.cs"), src)

    helper = next(s for s in result.symbols if s.name == "InternalHelper")
    assert helper.visibility == "internal"


def test_csharp_properties_extracted() -> None:
    """Public properties are extracted with correct visibility."""
    src = (FIXTURES / "sample.cs").read_bytes()
    result = CSharpAnalyzer().analyze(Path("sample.cs"), src)

    props = {s.name for s in result.symbols if s.kind == "property" and s.parent == "OrderService"}
    assert "Id" in props
    assert "Name" in props


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


def test_typescript_implements_extracted() -> None:
    """Class implementing interfaces populates the implements field."""
    src = (FIXTURES / "sample.ts").read_bytes()
    result = TypeScriptAnalyzer().analyze(Path("sample.ts"), src)

    user_svc = _by_name(result, "UserService")
    assert "IUserService" in user_svc.implements
    assert "Serializable" in user_svc.implements


def test_typescript_class_without_implements_has_empty_list() -> None:
    src = (FIXTURES / "sample.ts").read_bytes()
    result = TypeScriptAnalyzer().analyze(Path("sample.ts"), src)

    base_repo = _by_name(result, "BaseRepo")
    assert base_repo.implements == []


def test_typescript_extends_in_signature() -> None:
    """Class extending another includes extends in signature."""
    src = (FIXTURES / "sample.ts").read_bytes()
    result = TypeScriptAnalyzer().analyze(Path("sample.ts"), src)

    sql_repo = _by_name(result, "SqlRepo")
    assert "extends BaseRepo" in (sql_repo.signature or "")


def test_typescript_method_return_type_in_signature() -> None:
    """Method signatures include return type annotation."""
    src = (FIXTURES / "sample.ts").read_bytes()
    result = TypeScriptAnalyzer().analyze(Path("sample.ts"), src)

    get_user = _by_name(result, "getUser")
    assert "Promise<User>" in (get_user.signature or "")


def test_typescript_function_return_type_in_signature() -> None:
    """Top-level function signatures include return type."""
    src = (FIXTURES / "sample.ts").read_bytes()
    result = TypeScriptAnalyzer().analyze(Path("sample.ts"), src)

    fmt = _by_name(result, "formatName")
    assert "string" in (fmt.signature or "")


def test_typescript_decorators_include_arguments() -> None:
    """Decorators preserve full text including arguments."""
    src = (FIXTURES / "sample.ts").read_bytes()
    result = TypeScriptAnalyzer().analyze(Path("sample.ts"), src)

    user_svc = _by_name(result, "UserService")
    assert any("Injectable" in d for d in user_svc.decorators)

    controller = _by_name(result, "UserController")
    assert any("/api/users" in d for d in controller.decorators)

    find_one = next(s for s in result.symbols if s.name == "findOne" and s.parent == "UserController")
    assert any(":id" in d for d in find_one.decorators)


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
    old = [_make_symbol("foo")]
    new = [_make_symbol("foo"), _make_symbol("bar")]
    diff = diff_analysis(old, new)
    assert len(diff.added) == 1
    assert diff.added[0].name == "bar"
    assert diff.removed == []


def test_diff_removed() -> None:
    old = [_make_symbol("foo"), _make_symbol("bar")]
    new = [_make_symbol("foo")]
    diff = diff_analysis(old, new)
    assert len(diff.removed) == 1
    assert diff.removed[0].name == "bar"


def test_diff_modified_signature() -> None:
    old = [_make_symbol("foo", "def foo()")]
    new = [_make_symbol("foo", "def foo(x: int)")]
    diff = diff_analysis(old, new)
    assert len(diff.modified) == 1
    assert diff.modified[0].signature == "def foo(x: int)"


def test_diff_no_changes() -> None:
    old = [_make_symbol("foo", "def foo()")]
    new = [_make_symbol("foo", "def foo()")]
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


def test_impact_adding_public_method_is_medium() -> None:
    # C# has no standalone functions — all public members are methods.
    # Adding a public method must be classified as medium, not low.
    sym = SymbolInfo(name="ProcessOrder", kind="method", visibility="public", signature="...")
    assert classify_impact(sym, "added") == "medium"


def test_impact_removing_public_method_is_high() -> None:
    sym = SymbolInfo(name="ProcessOrder", kind="method", visibility="public", signature="...")
    assert classify_impact(sym, "removed") == "high"


def test_impact_adding_public_function_is_medium() -> None:
    sym = SymbolInfo(name="calculate", kind="function", visibility="public", signature="...")
    assert classify_impact(sym, "added") == "medium"


def test_impact_adding_private_method_is_low() -> None:
    sym = SymbolInfo(name="_helper", kind="method", visibility="private", signature="...")
    assert classify_impact(sym, "added") == "low"
