"""Python AST analyzer using tree-sitter."""

from pathlib import Path

import tree_sitter_python as tspython
from tree_sitter import Language, Parser, Node

from ..models import FileAnalysis, SymbolInfo
from .base import LanguageAnalyzer

PY_LANGUAGE = Language(tspython.language())


def _node_text(node: Node, source: bytes) -> str:
    return source[node.start_byte:node.end_byte].decode("utf-8", errors="replace")


def _get_child_by_field(node: Node, field: str) -> Node | None:
    return node.child_by_field_name(field)


def _get_decorators(node: Node, source: bytes) -> list[str]:
    """Collect decorator names from a decorated_definition or function/class node."""
    decorators = []
    parent = node.parent
    if parent and parent.type == "decorated_definition":
        for child in parent.children:
            if child.type == "decorator":
                # decorator text e.g. "@app.route" → strip leading @
                text = _node_text(child, source).lstrip("@").split("(")[0].strip()
                decorators.append(text)
    return decorators


def _build_signature(node: Node, source: bytes, kind: str) -> str:
    """Build a compact signature string."""
    if kind == "function":
        name_node = _get_child_by_field(node, "name")
        params_node = _get_child_by_field(node, "parameters")
        ret_node = _get_child_by_field(node, "return_type")
        name = _node_text(name_node, source) if name_node else "?"
        params = _node_text(params_node, source) if params_node else "()"
        ret = f" -> {_node_text(ret_node, source)}" if ret_node else ""
        return f"def {name}{params}{ret}"
    if kind == "class":
        name_node = _get_child_by_field(node, "name")
        bases_node = _get_child_by_field(node, "superclasses")
        name = _node_text(name_node, source) if name_node else "?"
        bases = _node_text(bases_node, source) if bases_node else ""
        return f"class {name}{bases}"
    return ""


def _infer_visibility(name: str) -> str:
    if name.startswith("__") and not name.endswith("__"):
        return "private"
    if name.startswith("_"):
        return "protected"
    return "public"


class PythonAnalyzer(LanguageAnalyzer):
    """Analyze Python source files."""

    def __init__(self) -> None:
        self._parser = Parser(PY_LANGUAGE)

    @property
    def language_key(self) -> str:
        return "python"

    def analyze(self, path: Path, source: bytes) -> FileAnalysis:
        tree = self._parser.parse(source)
        root = tree.root_node

        imports: list[str] = []
        symbols: list[SymbolInfo] = []

        self._walk(root, source, imports, symbols, parent_class=None)

        return FileAnalysis(
            path=str(path),
            language="python",
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
        if node.type in ("import_statement", "import_from_statement"):
            imports.append(_node_text(node, source).strip())
            return  # Don't recurse into imports

        if node.type == "class_definition":
            name_node = _get_child_by_field(node, "name")
            if name_node:
                name = _node_text(name_node, source)
                symbols.append(SymbolInfo(
                    name=name,
                    kind="class",
                    visibility=_infer_visibility(name),
                    signature=_build_signature(node, source, "class"),
                    decorators=_get_decorators(node, source),
                    parent=parent_class,
                    line_start=node.start_point[0] + 1,
                    line_end=node.end_point[0] + 1,
                ))
                # Recurse into class body with this class as parent
                body = _get_child_by_field(node, "body")
                if body:
                    for child in body.children:
                        self._walk(child, source, imports, symbols, parent_class=name)
            return

        if node.type == "function_definition":
            name_node = _get_child_by_field(node, "name")
            if name_node:
                name = _node_text(name_node, source)
                kind = "method" if parent_class else "function"
                symbols.append(SymbolInfo(
                    name=name,
                    kind=kind,
                    visibility=_infer_visibility(name),
                    signature=_build_signature(node, source, "function"),
                    decorators=_get_decorators(node, source),
                    parent=parent_class,
                    line_start=node.start_point[0] + 1,
                    line_end=node.end_point[0] + 1,
                ))
            return  # Don't recurse into function bodies

        if node.type == "decorated_definition":
            # Recurse to get the actual function/class inside
            for child in node.children:
                if child.type in ("function_definition", "class_definition"):
                    self._walk(child, source, imports, symbols, parent_class)
            return

        # Default: recurse into children
        for child in node.children:
            self._walk(child, source, imports, symbols, parent_class)
