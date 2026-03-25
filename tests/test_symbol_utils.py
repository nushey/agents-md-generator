"""Tests for symbol_utils.py — _is_minified, _format_full, _slim_symbol."""

from agents_md_mcp.models import FileAnalysis, SymbolInfo
from agents_md_mcp.symbol_utils import _format_full, _is_minified, _slim_symbol


# ── Helpers ───────────────────────────────────────────────────────────────────

def _sym(
    name: str,
    kind: str = "function",
    visibility: str = "public",
    sig: str = "sig",
    parent: str | None = None,
    decorators: list[str] | None = None,
) -> SymbolInfo:
    return SymbolInfo(
        name=name,
        kind=kind,
        visibility=visibility,
        signature=sig,
        parent=parent,
        decorators=decorators or [],
    )


def _analysis(path: str, lang: str, symbols: list[SymbolInfo]) -> FileAnalysis:
    return FileAnalysis(path=path, language=lang, symbols=symbols)


# ── _is_minified ──────────────────────────────────────────────────────────────

def test_is_minified_detects_short_names() -> None:
    """JS file where >30% of top-level names are 1-2 chars → minified."""
    syms = [_sym(n) for n in ["a", "b", "c", "d", "longName", "anotherName", "thirdName", "fourthName", "e", "f"]]
    assert _is_minified(_analysis("lib/bundle.js", "javascript", syms))


def test_is_minified_clean_file() -> None:
    """JS file with descriptive names is not minified."""
    syms = [_sym(n) for n in ["getUserById", "saveOrder", "deleteItem", "updateStatus", "fetchData", "renderView"]]
    assert not _is_minified(_analysis("src/api.js", "javascript", syms))


def test_is_minified_not_applied_to_csharp() -> None:
    """Short names in C# must NOT trigger minified detection."""
    syms = [_sym(n) for n in ["a", "b", "c", "d", "e", "f", "g", "h"]]
    assert not _is_minified(_analysis("src/Foo.cs", "c_sharp", syms))


def test_is_minified_not_applied_to_python() -> None:
    """Short names in Python must NOT trigger minified detection."""
    syms = [_sym(n) for n in ["a", "b", "c", "d", "e", "f", "g", "h"]]
    assert not _is_minified(_analysis("src/foo.py", "python", syms))


def test_is_minified_too_few_symbols() -> None:
    """Fewer than 5 symbols — not enough signal to decide."""
    syms = [_sym(n) for n in ["a", "b", "c"]]
    assert not _is_minified(_analysis("lib/tiny.js", "javascript", syms))


def test_is_minified_at_threshold_not_minified() -> None:
    """Exactly 30% short names → NOT minified (threshold is strictly >30%)."""
    # 3 short out of 10 = 30%
    syms = [_sym(n) for n in ["a", "b", "c", "name1", "name2", "name3", "name4", "name5", "name6", "name7"]]
    assert not _is_minified(_analysis("src/app.js", "javascript", syms))


def test_is_minified_ignores_child_symbols() -> None:
    """Methods inside a class (parent set) are excluded from the ratio."""
    # 5 short-name methods under a class parent + 1 top-level with a real name
    syms = (
        [_sym(n, parent="MyClass") for n in ["a", "b", "c", "d", "e"]]
        + [_sym("doWork"), _sym("processData"), _sym("handleEvent"), _sym("loadConfig"), _sym("saveState")]
    )
    assert not _is_minified(_analysis("src/app.js", "javascript", syms))


# ── _format_full ──────────────────────────────────────────────────────────────

def test_format_full_returns_none_for_empty_symbols() -> None:
    analysis = _analysis("src/empty.js", "javascript", [])
    assert _format_full("src/empty.js", "new", analysis) is None


def test_format_full_returns_none_when_only_private_symbols() -> None:
    syms = [_sym("_helper", visibility="private"), _sym("_internal", visibility="private")]
    analysis = _analysis("src/utils.py", "python", syms)
    assert _format_full("src/utils.py", "new", analysis) is None


def test_format_full_returns_none_for_minified_js() -> None:
    syms = [_sym(n) for n in ["a", "b", "c", "d", "e", "f", "g", "h"]]
    analysis = _analysis("lib/vendor.js", "javascript", syms)
    assert _format_full("lib/vendor.js", "new", analysis) is None


def test_format_full_includes_public_symbols() -> None:
    syms = [_sym("processOrder"), _sym("_internal", visibility="private")]
    analysis = _analysis("src/orders.py", "python", syms)
    result = _format_full("src/orders.py", "new", analysis)
    assert result is not None
    names = [s["name"] for s in result["symbols"]]
    assert "processOrder" in names
    assert "_internal" not in names


def test_format_full_omits_decorators_when_empty() -> None:
    syms = [_sym("MyClass", kind="class", decorators=[])]
    analysis = _analysis("src/Foo.cs", "c_sharp", syms)
    result = _format_full("src/Foo.cs", "new", analysis)
    assert result is not None
    assert "decorators" not in result["symbols"][0]


def test_format_full_includes_decorators_when_present() -> None:
    syms = [_sym("MyController", kind="class", decorators=["ApiController", "Route"])]
    analysis = _analysis("src/Ctrl.cs", "c_sharp", syms)
    result = _format_full("src/Ctrl.cs", "new", analysis)
    assert result is not None
    assert result["symbols"][0]["decorators"] == ["ApiController", "Route"]


def test_format_full_class_includes_public_methods() -> None:
    syms = [
        _sym("OrderService", kind="class"),
        _sym("Create", kind="method", parent="OrderService"),
        _sym("_validate", kind="method", visibility="private", parent="OrderService"),
    ]
    analysis = _analysis("src/OrderService.cs", "c_sharp", syms)
    result = _format_full("src/OrderService.cs", "new", analysis)
    assert result is not None
    cls = result["symbols"][0]
    assert cls["name"] == "OrderService"
    assert "Create" in cls["methods"]
    assert "_validate" not in cls["methods"]


def test_format_full_constructor_with_params_is_included() -> None:
    """Constructor with parameters is included as 'constructor' field."""
    syms = [
        _sym("OrderService", kind="class"),
        _sym("OrderService", kind="constructor", sig="public OrderService(IRepository repo)", parent="OrderService"),
        _sym("Create", kind="method", parent="OrderService"),
    ]
    result = _format_full("src/OrderService.cs", "new", _analysis("src/OrderService.cs", "c_sharp", syms))
    assert result is not None
    cls = result["symbols"][0]
    assert "constructor" in cls
    assert "IRepository" in cls["constructor"]


def test_format_full_empty_constructor_is_excluded() -> None:
    """Constructor with no parameters is not included."""
    syms = [
        _sym("SimpleEntity", kind="class"),
        _sym("SimpleEntity", kind="constructor", sig="public SimpleEntity()", parent="SimpleEntity"),
        _sym("Id", kind="property", sig="public int Id", parent="SimpleEntity"),
    ]
    result = _format_full("src/SimpleEntity.cs", "new", _analysis("src/SimpleEntity.cs", "c_sharp", syms))
    assert result is not None
    cls = result["symbols"][0]
    assert "constructor" not in cls


def test_format_full_properties_are_included() -> None:
    """Public properties are listed under the class entry."""
    syms = [
        _sym("Product", kind="class"),
        _sym("Name", kind="property", sig="public string Name", parent="Product"),
        _sym("Price", kind="property", sig="public decimal Price", parent="Product"),
    ]
    result = _format_full("src/Product.cs", "new", _analysis("src/Product.cs", "c_sharp", syms))
    assert result is not None
    cls = result["symbols"][0]
    assert "string Name" in cls["properties"]
    assert "decimal Price" in cls["properties"]


def test_format_full_properties_omitted_when_class_has_methods() -> None:
    """Properties are omitted when the class has public methods."""
    syms = [
        _sym("OrderService", kind="class"),
        _sym("Status", kind="property", sig="public string Status", parent="OrderService"),
        _sym("Process", kind="method", parent="OrderService"),
    ]
    result = _format_full("src/OrderService.cs", "new", _analysis("src/OrderService.cs", "c_sharp", syms))
    assert result is not None
    cls = result["symbols"][0]
    assert "properties" not in cls
    assert "Process" in cls["methods"]


def test_format_full_properties_all_inline_when_no_methods() -> None:
    """All properties are included inline as a string when class has no methods."""
    syms = [_sym("BigDto", kind="class")] + [
        _sym(f"Prop{i}", kind="property", sig=f"public string Prop{i}", parent="BigDto")
        for i in range(20)
    ]
    result = _format_full("src/BigDto.cs", "new", _analysis("src/BigDto.cs", "c_sharp", syms))
    assert result is not None
    cls = result["symbols"][0]
    assert isinstance(cls["properties"], str)
    assert cls["properties"].count(",") == 19  # 20 props → 19 commas
    assert "total_properties" not in cls


def test_format_full_interface_methods_listed() -> None:
    """Interface methods are listed under the interface entry."""
    syms = [
        _sym("IRepository", kind="interface"),
        _sym("GetAll", kind="method", parent="IRepository"),
        _sym("Save", kind="method", parent="IRepository"),
    ]
    result = _format_full("src/IRepository.cs", "new", _analysis("src/IRepository.cs", "c_sharp", syms))
    assert result is not None
    iface = result["symbols"][0]
    assert iface["kind"] == "interface"
    assert "GetAll" in iface["methods"]
    assert "Save" in iface["methods"]


def test_format_full_private_property_excluded() -> None:
    """Private properties are not listed."""
    syms = [
        _sym("Service", kind="class"),
        _sym("_cache", kind="property", sig="private Dictionary _cache", visibility="private", parent="Service"),
        _sym("Name", kind="property", sig="public string Name", parent="Service"),
    ]
    result = _format_full("src/Service.cs", "new", _analysis("src/Service.cs", "c_sharp", syms))
    assert result is not None
    cls = result["symbols"][0]
    props = cls.get("properties", "")
    assert "Name" in props
    assert "_cache" not in props


def test_format_full_top_level_function_not_nested_under_class() -> None:
    syms = [
        _sym("MyClass", kind="class"),
        _sym("standaloneFunc"),
        _sym("innerMethod", kind="method", parent="MyClass"),
    ]
    analysis = _analysis("src/app.py", "python", syms)
    result = _format_full("src/app.py", "new", analysis)
    assert result is not None
    names = [s["name"] for s in result["symbols"]]
    assert "MyClass" in names
    assert "standaloneFunc" in names
    assert "innerMethod" not in names  # belongs to class, not top-level


# ── _slim_symbol ──────────────────────────────────────────────────────────────

def test_slim_symbol_omits_empty_decorators() -> None:
    sym = _sym("doThing", decorators=[])
    result = _slim_symbol(sym)
    assert "decorators" not in result


def test_slim_symbol_includes_decorators_when_present() -> None:
    sym = _sym("handleGet", decorators=["HttpGet"])
    result = _slim_symbol(sym)
    assert result["decorators"] == ["HttpGet"]


def test_slim_symbol_excludes_line_numbers_and_parent() -> None:
    sym = _sym("myFunc", parent="MyClass")
    result = _slim_symbol(sym)
    assert "line_start" not in result
    assert "line_end" not in result
    assert "parent" not in result
