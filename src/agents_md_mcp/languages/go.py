"""Go AST analyzer using tree-sitter."""

from pathlib import Path

import tree_sitter_go as tsgo
from tree_sitter import Language, Parser, Node

from ..models import FileAnalysis, SymbolInfo
from .base import LanguageAnalyzer

GO_LANGUAGE = Language(tsgo.language())


def _node_text(node: Node, source: bytes) -> str:
    return source[node.start_byte:node.end_byte].decode("utf-8", errors="replace")


def _is_exported(name: str) -> bool:
    return bool(name) and name[0].isupper()


class GoAnalyzer(LanguageAnalyzer):
    """Analyze Go source files."""

    def __init__(self) -> None:
        self._parser = Parser(GO_LANGUAGE)

    @property
    def language_key(self) -> str:
        return "go"

    def analyze(self, path: Path, source: bytes) -> FileAnalysis:
        tree = self._parser.parse(source)
        root = tree.root_node

        imports: list[str] = []
        symbols: list[SymbolInfo] = []

        self._walk(root, source, imports, symbols)

        return FileAnalysis(
            path=str(path),
            language="go",
            imports=imports,
            symbols=symbols,
        )

    def _walk(
        self,
        node: Node,
        source: bytes,
        imports: list[str],
        symbols: list[SymbolInfo],
    ) -> None:
        t = node.type

        if t == "import_declaration":
            imports.append(_node_text(node, source).strip())
            return

        if t == "type_declaration":
            for child in node.children:
                if child.type == "type_spec":
                    name_node = child.child_by_field_name("name")
                    type_node = child.child_by_field_name("type")
                    if name_node:
                        name = _node_text(name_node, source)
                        kind = "struct" if (type_node and type_node.type == "struct_type") else "interface" if (type_node and type_node.type == "interface_type") else "class"
                        symbols.append(SymbolInfo(
                            name=name,
                            kind=kind,  # type: ignore[arg-type]
                            visibility="public" if _is_exported(name) else "private",
                            signature=f"type {name} {_node_text(type_node, source)[:40]}" if type_node else f"type {name}",
                            line_start=node.start_point[0] + 1,
                            line_end=node.end_point[0] + 1,
                        ))
            return

        if t == "function_declaration":
            name_node = node.child_by_field_name("name")
            params_node = node.child_by_field_name("parameters")
            if name_node:
                name = _node_text(name_node, source)
                params = _node_text(params_node, source) if params_node else "()"
                symbols.append(SymbolInfo(
                    name=name,
                    kind="function",
                    visibility="public" if _is_exported(name) else "private",
                    signature=f"func {name}{params}",
                    line_start=node.start_point[0] + 1,
                    line_end=node.end_point[0] + 1,
                ))
            return

        if t == "method_declaration":
            name_node = node.child_by_field_name("name")
            receiver_node = node.child_by_field_name("receiver")
            params_node = node.child_by_field_name("parameters")
            if name_node:
                name = _node_text(name_node, source)
                receiver = _node_text(receiver_node, source) if receiver_node else ""
                # Extract receiver type name for parent
                parent = None
                if receiver_node:
                    for rchild in receiver_node.children:
                        if rchild.type == "parameter_declaration":
                            type_node = rchild.child_by_field_name("type")
                            if type_node:
                                parent = _node_text(type_node, source).lstrip("*")
                params = _node_text(params_node, source) if params_node else "()"
                symbols.append(SymbolInfo(
                    name=name,
                    kind="method",
                    visibility="public" if _is_exported(name) else "private",
                    signature=f"func {receiver} {name}{params}",
                    parent=parent,
                    line_start=node.start_point[0] + 1,
                    line_end=node.end_point[0] + 1,
                ))
            return

        for child in node.children:
            self._walk(child, source, imports, symbols)
