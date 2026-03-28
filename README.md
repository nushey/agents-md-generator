<!-- mcp-name: io.github.nushey/agents-md-generator -->
# agents-md-generator

MCP server that analyzes codebases with [tree-sitter](https://tree-sitter.github.io/) and generates [`AGENTS.md`](https://agents.md/) files.

Compatible with any MCP-capable client: Claude Code, Gemini CLI, Cursor, Windsurf, and others.

**How it works:** The server does all the heavy lifting locally — AST parsing, incremental change detection, environment variable scanning, entry point detection. It writes a compact structured payload to disk and returns step-by-step instructions to your AI client. The client reads the payload and writes `AGENTS.md`. No large data travels over the MCP wire.

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

The client will call `generate_agents_md` automatically.

### Tool Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `project_path` | string | `"."` | Path to the project root |
| `force_full_scan` | boolean | `false` | Ignore cache and rescan everything from scratch |

> **Note on `force_full_scan`:** Use this only when explicitly requested. When asking Claude to _improve_ or _update_ an existing `AGENTS.md`, leave it as `false` — the incremental scan already provides all the data needed.

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

For large codebases the analysis payload can be too big to return inline over the MCP wire. The server handles this transparently through a second tool: `get_payload_chunk`.

**Flow:**

1. `generate_agents_md` runs the full analysis, writes the payload to disk, and returns a small response with `total_chunks` and instructions
2. The client calls `get_payload_chunk(project_path, chunk_index=0)`, then increments `chunk_index` until the response contains `has_more: false`
3. The client concatenates all `data` fields in order and parses the result as JSON
4. The payload file is automatically deleted after the last chunk is read

This flow is pure MCP — no filesystem access required from the client side. Any MCP-compatible client can follow it.

### Cache and Payload Location

All runtime artifacts are stored **outside your project**, in the user cache directory:

```
~/.cache/agents-md-generator/<project-hash>/cache.json  ← incremental scan cache
```

The `<project-hash>` is a SHA-256 of the project's absolute path — unique per project. Nothing is written to your repository.

> **Note:** The server also writes a temporary `payload.json` to this directory during analysis, but it is managed entirely by the `get_payload_chunk` tool and deleted automatically after the last chunk is read. You never need to access it directly.

---

## Project Configuration

Create `.agents-config.json` at your project root to customize behavior. This file is optional — all fields have defaults.

```json
{
  "impact_threshold": "medium",
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
  "max_file_size_bytes": 1048576,
  "dir_aggregation_threshold": 8
}
```

### Options

| Key | Default | Description |
|-----|---------|-------------|
| `impact_threshold` | `"medium"` | Minimum change impact to include in incremental payload (see [Impact Threshold](#impact-threshold)) |
| `exclude` | (see above) | Glob patterns to exclude from analysis |
| `include` | `[]` | If non-empty, only analyze files matching these patterns |
| `languages` | `"auto"` | `"auto"` detects all supported languages, or pass a list like `["typescript", "python"]` |
| `agents_md_path` | `"./AGENTS.md"` | Output path for the generated file |
| `max_file_size_bytes` | `1048576` | Files larger than this are skipped (default: 1 MB) |
| `dir_aggregation_threshold` | `8` | Directories with this many or more files of the same language are collapsed into a single directory summary instead of per-file entries. Reduces payload size significantly on large codebases. Set to a high number to disable. |

You can commit `.agents-config.json` to share exclusion rules and thresholds with your team.

### Impact Threshold

The `impact_threshold` controls which symbol changes are included in incremental scan payloads. Changes below the threshold are silently ignored — `AGENTS.md` is not regenerated for them.

| Change type | Symbol kind | Extra condition | Impact |
|---|---|---|---|
| any | any | Has HTTP decorator (`@HttpGet`, `@app.route`, `@Get`, …) | `high` |
| `added` or `removed` | `class`, `interface`, `struct` | — | `high` |
| `removed` | `method` | public | `high` |
| `modified` | any | public | `medium` |
| `added` | `function` or `method` | public | `medium` |
| any | any | none of the above | `low` |

**Choosing a threshold:**

- `"high"` — Only regenerate `AGENTS.md` for breaking or structural changes. Best for large, stable codebases where minor additions are frequent.
- `"medium"` _(default)_ — Regenerate when the public API surface grows or changes. Suitable for most projects.
- `"low"` — Regenerate on any public symbol change. Best for early-stage projects where the architecture is still evolving.

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
- **Instruction Prioritization:** Foundation mandates (instructions) are placed at the very top of the payload, ensuring the AI agent understands the project's "Rules of Engagement" before processing the code architecture.

---

## Credits

AGENTS.md format based on the open [agents.md](https://agents.md/) standard.
