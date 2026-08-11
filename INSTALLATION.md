# Installation Guide

Step-by-step setup for Linux, macOS, and Windows. Works with Claude Code, Gemini CLI, Cursor, Windsurf, Codex CLI, and any other MCP-compatible client.

---

## Prerequisites

### 1. Python 3.11 or later

**Linux**

```bash
# Verify current version
python3 --version

# Ubuntu / Debian
sudo apt update && sudo apt install python3

# Fedora / RHEL
sudo dnf install python3

# Arch
sudo pacman -S python
```

**macOS**

```bash
# Verify current version
python3 --version

# Homebrew
brew install python
```

**Windows**

Download and run the installer from [python.org/downloads](https://www.python.org/downloads/). During installation, check **"Add Python to PATH"**.

```powershell
python --version
```

---

### 2. Git

Required for incremental scanning. `agents-md-generator` uses `git ls-files` to enumerate tracked files.

**Linux**

```bash
# Ubuntu / Debian
sudo apt install git

# Fedora / RHEL
sudo dnf install git

# Arch
sudo pacman -S git
```

**macOS**

```bash
# Xcode Command Line Tools (includes git)
xcode-select --install

# or Homebrew
brew install git
```

**Windows**

Download from [git-scm.com](https://git-scm.com/download/win) and run the installer with default options.

---

### 3. An MCP-compatible client

Install at least one of the supported clients before proceeding.

---

## Option A — pip install + setup wizard (recommended)

Install the package once and use the interactive wizard to configure all your clients automatically.

```bash
pip install agents-md-generator
agents-md-generator setup
```

The wizard will:

1. Detect which MCP clients are installed on your system
2. Ask whether to configure **globally** (all projects) or **locally** (current project only)
3. Patch the config files for each client you select

**Supported clients:** Claude Code, Gemini CLI, Cursor, Windsurf, Codex CLI.

After setup, restart your clients and skip to [Verify](#verify).

---

## Option B — uvx (no install needed)

If you have [uv](https://github.com/astral-sh/uv) installed, `uvx` runs the package without a prior install step.

**Install uv**

Linux / macOS:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Windows (PowerShell):

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

Restart your terminal after installing, then verify:

```bash
uvx --version
```

Then configure your client manually:

---

### Claude Code

```bash
claude mcp add agents-md -- uvx agents-md-generator
```

`claude mcp add` defaults to `--scope local` (current project only). For all projects, add `-s user`:

```bash
claude mcp add agents-md -s user -- uvx agents-md-generator
```

Or add manually to your config file:

| Scope | Path |
|-------|------|
| Global (all projects) | `~/.claude.json` — Windows: `%USERPROFILE%\.claude.json` |
| Project-scoped | `.mcp.json` in the project root |

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

---

### Gemini CLI

| Platform | Path |
|----------|------|
| Linux / macOS | `~/.gemini/settings.json` |
| Windows | `%USERPROFILE%\.gemini\settings.json` |

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

---

### Cursor

Add to `~/.cursor/mcp.json` (global) or `.cursor/mcp.json` in your project root (project-scoped):

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

---

### Windsurf

Add to `~/.codeium/windsurf/mcp_config.json`:

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

---

### Codex CLI

Add to `~/.codex/config.toml` (global) or `.codex/config.toml` in your project root (project-scoped):

```toml
[mcp_servers.agents-md]
command = "uvx"
args = ["agents-md-generator"]
```

---

### Other clients

Any client that supports stdio MCP servers will work. Consult your client's documentation for the config file location and add the `"agents-md"` entry under `mcpServers`.

---

## Verify

Open any project and ask your AI client:

> "Generate the AGENTS.md for this project"

The client should call `generate_agents_md` automatically. If the tool does not appear:

1. Restart your client completely after any config change
2. Verify the config file is valid — no trailing commas or incorrect quotes in JSON; valid TOML syntax for Codex
3. For Option A: confirm `pip show agents-md-generator` reports the installed version
4. For Option B: confirm `uvx --version` works in your terminal
5. Check the MCP panel or logs in your client for server errors

---

## Runtime Files

`agents-md-generator` writes no files to your project. All runtime artifacts live in the user cache directory:

| Platform | Path |
|----------|------|
| Linux / macOS | `~/.cache/agents-md-generator/<project-hash>/` |
| Windows | `%USERPROFILE%\.cache\agents-md-generator\<project-hash>\` |

Each project gets its own subdirectory identified by a hash of its absolute path.

| File | Purpose |
|------|---------|
| `cache.json` | Incremental scan cache — persists between runs |
| `payload.json` | Temporary analysis payload — deleted after each run |

---

## Troubleshooting

### `agents-md-generator: command not found`

The package is not installed or not on your PATH. Run `pip install agents-md-generator` and restart your terminal.

> Do not run `agents-md-generator` with no arguments to test it — with no subcommand it starts the MCP server on stdio and waits for input, which looks like a hang. Use `pip show agents-md-generator` to confirm the install, or `agents-md-generator setup` to run the wizard.

### `uvx: command not found`

uv is not installed or not on your PATH. Run the install command in [Option B](#option-b--uvx-no-install-needed) and restart your terminal.

### Tool does not appear in your client

- Restart your client completely after any config change
- Confirm the config file is valid — no trailing commas or incorrect quotes in JSON; valid TOML syntax for Codex
- Run `pip show agents-md-generator` (Option A) or `uvx --version` (Option B) to confirm the package is accessible
- Check your client's MCP panel or logs for server errors

### Cache is stale after moving the project directory

The cache is keyed by the project's absolute path. Moving the directory triggers a cold start (full rescan) — this is expected.
