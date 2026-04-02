"""Interactive setup wizard for configuring MCP clients.

Invoked via: agents-md-generator setup
Detects installed clients, prompts the user for scope (global/local),
and patches the appropriate config files.
"""

import json
import tomllib
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm, Prompt
from rich.table import Table

console = Console()

MCP_KEY = "agents-md"
MCP_ENTRY = {"command": "agents-md-generator"}

_TOML_BLOCK = (
    "\n[mcp_servers.agents-md]\n"
    'command = "agents-md-generator"\n'
)


def _clients(cwd: Path) -> list[dict]:
    home = Path.home()
    return [
        {
            "name": "Claude Code",
            "detect": home / ".claude",
            "global_config": home / ".claude.json",
            "local_config": cwd / ".mcp.json",
            "fmt": "json",
        },
        {
            "name": "Gemini CLI",
            "detect": home / ".gemini",
            "global_config": home / ".gemini" / "settings.json",
            "local_config": cwd / ".gemini" / "settings.json",
            "fmt": "json",
        },
        {
            "name": "Cursor",
            "detect": home / ".cursor",
            "global_config": home / ".cursor" / "mcp.json",
            "local_config": cwd / ".cursor" / "mcp.json",
            "fmt": "json",
        },
        {
            "name": "Windsurf",
            "detect": home / ".codeium" / "windsurf",
            "global_config": home / ".codeium" / "windsurf" / "mcp_config.json",
            "local_config": cwd / ".windsurf" / "mcp.json",
            "fmt": "json",
        },
        {
            "name": "Codex CLI",
            "detect": home / ".codex",
            "global_config": home / ".codex" / "config.toml",
            "local_config": cwd / ".codex" / "config.toml",
            "fmt": "toml",
        },
    ]


def _is_detected(client: dict) -> bool:
    return (
        client["detect"].exists()
        or client["global_config"].exists()
        or client["local_config"].exists()
    )


def _patch_json(path: Path, key: str, entry: dict) -> tuple[bool, str]:
    try:
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                return False, "invalid JSON in config file"
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            data = {}

        servers = data.setdefault("mcpServers", {})
        if key in servers:
            return True, "already configured"

        servers[key] = entry
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        return True, "configured"
    except OSError as exc:
        return False, f"could not write: {exc}"


def _patch_toml(path: Path, key: str) -> tuple[bool, str]:
    try:
        if path.exists():
            try:
                data = tomllib.loads(path.read_text(encoding="utf-8"))
            except tomllib.TOMLDecodeError:
                return False, "invalid TOML in config file"
            if key in data.get("mcp_servers", {}):
                return True, "already configured"
            with path.open("a", encoding="utf-8") as f:
                f.write(_TOML_BLOCK)
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(_TOML_BLOCK.lstrip("\n"), encoding="utf-8")

        return True, "configured"
    except OSError as exc:
        return False, f"could not write: {exc}"


def _patch(client: dict, scope: str) -> tuple[bool, str]:
    path = client["global_config"] if scope == "global" else client["local_config"]
    if client["fmt"] == "toml":
        return _patch_toml(path, MCP_KEY)
    return _patch_json(path, MCP_KEY, MCP_ENTRY)


def run_setup() -> None:
    cwd = Path.cwd()
    console.print()
    console.print(
        Panel.fit(
            "[bold cyan]agents-md-generator[/bold cyan]  setup wizard\n"
            "[dim]Adds agents-md to your MCP clients[/dim]",
            border_style="cyan",
        )
    )
    console.print()

    # Scope selection
    console.print(
        "  [bold]global[/bold]  applies to all projects  [dim](user config)[/dim]\n"
        f"  [bold]local[/bold]   this project only        [dim]({cwd})[/dim]\n"
    )
    scope = Prompt.ask("Scope", choices=["global", "local"], default="global")
    console.print()

    clients = _clients(cwd)

    # Detection table
    table = Table(show_header=True, header_style="bold", box=None, padding=(0, 2))
    table.add_column("Client")
    table.add_column("Status")
    table.add_column("Config path", style="dim")

    for c in clients:
        detected = _is_detected(c)
        config_path = c["global_config"] if scope == "global" else c["local_config"]
        status = "[green]✓ detected[/green]" if detected else "[dim]✗ not found[/dim]"
        table.add_row(c["name"], status, str(config_path))

    console.print(table)
    console.print()

    # Client selection
    to_configure: list[dict] = []
    for c in clients:
        detected = _is_detected(c)
        label = f"Configure [bold]{c['name']}[/bold]?"
        if not detected:
            label += " [dim](not detected)[/dim]"
        if Confirm.ask(label, default=detected):
            to_configure.append(c)

    if not to_configure:
        console.print("\n[dim]No clients selected. Nothing changed.[/dim]\n")
        return

    console.print()

    for c in to_configure:
        ok, msg = _patch(c, scope)
        icon = "[green]✓[/green]" if ok else "[red]✗[/red]"
        console.print(f"  {icon}  {c['name']}  —  {msg}")

    console.print()
    console.print("[bold green]Done![/bold green] Restart your clients and ask:")
    console.print('  [dim]"Generate the AGENTS.md for this project"[/dim]')
    console.print()
