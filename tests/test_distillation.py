import pytest
from agents_md_mcp.symbol_utils import _is_low_entropy
from agents_md_mcp.models import FileAnalysis, SymbolInfo

def test_is_low_entropy_dto_only():
    # File with 3 classes and no methods (minified)
    analysis = FileAnalysis(
        path="UserDto.cs",
        language="c_sharp",
        symbols=[
            SymbolInfo(name="UserDto", kind="class", visibility="public"),
            SymbolInfo(name="AddressDto", kind="class", visibility="public"),
            SymbolInfo(name="RoleDto", kind="class", visibility="public"),
        ]
    )
    assert _is_low_entropy(analysis) is True

def test_is_low_entropy_too_few_containers():
    # Only 2 classes - should NOT be minified
    analysis = FileAnalysis(
        path="Small.cs",
        language="c_sharp",
        symbols=[
            SymbolInfo(name="One", kind="class", visibility="public"),
            SymbolInfo(name="Two", kind="class", visibility="public"),
        ]
    )
    assert _is_low_entropy(analysis) is False

def test_is_low_entropy_with_methods():
    # File with classes and methods (logic)
    analysis = FileAnalysis(
        path="UserService.cs",
        language="c_sharp",
        symbols=[
            SymbolInfo(name="UserService", kind="class", visibility="public"),
            SymbolInfo(name="One", kind="class", visibility="public"),
            SymbolInfo(name="Two", kind="class", visibility="public"),
            SymbolInfo(name="GetUser", kind="method", visibility="public", parent="UserService"),
        ]
    )
    assert _is_low_entropy(analysis) is False
