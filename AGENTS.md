# agents-md-generator

## Project Overview

`agents-md-generator` is a Python MCP (Model Context Protocol) server that analyzes codebases using tree-sitter AST parsing and produces structured `AGENTS.md` files for AI coding agents. It exposes a single MCP tool (`generate_agents_md`) that performs incremental or full scans, leverages a file-based cache to avoid redundant work, and returns a structured JSON response with instructions for the calling agent to write the final document. The stack is pure Python with Pydantic for data models and FastMCP for the server transport.

## Architecture & Data Flow

The system is a layered pipeline triggered by a single MCP tool call:

```
MCP Tool Call (server.py)
  → Config + Gitignore loading (config.py, gitignore.py)
  → Change detection against cache (change_detector.py, cache.py)
  → Per-file AST analysis (ast_analyzer.py → languages/<lang>.py)
  → Payload assembly (context_builder.py)
  → Cache persistence (cache.py)
  → JSON response returned to calling agent
```

**MCP Layer** (`server.py`): Bootstraps the FastMCP server and registers `generate_agents_md` as the sole tool. It serves as the entry point for all external interaction.

**Orchestration Layer** (`ast_analyzer.py`, `context_builder.py`): `ast_analyzer.py` coordinates which files need analysis, dispatches to the correct language analyzer, and computes symbol diffs. `context_builder.py` assembles the final payload dictionary from collected analyses, change metadata, and project structure.

**Infrastructure Layer** (`change_detector.py`, `cache.py`, `config.py`, `gitignore.py`): Handles git-based change detection, cache lifecycle (read/write/validation), project configuration, and gitignore filtering. These modules are agnostic of AST logic or output formatting.

**Analysis Layer** (`languages/`): Each supported language (Python, C#, Go, TypeScript) has a dedicated analyzer class implementing the `LanguageAnalyzer` ABC. Analyzers are stateless and extract `SymbolInfo` from provided file paths.

**Data Layer** (`models.py`): All Pydantic `BaseModel` definitions shared across layers live here. This module contains no logic, only schemas for data consistency.

## Conventions & Patterns

### Adding a new language analyzer

1. Create `src/agents_md_mcp/languages/<language>.py`.
2. Define a class `<Language>Analyzer(LanguageAnalyzer)` implementing:
   - `language_key(self) -> str` — returns the canonical key (e.g. `"python"`, `"go"`).
   - `analyze(self, file_path: Path) -> list[SymbolInfo]` — parses the file and returns extracted symbols.
3. Register the new analyzer in `ast_analyzer.py`'s `build_analyzer()` factory function.
4. Add fixture files under `tests/fixtures/sample.<ext>` and test coverage in `tests/test_ast_analyzer.py`.

### Data models

All Pydantic models live exclusively in `models.py`. Never define `BaseModel` subclasses in other modules. When a new data contract is needed (e.g., a new cache field or tool parameter), update `models.py` first.

### Module responsibilities are strict

Each module owns exactly one concern. Do not add file I/O to `models.py`, do not add AST logic to `cache.py`, and do not add payload formatting to `ast_analyzer.py`. The layered separation is intentional and must be preserved.

### Cache location

The cache is stored outside the project directory at `~/.cache/agents-md-generator/<project-hash>/`. Never write cache or payload files inside the project root.

## Setup Commands

```bash
# Install dependencies (requires uv)
uv sync

# Run the MCP server directly
uv run agents-md-generator
```

The server bootstrap is located in `src/agents_md_mcp/server.py`.

## Development Workflow

```bash
# Run the server for local testing
uv run agents-md-generator
```

## Testing Instructions

Tests live in `tests/` and use pytest. The suite includes fixture-based testing for multi-language AST analysis using sample files in `tests/fixtures/` (`.cs`, `.go`, `.py`, `.ts`).

```bash
uv run pytest
```

The comprehensive test suite covers: AST analysis for all supported languages, cache lifecycle, change detection (including symbol diffs and impact analysis), config loading, and context building.

## Keeping AGENTS.md Up to Date

This file is generated and maintained by the `agents-md-generator` MCP tool.
**Never edit it manually.** To regenerate after code changes, ask Claude Code:

> "Update the AGENTS.md for this project"

Claude will invoke the `generate_agents_md` tool automatically, perform an
incremental scan of changed files, and rewrite only the affected sections.
To force a full rescan from scratch: "Regenerate the AGENTS.md from scratch".
