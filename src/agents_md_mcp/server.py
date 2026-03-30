"""agents-md-generator MCP Server.

Exposes two tools:
- scan_codebase: runs the full analysis pipeline and writes the payload to disk.
- read_payload_chunk: streams the payload back in 500-line chunks until has_more is false.

Architecture: the server does all heavy analysis (tree-sitter, change detection,
caching) and writes a temporary payload.json to the user cache directory. It returns
a small response (~1k chars) with step-by-step instructions for the AI client to
retrieve the payload via read_payload_chunk and write AGENTS.md. No large data travels
over the MCP wire, and no filesystem access is required from the client side.
"""

import json
import logging
import sys
from importlib.metadata import version as pkg_version
from pathlib import Path

from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.server import Context

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
from .symbol_utils import _is_public, _is_test_file
from .connectors import build_connector_instruction, get_connector_spec
from .models import CachedFile, CachedSymbol, ScanCodebaseInput, ReadPayloadChunkInput

# Log to stderr only — never stdout (stdio MCP transport uses stdout)
logging.basicConfig(
    stream=sys.stderr,
    level=logging.INFO,
    format="[agents-md] %(levelname)s %(message)s",
)
logger = logging.getLogger(__name__)

PAYLOAD_FILENAME = "payload.json"
CHUNK_LINES = 500
CHUNK_BYTES = 50_000  # ~50kb per chunk for compact (single-line) JSON

def _compute_total_chunks(payload_text: str, compact: bool) -> int:
    """Compute total chunks based on format: line-based for pretty, byte-based for compact."""
    if compact:
        size = len(payload_text.encode("utf-8"))
        return (size + CHUNK_BYTES - 1) // CHUNK_BYTES
    lines = payload_text.count("\n") + 1
    return (lines + CHUNK_LINES - 1) // CHUNK_LINES


def _get_client_name(ctx: Context) -> str | None:
    """Extract the client name from the MCP initialize handshake, or None."""
    try:
        client_params = ctx.session.client_params
        if client_params and client_params.clientInfo:
            return client_params.clientInfo.name
    except Exception:
        pass
    return None


mcp = FastMCP("agents_md_mcp")

_server = getattr(mcp, "_mcp_server", None)
if _server is not None:
    _server.version = pkg_version("agents-md-generator")


@mcp.tool(
    name="scan_codebase",
    annotations={
        "title": "Scan Codebase",
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def scan_codebase(params: ScanCodebaseInput, ctx: Context) -> str:
    """Scan and analyze a codebase with tree-sitter, then write the payload to disk.

    This tool performs all heavy analysis locally (AST parsing, change detection,
    caching) and saves the structured payload to disk. It returns a small response
    with step-by-step instructions for the AI client to read the payload via
    read_payload_chunk and write AGENTS.md — no large data travels over the MCP wire.

    Supported languages: Python, C#, TypeScript, JavaScript, Go.

    Args:
        params (ScanCodebaseInput): Input parameters containing:
            - project_path (str): Path to the project root (default: ".")
            - force_full_scan (bool): Ignore cache, rescan everything (default: False).
              Set to True ONLY when the user explicitly asks to rescan from scratch.
              When asked to improve, review, or update an existing AGENTS.md,
              always use force_full_scan=False — the cache is valid and sufficient.

    Returns:
        str: Small JSON response with payload file path and exact instructions
             for the AI client to follow. Never returns the full payload inline.
    """
    project_path = Path(params.project_path).resolve()

    if not project_path.exists():
        return json.dumps({"error": f"Project path does not exist: {project_path}"})

    if not project_path.is_dir():
        return json.dumps({"error": f"Project path is not a directory: {project_path}"})

    # Extract client name from MCP initialize handshake
    client_name = _get_client_name(ctx)
    if client_name:
        logger.info("MCP client identified: %s", client_name)

    try:
        return await _run_pipeline(project_path, params.force_full_scan, client_name)
    except Exception as exc:
        logger.exception("Pipeline failed for %s", project_path)
        return json.dumps({"error": f"Analysis failed: {type(exc).__name__}: {exc}"})


async def _run_pipeline(
    project_path: Path, force_full_scan: bool, client_name: str | None = None
) -> str:
    """Execute the full analysis pipeline. Returns a small response JSON."""

    # 1. Load config
    config = load_config(project_path)
    logger.info("Config loaded for %s (project_size=%s)", project_path, config.project_size)

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
    #    Use compact JSON (no indent) for large payloads to save ~30% size.
    payload_path = get_project_cache_dir(project_path) / PAYLOAD_FILENAME
    payload_json = json.dumps(payload, indent=2, default=str)
    compact = len(payload_json) > 300_000
    if compact:
        payload_json = json.dumps(payload, default=str, separators=(",", ":"))
        logger.info("Using compact JSON (payload > 300kb)")
    payload_path.write_text(payload_json, encoding="utf-8")
    payload_size = len(payload_json.encode("utf-8"))
    logger.info("Payload written to %s (%d bytes)", payload_path, payload_size)

    agents_md_path = (project_path / config.agents_md_path.lstrip("./")).resolve()

    # 8. Return small response with instructions to call read_payload_chunk
    num_chunks = _compute_total_chunks(payload_json, compact)
    return json.dumps(
        _build_response(payload_path, num_chunks, agents_md_path, project_path, client_name),
        indent=2,
    )


@mcp.tool(
    name="read_payload_chunk",
    annotations={
        "title": "Read Payload Chunk",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def read_payload_chunk(params: ReadPayloadChunkInput) -> str:
    """Read a chunk of the analysis payload produced by scan_codebase.

    Call this tool repeatedly starting at chunk_index=0, incrementing by 1 each time,
    until the response contains has_more=false. Concatenate all 'data' fields in order
    to reconstruct the full payload JSON.

    The payload file is automatically deleted after the last chunk is read.

    Args:
        params (ReadPayloadChunkInput): Input parameters containing:
            - project_path (str): Path to the project root (must match scan_codebase call).
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
                "Call scan_codebase first to produce the analysis payload."
            )
        })

    payload_text = payload_path.read_text(encoding="utf-8")
    payload_bytes = payload_text.encode("utf-8")

    # Detect compact mode: single-line JSON uses byte-based chunking
    compact = payload_text.count("\n") < 5

    if compact:
        total_size = len(payload_bytes)
        total_chunks = (total_size + CHUNK_BYTES - 1) // CHUNK_BYTES

        if params.chunk_index < 0 or params.chunk_index >= total_chunks:
            return json.dumps({
                "error": f"chunk_index {params.chunk_index} is out of range (0–{total_chunks - 1})."
            })

        start = params.chunk_index * CHUNK_BYTES
        end = min(start + CHUNK_BYTES, total_size)
        chunk_data = payload_bytes[start:end].decode("utf-8", errors="replace")
    else:
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
    num_chunks: int,
    agents_md_path: Path,
    project_path: Path,
    client_name: str | None = None,
) -> dict:
    """Build the small response that instructs the agent to use read_payload_chunk."""

    connector_spec = get_connector_spec(client_name)
    connector_step = ""
    if connector_spec:
        connector_step = (
            "\n\n"
            + build_connector_instruction(connector_spec, agents_md_path, project_path)
        )
        total_steps = "5"
    else:
        total_steps = "4"

    return {
        "status": "ready",
        "total_chunks": num_chunks,
        "agents_md_path": str(agents_md_path),
        "instructions": (
            f"The codebase analysis is complete. Follow these steps EXACTLY -- "
            f"do NOT deviate, ask questions, or read any other files:\n\n"
            f"STEP 1 -- Retrieve the full payload by calling the read_payload_chunk tool "
            f"repeatedly with project_path='{project_path}' and chunk_index starting at 0. "
            f"Each response contains a 'has_more' field. Keep calling with the next "
            f"chunk_index until has_more is false. Accumulate all 'data' fields in order.\n\n"
            f"STEP 2 -- The concatenated data is the full analysis payload. Read the "
            f"'instructions' field FIRST -- it contains the exact format and rules for "
            f"writing AGENTS.md. Then use the remaining fields as your data source.\n\n"
            f"STEP 3 -- Write the generated AGENTS.md to: {agents_md_path}\n\n"
            f"STEP 4 -- Tell the user: 'AGENTS.md has been generated at {agents_md_path}'"
            f"{connector_step}\n\n"
            f"IMPORTANT: Do not read any source files. Do not call scan_codebase again. "
            f"Do not ask the user for anything. Complete all {total_steps} steps autonomously."
        ),
    }


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
