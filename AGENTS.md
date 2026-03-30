# AGENTS.md — agents-md-generator

## Project Overview

`agents-md-generator` is a Python-based MCP (Model Context Protocol) server designed to generate and maintain `AGENTS.md` files—architectural context documents for AI coding agents. It uses Tree-sitter for high-fidelity AST analysis across multiple languages (Python, TypeScript, Go, C#) and `uv` for dependency management. The system operates as an incremental, cache-aware pipeline that transforms a codebase into a structured payload for AI assistants to perform maintenance tasks without manual exploration.

## Tech Stack

- **Backend**: Python, MCP SDK, Pydantic, Tree-sitter.
- **Package Management**: `uv`.
- **Infrastructure**: GitHub Actions (CI/CD), Pytest.
- **Configuration**: `pyproject.toml`.

## Project Map

| Module | Purpose |
| :--- | :--- |
| `src/agents_md_mcp/` | Core analysis pipeline, caching logic, and MCP server implementation. |
| `src/agents_md_mcp/languages/` | Language-specific AST analyzer implementations (Python, Go, TypeScript, C#). |
| `tests/` | Unit and integration test suite covering the full analysis pipeline. |
| `tests/fixtures/` | Sample source files in various languages used as AST parsing targets. |
| `docs/` | Architectural design notes and technical documentation. |
| `.gemini/` | Configuration and settings for the Gemini CLI agent. |
| `.claude/` | Local settings and hooks for Claude Code. |
| `.github/workflows/` | CI/CD workflow definitions for automated testing and releases. |

## Architecture & Data Flow

The system follows a linear pipeline architecture: `project_scanner` identifies files, `change_detector` determines analysis targets via a git-based cache, `ast_analyzer` parses source code into structured symbols, `aggregator` collapses large directories, and `context_builder` assembles the final JSON payload.

- **Architectural Anchors**:
    - `LanguageAnalyzer`: The abstract base class in `src/agents_md_mcp/languages/base.py` that all language-specific analyzers must implement.
    - `ProjectConfig`: Loaded via `load_config` in `src/agents_md_mcp/config.py`, governing the scan scope and language mapping.
- **Routing**: The MCP interface is defined in `src/agents_md_mcp/server.py` using `@mcp.tool` decorators, which orchestrate the internal modules.

## Key Models

Domain models and DTOs (Data Transfer Objects) are defined in `src/agents_md_mcp/models.py` and `src/agents_md_mcp/connectors.py`. They follow a pattern of using `dataclass(frozen=True, slots=True)` or Pydantic models to ensure data integrity as it flows through the pipeline.

## Backend Guidelines

- **Language Analyzers**: To support a new language, create a class inheriting from `LanguageAnalyzer` in `src/agents_md_mcp/languages/`. You must implement `language_key()` and `analyze()`.
- **MCP Tools**: Public tools (`scan_codebase`, `read_payload_chunk`) must reside in `server.py` and use the `@mcp.tool` decorator.
- **Caching**: All persistent state is managed via `cache.py`. Modules should interact with `CacheData` objects to support incremental scans.
- **Error Handling**: Follow the pattern in `server.py` where exceptions are caught at the tool level and returned as JSON error messages to the client.

## Conventions & Patterns

- **Analyzer Naming**: Files in `src/agents_md_mcp/languages/` are named after the language (e.g., `python.py`) and contain a `<Language>Analyzer` class.
- **Test Organization**: Tests mirror the source structure in the `tests/` directory. Fixtures for parser testing are strictly kept in `tests/fixtures/`.
- **Connector Files**: Agent-specific connectors (e.g., `CLAUDE.md`, `.cursorrules`) are automatically updated via `connectors.py` to point to `AGENTS.md`.

## How to Add a Feature

1. **New Language Support**:
   - Create `src/agents_md_mcp/languages/<language>.py`.
   - Implement `<Language>Analyzer` extending `LanguageAnalyzer`.
   - Register the new analyzer in `src/agents_md_mcp/ast_analyzer.py`.
   - Add a sample file in `tests/fixtures/sample.<ext>`.
2. **New MCP Tool**: Add a decorated function to `src/agents_md_mcp/server.py` and define its input/output models in `models.py`.

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
- **Conventions**: Integration tests verify AST extraction accuracy using the multilingual samples in `tests/fixtures/`.

## Keeping AGENTS.md Up to Date

This file is generated and maintained by the `agents-md-generator` MCP tool.
**Never edit it manually.** To regenerate after code changes, ask your AI assistant:

> "Update the AGENTS.md for this project"

The assistant will invoke the `scan_codebase` tool automatically, perform an
incremental scan of changed files, and rewrite only the affected sections.
To force a full rescan from scratch: "Regenerate the AGENTS.md from scratch".
