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
    "constructor_declaration": "method",
    "property_declaration": "property",
    "field_declaration": "field",
}

_VISIBILITY_KEYWORDS = {"public", "private", "protected", "internal"}


def _node_text(node: Node, source: bytes) -> str:
    return source[node.start_byte:node.end_byte].decode("utf-8", errors="replace")


def _extract_visibility(node: Node, source: bytes) -> str:
    """Scan modifiers for visibility keywords."""
    for child in node.children:
        if child.type == "modifier":
            text = _node_text(child, source).lower()
            if text in _VISIBILITY_KEYWORDS:
                return text
    return "private"  # C# default


def _extract_attributes(node: Node, source: bytes) -> list[str]:
    """Collect [Attribute] names from attribute_list nodes."""
    attrs = []
    for child in node.children:
        if child.type == "attribute_list":
            for attr in child.children:
                if attr.type == "attribute":
                    name_node = attr.child_by_field_name("name")
                    if name_node:
                        attrs.append(_node_text(name_node, source))
    return attrs


def _build_cs_signature(node: Node, source: bytes, kind: str, name: str) -> str:
    visibility = _extract_visibility(node, source)
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

        self._walk(root, source, imports, symbols, parent_class=None)

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
                visibility = _extract_visibility(node, source)
                attributes = _extract_attributes(node, source)
                symbols.append(SymbolInfo(
                    name=name,
                    kind=kind,  # type: ignore[arg-type]
                    visibility=visibility,
                    signature=_build_cs_signature(node, source, kind, name),
                    decorators=attributes,
                    parent=parent_class,
                    line_start=node.start_point[0] + 1,
                    line_end=node.end_point[0] + 1,
                ))
                # Recurse into class/interface/struct bodies
                if kind in ("class", "interface", "struct"):
                    body = node.child_by_field_name("body")
                    if body:
                        for child in body.children:
                            self._walk(child, source, imports, symbols, parent_class=name)
                    return

        for child in node.children:
            self._walk(child, source, imports, symbols, parent_class)
