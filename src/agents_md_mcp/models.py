"""Pydantic models for agents-md-generator."""

import re
from typing import Literal, Optional
from pydantic import BaseModel, Field, ConfigDict, field_validator

_WHITESPACE_RUN = re.compile(r"\s+")


def normalize_signature(value: Optional[str]) -> Optional[str]:
    """Flatten verbatim AST text into a single compact line.

    Tree-sitter extracts signatures and decorators straight from source, so
    multi-line definitions arrive carrying newlines and indentation. Once
    serialized to JSON those turn into escaped ``\\n`` plus runs of whitespace
    that bloat the payload and hurt readability for the agent. This collapses
    every whitespace run to a single space and tidies the bracket spacing that
    trailing commas in multi-line parameter lists leave behind.
    """
    if not value:
        return value
    flat = _WHITESPACE_RUN.sub(" ", value).strip()
    flat = flat.replace("( ", "(").replace(" )", ")")
    flat = flat.replace(", )", ")").replace(",)", ")")
    return flat


class FileChange(BaseModel):
    """Represents a file that changed since the last scan."""

    model_config = ConfigDict(str_strip_whitespace=True)

    path: str
    status: Literal["new", "modified", "deleted"]
    old_hash: Optional[str] = None
    new_hash: Optional[str] = None


class SymbolInfo(BaseModel):
    """A code symbol extracted via AST analysis."""

    model_config = ConfigDict(str_strip_whitespace=True)

    name: str
    kind: Literal[
        "class", "method", "function", "interface",
        "enum", "struct", "property", "field", "constructor"
    ]
    visibility: Optional[str] = None
    signature: Optional[str] = None
    decorators: list[str] = Field(default_factory=list)
    implements: list[str] = Field(default_factory=list)
    parent: Optional[str] = None
    line_start: int = 0
    line_end: int = 0

    @field_validator("signature")
    @classmethod
    def _clean_signature(cls, v: Optional[str]) -> Optional[str]:
        return normalize_signature(v)

    @field_validator("decorators", "implements")
    @classmethod
    def _clean_str_list(cls, v: list[str]) -> list[str]:
        return [normalize_signature(item) or item for item in v]


class FileAnalysis(BaseModel):
    """Full AST analysis result for a single file."""

    model_config = ConfigDict(str_strip_whitespace=True)

    path: str
    language: str
    imports: list[str] = Field(default_factory=list)
    symbols: list[SymbolInfo] = Field(default_factory=list)
    exports: list[str] = Field(default_factory=list)


class AnalysisDiff(BaseModel):
    """Semantic diff between two versions of a file."""

    added: list[SymbolInfo] = Field(default_factory=list)
    removed: list[SymbolInfo] = Field(default_factory=list)
    modified: list[SymbolInfo] = Field(default_factory=list)


class CachedSymbol(BaseModel):
    """Minimal symbol stored in cache — only the fields needed for semantic diff."""

    name: str
    kind: Literal[
        "class", "method", "function", "interface",
        "enum", "struct", "property", "field", "constructor"
    ]
    visibility: Optional[str] = None
    signature: Optional[str] = None
    decorators: list[str] = Field(default_factory=list)

    @field_validator("signature")
    @classmethod
    def _clean_signature(cls, v: Optional[str]) -> Optional[str]:
        return normalize_signature(v)

    @field_validator("decorators")
    @classmethod
    def _clean_str_list(cls, v: list[str]) -> list[str]:
        return [normalize_signature(item) or item for item in v]


class CachedFile(BaseModel):
    """Cache entry for a single analyzed file."""

    hash: str
    symbols: list[CachedSymbol] = Field(default_factory=list)


class CacheData(BaseModel):
    """Root cache structure stored in .agents-cache.json."""

    version: str = "1.0"
    last_run: str
    base_commit: Optional[str] = None
    files: dict[str, CachedFile] = Field(default_factory=dict)


class ReadPayloadChunkInput(BaseModel):
    """Input parameters for the read_payload_chunk MCP tool."""

    model_config = ConfigDict(str_strip_whitespace=True)

    project_path: str = Field(
        default=".",
        description="Path to the project root. Must match the value used in scan_codebase.",
    )
    chunk_index: int = Field(
        description="Zero-based index of the chunk to retrieve.",
    )


class ScanCodebaseInput(BaseModel):
    """Input parameters for the scan_codebase MCP tool."""

    model_config = ConfigDict(str_strip_whitespace=True, validate_assignment=True)

    project_path: str = Field(
        default=".",
        description="Path to the project root. Default: current directory.",
    )
    force_full_scan: bool = Field(
        default=True,
        description=(
            "Force a full scan ignoring any existing cache. Defaults to True — "
            "direct calls always perform a full scan for complete context. "
            "Set to False only when called as part of an incremental update workflow "
            "(e.g. orchestrated by generate_agents_md)."
        ),
    )


class GenerateAgentsMdInput(BaseModel):
    """Input parameters for the generate_agents_md MCP tool."""

    model_config = ConfigDict(str_strip_whitespace=True)

    project_path: str = Field(
        default=".",
        description="Path to the project root. Default: current directory.",
    )
