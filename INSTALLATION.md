# Installation Guide

This guide covers full installation of `agents-md-generator` on Linux and Windows, including all prerequisites.

---

## Prerequisites

### Python 3.10 or later

`agents-md-generator` requires Python 3.10+. Python 3.12 is recommended.

**Linux**

```bash
# Check your current version
python3 --version

# Ubuntu / Debian
sudo apt update && sudo apt install python3 python3-pip

# Fedora / RHEL
sudo dnf install python3 python3-pip

# Arch
sudo pacman -S python python-pip

# Or install via pyenv for version management
curl https://pyenv.run | bash
pyenv install 3.12
pyenv global 3.12
```

**Windows**

Download and run the installer from [python.org/downloads](https://www.python.org/downloads/). During installation, check **"Add Python to PATH"**.

Verify the installation:

```powershell
python --version
```

---

### Git

Required for incremental scanning. `agents-md-generator` uses `git ls-files` to enumerate tracked files and `git rev-parse HEAD` to track the cache baseline.

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

Download from [git-scm.com](https://git-scm.com/download/win) and run the installer. Use the default options. Git Bash is not required — the standard Windows installer is sufficient.

---

### Claude Code

`agents-md-generator` is an MCP server for [Claude Code](https://claude.ai/code). Install Claude Code first and verify it works before proceeding.

---

## Installation Methods

### Method 1 — uvx (recommended)

`uvx` runs Python tools in isolated environments without requiring you to manage a virtual environment. It is part of [uv](https://github.com/astral-sh/uv), the fast Python package manager.

**Install uv:**

```bash
# Linux / macOS
curl -LsSf https://astral.sh/uv/install.sh | sh

# Windows (PowerShell)
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

Restart your terminal after installing uv, then verify:

```bash
uv --version
uvx --version
```

**Run the MCP server with uvx:**

```bash
uvx agents-md-generator
```

uvx automatically downloads the package and its dependencies on first run and caches them locally. No `pip install` needed.

---

### Method 2 — pip

If you prefer a standard pip installation:

```bash
pip install agents-md-generator
```

To install into a virtual environment (recommended for pip installs):

```bash
# Linux
python3 -m venv .venv
source .venv/bin/activate
pip install agents-md-generator

# Windows
python -m venv .venv
.venv\Scripts\activate
pip install agents-md-generator
```

---

## Claude Code MCP Configuration

Once installed, register the server in Claude Code's MCP configuration.

### Locate the config file

| Platform | Path |
|----------|------|
| Linux | `~/.claude.json` |
| Windows | `%USERPROFILE%\.claude.json` |

### With uvx

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

### With pip (global install)

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

### With pip (virtual environment)

**Linux:**

```json
{
  "mcpServers": {
    "agents-md": {
      "command": "/path/to/your/.venv/bin/python",
      "args": ["-m", "agents_md_mcp.server"]
    }
  }
}
```

**Windows:**

```json
{
  "mcpServers": {
    "agents-md": {
      "command": "C:\\path\\to\\your\\.venv\\Scripts\\python.exe",
      "args": ["-m", "agents_md_mcp.server"]
    }
  }
}
```

---

## Verification

Restart Claude Code after editing the config file. Then ask:

> "Generate the AGENTS.md for this project"

Claude should call `generate_agents_md` automatically. If the tool does not appear, check the MCP server logs:

```bash
# The server logs to stderr — visible in Claude Code's MCP log panel
# or by running it directly:
uvx agents-md-generator
```

---

## Runtime Files

`agents-md-generator` writes no files to your project. All runtime artifacts are stored in the user cache directory:

| Platform | Path |
|----------|------|
| Linux | `~/.cache/agents-md-generator/<project-hash>/` |
| Windows | `%LOCALAPPDATA%\agents-md-generator\<project-hash>\` |

> **Note:** On Windows, the server currently uses `~/.cache/agents-md-generator/` (the user's home directory). Native `%LOCALAPPDATA%` support is planned.

Each project gets its own subdirectory identified by a hash of its absolute path. Files stored:

| File | Purpose |
|------|---------|
| `cache.json` | Incremental scan cache — persists between runs |
| `payload.json` | Temporary analysis payload — deleted after each run |

---

## Troubleshooting

### `uvx: command not found`

uv is not installed or not on your PATH. Follow the uv installation steps above and restart your terminal.

### `python: command not found` (Linux)

Try `python3` instead, or install Python via your package manager. If using a virtual environment, make sure it is activated.

### Tool does not appear in Claude Code

1. Verify the JSON in your `.claude.json` is valid (no trailing commas, correct quotes)
2. Confirm the `command` path exists and is executable
3. Restart Claude Code completely after any config change
4. Run the server command directly in a terminal to see any startup errors

### Cache is stale after moving the project directory

The cache is keyed by the project's absolute path. Moving the directory produces a new hash and triggers a cold start (full rescan). This is expected behavior.

### `force_full_scan` not working as expected

`force_full_scan: true` bypasses the cache entirely and rescans all files. Use it only when the cache is suspected to be out of sync. For improving an existing `AGENTS.md` without code changes, leave it as `false`.
