<!-- mcp-name: io.github.nushey/agents-md-generator -->
# agents-md-generator

MCP server that analyzes codebases with [tree-sitter](https://tree-sitter.github.io/) and generates [`AGENTS.md`](https://agents.md/) files.

Compatible with any MCP-capable client: Claude Code, Gemini CLI, Cursor, Windsurf, and others.

**How it works:** The server exposes three tools with a clear separation of concerns. `generate_agents_md` is the main entry point — it runs the analysis pipeline internally, embeds writing rules into the payload, and returns chunked read instructions to your client. `scan_codebase` is a standalone context tool for when you want deep codebase understanding without generating any file. `read_payload_chunk` streams the payload back in chunks regardless of which tool produced it. No large data travels over the MCP wire.

## Supported Languages

Python · C# · TypeScript · JavaScript · Go

---

## Installation

See [INSTALLATION.md](https://github.com/nushey/agents-md-generator/blob/main/INSTALLATION.md) for the full guide including prerequisites and troubleshooting.

**Requirements:** Python 3.11+, [uv](https://github.com/astral-sh/uv), Git, and any MCP-compatible client.

### Claude Code

```bash
claude mcp add agents-md uvx agents-md-generator
```

Or add it manually to `~/.claude.json` (Linux/macOS) or `%USERPROFILE%\.claude.json` (Windows):

```json
{
  "mcpServers": {
    "agents-md": {
      "command": "uvx",
      "args": ["agents-md-generator"]
    }
  }
}
```

### Gemini CLI

Add it to `~/.gemini/settings.json`:

```json
{
  "mcpServers": {
    "agents-md": {
      "command": "uvx",
      "args": ["agents-md-generator"]
    }
  }
}
```

### Other MCP clients (Cursor, Windsurf, etc.)

The server uses stdio transport. Add this entry to your client's MCP config under `mcpServers`:

```json
"agents-md": {
  "command": "uvx",
  "args": ["agents-md-generator"]
}
```

Restart your client — `uvx` downloads the package automatically on first run.

---

## Usage

Once registered, ask your AI client:

> "Generate the AGENTS.md for this project"

The client will call `generate_agents_md` automatically. To scan a different directory:

> "Generate the AGENTS.md for the project at /path/to/project"

### Tools

| Tool | Purpose |
|------|---------|
| `generate_agents_md` | Main entry point. Runs the pipeline internally, embeds writing rules into the payload, and returns chunked read instructions. Use this to create or update `AGENTS.md`. |
| `scan_codebase` | Standalone context tool. Analyzes the codebase and returns a pure data payload with no `AGENTS.md` mandate. Use this when you need architectural context for any other task. |
| `read_payload_chunk` | Streams the payload written by either tool in chunks until `has_more` is false. |

### Tool Parameters

**`generate_agents_md`**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `project_path` | string | `"."` | Path to the project root |

**`scan_codebase`**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `project_path` | string | `"."` | Path to the project root |
| `force_full_scan` | boolean | `true` | Ignore cache and rescan everything. Defaults to `true` — direct calls always perform a full scan. |

**`read_payload_chunk`**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `project_path` | string | `"."` | Must match the path used in the preceding tool call |
| `chunk_index` | integer | — | Zero-based chunk index. Increment until `has_more` is false |

---

## What Gets Generated

The generated `AGENTS.md` follows the [agents.md](https://agents.md/) open standard. It is written as a **README for AI agents**, not as documentation for humans. Sections include:

- **Project Overview** — tech stack and top-level architecture shape
- **Architecture & Data Flow** — detected layers or domains with data flow direction
- **Conventions & Patterns** — naming rules, export contracts, import rules, and how to add new entities end-to-end
- **Environment Variables** — variables detected in source files and `.env.example`
- **Setup Commands** — exact install and run commands from `package.json`, `Makefile`, etc.
- **Development Workflow** — build, watch, and dev server commands
- **Testing Instructions** — test commands and framework info (if detected)
- **Code Style** — lint/format commands (if config files detected)
- **Build and Deployment** — CI pipeline info (if detected)

Sections with no detected data are omitted entirely.

---

## How Incremental Scanning Works

1. **First run (cold start):** All git-tracked source files are parsed with tree-sitter and cached
2. **Subsequent runs:** Only files whose SHA-256 hash changed since the last scan are re-parsed
3. **Semantic diff:** For modified files, only changed public symbols are included in the payload
4. **No source changes?** The tool stops and asks whether you want to improve the existing `AGENTS.md` content anyway
5. **Private symbols and test file internals** are excluded from both cache and payload — only the public API surface matters for `AGENTS.md`

### How Large Payloads Are Streamed

For large codebases the analysis payload can be too big to return inline over the MCP wire. The server handles this transparently through `read_payload_chunk`.

**`generate_agents_md` flow:**

1. `generate_agents_md` runs the pipeline internally, writes the payload to disk (including `AGENTS.md` writing rules), and returns `total_chunks` with read instructions
2. The client calls `read_payload_chunk(project_path, chunk_index=0)`, then increments `chunk_index` until `has_more` is false
3. The client concatenates all `data` fields — the payload contains the rules and analysis data needed to write `AGENTS.md`
4. The payload file is automatically deleted after the last chunk is read

**`scan_codebase` flow** (pure context, no `AGENTS.md` mandate):

1. `scan_codebase` runs the analysis and writes a pure data payload to disk
2. Same chunked read via `read_payload_chunk`
3. The client uses the payload for any purpose — code review, planning, Q&A

This flow is pure MCP — no filesystem access required from the client side. Any MCP-compatible client can follow it.

### Cache and Payload Location

All runtime artifacts are stored **outside your project**, in the user cache directory:

```
~/.cache/agents-md-generator/<project-hash>/cache.json  ← incremental scan cache
```

The `<project-hash>` is a SHA-256 of the project's absolute path — unique per project. Nothing is written to your repository.

> **Note:** The server also writes a temporary `payload.json` to this directory during analysis, but it is managed entirely by the `read_payload_chunk` tool and deleted automatically after the last chunk is read. You never need to access it directly.

---

## Project Configuration

Create `.agents-config.json` at your project root to customize behavior. This file is optional — all fields have defaults.

```json
{
  "project_size": "medium",
  "exclude": [
    "**/node_modules/**",
    "**/bin/**",
    "**/obj/**",
    "**/.git/**",
    "**/dist/**",
    "**/build/**",
    "**/__pycache__/**",
    "**/*.min.js",
    "**/*.min.css",
    "**/*.bundle.js",
    "**/vendor/**",
    "**/packages/**",
    "**/.venv/**",
    "**/venv/**",
    "**/bower_components/**",
    "**/app/lib/**",
    "**/wwwroot/lib/**",
    "**/wwwroot/libs/**",
    "**/static/vendor/**",
    "**/public/vendor/**",
    "**/assets/vendor/**",
    "**/site-packages/**"
  ],
  "include": [],
  "languages": "auto",
  "agents_md_path": "./AGENTS.md",
  "max_file_size_bytes": 1048576
}
```

### Options

| Key | Default | Description |
|-----|---------|-------------|
| `project_size` | `"medium"` | Project scale — tunes all internal caps and thresholds (see [Project Size Profiles](#project-size-profiles)) |
| `exclude` | (see above) | Glob patterns to exclude from analysis |
| `include` | `[]` | If non-empty, only analyze files matching these patterns |
| `languages` | `"auto"` | `"auto"` detects all supported languages, or pass a list like `["typescript", "python"]` |
| `agents_md_path` | `"./AGENTS.md"` | Output path for the generated file |
| `max_file_size_bytes` | `1048576` | Files larger than this are skipped (default: 1 MB) |

You can commit `.agents-config.json` to share settings with your team.

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `AGENTS_MD_LOG_LEVEL` | `INFO` | Server log verbosity. Set to `DEBUG` to see per-file analysis details. Valid values: `DEBUG`, `INFO`, `WARNING`, `ERROR` |

### Project Size Profiles

The `project_size` setting controls how aggressively the payload is compressed. A single knob tunes all internal caps — methods per class, symbols per file, directory aggregation, route caps, tree depth, and impact filtering.

| Profile | Lines (guidance) | Impact filter | Description |
|---------|-----------------|---------------|-------------|
| `"small"` | 0–15k | medium | Generous caps — nearly everything is included. Best for small projects where full visibility matters. |
| `"medium"` _(default)_ | 15k–50k | medium | Balanced caps suitable for most projects. |
| `"large"` | 50k+ | high | Aggressive compression — only structural/breaking changes in diffs, more directory collapsing, tighter symbol caps. |

**Detailed profile values:**

| Constant | Small | Medium | Large |
|----------|-------|--------|-------|
| Methods per class | 30 | 12 | 8 |
| Symbols per file | 40 | 20 | 10 |
| Dir aggregation threshold | 20 | 10 | 5 |
| Files per layer (before overflow) | 15 | 8 | 5 |
| Aggregation sample size | 5 | 4 | 3 |
| Route controllers cap | 30 | 15 | 10 |
| Routes per controller | 15 | 8 | 5 |
| Go handlers cap | 15 | 8 | 5 |
| Directory tree depth | 4 | 3 | 2 |
| Impact filter | medium | medium | high |

---

## What the Analysis Detects

### Environment Variables

The server scans all source files for environment variable references using language-specific patterns:

| Language | Pattern detected |
|----------|-----------------|
| JavaScript / TypeScript | `process.env.VAR_NAME` |
| Python | `os.environ['VAR']`, `os.getenv('VAR')` |
| Go | `os.Getenv("VAR")` |
| Ruby | `ENV['VAR']` |
| Rust | `env!("VAR")`, `var("VAR")` |

It also parses `.env.example`, `.env.template`, and `.env.sample` files at the project root.

### Entry Points

Files named `index`, `main`, `app`, `server`, `program`, `bootstrap`, or `startup` (with any supported extension) are detected as entry points and annotated with their inferred role (e.g., "HTTP server bootstrap", "Electron main process").

### Public API Surface

Tree-sitter parses each source file and extracts public symbols — classes, functions, methods, interfaces — filtering out private/protected members and underscore-prefixed symbols. For classes and structs, constructors (when they have parameters) and public properties are also included, revealing dependency injection patterns and data shapes. Interface methods are always included as they define the public contract. These are used to detect naming conventions, DI patterns, and export contracts across layers.

### Architectural Distillation

For large codebases, the tool applies several heuristics to ensure the payload remains high-signal:

- **Boilerplate Suppression:** Common directories like `Migrations`, `bin`, `obj`, and `Properties` are automatically flagged and collapsed in the project structure, preventing them from bloating the directory listing.
- **Low-Entropy Summarization:** Files that primarily contain data structures (DTOs, Entities) with no logic methods are "minified". Instead of listing every property, the tool provides a high-level summary (e.g., "Contains 25 DTO classes").
- **Semantic Clustering:** The aggregator groups these minified summaries at the directory level, allowing the consuming AI to understand entire data layers through a single line of signal.
- **Instruction Embedding:** When called via `generate_agents_md`, writing rules are embedded directly in the payload so the AI agent reads the "Rules of Engagement" before processing the code architecture. Direct `scan_codebase` calls return pure data with no mandate.

---

## Credits

AGENTS.md format based on the open [agents.md](https://agents.md/) standard.
