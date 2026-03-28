"""TypeScript/JavaScript AST analyzer using tree-sitter."""

from pathlib import Path

import tree_sitter_typescript as tsts
import tree_sitter_javascript as tsjs
from tree_sitter import Language, Parser, Node

from ..models import FileAnalysis, SymbolInfo
from .base import LanguageAnalyzer

TS_LANGUAGE = Language(tsts.language_typescript())
TSX_LANGUAGE = Language(tsts.language_tsx())
JS_LANGUAGE = Language(tsjs.language())


def _node_text(node: Node, source: bytes) -> str:
    return source[node.start_byte:node.end_byte].decode("utf-8", errors="replace")


def _get_decorators(node: Node, source: bytes) -> list[str]:
    """Collect TypeScript decorators with full arguments.

    Preserves: "Injectable()", "Controller('/api/users')", "Get()"
    """
    decorators = []
    parent = node.parent
    if parent:
        for child in parent.children:
            if child.type == "decorator":
                text = _node_text(child, source).lstrip("@").strip()
                decorators.append(text)
    return decorators


def _extract_implements(node: Node, source: bytes) -> list[str]:
    """Extract implemented interfaces from class_heritage → implements_clause."""
    result = []
    for child in node.children:
        if child.type == "class_heritage":
            for heritage_child in child.children:
                if heritage_child.type == "implements_clause":
                    for type_node in heritage_child.children:
                        if type_node.type in ("type_identifier", "generic_type"):
                            result.append(_node_text(type_node, source).strip())
    return result


def _extract_extends(node: Node, source: bytes) -> str | None:
    """Extract the base class name from class_heritage → extends_clause."""
    for child in node.children:
        if child.type == "class_heritage":
            for heritage_child in child.children:
                if heritage_child.type == "extends_clause":
                    for type_node in heritage_child.children:
                        if type_node.type in ("type_identifier", "generic_type", "identifier"):
                            return _node_text(type_node, source).strip()
    return None


def _infer_visibility(node: Node, source: bytes) -> str:
    for child in node.children:
        text = _node_text(child, source)
        if text in ("private", "protected", "public"):
            return text
    return "public"


class TypeScriptAnalyzer(LanguageAnalyzer):
    """Analyze TypeScript and TSX source files."""

    def __init__(self, lang_key: str = "typescript") -> None:
        self._lang_key = lang_key
        if lang_key == "tsx":
            self._parser = Parser(TSX_LANGUAGE)
        else:
            self._parser = Parser(TS_LANGUAGE)

    @property
    def language_key(self) -> str:
        return self._lang_key

    def analyze(self, path: Path, source: bytes) -> FileAnalysis:
        tree = self._parser.parse(source)
        root = tree.root_node

        imports: list[str] = []
        symbols: list[SymbolInfo] = []
        exports: list[str] = []

        self._walk(root, source, imports, symbols, exports, parent_class=None)

        return FileAnalysis(
            path=str(path),
            language=self._lang_key,
            imports=imports,
            symbols=symbols,
            exports=exports,
        )

    def _walk(
        self,
        node: Node,
        source: bytes,
        imports: list[str],
        symbols: list[SymbolInfo],
        exports: list[str],
        parent_class: str | None,
    ) -> None:
        t = node.type

        if t in ("import_statement", "import_declaration"):
            imports.append(_node_text(node, source).strip())
            return

        if t == "export_statement":
            # Collect what's being exported
            decl = node.child_by_field_name("declaration")
            if decl:
                name_node = decl.child_by_field_name("name")
                if name_node:
                    exports.append(_node_text(name_node, source))
            # Also recurse into the declaration
            for child in node.children:
                if child.type not in ("export", "default"):
                    self._walk(child, source, imports, symbols, exports, parent_class)
            return

        if t in ("class_declaration", "abstract_class_declaration"):
            name_node = node.child_by_field_name("name")
            if name_node:
                name = _node_text(name_node, source)
                extends = _extract_extends(node, source)
                sig = f"class {name} extends {extends}" if extends else f"class {name}"
                symbols.append(SymbolInfo(
                    name=name,
                    kind="class",
                    visibility=_infer_visibility(node, source),
                    signature=sig,
                    decorators=_get_decorators(node, source),
                    implements=_extract_implements(node, source),
                    parent=parent_class,
                    line_start=node.start_point[0] + 1,
                    line_end=node.end_point[0] + 1,
                ))
                body = node.child_by_field_name("body")
                if body:
                    for child in body.children:
                        self._walk(child, source, imports, symbols, exports, parent_class=name)
            return

        if t == "interface_declaration":
            name_node = node.child_by_field_name("name")
            if name_node:
                name = _node_text(name_node, source)
                symbols.append(SymbolInfo(
                    name=name,
                    kind="interface",
                    visibility="public",
                    signature=f"interface {name}",
                    decorators=[],
                    parent=parent_class,
                    line_start=node.start_point[0] + 1,
                    line_end=node.end_point[0] + 1,
                ))
            return

        if t in ("function_declaration", "function"):
            name_node = node.child_by_field_name("name")
            if name_node:
                name = _node_text(name_node, source)
                kind = "method" if parent_class else "function"
                params_node = node.child_by_field_name("parameters")
                params = _node_text(params_node, source) if params_node else "()"
                ret_node = node.child_by_field_name("return_type")
                ret = _node_text(ret_node, source) if ret_node else ""
                symbols.append(SymbolInfo(
                    name=name,
                    kind=kind,
                    visibility=_infer_visibility(node, source),
                    signature=f"function {name}{params}{ret}",
                    decorators=_get_decorators(node, source),
                    parent=parent_class,
                    line_start=node.start_point[0] + 1,
                    line_end=node.end_point[0] + 1,
                ))
            return

        if t == "method_definition":
            name_node = node.child_by_field_name("name")
            if name_node:
                name = _node_text(name_node, source)
                params_node = node.child_by_field_name("parameters")
                params = _node_text(params_node, source) if params_node else "()"
                ret_node = node.child_by_field_name("return_type")
                ret = _node_text(ret_node, source) if ret_node else ""
                symbols.append(SymbolInfo(
                    name=name,
                    kind="method",
                    visibility=_infer_visibility(node, source),
                    signature=f"{name}{params}{ret}",
                    decorators=_get_decorators(node, source),
                    parent=parent_class,
                    line_start=node.start_point[0] + 1,
                    line_end=node.end_point[0] + 1,
                ))
            return

        if t in ("lexical_declaration", "variable_declaration"):
            # Arrow functions assigned to const
            for child in node.children:
                if child.type == "variable_declarator":
                    name_node = child.child_by_field_name("name")
                    value_node = child.child_by_field_name("value")
                    if name_node and value_node and value_node.type in (
                        "arrow_function", "function"
                    ):
                        name = _node_text(name_node, source)
                        kind = "method" if parent_class else "function"
                        symbols.append(SymbolInfo(
                            name=name,
                            kind=kind,
                            visibility="public",
                            signature=f"const {name} = ...",
                            decorators=[],
                            parent=parent_class,
                            line_start=node.start_point[0] + 1,
                            line_end=node.end_point[0] + 1,
                        ))
            return

        for child in node.children:
            self._walk(child, source, imports, symbols, exports, parent_class)


class JavaScriptAnalyzer(TypeScriptAnalyzer):
    """Analyze JavaScript and JSX source files."""

    def __init__(self) -> None:
        self._lang_key = "javascript"
        self._parser = Parser(JS_LANGUAGE)
