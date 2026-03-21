# agents-md-generator

MCP server that analyzes codebases with [tree-sitter](https://tree-sitter.github.io/) and generates [`AGENTS.md`](https://agents.md/) files.

**How it works:** 90% of the work happens locally. The server parses your code with tree-sitter, detects changes incrementally, and returns a compact structured JSON payload to Claude Code. Claude then writes or updates your `AGENTS.md` — no extra API calls needed.

## Supported Languages

Python · C# · TypeScript · JavaScript · Go · Java · Rust · Ruby

## Installation

### With uvx (recommended)

```bash
uvx agents-md-generator
```

### With pip

```bash
pip install agents-md-generator
```

## Claude Code Configuration

Add to your `.claude.json` or `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "agents-md-generator": {
      "command": "uvx",
      "args": ["agents-md-generator"],
      "env": {}
    }
  }
}
```

Or with a local install:

```json
{
  "mcpServers": {
    "agents-md-generator": {
      "command": "python",
      "args": ["-m", "agents_md_mcp.server"],
      "env": {}
    }
  }
}
```

## Usage

Once registered, ask Claude Code:

> "Generate the AGENTS.md for this project"

Claude will call `generate_agents_md` automatically. You can also be explicit:

> "Run generate_agents_md with force_full_scan=true"

### Tool Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `project_path` | string | `"."` | Path to the project root |
| `force_full_scan` | boolean | `false` | Ignore cache, rescan everything |

## Configuration

Create `.agents-config.json` in your project root to customize behavior:

```json
{
  "impact_threshold": "medium",
  "exclude": [
    "**/node_modules/**",
    "**/dist/**",
    "**/build/**",
    "**/.git/**"
  ],
  "include": [],
  "agents_md_path": "./AGENTS.md",
  "base_ref": null,
  "max_file_size_bytes": 1048576
}
```

### Options

| Key | Default | Description |
|-----|---------|-------------|
| `impact_threshold` | `"medium"` | Minimum impact to include in payload: `"high"`, `"medium"`, `"low"` |
| `exclude` | (see above) | Glob patterns to exclude from analysis |
| `include` | `[]` | If non-empty, only analyze files matching these patterns |
| `agents_md_path` | `"./AGENTS.md"` | Output path for the generated file |
| `base_ref` | `null` | Git branch for diff reference (null = use hash cache) |
| `max_file_size_bytes` | `1048576` | Files larger than this are skipped (1MB default) |

## How Incremental Scanning Works

1. **First run (cold start):** All tracked files are parsed and cached in `.agents-cache.json`
2. **Subsequent runs:** Only files whose SHA-256 hash changed since the last scan are re-parsed
3. **Semantic diff:** For modified files, only the changed symbols are included in the payload
4. **No changes?** The tool returns early with a clear message — no unnecessary regeneration

Add `.agents-cache.json` to your `.gitignore`.

## Credits

AGENTS.md format based on the [`create-agentsmd`](https://skills.sh/github/awesome-copilot/create-agentsmd) skill, following the open [agents.md](https://agents.md/) standard.
