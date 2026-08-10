"""Incremental-scan completeness: wiring, interface map, and env vars must not
shrink to just the changed files — plus the payload budget enforcer."""

import json
from pathlib import Path

from agents_md_mcp.cache import make_empty_cache
from agents_md_mcp.config import SIZE_PROFILES, ProjectConfig, DEFAULT_CONFIG, load_config
from agents_md_mcp.context_builder import build_payload
from agents_md_mcp.models import CachedFile, CachedSymbol, FileChange
from agents_md_mcp.server import PAYLOAD_BUDGET_CHARS, _enforce_budget

from tests.conftest import git_init


def _controller_symbols() -> list[CachedSymbol]:
    return [
        CachedSymbol(
            name="UsersController", kind="class", visibility="public",
            signature="class UsersController",
            decorators=["ApiController", 'Route("api/users")'],
        ),
        CachedSymbol(
            name="GetAll", kind="method", visibility="public",
            signature="public IActionResult GetAll()",
            decorators=["HttpGet"], parent="UsersController",
        ),
    ]


def test_wiring_includes_unchanged_cached_files(tmp_path: Path) -> None:
    git_init(tmp_path)
    cfg = load_config(tmp_path)
    cache = make_empty_cache()
    cache.files["Api/UsersController.cs"] = CachedFile(
        hash="abc", symbols=_controller_symbols(),
    )
    # The only change is an unrelated file — the controller must still be wired.
    changes = [FileChange(path="other.py", status="new", new_hash="x")]

    payload = build_payload(tmp_path, cfg, changes, {}, cache=cache, scan_type="incremental")

    route_files = [e["file"] for e in payload["wiring"].get("route_map", [])]
    assert "Api/UsersController.cs" in route_files


def test_interface_map_includes_unchanged_cached_files(tmp_path: Path) -> None:
    git_init(tmp_path)
    cfg = load_config(tmp_path)
    cache = make_empty_cache()
    cache.files["Domain/IRepo.cs"] = CachedFile(hash="a", symbols=[
        CachedSymbol(name="IRepo", kind="interface", visibility="public", signature="interface IRepo"),
    ])
    cache.files["Infra/Repo.cs"] = CachedFile(hash="b", symbols=[
        CachedSymbol(name="Repo", kind="class", visibility="public",
                     signature="class Repo", implements=["IRepo"]),
    ])
    changes = [FileChange(path="other.py", status="new", new_hash="x")]

    payload = build_payload(tmp_path, cfg, changes, {}, cache=cache, scan_type="incremental")
    assert payload["interface_impl_map"] == {"IRepo": ["Repo"]}


def test_deleted_files_dropped_from_merged_maps(tmp_path: Path) -> None:
    git_init(tmp_path)
    cfg = load_config(tmp_path)
    cache = make_empty_cache()
    cache.files["Api/UsersController.cs"] = CachedFile(
        hash="abc", symbols=_controller_symbols(),
    )
    changes = [FileChange(path="Api/UsersController.cs", status="deleted", old_hash="abc")]

    payload = build_payload(tmp_path, cfg, changes, {}, cache=cache, scan_type="incremental")
    assert payload["wiring"].get("route_map") is None


# ── budget enforcement ───────────────────────────────────────────────────────

def _dump(p: dict) -> str:
    return json.dumps(p, separators=(",", ":"), ensure_ascii=False)


def _fat_payload(n_entries: int) -> dict:
    return {
        "metadata": {"project_name": "big"},
        "method_patterns": {},
        "full_analysis": [
            {
                "file": f"src/file{i}.py",
                "symbols": [{"name": f"C{i}", "kind": "class",
                             "methods": ["public void DoTheThing(int a, string b)"] * 20}],
            }
            for i in range(n_entries)
        ],
    }


def test_enforce_budget_fits_oversized_payload() -> None:
    cfg = ProjectConfig({**DEFAULT_CONFIG, "project_size": "large"})
    payload = _fat_payload(5000)
    payload_json = _dump(payload)
    assert len(payload_json) > PAYLOAD_BUDGET_CHARS

    payload, payload_json = _enforce_budget(
        payload, payload_json, _dump, cfg, rebuild=lambda: payload,
    )
    assert len(payload_json) <= PAYLOAD_BUDGET_CHARS
    assert payload["metadata"]["degradations"]
    # methods were stripped before truncation
    for entry in payload["full_analysis"]:
        for sym in entry["symbols"]:
            assert "methods" not in sym


def test_enforce_budget_reprofiles_first() -> None:
    cfg = ProjectConfig(dict(DEFAULT_CONFIG))
    cfg.project_size = "medium"
    cfg.profile = SIZE_PROFILES["medium"]
    small = {"metadata": {}, "full_analysis": []}
    rebuilt: list[bool] = []

    def rebuild():
        rebuilt.append(True)
        return small

    _enforce_budget(_fat_payload(5000), _dump(_fat_payload(5000)), _dump, cfg, rebuild)
    assert rebuilt == [True]
    assert cfg.project_size == "large"
