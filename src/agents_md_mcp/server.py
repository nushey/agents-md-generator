"""agents-md-generator MCP Server.

Exposes three tools:
- scan_codebase: runs the full analysis pipeline and writes the payload to disk.
- read_payload_chunk: streams the payload back in chunks until has_more is false.
- generate_agents_md: orchestrates the full AGENTS.md create/update workflow.

Architecture: scan_codebase performs heavy analysis (tree-sitter, change detection,
caching) and writes a temporary payload.json to disk. It returns a neutral response
with instructions to retrieve the payload via read_payload_chunk — pure context data,
no AGENTS.md mandate. generate_agents_md is the dedicated tool for AGENTS.md
generation: it reads the existing file if present, returns writing rules and
step-by-step orchestration instructions. No large data travels over the MCP wire.
"""

import json
import logging
import os
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
from .change_detector import NotAGitRepositoryError, detect_changes
from .config import SIZE_PROFILES, load_config
from .context_builder import build_payload
from .project_scanner import detect_env_vars_for_changes, detect_root_env_vars
from .symbol_utils import _is_public, _is_test_file
from .connectors import setup_connectors, get_connector_spec
from .models import CachedFile, CachedSymbol, ScanCodebaseInput, ReadPayloadChunkInput, GenerateAgentsMdInput

# Log to stderr only — never stdout (stdio MCP transport uses stdout)
_log_level = getattr(logging, os.environ.get("AGENTS_MD_LOG_LEVEL", "INFO").upper(), logging.INFO)
logging.basicConfig(
    stream=sys.stderr,
    level=_log_level,
    format="[agents-md] %(levelname)s %(message)s",
)
logger = logging.getLogger(__name__)

PAYLOAD_FILENAME = "payload.json"
# Each chunk's 'data' is JSON-escaped into the tool response, which inflates it
# (~1.2-1.5x for dense JSON-of-JSON). 20k source chars keeps the final escaped
# response comfortably under MCP client tool-result token limits.
CHUNK_CHARS = 20_000

# Hard ceiling on the serialized payload. Beyond this the consuming agent
# drowns in chunks regardless of how fast the scan was. When exceeded, the
# payload is degraded in order: rebuild with the "large" profile → strip method
# signatures → truncate full_analysis. Each step is recorded in
# metadata.degradations so the agent knows detail was dropped.
PAYLOAD_BUDGET_CHARS = 300_000

# The server is long-lived: cache the payload text per path so sequential
# read_payload_chunk calls slice one in-memory string instead of re-reading the
# whole file from disk on every chunk. Identity is (st_mtime_ns, st_size) —
# nanosecond mtime plus size guards against same-second rewrites on
# coarse-timestamp filesystems. _run_pipeline additionally invalidates the
# entry explicitly whenever it rewrites the payload, so a stale hit would need
# an out-of-process rewrite that preserves both mtime_ns and size.
# Bounded FIFO (payloads can be multi-MB and an abandoned chunk sequence would
# otherwise pin its text for the life of the process).
_PAYLOAD_CACHE_MAX_ENTRIES = 4
_payload_cache: dict[Path, tuple[tuple[int, int], str]] = {}


def _payload_cache_put(payload_path: Path, key: tuple[int, int], text: str) -> None:
    _payload_cache.pop(payload_path, None)
    while len(_payload_cache) >= _PAYLOAD_CACHE_MAX_ENTRIES:
        _payload_cache.pop(next(iter(_payload_cache)))
    _payload_cache[payload_path] = (key, text)


def _read_payload_cached(payload_path: Path) -> str:
    stat = payload_path.stat()
    key = (stat.st_mtime_ns, stat.st_size)
    cached = _payload_cache.get(payload_path)
    if cached is not None and cached[0] == key:
        return cached[1]
    text = payload_path.read_text(encoding="utf-8")
    _payload_cache_put(payload_path, key, text)
    return text


def _compute_total_chunks(payload_text: str) -> int:
    """Number of character-based chunks needed to stream the payload."""
    return max(1, (len(payload_text) + CHUNK_CHARS - 1) // CHUNK_CHARS)


def _enforce_budget(payload, payload_json, dump, config, rebuild):
    """Degrade an over-budget payload until it fits PAYLOAD_BUDGET_CHARS.

    Ladder: (1) rebuild with the harsher "large" profile, (2) strip method
    signatures, (3) truncate full_analysis proportionally. Applied steps are
    recorded in metadata.degradations.
    """
    degradations: list[str] = []

    if config.project_size != "large":
        config.project_size = "large"
        config.profile = SIZE_PROFILES["large"]
        payload = rebuild()
        payload_json = dump(payload)
        degradations.append("reprofiled_to_large")

    if len(payload_json) > PAYLOAD_BUDGET_CHARS:
        for entry in payload.get("full_analysis", []):
            for sym in entry.get("symbols", []):
                sym.pop("methods", None)
                sym.pop("total_methods", None)
            entry.pop("common_methods", None)
        payload["method_patterns"] = {}
        payload_json = dump(payload)
        degradations.append("stripped_method_signatures")

    truncated = 0
    while len(payload_json) > PAYLOAD_BUDGET_CHARS and payload.get("full_analysis"):
        entries = payload["full_analysis"]
        # Keep a proportional slice with 10% margin; re-dump and repeat if needed.
        keep = max(1, int(len(entries) * PAYLOAD_BUDGET_CHARS / len(payload_json) * 0.9))
        if keep >= len(entries):
            break
        truncated += len(entries) - keep
        payload["full_analysis"] = entries[:keep]
        payload_json = dump(payload)
    if truncated:
        payload["metadata"]["truncated_entries"] = truncated
        degradations.append("truncated_full_analysis")

    payload["metadata"]["degradations"] = degradations
    payload_json = dump(payload)
    logger.warning(
        "Payload exceeded budget (%d chars); degradations applied: %s → %d chars",
        PAYLOAD_BUDGET_CHARS, degradations, len(payload_json),
    )
    return payload, payload_json


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
    """Scan and analyze a codebase with tree-sitter, producing a structured context payload.

    Performs AST analysis, change detection, and caching. Writes the analysis payload
    to disk and returns instructions to retrieve it via read_payload_chunk. The payload
    contains pure architectural data — no AGENTS.md writing instructions.

    Use this tool when you need deep codebase understanding for any task (code review,
    refactoring, planning, Q&A). To generate or update AGENTS.md specifically, use
    generate_agents_md instead — it orchestrates the full workflow automatically.

    Supported languages: Python, C#, TypeScript, JavaScript, Go.

    Args:
        params (ScanCodebaseInput): Input parameters containing:
            - project_path (str): Path to the project root (default: ".")
            - force_full_scan (bool): Ignore cache and rescan everything (default: True).
              Set to False only when called as part of an incremental update workflow.

    Returns:
        str: JSON with total_chunks and instructions to call read_payload_chunk.
    """
    project_path = Path(params.project_path).resolve()

    if not project_path.exists():
        return json.dumps({"error": f"Project path does not exist: {project_path}"}, ensure_ascii=False)

    if not project_path.is_dir():
        return json.dumps({"error": f"Project path is not a directory: {project_path}"}, ensure_ascii=False)

    logger.info("scan_codebase: %s (force_full_scan=%s)", project_path, params.force_full_scan)

    try:
        result = await _run_pipeline(project_path, params.force_full_scan)
        return json.dumps(result, indent=2, ensure_ascii=False)
    except NotAGitRepositoryError as exc:
        return json.dumps({"error": str(exc)}, ensure_ascii=False)
    except Exception as exc:
        logger.exception("Pipeline failed for %s", project_path)
        return json.dumps({"error": f"Analysis failed: {type(exc).__name__}: {exc}"}, ensure_ascii=False)


async def _run_pipeline(
    project_path: Path,
    force_full_scan: bool,
    include_agents_md_context: bool = False,
) -> dict:
    """Execute the full analysis pipeline. Returns a response dict."""

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

    # 3. Detect changes (raises NotAGitRepositoryError on non-git projects)
    changes = detect_changes(project_path, config, cache)

    if not changes:
        return {
            "status": "no_changes",
            "message": (
                "No source file changes detected since the last scan. "
                "STOP and report this to the user. Do not read any files. Do not rewrite anything. "
                "Tell the user exactly this: 'No se detectaron cambios en el código fuente desde el último scan. "
                "¿Querés que mejore el contenido del AGENTS.md existente de todas formas?' "
                "Then WAIT for the user to respond before doing anything else. "
                "Do NOT call this tool again with force_full_scan=True unless the user explicitly requests a full rescan."
            ),
        }

    logger.info("Detected %d changed files", len(changes))

    # 4. AST analysis
    new_analyses = analyze_changes(project_path, changes, config, cache)
    logger.info("Analyzed %d files", len(new_analyses))

    # 4b. Env vars: scan only changed files; unchanged files contribute their
    #     cached env_vars. Cold starts cover everything because every file is a change.
    env_map = detect_env_vars_for_changes(project_path, config, changes)
    env_union: set[str] = set().union(*env_map.values()) if env_map else set()
    changed_paths = {c.path for c in changes}
    if cache is not None:
        for path, cached_file in cache.files.items():
            if path not in changed_paths:
                env_union.update(cached_file.env_vars)
    env_union |= detect_root_env_vars(project_path)
    env_vars = sorted(env_union)

    # 5. Build payload
    payload = build_payload(
        project_path=project_path,
        config=config,
        changes=changes,
        new_analyses=new_analyses,
        cache=cache,
        scan_type=scan_type,
        include_agents_md_context=include_agents_md_context,
        env_vars=env_vars,
    )

    # 6. Update and save cache
    current_commit = get_current_commit(project_path)
    new_cache = make_empty_cache(base_commit=current_commit)
    if cache is not None:
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
                    implements=s.implements,
                    parent=s.parent,
                )
                for s in analysis.symbols
                if _is_public(s)
            ]
            new_cache.files[change.path] = CachedFile(
                hash=change.new_hash,
                symbols=symbols,
                env_vars=env_map.get(change.path, []),
            )
    save_cache(project_path, new_cache)
    logger.info("Cache saved with %d entries", len(new_cache.files))

    # 7. Serialize within budget, then write to disk — never send it inline over
    #    MCP. Always compact, single-line JSON: the agent reassembles and parses
    #    it, so pretty-printing adds no value and would only complicate chunk math.
    #    ensure_ascii=False keeps accented identifiers readable instead of \uXXXX.
    def _dump(p: dict) -> str:
        return json.dumps(p, default=str, separators=(",", ":"), ensure_ascii=False)

    payload_json = _dump(payload)
    if len(payload_json) > PAYLOAD_BUDGET_CHARS:
        payload, payload_json = _enforce_budget(
            payload, payload_json, _dump, config,
            rebuild=lambda: build_payload(
                project_path=project_path,
                config=config,
                changes=changes,
                new_analyses=new_analyses,
                cache=cache,
                scan_type=scan_type,
                include_agents_md_context=include_agents_md_context,
                env_vars=env_vars,
            ),
        )

    payload_path = get_project_cache_dir(project_path) / PAYLOAD_FILENAME
    payload_path.write_text(payload_json, encoding="utf-8")
    # Invalidate any cached text for this path — the identity key alone cannot
    # rule out a rewrite that lands on the same (mtime_ns, size).
    _payload_cache.pop(payload_path, None)
    payload_size = len(payload_json.encode("utf-8"))
    logger.info("Payload written to %s (%d bytes)", payload_path, payload_size)

    # 8. Return response dict with instructions to call read_payload_chunk
    num_chunks = _compute_total_chunks(payload_json)
    return _build_response(num_chunks, project_path)


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
        }, ensure_ascii=False)

    try:
        payload_text = _read_payload_cached(payload_path)
    except OSError:
        return json.dumps({
            "error": (
                "Payload file not found. "
                "Call scan_codebase first to produce the analysis payload."
            )
        }, ensure_ascii=False)

    # Character-based chunking. Python slices strings by code point, so multi-byte
    # UTF-8 (accented identifiers, etc.) is never split mid-character. The agent
    # reconstructs the payload by concatenating each chunk's 'data' in order, so
    # boundaries that fall inside JSON escape sequences rejoin losslessly.
    total_size = len(payload_text)
    total_chunks = max(1, (total_size + CHUNK_CHARS - 1) // CHUNK_CHARS)

    if params.chunk_index < 0 or params.chunk_index >= total_chunks:
        return json.dumps({
            "error": f"chunk_index {params.chunk_index} is out of range (0-{total_chunks - 1})."
        }, ensure_ascii=False)

    start = params.chunk_index * CHUNK_CHARS
    end = min(start + CHUNK_CHARS, total_size)
    chunk_data = payload_text[start:end]

    has_more = params.chunk_index < total_chunks - 1

    if not has_more:
        _payload_cache.pop(payload_path, None)
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
    }, ensure_ascii=False)


@mcp.tool(
    name="generate_agents_md",
    annotations={
        "title": "Generate AGENTS.md",
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def generate_agents_md(params: GenerateAgentsMdInput, ctx: Context) -> str:
    """Orchestrate the full AGENTS.md creation or update workflow.

    Determines whether to create or update AGENTS.md by checking if the file already
    exists. Returns writing rules, the existing content (if any), and step-by-step
    instructions to scan the codebase and produce the final file.

    Use this tool whenever the user asks to generate, create, update, or refresh
    AGENTS.md. For general codebase context without AGENTS.md generation, use
    scan_codebase + read_payload_chunk directly.

    Args:
        params (GenerateAgentsMdInput): Input parameters containing:
            - project_path (str): Path to the project root (default: ".")

    Returns:
        str: JSON with agents_md_path, agents_md_rules, existing_agents_md (if any),
             and step-by-step instructions for the agent to follow.
    """
    project_path = Path(params.project_path).resolve()

    if not project_path.exists():
        return json.dumps({"error": f"Project path does not exist: {project_path}"}, ensure_ascii=False)

    if not project_path.is_dir():
        return json.dumps({"error": f"Project path is not a directory: {project_path}"}, ensure_ascii=False)

    config = load_config(project_path)
    agents_md_path = (project_path / config.agents_md_path.lstrip("./")).resolve()

    client_name = _get_client_name(ctx)
    setup_connectors(project_path, agents_md_path, client_name)
    logger.info("generate_agents_md: %s (client=%s)", project_path, client_name or "unknown")

    try:
        result = await _run_pipeline(
            project_path,
            force_full_scan=False,
            include_agents_md_context=True,
        )

        if result.get("status") == "no_changes":
            return json.dumps(result, ensure_ascii=False)

        result["agents_md_path"] = str(agents_md_path)
        result["instructions"] = (
            f"Retrieve the analysis payload by calling read_payload_chunk with "
            f"project_path='{project_path}' and chunk_index starting at 0. "
            f"Keep calling until has_more is false. Accumulate all 'data' fields in order.\n\n"
            f"The payload contains an 'instructions' field - read it FIRST, it has the exact "
            f"rules and format for writing AGENTS.md.\n\n"
            f"Write AGENTS.md to: {agents_md_path}\n\n"
            f"Tell the user: 'AGENTS.md has been generated at {agents_md_path}'\n\n"
            f"IMPORTANT: Do not read any source files. Do not call generate_agents_md or "
            f"scan_codebase again. Complete all steps autonomously."
        )
        return json.dumps(result, indent=2, ensure_ascii=False)
    except NotAGitRepositoryError as exc:
        return json.dumps({"error": str(exc)}, ensure_ascii=False)
    except Exception as exc:
        logger.exception("generate_agents_md failed for %s", project_path)
        return json.dumps({"error": f"Failed: {type(exc).__name__}: {exc}"}, ensure_ascii=False)


@mcp.prompt(name="initialize-agents-md")
def initialize_agents_md_prompt(project_path: str = ".") -> str:
    """Guide the agent to create the first AGENTS.md file for a project."""
    return (
        f"Call the generate_agents_md tool with project_path='{project_path}' "
        "and follow its instructions exactly to create AGENTS.md."
    )


@mcp.prompt(name="update-agents-md")
def update_agents_md_prompt(project_path: str = ".") -> str:
    """Guide the agent to update an existing AGENTS.md after code changes."""
    return (
        f"Call the generate_agents_md tool with project_path='{project_path}' "
        "and follow its instructions exactly to update AGENTS.md."
    )


def _build_response(num_chunks: int, project_path: Path) -> dict:
    """Build the neutral response that instructs the agent to use read_payload_chunk."""
    return {
        "status": "ready",
        "total_chunks": num_chunks,
        "instructions": (
            f"Codebase analysis complete. Retrieve the full payload by calling "
            f"read_payload_chunk with project_path='{project_path}' and chunk_index "
            f"starting at 0. Keep calling until has_more is false. "
            f"Accumulate all 'data' fields in order to reconstruct the analysis payload."
        ),
    }


def main() -> None:
    import argparse
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("command", nargs="?", default=None, help="setup — configure MCP clients")
    parser.add_argument("--transport", default="stdio", choices=["stdio", "streamable-http"])
    parser.add_argument("--port", type=int, default=int(os.environ.get("PORT", 8000)))
    parser.add_argument("--host", default="0.0.0.0")
    args, _ = parser.parse_known_args()

    if args.command == "setup":
        from .setup_wizard import run_setup
        run_setup()
        return

    if args.transport == "streamable-http":
        mcp.run(transport="streamable-http", host=args.host, port=args.port)
    else:
        mcp.run()


if __name__ == "__main__":
    main()
