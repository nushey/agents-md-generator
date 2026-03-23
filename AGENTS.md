# AGENTS.md — agents-md-generator

## Project Overview

`agents-md-generator` is a Python MCP (Model Context Protocol) server that analyzes codebases using tree-sitter AST parsing and generates `AGENTS.md` files for AI coding agents. It supports Python, TypeScript, JavaScript, Go, and C#. The architecture is a sequential pipeline: change detection → AST analysis → payload assembly → MCP tool exposure, with an incremental caching layer to avoid full rescans on every call.

---

## Architecture & Data Flow

### Module Inventory

- `src/agents_md_mcp/` — Core package: MCP server, pipeline orchestration, caching, config, and payload assembly.
- `src/agents_md_mcp/languages/` — Language-specific AST analyzers, one per supported language, all extending a shared abstract base.
- `tests/` — Pytest test suite covering all pipeline modules.
- `tests/fixtures/` — Sample source files in each supported language, used as AST parsing inputs in tests.
- `docs/` — Project documentation.

### Data Flow

```
change_detector  →  ast_analyzer  →  context_builder  →  server (MCP tools)
     ↑                   ↑
   cache.py          languages/
   config.py
```

1. `change_detector.detect_changes` compares the current state against the cache to produce a list of `FileChange` objects.
2. `ast_analyzer.analyze_changes` selects the appropriate `LanguageAnalyzer` via `build_analyzer` and extracts public symbols from changed files.
3. `context_builder.build_payload` merges new analyses with cached data into a structured JSON payload.
4. `server.py` exposes two MCP tools (`generate_agents_md`, `get_payload_chunk`) that orchestrate the pipeline and stream the payload back to the caller in chunks.

---

## Conventions & Patterns

### Adding a New Language Analyzer

Each supported language has exactly one analyzer class in `src/agents_md_mcp/languages/<language>.py` following this contract:

1. Create `src/agents_md_mcp/languages/<language>.py`.
2. Define a class `<Language>Analyzer(LanguageAnalyzer)` implementing `language_key` (returns the string key) and `analyze` (returns a `FileAnalysis`).
3. Register it in `ast_analyzer.build_analyzer` so it can be resolved by language key.

JavaScript reuses the TypeScript analyzer via inheritance (`JavaScriptAnalyzer(TypeScriptAnalyzer)`) — apply the same pattern for closely related languages.

### Models

All data structures are Pydantic `BaseModel` subclasses defined in `src/agents_md_mcp/models.py`. Add new models there; do not define them inline in other modules.

### MCP Tools

MCP tools live exclusively in `src/agents_md_mcp/server.py` and are registered with the `@mcp.tool` decorator. Tool input schemas are Pydantic models defined in `models.py`.

### Chunk-Based Payload Transfer

The payload is written to `.agents-payload.json` and read back in indexed chunks via `get_payload_chunk`. The file is deleted after the last chunk is consumed. This pattern avoids large MCP wire payloads — preserve it when adding new data to the payload.

---

## Environment Variables

| Variable | Purpose |
|---|---|
| `PYPI_TOKEN` | PyPI API token used by `publish.sh` to publish the package. |

---

## Setup Commands

```bash
uv sync
```

The server bootstrap is `src/agents_md_mcp/server.py`. To run the MCP server:

```bash
uv run agents-md-generator
```

---

## Testing Instructions

```bash
uv run pytest
```

Tests live in `tests/` (81 test functions across 7 modules). Fixtures for AST parsing are in `tests/fixtures/` — one sample file per supported language.

---

## Keeping AGENTS.md Up to Date

This file is generated and maintained by the `agents-md-generator` MCP tool.
**Never edit it manually.** To regenerate after code changes, ask Claude Code:

> "Update the AGENTS.md for this project"

Claude will invoke the `generate_agents_md` tool automatically, perform an
incremental scan of changed files, and rewrite only the affected sections.
To force a full rescan from scratch: "Regenerate the AGENTS.md from scratch".
