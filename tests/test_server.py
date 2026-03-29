"""Tests for server.py — read_payload_chunk tool."""

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from agents_md_mcp.models import ReadPayloadChunkInput
from agents_md_mcp.server import CHUNK_LINES, read_payload_chunk


# ── Helpers ───────────────────────────────────────────────────────────────────


def _write_payload(cache_dir: Path, content: str) -> Path:
    cache_dir.mkdir(parents=True, exist_ok=True)
    payload_path = cache_dir / "payload.json"
    payload_path.write_text(content, encoding="utf-8")
    return payload_path


def _params(project_path: str, chunk_index: int) -> ReadPayloadChunkInput:
    return ReadPayloadChunkInput(project_path=project_path, chunk_index=chunk_index)


# ── File not found ─────────────────────────────────────────────────────────────


async def test_read_payload_chunk_no_file(tmp_path: Path) -> None:
    with patch("agents_md_mcp.server.get_project_cache_dir", return_value=tmp_path):
        result = json.loads(await read_payload_chunk(_params(str(tmp_path), 0)))
    assert "error" in result
    assert "scan_codebase" in result["error"]


# ── Single chunk (small payload) ───────────────────────────────────────────────


async def test_read_payload_chunk_single_chunk(tmp_path: Path) -> None:
    content = '{"key": "value"}\n'
    payload_path = _write_payload(tmp_path, content)

    with patch("agents_md_mcp.server.get_project_cache_dir", return_value=tmp_path):
        result = json.loads(await read_payload_chunk(_params(str(tmp_path), 0)))

    assert result["chunk_index"] == 0
    assert result["total_chunks"] == 1
    assert result["has_more"] is False
    assert result["data"] == content
    # File must be deleted after last chunk
    assert not payload_path.exists()


# ── Multi-chunk payload ────────────────────────────────────────────────────────


async def test_read_payload_chunk_multi_chunk_reads_all(tmp_path: Path) -> None:
    lines = [f"line {i}\n" for i in range(CHUNK_LINES + 10)]
    content = "".join(lines)
    _write_payload(tmp_path, content)

    accumulated = ""
    with patch("agents_md_mcp.server.get_project_cache_dir", return_value=tmp_path):
        chunk_index = 0
        while True:
            result = json.loads(await read_payload_chunk(_params(str(tmp_path), chunk_index)))
            assert result["total_chunks"] == 2
            accumulated += result["data"]
            if not result["has_more"]:
                break
            chunk_index += 1

    assert accumulated == content


async def test_read_payload_chunk_last_chunk_deletes_file(tmp_path: Path) -> None:
    lines = [f"line {i}\n" for i in range(CHUNK_LINES + 1)]
    payload_path = _write_payload(tmp_path, "".join(lines))

    with patch("agents_md_mcp.server.get_project_cache_dir", return_value=tmp_path):
        # Read first chunk — file must still exist
        await read_payload_chunk(_params(str(tmp_path), 0))
        assert payload_path.exists()

        # Read last chunk — file must be deleted
        await read_payload_chunk(_params(str(tmp_path), 1))
        assert not payload_path.exists()


async def test_read_payload_chunk_intermediate_has_more_true(tmp_path: Path) -> None:
    lines = [f"line {i}\n" for i in range(CHUNK_LINES * 3)]
    _write_payload(tmp_path, "".join(lines))

    with patch("agents_md_mcp.server.get_project_cache_dir", return_value=tmp_path):
        result = json.loads(await read_payload_chunk(_params(str(tmp_path), 0)))
    assert result["has_more"] is True
    assert result["total_chunks"] == 3


# ── Out-of-range chunk_index ───────────────────────────────────────────────────


async def test_read_payload_chunk_out_of_range(tmp_path: Path) -> None:
    _write_payload(tmp_path, "line 1\n")

    with patch("agents_md_mcp.server.get_project_cache_dir", return_value=tmp_path):
        result = json.loads(await read_payload_chunk(_params(str(tmp_path), 99)))
    assert "error" in result
    assert "out of range" in result["error"]
