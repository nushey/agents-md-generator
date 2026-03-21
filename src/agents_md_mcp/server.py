"""agents-md-generator MCP Server.

Exposes a single tool: generate_agents_md.
Analyzes a codebase incrementally using tree-sitter and returns a structured
JSON payload that Claude Code uses to generate or update AGENTS.md.
"""

import json
import logging
import sys
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from .ast_analyzer import analyze_changes
from .cache import (
    get_current_commit,
    is_cache_valid,
    load_cache,
    make_empty_cache,
    save_cache,
)
from .change_detector import detect_changes
from .config import load_config
from .context_builder import build_payload
from .models import CachedFile, GenerateAgentsMdInput

# Log to stderr only — never stdout (stdio MCP transport uses stdout)
logging.basicConfig(
    stream=sys.stderr,
    level=logging.INFO,
    format="[agents-md] %(levelname)s %(message)s",
)
logger = logging.getLogger(__name__)

mcp = FastMCP("agents_md_mcp")


@mcp.tool(
    name="generate_agents_md",
    annotations={
        "title": "Generate or Update AGENTS.md",
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def generate_agents_md(params: GenerateAgentsMdInput) -> str:
    """Analyze a codebase and return a structured payload for generating AGENTS.md.

    Performs incremental AST analysis using tree-sitter, detects changes since
    the last run, and returns a compact JSON payload. Claude Code interprets
    this payload to write or update the AGENTS.md file.

    Supported languages: Python, C#, TypeScript, JavaScript, Go, Java, Rust, Ruby.

    Args:
        params (GenerateAgentsMdInput): Input parameters containing:
            - project_path (str): Path to the project root (default: ".")
            - force_full_scan (bool): Ignore cache and do a full scan (default: False)

    Returns:
        str: JSON-formatted payload with the following top-level keys:
            - metadata: scan info (project name, scan type, file counts, timestamp)
            - project_structure: directory layout, CI files, config files, test dirs
            - build_system: detected build tools and parsed scripts
            - changes: modified/deleted files with semantic diffs
            - full_analysis: new files with full symbol listing
            - existing_agents_md: current AGENTS.md content if it exists
            - instructions: prompt for Claude Code on how to generate AGENTS.md

    Examples:
        - Analyze current directory: params with project_path="."
        - Force full rescan: params with force_full_scan=True
        - Analyze specific project: params with project_path="/path/to/project"
    """
    project_path = Path(params.project_path).resolve()

    if not project_path.exists():
        return json.dumps({"error": f"Project path does not exist: {project_path}"})

    if not project_path.is_dir():
        return json.dumps({"error": f"Project path is not a directory: {project_path}"})

    try:
        return await _run_pipeline(project_path, params.force_full_scan)
    except Exception as exc:
        logger.exception("Pipeline failed for %s", project_path)
        return json.dumps({"error": f"Analysis failed: {type(exc).__name__}: {exc}"})


async def _run_pipeline(project_path: Path, force_full_scan: bool) -> str:
    """Execute the full analysis pipeline and return JSON string."""

    # 1. Load config
    config = load_config(project_path)
    logger.info("Config loaded for %s (impact_threshold=%s)", project_path, config.impact_threshold)

    # 2. Load cache (None if force_full_scan or missing/corrupt)
    cache = None if force_full_scan else load_cache(project_path)

    if cache is not None and not is_cache_valid(cache, project_path):
        logger.warning("Cache base_commit not found in repo, falling back to cold start")
        cache = None

    scan_type = "incremental" if cache is not None else "full"
    logger.info("Scan type: %s", scan_type)

    # 3. Detect changes
    changes = detect_changes(project_path, config, cache)

    if not changes:
        return json.dumps({
            "status": "no_changes",
            "message": "No changes detected since the last scan. AGENTS.md is up to date.",
        })

    logger.info("Detected %d changed files", len(changes))

    # 4. AST analysis for new/modified files
    new_analyses = analyze_changes(project_path, changes, config, cache)
    logger.info("Analyzed %d files", len(new_analyses))

    # 5. Build payload
    payload = build_payload(
        project_path=project_path,
        config=config,
        changes=changes,
        new_analyses=new_analyses,
        cache=cache,
        scan_type=scan_type,
    )

    # 6. Update cache
    current_commit = get_current_commit(project_path)
    new_cache = make_empty_cache(base_commit=current_commit)

    # Carry forward unchanged files from old cache
    if cache is not None:
        for path, cached_file in cache.files.items():
            changed_paths = {c.path for c in changes}
            if path not in changed_paths:
                new_cache.files[path] = cached_file

    # Add newly analyzed files
    for change in changes:
        if change.status == "deleted":
            continue  # Remove from cache by not adding
        analysis = new_analyses.get(change.path)
        if analysis and change.new_hash:
            new_cache.files[change.path] = CachedFile(
                hash=change.new_hash,
                analysis=analysis,
            )

    save_cache(project_path, new_cache)
    logger.info("Cache saved with %d entries", len(new_cache.files))

    return json.dumps(payload, indent=2, default=str)


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
