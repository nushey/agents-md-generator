# Installation Guide

Step-by-step setup for Linux, macOS, and Windows. Works with Claude Code, Gemini CLI, Cursor, Windsurf, and any other MCP-compatible client.

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

**Windows**

Download and run the installer from [python.org/downloads](https://www.python.org/downloads/). During installation, check **"Add Python to PATH"**.

```powershell
python --version
```

---

### 2. uv (includes uvx)

`uvx` downloads and runs Python tools in isolated environments — no virtual environment management needed.

**Linux / macOS**

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

**Windows (PowerShell)**

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

Restart your terminal after installing, then verify:

```bash
uvx --version
```

---

### 3. Git

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

**Windows**

Download from [git-scm.com](https://git-scm.com/download/win) and run the installer with default options.

---

### 4. An MCP-compatible client

Install at least one of the supported clients before proceeding.

---

## Configure your client

Add `agents-md-generator` to your client's MCP server list. The config block is the same for all clients — only the file location differs.

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

If `mcpServers` already exists in your config file, add only the `"agents-md"` entry inside it.

---

### Claude Code

**Quick install (recommended)**

```bash
claude mcp add agents-md uvx agents-md-generator
```

**Manual config file location**

| Platform | Path |
|----------|------|
| Linux / macOS | `~/.claude.json` |
| Windows | `%USERPROFILE%\.claude.json` |

Restart Claude Code after saving the config.

---

### Gemini CLI

**Config file location**

| Platform | Path |
|----------|------|
| Linux / macOS | `~/.gemini/settings.json` |
| Windows | `%USERPROFILE%\.gemini\settings.json` |

Create the file if it does not exist, then add the `mcpServers` block:

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

Restart Gemini CLI after saving.

---

### Cursor

Add the entry to `.cursor/mcp.json` in your project root (project-scoped) or to the global Cursor settings under **Settings → MCP**.

---

### Other clients (Windsurf, Continue, etc.)

Any client that supports stdio MCP servers will work. Consult your client's documentation for the config file location and add the `"agents-md"` entry under `mcpServers`.

---

## Verify

On first start, `uvx` downloads the package and its dependencies automatically — this takes a few seconds only once.

Open any project and ask your AI client:

> "Generate the AGENTS.md for this project"

The client should call `generate_agents_md` automatically. If the tool does not appear:

1. Verify the JSON is valid — no trailing commas, correct quotes
2. Restart your client completely
3. Check that `uvx --version` works in your terminal
4. Check the MCP panel or logs in your client for server errors

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

### `uvx: command not found`

uv is not installed or not on your PATH. Run the install command above and restart your terminal.

### Tool does not appear in your client

- Confirm the JSON in your config file is valid — no trailing commas, correct quotes
- Restart your client completely after any config change
- Check that `uvx --version` works in your terminal
- Check your client's MCP panel or logs for server errors

### Cache is stale after moving the project directory

The cache is keyed by the project's absolute path. Moving the directory triggers a cold start (full rescan) — this is expected.
