# Installation Guide

Step-by-step setup for Linux and Windows.

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

### 4. Claude Code

Install [Claude Code](https://claude.ai/code) and verify it works before proceeding.

---

## Configure Claude Code

Open your Claude Code config file and add the `agents-md` server to `mcpServers`.

### Config file location

| Platform | Path |
|----------|------|
| Linux / macOS | `~/.claude.json` |
| Windows | `%USERPROFILE%\.claude.json` |

### Add this block

```json
{
  "mcpServers": {
    "agents-md": {
      "command": "uvx",
      "args": [
        "--from",
        "git+https://github.com/nushey/agents-md-generator",
        "agents-md-generator"
      ]
    }
  }
}
```

If `mcpServers` already exists in your config, add only the `"agents-md"` entry inside it.

---

## Verify

Restart Claude Code after saving the config. On first start, `uvx` will download the package and its dependencies automatically — this takes a few seconds only once.

Then open any project and ask:

> "Generate the AGENTS.md for this project"

Claude should call `generate_agents_md` automatically. If the tool does not appear:

1. Verify the JSON is valid — no trailing commas, correct quotes
2. Restart Claude Code completely
3. Check the MCP panel in Claude Code for server errors

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

### Tool does not appear in Claude Code

- Confirm the JSON in `.claude.json` is valid
- Restart Claude Code completely after any config change
- Check that `uvx --version` works in your terminal

### Cache is stale after moving the project directory

The cache is keyed by the project's absolute path. Moving the directory triggers a cold start (full rescan) — this is expected.
