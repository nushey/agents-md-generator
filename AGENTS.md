# AGENTS.md — agents-md-generator

## Project Overview

`agents-md-generator` is a Python MCP (Model Context Protocol) server that analyzes codebases using tree-sitter AST parsing and generates `AGENTS.md` files — structured context documents for AI coding agents. The tool performs incremental, cache-aware scans across Python, TypeScript/JavaScript, Go, and C# projects, then instructs the connected AI assistant to write the final document. The architecture is a linear pipeline: detect changes → analyze AST → build payload → serve via MCP → Claude writes AGENTS.md.

## Architecture & Data Flow

### Module inventory

- `src/agents_md_mcp/` — Core package: MCP server, analysis pipeline, caching, and all domain logic.
- `src/agents_md_mcp/languages/` — Per-language AST analyzer implementations behind a common abstract interface.
- `tests/` — Pytest unit and integration test suite covering the full pipeline.
- `tests/fixtures/` — Sample source files (`.py`, `.ts`, `.go`, `.cs`) used as AST parsing targets in tests.
- `docs/` — Project documentation and design notes.
- `.claude/` — Claude Code configuration (settings, hooks).

### Data flow

```
change_detector  →  ast_analyzer  →  context_builder  →  server (MCP tools)  →  Claude writes AGENTS.md
     ↕                                      ↕
   cache                               project_scanner / build_system / gitignore
```

1. `change_detector.detect_changes` compares the current git state against the cache to produce a list of `FileChange` objects.
2. `ast_analyzer.analyze_changes` dispatches each changed file to the appropriate `LanguageAnalyzer`, returning a `dict[str, FileAnalysis]`.
3. `context_builder.build_payload` merges new analyses with cached data into a structured JSON payload:
   - Filters out generated files (`_is_generated`) and trivial entries (no methods/deps/implements/decorators)
   - Aggregates directories above a dynamic threshold into directory summaries
   - Deduplicates repeated method signatures into a `method_patterns` lookup registry
   - Strips per-entry `language` field (already in metadata) and noise decorators
4. `server.scan_codebase` (MCP tool) orchestrates the above, serializes to compact JSON for large payloads (>300kb), and returns instructions to the AI client.
5. The client calls `server.read_payload_chunk` repeatedly (line-based chunking for pretty JSON, byte-based for compact) to retrieve the payload, then writes `AGENTS.md`.

## Conventions & Patterns

### Adding a new language analyzer

Each supported language has exactly one analyzer class in `src/agents_md_mcp/languages/<language>.py`:

- Class name: `<Language>Analyzer` extending `LanguageAnalyzer` (ABC from `languages/base.py`).
- Must implement two abstract methods: `language_key() -> str` and `analyze(file_path, source) -> FileAnalysis`.
- Register the new analyzer in `ast_analyzer.build_analyzer` so it can be resolved by language key.
- Add at least one fixture file in `tests/fixtures/sample.<ext>` for parser testing.

### Models

All data structures are Pydantic `BaseModel` subclasses defined in `src/agents_md_mcp/models.py`. Add new models there — never define inline dataclasses elsewhere.

### MCP tools

The two public MCP tools live exclusively in `src/agents_md_mcp/server.py` and are decorated with `@mcp.tool`. Business logic must not live in `server.py`; delegate to the appropriate pipeline module.

### Cache

Cache I/O is fully encapsulated in `src/agents_md_mcp/cache.py`. All other modules receive `CacheData | None` — they never read/write the cache file directly.

### Payload size management

The payload must stay under ~300kb to fit in LLM context windows. Size is controlled at multiple layers:

- **`symbol_utils.py`**: Per-file caps (`_MAX_METHODS_PER_SYMBOL=10`, `_MAX_SYMBOLS_PER_FILE=10`), generated file detection (`_is_generated`), trivial entry stripping, noise decorator filtering (`_filter_decorators`).
- **`aggregator.py`**: Directory-level collapsing when files exceed the aggregation threshold, DTO directory detection, outlier capping.
- **`context_builder.py`**: Dynamic aggregation threshold (`_effective_threshold` — auto-lowers for projects >400 files), method signature deduplication (`_deduplicate_methods`), per-entry language stripping.
- **`build_system.py`**: Common dotnet package deduplication across `.csproj` files.
- **`server.py`**: Compact JSON serialization (no indent, minimal separators) for payloads >300kb, with byte-based chunking (`CHUNK_BYTES=50kb`).

## Environment Variables

| Variable | Purpose |
|----------|---------|
| `PYPI_TOKEN` | Authentication token used to publish the package to PyPI via `publish.sh`. |

## Setup Commands

```bash
uv sync
```

The MCP server bootstrap is `src/agents_md_mcp/server.py`. The `main()` function is the entry point registered in `pyproject.toml`.

## Development Workflow

Run the CLI entry point:

```bash
uv run agents-md-generator
```

## Testing Instructions

```bash
uv run pytest
```

Tests live in `tests/` (Python). Fixture source files for AST parsing are in `tests/fixtures/`.

## Keeping AGENTS.md Up to Date

This file is generated and maintained by the `agents-md-generator` MCP tool.
**Never edit it manually.** To regenerate after code changes, ask your AI assistant:

> "Update the AGENTS.md for this project"

The assistant will invoke the `scan_codebase` tool automatically, perform an
incremental scan of changed files, and rewrite only the affected sections.
To force a full rescan from scratch: "Regenerate the AGENTS.md from scratch".
