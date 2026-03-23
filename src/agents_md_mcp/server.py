"""agents-md-generator MCP Server.

Exposes a single tool: generate_agents_md.

Architecture: the server does all heavy analysis (tree-sitter, change detection,
caching) and writes the payload to .agents-payload.json. It returns a small
response (~1k chars) that tells Claude Code exactly how to proceed — including
how to read the payload in chunks if it is large. Claude Code never receives
a large payload over the MCP wire.
"""

import json
import logging
import sys
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from .ast_analyzer import analyze_changes
from .cache import (
    get_current_commit,
    get_project_cache_dir,
    is_cache_valid,
    load_cache,
    make_empty_cache,
    save_cache,
)
from .change_detector import detect_changes
from .config import load_config
from .context_builder import build_payload
from .context_builder import _is_public, _is_test_file
from .models import CachedFile, CachedSymbol, GenerateAgentsMdInput, GetPayloadChunkInput

# Log to stderr only — never stdout (stdio MCP transport uses stdout)
logging.basicConfig(
    stream=sys.stderr,
    level=logging.INFO,
    format="[agents-md] %(levelname)s %(message)s",
)
logger = logging.getLogger(__name__)

PAYLOAD_FILENAME = "payload.json"
CHUNK_LINES = 500

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
    """Analyze a codebase with tree-sitter and write AGENTS.md.

    This tool performs all heavy analysis locally (AST parsing, change detection,
    caching) and saves the structured payload to .agents-payload.json. It returns
    a small response with step-by-step instructions for Claude Code to read the
    payload and write AGENTS.md — no large data travels over the MCP wire.

    Supported languages: Python, C#, TypeScript, JavaScript, Go.

    Args:
        params (GenerateAgentsMdInput): Input parameters containing:
            - project_path (str): Path to the project root (default: ".")
            - force_full_scan (bool): Ignore cache, rescan everything (default: False).
              Set to True ONLY when the user explicitly asks to rescan from scratch.
              When asked to improve, review, or update an existing AGENTS.md,
              always use force_full_scan=False — the cache is valid and sufficient.

    Returns:
        str: Small JSON response with payload file path and exact instructions
             for Claude Code to follow. Never returns the full payload inline.
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
    """Execute the full analysis pipeline. Returns a small response JSON."""

    # 1. Load config
    config = load_config(project_path)
    logger.info("Config loaded for %s (impact_threshold=%s)", project_path, config.impact_threshold)

    # 2. Load cache
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
            "message": (
                "No source file changes detected since the last scan. "
                "STOP and report this to the user. Do not read any files. Do not rewrite anything. "
                "Tell the user exactly this: 'No se detectaron cambios en el código fuente desde el último scan. "
                "¿Querés que mejore el contenido del AGENTS.md existente de todas formas?' "
                "Then WAIT for the user to respond before doing anything else. "
                "Do NOT call this tool again with force_full_scan=True unless the user explicitly requests a full rescan."
            ),
        })

    logger.info("Detected %d changed files", len(changes))

    # 4. AST analysis
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

    # 6. Update and save cache
    current_commit = get_current_commit(project_path)
    new_cache = make_empty_cache(base_commit=current_commit)
    if cache is not None:
        changed_paths = {c.path for c in changes}
        for path, cached_file in cache.files.items():
            if path not in changed_paths:
                new_cache.files[path] = cached_file
    for change in changes:
        if change.status == "deleted":
            continue
        analysis = new_analyses.get(change.path)
        if analysis and change.new_hash:
            # Test files: store only the hash for change detection — symbols
            # are never used (payload collapses them into directory summaries).
            symbols = [] if _is_test_file(change.path) else [
                CachedSymbol(
                    name=s.name,
                    kind=s.kind,
                    visibility=s.visibility,
                    signature=s.signature,
                    decorators=s.decorators,
                )
                for s in analysis.symbols
                if _is_public(s)
            ]
            new_cache.files[change.path] = CachedFile(
                hash=change.new_hash,
                symbols=symbols,
            )
    save_cache(project_path, new_cache)
    logger.info("Cache saved with %d entries", len(new_cache.files))

    # 7. Write payload to disk — never send it inline over MCP
    payload_path = get_project_cache_dir(project_path) / PAYLOAD_FILENAME
    payload_json = json.dumps(payload, indent=2, default=str)
    payload_path.write_text(payload_json, encoding="utf-8")
    payload_lines = payload_json.count("\n") + 1
    logger.info("Payload written to %s (%d lines)", payload_path, payload_lines)

    agents_md_path = (project_path / config.agents_md_path.lstrip("./")).resolve()

    # 8. Return small response with instructions to call get_payload_chunk
    return json.dumps(
        _build_response(payload_path, payload_lines, agents_md_path, project_path),
        indent=2,
    )


@mcp.tool(
    name="get_payload_chunk",
    annotations={
        "title": "Get Payload Chunk",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def get_payload_chunk(params: GetPayloadChunkInput) -> str:
    """Retrieve a chunk of the analysis payload produced by generate_agents_md.

    Call this tool repeatedly starting at chunk_index=0, incrementing by 1 each time,
    until the response contains has_more=false. Concatenate all 'data' fields in order
    to reconstruct the full payload JSON.

    The payload file is automatically deleted after the last chunk is read.

    Args:
        params (GetPayloadChunkInput): Input parameters containing:
            - project_path (str): Path to the project root (must match generate_agents_md call).
            - chunk_index (int): Zero-based index of the chunk to retrieve.

    Returns:
        str: JSON with fields: chunk_index, total_chunks, has_more (bool), data (str).
             On the last chunk (has_more=false), the payload file is deleted from disk.
    """
    project_path = Path(params.project_path).resolve()
    payload_path = get_project_cache_dir(project_path) / PAYLOAD_FILENAME

    if not payload_path.exists():
        return json.dumps({
            "error": (
                "Payload file not found. "
                "Call generate_agents_md first to produce the analysis payload."
            )
        })

    payload_text = payload_path.read_text(encoding="utf-8")
    lines = payload_text.splitlines(keepends=True)
    total_lines = len(lines)
    total_chunks = (total_lines + CHUNK_LINES - 1) // CHUNK_LINES

    if params.chunk_index < 0 or params.chunk_index >= total_chunks:
        return json.dumps({
            "error": f"chunk_index {params.chunk_index} is out of range (0–{total_chunks - 1})."
        })

    start = params.chunk_index * CHUNK_LINES
    end = min(start + CHUNK_LINES, total_lines)
    chunk_data = "".join(lines[start:end])

    has_more = params.chunk_index < total_chunks - 1

    if not has_more:
        try:
            payload_path.unlink()
            logger.info("Payload file deleted after last chunk: %s", payload_path)
        except OSError as exc:
            logger.warning("Could not delete payload file: %s", exc)

    return json.dumps({
        "chunk_index": params.chunk_index,
        "total_chunks": total_chunks,
        "has_more": has_more,
        "data": chunk_data,
    })


def _build_response(
    payload_path: Path,
    payload_lines: int,
    agents_md_path: Path,
    project_path: Path,
) -> dict:
    """Build the small response that instructs the agent to use get_payload_chunk."""

    num_chunks = (payload_lines + CHUNK_LINES - 1) // CHUNK_LINES

    return {
        "status": "ready",
        "payload_lines": payload_lines,
        "total_chunks": num_chunks,
        "agents_md_path": str(agents_md_path),
        "instructions": (
            f"The codebase analysis is complete. Follow these steps EXACTLY — "
            f"do NOT deviate, ask questions, or read any other files:\n\n"
            f"STEP 1 — Retrieve the full payload by calling the get_payload_chunk tool "
            f"repeatedly with project_path='{project_path}' and chunk_index starting at 0. "
            f"Each response contains a 'has_more' field. Keep calling with the next "
            f"chunk_index until has_more is false. Accumulate all 'data' fields in order.\n\n"
            f"STEP 2 — Concatenate the accumulated data strings and parse the result as JSON. "
            f"Use ONLY this data to generate AGENTS.md. The payload contains an 'instructions' "
            f"field with the exact format requirements.\n\n"
            f"STEP 3 — Write the generated AGENTS.md to: {agents_md_path}\n\n"
            f"STEP 4 — Tell the user: 'AGENTS.md has been generated at {agents_md_path}'\n\n"
            f"IMPORTANT: Do not read any source files. Do not call generate_agents_md again. "
            f"Do not ask the user for anything. Complete all 4 steps autonomously."
        ),
    }


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
