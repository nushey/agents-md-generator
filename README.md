# agents-md-generator

MCP server that analyzes codebases with [tree-sitter](https://tree-sitter.github.io/) and generates [`AGENTS.md`](https://agents.md/) files.

**How it works:** The server does all the heavy lifting locally — AST parsing, incremental change detection, environment variable scanning, entry point detection. It writes a compact structured payload to disk and returns step-by-step instructions to Claude Code. Claude reads the payload and writes `AGENTS.md`. No large data travels over the MCP wire.

## Supported Languages

Python · C# · TypeScript · JavaScript · Go · Java · Rust · Ruby

---

## Installation

For full step-by-step instructions including prerequisites, platform-specific setup (Linux and Windows), and troubleshooting, see [INSTALLATION.md](./INSTALLATION.md).

### Quick start

```bash
# With uvx (recommended — no virtual env needed)
uvx agents-md-generator

# With pip
pip install agents-md-generator
```

---

## Claude Code Configuration

Add to your `.claude.json`:

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

Or with a local install:

```json
{
  "mcpServers": {
    "agents-md": {
      "command": "python",
      "args": ["-m", "agents_md_mcp.server"]
    }
  }
}
```

---

## Usage

Once registered, ask Claude Code:

> "Generate the AGENTS.md for this project"

Claude will call `generate_agents_md` automatically.

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

### Cache and Payload Location

All runtime artifacts are stored **outside your project**, in the user cache directory:

```
~/.cache/agents-md-generator/<project-hash>/cache.json    ← incremental scan cache
~/.cache/agents-md-generator/<project-hash>/payload.json  ← temporary, deleted after each run
```

The `<project-hash>` is a SHA-256 of the project's absolute path — unique per project. Nothing is written to your repository.

---

## Project Configuration

Create `.agents-config.json` at your project root to customize behavior. This file is optional — all fields have defaults.

```json
{
  "impact_threshold": "medium",
  "exclude": [
    "**/node_modules/**",
    "**/dist/**",
    "**/build/**",
    "**/.git/**",
    "**/bin/**",
    "**/obj/**",
    "**/__pycache__/**",
    "**/*.min.js",
    "**/vendor/**",
    "**/.venv/**"
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
| `impact_threshold` | `"medium"` | Minimum change impact to include in incremental payload (see [Impact Threshold](#impact-threshold)) |
| `exclude` | (see above) | Glob patterns to exclude from analysis |
| `include` | `[]` | If non-empty, only analyze files matching these patterns |
| `languages` | `"auto"` | `"auto"` detects all supported languages, or pass a list like `["typescript", "python"]` |
| `agents_md_path` | `"./AGENTS.md"` | Output path for the generated file |
| `max_file_size_bytes` | `1048576` | Files larger than this are skipped (default: 1 MB) |

You can commit `.agents-config.json` to share exclusion rules and thresholds with your team.

### Impact Threshold

The `impact_threshold` controls which symbol changes are included in incremental scan payloads. Changes below the threshold are silently ignored — `AGENTS.md` is not regenerated for them.

| Level | What qualifies |
|-------|---------------|
| `"high"` | HTTP endpoints (decorated routes), adding or removing a class / interface / struct, removing a public method |
| `"medium"` | Adding a new public function, changing a public method's signature |
| `"low"` | Any other public symbol change (e.g. adding a non-route method, minor signature tweaks) |

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

Tree-sitter parses each source file and extracts public symbols — classes, functions, methods, interfaces — filtering out private/protected members and underscore-prefixed symbols. These are used to detect naming conventions and export contracts across layers.

---

## Credits

AGENTS.md format based on the open [agents.md](https://agents.md/) standard.
