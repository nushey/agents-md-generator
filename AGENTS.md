# AGENTS.md — agents-md-generator

## Project Overview

`agents-md-generator` is a Python-based MCP (Model Context Protocol) server designed to generate and maintain `AGENTS.md` files—context documents for AI coding agents. It utilizes Tree-sitter for high-fidelity AST analysis across multiple languages and `uv` for dependency management. The system operates as an incremental, cache-aware data pipeline that scans codebases, detects changes, and builds a structured payload for AI assistants to consume.

## Tech Stack

- **Backend**: Python, MCP SDK, Pydantic, Tree-sitter (with parsers for C#, Go, Java, JavaScript, Python, Ruby, Rust, and TypeScript).
- **Package Management**: `uv`.
- **Infrastructure**: GitHub Actions (CI/CD workflows for testing and releases).
- **Testing**: Pytest with `pytest-asyncio`.
- **Configuration**: `pyproject.toml`.

## Project Map

| Module | Purpose |
| :--- | :--- |
| `src/agents_md_mcp/` | Core package containing the analysis pipeline, caching logic, and MCP server implementation. |
| `src/agents_md_mcp/languages/` | Language-specific AST analyzer implementations behind a common interface. |
| `tests/` | Pytest suite covering unit and integration tests for the full pipeline. |
| `tests/fixtures/` | Sample source files in various languages used as AST parsing targets in tests. |
| `docs/` | Technical documentation and architectural design notes. |
| `.gemini/` | Configuration and settings for the Gemini CLI agent. |
| `.claude/` | Local settings and hooks for Claude Code. |

## Architecture & Data Flow

The system follows a linear pipeline architecture: `project_scanner` identifies files, `change_detector` determines analysis targets via a git-based cache, `ast_analyzer` parses source code into structured symbols, `aggregator` collapses large directories to manage context size, and `context_builder` assembles the final JSON payload.

- **Architectural Anchors**:
    - `LanguageAnalyzer`: The abstract base class in `src/agents_md_mcp/languages/base.py` that all language-specific analyzers (e.g., `PythonAnalyzer`, `GoAnalyzer`) must implement.
    - `BaseModel`: All domain models and DTOs in `src/agents_md_mcp/models.py` inherit from Pydantic's `BaseModel` for validation and serialization.
- **Routing**: The MCP tool interface is defined in `src/agents_md_mcp/server.py` using `@mcp.tool` decorators, which orchestrate the pipeline modules.

## Key Models

Domain models and Data Transfer Objects (DTOs) live in `src/agents_md_mcp/models.py` and `src/agents_md_mcp/connectors.py`. They follow a strict pattern of inheriting from Pydantic's `BaseModel`. This layer ensures that the complex AST data is consistently shaped as it moves from the analyzers to the final payload.

## Backend Guidelines

- **Language Analyzers**: To support a new language, create a class inheriting from `LanguageAnalyzer` in `src/agents_md_mcp/languages/`. You must implement `language_key()` and `analyze()`.
- **MCP Tools**: Public tools (`scan_codebase`, `read_payload_chunk`) must reside in `server.py`. Logic should be delegated to specialized modules like `cache.py` or `ast_analyzer.py`.
- **Caching**: All persistent state is managed via `cache.py`. Modules should interact with `CacheData` objects rather than the filesystem directly.
- **Size Management**: The pipeline enforces caps on the number of symbols and methods per file to ensure payloads remain within LLM context limits.

## Conventions & Patterns

- **Analyzer Naming**: Files in `src/agents_md_mcp/languages/` are named after the language (e.g., `python.py`) and contain a corresponding `<Language>Analyzer` class.
- **Test Organization**: Tests mirror the source structure in the `tests/` directory. Fixtures for parser testing are strictly kept in `tests/fixtures/`.
- **Feature Addition**: Adding a new language follows a predictable pattern of creating an analyzer, registering it in `ast_analyzer.py`, and adding a corresponding fixture.

## How to Add a Feature

1. **New Language Analyzer**:
   - Create `src/agents_md_mcp/languages/<language>.py`.
   - Implement `<Language>Analyzer` extending `LanguageAnalyzer`.
   - Register the new analyzer in `src/agents_md_mcp/ast_analyzer.py`.
   - Add a sample file in `tests/fixtures/sample.<ext>`.
2. **New Model**: Add a Pydantic `BaseModel` to `src/agents_md_mcp/models.py`.

## Environment Variables

| Variable | Purpose |
| :--- | :--- |
| `PYPI_TOKEN` | Authentication token used to publish the package to PyPI via `publish.sh`. |

## Setup & Build Commands

```bash
uv sync
```

The bootstrap entry point is `src/agents_md_mcp/server.py` via the `main()` function, which is registered as the `agents-md-generator` script.

## Testing

- **Framework**: Pytest.
- **Run Tests**:
  ```bash
  uv run pytest
  ```
- **Conventions**: Integration tests use the source files in `tests/fixtures/` to verify AST extraction accuracy.

## Keeping AGENTS.md Up to Date

This file is generated and maintained by the `agents-md-generator` MCP tool.
**Never edit it manually.** To regenerate after code changes, ask your AI assistant:

> "Update the AGENTS.md for this project"

The assistant will invoke the `scan_codebase` tool automatically, perform an
incremental scan of changed files, and rewrite only the affected sections.
To force a full rescan from scratch: "Regenerate the AGENTS.md from scratch".
