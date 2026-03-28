"""C# AST analyzer using tree-sitter."""

from pathlib import Path

import tree_sitter_c_sharp as tscsharp
from tree_sitter import Language, Parser, Node

from ..models import FileAnalysis, SymbolInfo
from .base import LanguageAnalyzer

CS_LANGUAGE = Language(tscsharp.language())

_KIND_MAP = {
    "class_declaration": "class",
    "interface_declaration": "interface",
    "struct_declaration": "struct",
    "enum_declaration": "enum",
    "method_declaration": "method",
    "constructor_declaration": "constructor",
    "property_declaration": "property",
    "field_declaration": "field",
}

_VISIBILITY_KEYWORDS = {"public", "private", "protected", "internal"}

_TYPE_DECLARATIONS = frozenset({
    "class_declaration",
    "interface_declaration",
    "struct_declaration",
    "enum_declaration",
})


def _node_text(node: Node, source: bytes) -> str:
    return source[node.start_byte:node.end_byte].decode("utf-8", errors="replace")


def _extract_visibility(
    node: Node,
    source: bytes,
    in_interface: bool = False,
    is_nested: bool = False,
) -> str:
    """Determine the access modifier for a C# node.

    C# visibility defaults (from the language spec):
    - Interface members: implicitly public (no explicit modifier for visibility)
    - Type declarations (class/struct/interface/enum) at top level: internal
    - Type declarations nested inside another type: private
    - Class/struct members (methods, fields, properties): private
    """
    for child in node.children:
        if child.type == "modifier":
            text = _node_text(child, source).lower()
            if text in _VISIBILITY_KEYWORDS:
                return text
    if in_interface:
        return "public"
    if node.type in _TYPE_DECLARATIONS:
        return "private" if is_nested else "internal"
    return "private"


def _extract_attributes(node: Node, source: bytes) -> list[str]:
    """Collect [Attribute(args)] from attribute_list nodes.

    Includes arguments when present to enable downstream wiring detection:
    [HttpGet("api/orders")] → 'HttpGet("api/orders")'
    [Authorize]             → 'Authorize'

    Tree-sitter C# grammar: attribute → identifier (name) + attribute_argument_list.
    The name node is the first identifier child (not a field), and the args are an
    attribute_argument_list child node.
    """
    attrs = []
    for child in node.children:
        if child.type == "attribute_list":
            for attr in child.children:
                if attr.type == "attribute":
                    # Name is the first identifier/qualified_name child
                    name_node = None
                    args_node = None
                    for ac in attr.children:
                        if ac.type in ("identifier", "qualified_name", "generic_name") and name_node is None:
                            name_node = ac
                        elif ac.type == "attribute_argument_list":
                            args_node = ac
                    if not name_node:
                        continue
                    name = _node_text(name_node, source)
                    if args_node:
                        args_text = _node_text(args_node, source).strip()
                        if args_text and args_text != "()":
                            attrs.append(f"{name}{args_text}")
                            continue
                    attrs.append(name)
    return attrs


def _extract_implements(node: Node, source: bytes) -> list[str]:
    """Extract base types (interfaces/classes) from a class/struct declaration.

    C# base_list: `class Foo : IBar, IBaz, BaseClass` → ["IBar", "IBaz", "BaseClass"]

    The tree-sitter C# grammar uses a `base_list` child node (not a field),
    containing identifier / generic_name children separated by commas.
    """
    base_list = None
    for child in node.children:
        if child.type == "base_list":
            base_list = child
            break
    if not base_list:
        return []
    result = []
    for child in base_list.children:
        if child.type in (
            "identifier", "generic_name", "qualified_name",
            "predefined_type", "nullable_type",
        ):
            name = _node_text(child, source).strip()
            if name:
                result.append(name)
    return result


def _build_cs_signature(node: Node, source: bytes, kind: str, name: str, visibility: str) -> str:
    if kind == "constructor":
        params_node = node.child_by_field_name("parameters")
        params = _node_text(params_node, source) if params_node else "()"
        return f"{visibility} {name}{params}"
    if kind == "method":
        params_node = node.child_by_field_name("parameters")
        ret_node = node.child_by_field_name("type")
        params = _node_text(params_node, source) if params_node else "()"
        ret = _node_text(ret_node, source) if ret_node else "void"
        return f"{visibility} {ret} {name}{params}"
    if kind in ("class", "interface", "struct"):
        bases_node = node.child_by_field_name("bases")
        bases = f" : {_node_text(bases_node, source)}" if bases_node else ""
        return f"{visibility} {kind} {name}{bases}"
    if kind == "property":
        type_node = node.child_by_field_name("type")
        type_str = _node_text(type_node, source) if type_node else "?"
        return f"{visibility} {type_str} {name}"
    return f"{visibility} {kind} {name}"


class CSharpAnalyzer(LanguageAnalyzer):
    """Analyze C# source files."""

    def __init__(self) -> None:
        self._parser = Parser(CS_LANGUAGE)

    @property
    def language_key(self) -> str:
        return "c_sharp"

    def analyze(self, path: Path, source: bytes) -> FileAnalysis:
        tree = self._parser.parse(source)
        root = tree.root_node

        imports: list[str] = []
        symbols: list[SymbolInfo] = []

        self._walk(root, source, imports, symbols, parent_class=None, in_interface=False)

        return FileAnalysis(
            path=str(path),
            language="c_sharp",
            imports=imports,
            symbols=symbols,
        )

    def _walk(
        self,
        node: Node,
        source: bytes,
        imports: list[str],
        symbols: list[SymbolInfo],
        parent_class: str | None,
        in_interface: bool,
    ) -> None:
        if node.type == "using_directive":
            imports.append(_node_text(node, source).strip())
            return

        if node.type in _KIND_MAP:
            kind = _KIND_MAP[node.type]
            name_node = node.child_by_field_name("name")
            if name_node is None:
                # field_declaration may have variable_declarator
                for child in node.children:
                    if child.type == "variable_declaration":
                        for vchild in child.children:
                            if vchild.type == "variable_declarator":
                                name_node = vchild.child_by_field_name("name") or vchild
                                break
                        break

            if name_node:
                name = _node_text(name_node, source).strip()
                visibility = _extract_visibility(
                    node, source,
                    in_interface=in_interface,
                    is_nested=parent_class is not None,
                )
                attributes = _extract_attributes(node, source)
                implements = _extract_implements(node, source) if kind in ("class", "struct") else []
                symbols.append(SymbolInfo(
                    name=name,
                    kind=kind,  # type: ignore[arg-type]
                    visibility=visibility,
                    signature=_build_cs_signature(node, source, kind, name, visibility),
                    decorators=attributes,
                    implements=implements,
                    parent=parent_class,
                    line_start=node.start_point[0] + 1,
                    line_end=node.end_point[0] + 1,
                ))
                # Recurse into class/interface/struct bodies
                if kind in ("class", "interface", "struct"):
                    body = node.child_by_field_name("body")
                    if body:
                        for child in body.children:
                            self._walk(
                                child, source, imports, symbols,
                                parent_class=name,
                                in_interface=(kind == "interface"),
                            )
                    return

        for child in node.children:
            self._walk(child, source, imports, symbols, parent_class, in_interface)
