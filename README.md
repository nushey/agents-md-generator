<!-- mcp-name: io.github.nushey/agents-md-generator -->

<div align="center">

# agents-md-generator

**MCP server that analyzes codebases with [tree-sitter](https://tree-sitter.github.io/) and generates [`AGENTS.md`](https://agents.md/) files.**

[![PyPI](https://img.shields.io/pypi/v/agents-md-generator?color=3775A9&logo=pypi&logoColor=white)](https://pypi.org/project/agents-md-generator/)
[![Python](https://img.shields.io/badge/python-3.11%2B-3776AB?logo=python&logoColor=white)](https://pypi.org/project/agents-md-generator/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](https://github.com/nushey/agents-md-generator/blob/main/LICENSE)
[![MCP](https://img.shields.io/badge/MCP-server-black?logo=modelcontextprotocol&logoColor=white)](https://modelcontextprotocol.io/)

Python · C# · TypeScript · JavaScript · Go

[Installation](#installation) ·
[Usage](#usage) ·
[Configuration](#project-configuration) ·
[How It Works](#how-incremental-scanning-works) ·
[Contributing](https://github.com/nushey/agents-md-generator/blob/main/CONTRIBUTING.md)

</div>

---

Compatible with any MCP-capable client: **Claude Code**, **Gemini CLI**, **Cursor**, **Windsurf**, **Codex CLI**, and others.

The server exposes three tools with a clear separation of concerns:

- **`generate_agents_md`** — main entry point. Runs the analysis pipeline internally, embeds writing rules into the payload, and returns chunked read instructions to your client.
- **`scan_codebase`** — standalone context tool for when you want deep codebase understanding without generating any file.
- **`read_payload_chunk`** — streams the payload back in chunks regardless of which tool produced it.

No large data travels over the MCP wire.

## Table of Contents

- [Installation](#installation)
  - [Option A — pip install + setup wizard](#option-a--pip-install--setup-wizard-recommended)
  - [Option B — uvx](#option-b--uvx-no-install-needed)
- [Usage](#usage)
  - [Tools](#tools)
  - [Tool Parameters](#tool-parameters)
- [What Gets Generated](#what-gets-generated)
- [How Incremental Scanning Works](#how-incremental-scanning-works)
  - [How Large Payloads Are Streamed](#how-large-payloads-are-streamed)
  - [Cache and Payload Location](#cache-and-payload-location)
- [Project Configuration](#project-configuration)
  - [Options](#options)
  - [Environment Variables](#environment-variables)
  - [Project Size Profiles](#project-size-profiles)
- [What the Analysis Detects](#what-the-analysis-detects)
- [Credits](#credits)

---

## Installation

> **Requirements:** Python 3.11+, Git, and any MCP-compatible client.

See **[INSTALLATION.md](https://github.com/nushey/agents-md-generator/blob/main/INSTALLATION.md)** for the full guide including prerequisites and troubleshooting.

### Option A — pip install + setup wizard (recommended)

```bash
pip install agents-md-generator
agents-md-generator setup
```

The setup wizard detects your installed clients, asks whether to configure globally or per-project, and patches the config files automatically. Supports Claude Code, Gemini CLI, Cursor, Windsurf, and Codex CLI.

### Option B — uvx (no install needed)

If you have [uv](https://github.com/astral-sh/uv) installed, `uvx` runs the package without a prior install step. Add the entry manually to your client's MCP config:

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

For Claude Code specifically:

```bash
claude mcp add agents-md -- uvx agents-md-generator
```

> `claude mcp add` defaults to `--scope local` (current project only). Add `-s user` to register it for all projects.

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

<details>
<summary><code>generate_agents_md</code></summary>

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `project_path` | string | `"."` | Path to the project root |

</details>

<details>
<summary><code>scan_codebase</code></summary>

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `project_path` | string | `"."` | Path to the project root |
| `force_full_scan` | boolean | `true` | Ignore cache and rescan everything. Defaults to `true` — direct calls always perform a full scan. |

</details>

<details>
<summary><code>read_payload_chunk</code></summary>

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `project_path` | string | `"."` | Must match the path used in the preceding tool call |
| `chunk_index` | integer | — | Zero-based chunk index. Increment until `has_more` is false |

</details>

---

## What Gets Generated

The generated `AGENTS.md` follows the [agents.md](https://agents.md/) open standard. It is written as a **README for AI agents**, not as documentation for humans. Sections include:

| Section | Contents |
|---------|----------|
| **Project Overview** | Tech stack and top-level architecture shape |
| **Architecture & Data Flow** | Detected layers or domains with data flow direction |
| **Conventions & Patterns** | Naming rules, export contracts, import rules, how to add new entities end-to-end |
| **Environment Variables** | Variables detected in source files and `.env.example` |
| **Setup Commands** | Exact install and run commands from `package.json`, `Makefile`, etc. |
| **Development Workflow** | Build, watch, and dev server commands |
| **Testing Instructions** | Test commands and framework info (if detected) |
| **Code Style** | Lint/format commands (if config files detected) |
| **Build and Deployment** | CI pipeline info (if detected) |

> Sections with no detected data are omitted entirely.

---

## How Incremental Scanning Works

1. **First run (cold start)** — all git-tracked source files are parsed with tree-sitter and cached
2. **Subsequent runs** — only files whose SHA-256 hash changed since the last scan are re-parsed
3. **Semantic diff** — for modified files, only changed public symbols are included in the payload
4. **No source changes?** — the tool stops and asks whether you want to improve the existing `AGENTS.md` content anyway
5. **Private symbols and test file internals** are excluded from both cache and payload — only the public API surface matters for `AGENTS.md`

### How Large Payloads Are Streamed

For large codebases the analysis payload can be too big to return inline over the MCP wire. The server handles this transparently through `read_payload_chunk`.

<details>
<summary><b><code>generate_agents_md</code> flow</b></summary>

1. `generate_agents_md` runs the pipeline internally, writes the payload to disk (including `AGENTS.md` writing rules), and returns `total_chunks` with read instructions
2. The client calls `read_payload_chunk(project_path, chunk_index=0)`, then increments `chunk_index` until `has_more` is false
3. The client concatenates all `data` fields — the payload contains the rules and analysis data needed to write `AGENTS.md`
4. The payload file is automatically deleted after the last chunk is read

</details>

<details>
<summary><b><code>scan_codebase</code> flow</b> (pure context, no <code>AGENTS.md</code> mandate)</summary>

1. `scan_codebase` runs the analysis and writes a pure data payload to disk
2. Same chunked read via `read_payload_chunk`
3. The client uses the payload for any purpose — code review, planning, Q&A

</details>

This flow is pure MCP — no filesystem access required from the client side. Any MCP-compatible client can follow it.

### Cache and Payload Location

All runtime artifacts are stored **outside your project**, in the user cache directory:

```
~/.cache/agents-md-generator/<project-hash>/cache.json  ← incremental scan cache
```

The `<project-hash>` is a SHA-256 of the project's absolute path — unique per project. **Nothing is written to your repository.**

> **Note:** The server also writes a temporary `payload.json` to this directory during analysis, but it is managed entirely by the `read_payload_chunk` tool and deleted automatically after the last chunk is read. You never need to access it directly.

---

## Project Configuration

Create `.agents-config.json` at your project root to customize behavior. This file is optional — all fields have defaults, and you can commit it to share settings with your team.

<details>
<summary><b>Full default configuration</b></summary>

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

</details>

### Options

| Key | Default | Description |
|-----|---------|-------------|
| `project_size` | `"medium"` | Project scale — tunes all internal caps and thresholds (see [Project Size Profiles](#project-size-profiles)) |
| `exclude` | (see above) | Glob patterns to exclude from analysis |
| `include` | `[]` | If non-empty, only analyze files matching these patterns |
| `languages` | `"auto"` | `"auto"` detects all supported languages, or pass a list like `["typescript", "python"]` |
| `agents_md_path` | `"./AGENTS.md"` | Output path for the generated file |
| `max_file_size_bytes` | `1048576` | Files larger than this are skipped (default: 1 MB) |

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

<details>
<summary><b>Detailed profile values</b></summary>

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

</details>

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

- **Boilerplate Suppression** — common directories like `Migrations`, `bin`, `obj`, and `Properties` are automatically flagged and collapsed in the project structure, preventing them from bloating the directory listing.
- **Low-Entropy Summarization** — files that primarily contain data structures (DTOs, Entities) with no logic methods are "minified". Instead of listing every property, the tool provides a high-level summary (e.g., "Contains 25 DTO classes").
- **Semantic Clustering** — the aggregator groups these minified summaries at the directory level, allowing the consuming AI to understand entire data layers through a single line of signal.
- **Instruction Embedding** — when called via `generate_agents_md`, writing rules are embedded directly in the payload so the AI agent reads the "Rules of Engagement" before processing the code architecture. Direct `scan_codebase` calls return pure data with no mandate.

---

## Credits

AGENTS.md format based on the open [agents.md](https://agents.md/) standard.

<div align="center">

**[Back to top](#agents-md-generator)**

Licensed under the [MIT License](https://github.com/nushey/agents-md-generator/blob/main/LICENSE)

</div>
