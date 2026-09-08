import asyncio
import json
import multiprocessing
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from agents_md_mcp import cache, change_detector, server
from agents_md_mcp.ast_analyzer import classify_impact, diff_analysis
from agents_md_mcp.config import DEFAULT_CONFIG, ProjectConfig
from agents_md_mcp.context_builder import build_payload
from agents_md_mcp.models import CachedFile, CachedSymbol, FileAnalysis, FileChange, ReadPayloadChunkInput, SymbolInfo


def _isolated_worker(connection, project_path, force_full_scan, include_agents_md_context):
    cache_dir = project_path / ".scan-cache"
    cache_dir.mkdir(exist_ok=True)
    cache.get_project_cache_dir = lambda _: cache_dir
    server.get_project_cache_dir = lambda _: cache_dir
    server._pipeline_worker(connection, project_path, force_full_scan, include_agents_md_context)


def _slow_worker(connection, *args):
    connection.send(("progress", "Parsing"))
    time.sleep(30)


def _worker_with_subprocess(connection, project_path, *args):
    if os.name != "nt":
        os.setsid()
    child = subprocess.Popen(
        [sys.executable, "-c", "import pathlib,sys,time; print('ready', flush=True); time.sleep(2); pathlib.Path(sys.argv[1]).touch()", str(project_path / "survived")],
        stdout=subprocess.PIPE,
    )
    child.stdout.readline()
    connection.send(("progress", "Child running"))
    child.wait()


@pytest.fixture
def repo(tmp_path, monkeypatch):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    (tmp_path / "main.py").write_text("@app.get('/hello')\ndef hello():\n    pass\n", encoding="utf-8")
    cache_dir = tmp_path / ".scan-cache"
    cache_dir.mkdir()
    monkeypatch.setattr(cache, "get_project_cache_dir", lambda _: cache_dir)
    monkeypatch.setattr(server, "get_project_cache_dir", lambda _: cache_dir)
    return tmp_path


def _payload(repo):
    return json.loads((repo / ".scan-cache" / server.PAYLOAD_FILENAME).read_text(encoding="utf-8"))


@pytest.mark.parametrize("existing", [False, True])
def test_generation_retry_reuses_analysis_without_losing_context(repo, monkeypatch, existing):
    if existing:
        (repo / "AGENTS.md").write_text("Existing rules", encoding="utf-8")
    server._run_pipeline_sync(repo, False, True)
    original = _payload(repo)
    monkeypatch.setattr("agents_md_mcp.ast_analyzer._get_analyzer", lambda _: pytest.fail("Unchanged source was parsed"))
    result = server._run_pipeline_sync(repo, False, True)
    assert result["status"] == "ready"
    assert _payload(repo)["full_analysis"] == original["full_analysis"]
    assert _payload(repo)["existing_agents_md"] == ("Existing rules" if existing else None)


def test_general_scan_does_not_consume_generation(repo):
    server._run_pipeline_sync(repo, False)
    assert server._run_pipeline_sync(repo, False, True)["status"] == "ready"
    assert _payload(repo)["full_analysis"]
    assert _payload(repo)["mode"] == "create"


def test_interrupted_update_survives_another_general_scan(repo):
    (repo / "AGENTS.md").write_text("Document before update", encoding="utf-8")
    server._run_pipeline_sync(repo, False, True)
    (repo / "main.py").write_text("@app.get('/replacement')\ndef replacement():\n    pass\n", encoding="utf-8")
    server._run_pipeline_sync(repo, False)
    server._run_pipeline_sync(repo, False, True)
    payload = _payload(repo)
    assert "replacement" in json.dumps(payload["full_analysis"])
    assert "hello" not in json.dumps(payload["full_analysis"])
    assert payload["existing_agents_md"] == "Document before update"


@pytest.mark.asyncio
async def test_retry_after_last_chunk_is_consumed(repo):
    result = server._run_pipeline_sync(repo, False, True)
    for index in range(result["total_chunks"]):
        await server.read_payload_chunk(ReadPayloadChunkInput(project_path=str(repo), chunk_index=index))
    assert not (repo / ".scan-cache" / server.PAYLOAD_FILENAME).exists()
    assert server._run_pipeline_sync(repo, False, True)["status"] == "ready"
    assert _payload(repo)["full_analysis"]


def test_generation_handles_no_supported_files(repo):
    (repo / "main.py").unlink()
    assert server._run_pipeline_sync(repo, False, True)["status"] == "ready"
    assert _payload(repo)["mode"] == "create"


def test_snapshot_removes_deleted_source(repo):
    server._run_pipeline_sync(repo, False, True)
    (repo / "main.py").unlink()
    server._run_pipeline_sync(repo, False, True)
    assert _payload(repo)["full_analysis"] == []
    assert not _payload(repo)["wiring"]


def test_payload_failure_does_not_advance_cache(repo, monkeypatch):
    server._run_pipeline_sync(repo, False)
    previous = cache.load_cache(repo)
    (repo / "main.py").write_text("def updated(): pass", encoding="utf-8")
    monkeypatch.setattr(server, "PAYLOAD_BUDGET_CHARS", 1)
    with pytest.raises(ValueError, match="budget"):
        server._run_pipeline_sync(repo, False, True)
    assert cache.load_cache(repo) == previous


@pytest.mark.asyncio
async def test_real_worker_keeps_event_loop_responsive(repo, monkeypatch):
    monkeypatch.setattr(server, "_pipeline_worker", _isolated_worker)
    ticks = 0
    task = asyncio.create_task(server._run_pipeline(repo, False, True))
    while not task.done():
        ticks += 1
        await asyncio.sleep(0.01)
    result = await task
    assert result["status"] == "ready"
    assert ticks > 1
    assert _payload(repo)["full_analysis"]
    assert not server._active_scans


@pytest.mark.asyncio
async def test_timeout_stops_worker_and_releases_project(repo, monkeypatch):
    before = set(multiprocessing.active_children())
    monkeypatch.setattr(server, "_pipeline_worker", _slow_worker)
    monkeypatch.setattr(server, "SCAN_TIMEOUT_SECONDS", 0.2)
    with pytest.raises(TimeoutError, match="Scan exceeded"):
        await server._run_pipeline(repo, False)
    assert set(multiprocessing.active_children()) == before
    assert not server._active_scans


@pytest.mark.asyncio
async def test_cancellation_stops_worker_and_reports_progress(repo, monkeypatch):
    before = set(multiprocessing.active_children())
    monkeypatch.setattr(server, "_pipeline_worker", _slow_worker)
    reported = asyncio.Event()

    class Context:
        async def report_progress(self, **kwargs):
            assert kwargs["message"] == "Parsing"
            reported.set()

    task = asyncio.create_task(server._run_pipeline(repo, False, ctx=Context()))
    try:
        await asyncio.wait_for(reported.wait(), 10)
        with pytest.raises(RuntimeError, match="already running"):
            await server._run_pipeline(repo, False)
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    assert set(multiprocessing.active_children()) == before
    assert not server._active_scans


@pytest.mark.asyncio
async def test_cancellation_stops_worker_subprocesses(repo, monkeypatch):
    monkeypatch.setattr(server, "_pipeline_worker", _worker_with_subprocess)
    reported = asyncio.Event()

    class Context:
        async def report_progress(self, **kwargs):
            reported.set()

    task = asyncio.create_task(server._run_pipeline(repo, False, ctx=Context()))
    try:
        await asyncio.wait_for(reported.wait(), 10)
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    await asyncio.sleep(3)
    assert not (repo / "survived").exists()
    assert not server._active_scans


def test_excluded_unsupported_and_oversized_files_are_not_hashed(repo, monkeypatch):
    (repo / "node_modules").mkdir()
    (repo / "node_modules" / "dependency.js").write_text("dependency", encoding="utf-8")
    (repo / "asset.bin").write_bytes(b"binary")
    (repo / "big.py").write_text("x" * 1000, encoding="utf-8")
    config = ProjectConfig({**DEFAULT_CONFIG, "max_file_size_bytes": 100})
    original = change_detector._git_blob_hashes
    hashed = []

    def record(root, paths):
        hashed.extend(paths)
        return original(root, paths)

    monkeypatch.setattr(change_detector, "_git_blob_hashes", record)
    changes = change_detector.detect_changes(repo, config, None)
    assert hashed == ["main.py"]
    assert [change.path for change in changes] == ["main.py"]


@pytest.mark.parametrize("command", ["status", "hash-object"])
def test_git_failure_cannot_report_unchanged(repo, monkeypatch, command):
    server._run_pipeline_sync(repo, False)
    (repo / "main.py").write_text("def changed(): pass", encoding="utf-8")
    original = change_detector._run_git

    def fail(root, args, input_text=None):
        return None if args[0] == command else original(root, args, input_text)

    monkeypatch.setattr(change_detector, "_run_git", fail)
    with pytest.raises(change_detector.GitCommandError):
        change_detector.detect_changes(repo, ProjectConfig(DEFAULT_CONFIG), cache.load_cache(repo))


def test_git_timeout_is_explicit(repo, monkeypatch):
    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired("git status", 120)

    monkeypatch.setattr(change_detector.subprocess, "run", timeout)
    with pytest.raises(change_detector.GitCommandError, match="status"):
        change_detector._run_git(repo, ["status"])


def test_incomplete_hash_batch_is_an_error(repo, monkeypatch):
    monkeypatch.setattr(change_detector, "_run_git", lambda *args, **kwargs: "one-hash\n")
    with pytest.raises(change_detector.GitCommandError, match="incomplete"):
        change_detector._git_blob_hashes(repo, ["a.py", "b.py"])


def _dump(payload):
    return json.dumps(payload, separators=(",", ":"), ensure_ascii=False)


@pytest.mark.parametrize("section", ["changes", "full_analysis", "entry_points", "env_vars", "interface_impl_map", "project_structure", "build_system", "wiring"])
def test_every_analysis_section_obeys_budget(section):
    entries = [f"module/{i}/" + "x" * 80 for i in range(5000)]
    value = {str(i): entry for i, entry in enumerate(entries)} if section in {"interface_impl_map", "project_structure", "build_system", "wiring"} else entries
    payload = {"metadata": {}, "instructions": "Preserve rules", "existing_agents_md": "Existing document", section: value}
    if section == "full_analysis":
        payload[section] = [{"file": entry} for entry in entries]
    config = ProjectConfig({**DEFAULT_CONFIG, "project_size": "large"})
    result, text = server._enforce_budget(payload, _dump(payload), _dump, config, lambda: payload)
    assert len(text) <= server.PAYLOAD_BUDGET_CHARS
    assert json.loads(text) == result
    assert result["existing_agents_md"] == "Existing document"
    assert result["instructions"] == "Preserve rules"
    assert result["metadata"]["truncated_sections"][section] > 0


def test_single_oversized_analysis_entry_can_be_removed():
    payload = {"metadata": {}, "full_analysis": [{"file": "x" * 400000}]}
    config = ProjectConfig({**DEFAULT_CONFIG, "project_size": "large"})
    result, text = server._enforce_budget(payload, _dump(payload), _dump, config, lambda: payload)
    assert len(text) <= server.PAYLOAD_BUDGET_CHARS
    assert result["metadata"]["truncated_entries"] == 1


def test_existing_document_is_never_silently_truncated():
    payload = {"metadata": {}, "existing_agents_md": "x" * 400000}
    config = ProjectConfig({**DEFAULT_CONFIG, "project_size": "large"})
    with pytest.raises(ValueError, match="cannot be safely truncated"):
        server._enforce_budget(payload, _dump(payload), _dump, config, lambda: payload)


def _symbol(parent="A", signature="get()", **kwargs):
    return SymbolInfo(name="get", kind="method", parent=parent, signature=signature, visibility="public", **kwargs)


def test_diff_keeps_parent_identity():
    a, b = _symbol(), _symbol(parent="B")
    diff = diff_analysis([a, b], [b])
    assert diff.removed == [a]


def test_diff_preserves_overloads_and_ignores_order():
    a, b = _symbol(signature="get(int id)"), _symbol(signature="get(string name)")
    assert diff_analysis([a, b], [b, a]).model_dump() == {"added": [], "removed": [], "modified": []}
    assert diff_analysis([a, b], [b]).removed == [a]
    updated = _symbol(signature="get(long id)")
    assert diff_analysis([a, b], [b, updated]).modified == [updated]


@pytest.mark.parametrize("field,value", [("decorators", ['HttpGet("new")']), ("implements", ["IReader"]), ("visibility", "private")])
def test_diff_detects_architectural_attributes(field, value):
    old = _symbol()
    updated = old.model_copy(update={field: value})
    assert diff_analysis([old], [updated]).modified == [updated]


def test_diff_accepts_cached_symbols_for_removals():
    old = CachedSymbol(name="get", kind="method", parent="A", signature="get()")
    assert diff_analysis([old], []).removed[0].parent == "A"


def test_route_arguments_remain_high_impact():
    assert classify_impact(_symbol(decorators=['HttpGet("new")']), "modified") == "high"


def test_removed_route_decorator_survives_large_profile(repo):
    old = _symbol(decorators=['HttpGet("old")'])
    updated = old.model_copy(update={"decorators": []})
    previous = cache.make_empty_cache()
    previous.files["main.py"] = CachedFile(hash="old", symbols=[CachedSymbol(**old.model_dump(exclude={"line_start", "line_end"}))])
    payload = build_payload(
        repo, ProjectConfig({**DEFAULT_CONFIG, "project_size": "large"}),
        [FileChange(path="main.py", status="modified")],
        {"main.py": FileAnalysis(path="main.py", language="python", symbols=[updated])}, previous,
    )
    change = payload["changes"][0]
    assert change["impact"] == "high"
    assert change["diff"]["modified_symbols"][0]["parent"] == "A"


def test_budget_rebuild_reuses_file_listing(repo, monkeypatch):
    calls = []
    original_walk = server._walk_files

    def walk(*args):
        calls.append(True)
        return original_walk(*args)

    def unexpected_walk(*args):
        pytest.fail("Budget rebuild listed project files again")

    monkeypatch.setattr(server, "_walk_files", walk)
    monkeypatch.setattr("agents_md_mcp.context_builder._walk_files", unexpected_walk)
    monkeypatch.setattr(server, "PAYLOAD_BUDGET_CHARS", 1)
    with pytest.raises(ValueError, match="budget"):
        server._run_pipeline_sync(repo, False, True)
    assert calls == [True]


@pytest.mark.asyncio
async def test_worker_errors_reach_the_tool(repo, monkeypatch):
    monkeypatch.setattr(server, "_pipeline_worker", _isolated_worker)
    (repo / "AGENTS.md").write_text("x" * 400000, encoding="utf-8")
    from agents_md_mcp.models import GenerateAgentsMdInput
    result = json.loads(await server.generate_agents_md(GenerateAgentsMdInput(project_path=str(repo)), None))
    assert "cannot be safely truncated" in result["error"]
    assert not server._active_scans
