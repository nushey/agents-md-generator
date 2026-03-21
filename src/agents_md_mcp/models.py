"""Pydantic models for agents-md-generator."""

from typing import Literal, Optional
from pydantic import BaseModel, Field, ConfigDict


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
        "enum", "struct", "property", "field"
    ]
    visibility: Optional[str] = None
    signature: Optional[str] = None
    decorators: list[str] = Field(default_factory=list)
    parent: Optional[str] = None
    line_start: int = 0
    line_end: int = 0


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


class CachedFile(BaseModel):
    """Cache entry for a single analyzed file."""

    hash: str
    analysis: FileAnalysis


class CacheData(BaseModel):
    """Root cache structure stored in .agents-cache.json."""

    version: str = "1.0"
    last_run: str
    base_commit: Optional[str] = None
    files: dict[str, CachedFile] = Field(default_factory=dict)


class GenerateAgentsMdInput(BaseModel):
    """Input parameters for the generate_agents_md MCP tool."""

    model_config = ConfigDict(str_strip_whitespace=True, validate_assignment=True)

    project_path: str = Field(
        default=".",
        description="Path to the project root. Default: current directory.",
    )
    force_full_scan: bool = Field(
        default=False,
        description=(
            "Force a full scan ignoring any existing cache. "
            "Use ONLY when the user explicitly asks to rescan or rebuild from scratch. "
            "Do NOT set this to True when asked to improve, review, or update AGENTS.md — "
            "the incremental scan already provides all the data needed."
        ),
    )
