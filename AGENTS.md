# agents-md-generator

## Project Overview

MCP (Model Context Protocol) server that analyzes codebases using tree-sitter AST parsing and returns a structured payload for generating `AGENTS.md` files. Claude Code interprets the payload and writes or updates the file.

**Key technologies:**
- Python 3.x with [FastMCP](https://github.com/jlowin/fastmcp) as the MCP server framework
- [tree-sitter](https://tree-sitter.github.io/) for language-agnostic AST analysis
- Pydantic v2 for data models
- Incremental scanning via a local cache keyed to the current git commit

**Supported languages for analysis:** Python, TypeScript, JavaScript, Go, C#

**Architecture:**

```
src/agents_md_mcp/
├── server.py           # FastMCP entry point — exposes generate_agents_md tool
├── config.py           # ProjectConfig: file extension → language mapping, load_config()
├── change_detector.py  # detect_changes(): git-aware file diff, gitignore-aware
├── ast_analyzer.py     # analyze_changes(), diff_analysis(), classify_impact()
├── context_builder.py  # build_payload(): assembles final JSON payload for Claude
├── cache.py            # Incremental scan cache (commit-keyed JSON)
├── models.py           # Pydantic models: FileChange, SymbolInfo, FileAnalysis, CacheData…
├── gitignore.py        # load_gitignore_spec(), is_gitignored()
└── languages/
    ├── base.py         # LanguageAnalyzer ABC
    ├── python.py       # PythonAnalyzer
    ├── typescript.py   # TypeScriptAnalyzer, JavaScriptAnalyzer
    ├── go.py           # GoAnalyzer
    └── csharp.py       # CSharpAnalyzer
```

---

## Setup Commands

```bash
# Install the package with all dependencies
pip install -e .

# Or with uv (recommended)
uv sync
```

Configuration is optional. To customize scanning behaviour, copy the example config:

```bash
cp .agents-config.example.json .agents-config.json
```

---

## Development Workflow

Run the MCP server directly:

```bash
python run.py
```

Or via the installed entry point (defined in `pyproject.toml`):

```bash
agents-md-generator
```

---

## Testing Instructions

```bash
# Run the full test suite
pytest tests/

# Run with verbose output
pytest tests/ -v

# Run a specific test file
pytest tests/test_ast_analyzer.py -v
pytest tests/test_change_detector.py -v
pytest tests/test_context_builder.py -v
pytest tests/test_cache.py -v
pytest tests/test_config.py -v
```

Test fixtures (sample source files used by AST analyzer tests) live in `tests/fixtures/` and cover Python, TypeScript, Go, and C#.

---

## Code Style

Project uses `pyproject.toml` for tooling configuration. Run linting and formatting with:

```bash
# Format code
ruff format src/ tests/

# Lint
ruff check src/ tests/

# Type check
mypy src/
```

---

## MCP Tool Reference

### `generate_agents_md`

Analyzes a codebase and returns a JSON payload for AGENTS.md generation.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `project_path` | `str` | `"."` | Path to the project root |
| `force_full_scan` | `bool` | `false` | Ignore cache and force a full rescan |

**Incremental scans:** On repeat invocations the tool loads a cache from `.agents-md-cache.json` at the project root and only re-analyzes files changed since the last commit. Pass `force_full_scan: true` to bypass this.

---

## Key Conventions

- **Models** are defined in `models.py` as Pydantic `BaseModel` subclasses. Add new data shapes there first.
- **Language analyzers** must extend `LanguageAnalyzer` (ABC in `languages/base.py`) and implement `language_key` and `analyze`. Register them in `ast_analyzer.py`.
- **`_is_excluded`** in `change_detector.py` is also imported by `context_builder.py` — keep its signature stable.
- Cache is invalidated automatically when the git commit hash changes. Manual invalidation: delete `.agents-md-cache.json`.
