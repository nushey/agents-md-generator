"""Guards for the performance fixes.

Covers: git-backed file listing, csproj artifact exclusion, the payload chunk
cache, and the env-regex substring pre-filter on the per-file scanner.
"""

import json
import subprocess
from pathlib import Path

import pytest

from agents_md_mcp.build_system import _detect_build_systems
from agents_md_mcp.config import ProjectConfig, DEFAULT_CONFIG
from agents_md_mcp.models import FileChange
from agents_md_mcp.project_scanner import (
    _scan_file_env_vars,
    _walk_files,
    detect_env_vars_for_changes,
)


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=str(root), capture_output=True, check=True)


def _write(path: Path, content: str = "") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


@pytest.fixture
def config() -> ProjectConfig:
    return ProjectConfig(dict(DEFAULT_CONFIG))


@pytest.fixture
def tree(tmp_path: Path) -> Path:
    """Git project tree with committed dependency dirs and gitignored files."""
    _write(tmp_path / "src" / "main.py", "print('hi')\n")
    _write(tmp_path / "src" / "app.ts", "export {}\n")
    _write(tmp_path / "app" / "wwwroot" / "lib" / "jquery.js")
    _write(tmp_path / "node_modules" / "react" / "index.js")
    _write(tmp_path / "obj" / "App.csproj", "<Project/>")
    _write(tmp_path / "App.csproj", "<Project/>")
    _write(tmp_path / ".gitignore", "logs/\n")
    _write(tmp_path / "logs" / "debug.log")
    _git(tmp_path, "init", "-q")
    return tmp_path


class TestGitWalk:
    def test_dependency_dirs_excluded(self, tree: Path, config: ProjectConfig) -> None:
        rels = {rel for _p, rel in _walk_files(tree, config)}
        assert not any(r.startswith(("node_modules/", "obj/")) for r in rels)
        assert "app/wwwroot/lib/jquery.js" not in rels
        assert "src/main.py" in rels

    def test_gitignored_files_excluded(self, tree: Path, config: ProjectConfig) -> None:
        rels = {rel for _p, rel in _walk_files(tree, config)}
        assert not any(r.startswith("logs/") for r in rels)

    def test_walk_order_deterministic(self, tree: Path, config: ProjectConfig) -> None:
        rels = [rel for _p, rel in _walk_files(tree, config)]
        assert rels == sorted(rels)
        assert rels == [rel for _p, rel in _walk_files(tree, config)]


class TestCsprojFromWalk:
    def test_artifact_copy_not_detected(self, tree: Path, config: ProjectConfig) -> None:
        walked = _walk_files(tree, config)
        csprojs = [p for p, _rel in walked if p.suffix == ".csproj"]
        result = _detect_build_systems(tree, csprojs)
        assert "App.csproj" in result["package_files"]
        assert "obj/App.csproj" not in result["package_files"]

    def test_fallback_rglob_without_walk(self, tree: Path) -> None:
        result = _detect_build_systems(tree)
        assert "dotnet" in result["detected"]

    def test_build_payload_wires_walk_into_build_detection(
        self, tree: Path, config: ProjectConfig
    ) -> None:
        from agents_md_mcp.context_builder import build_payload

        payload = build_payload(
            project_path=tree,
            config=config,
            changes=[],
            new_analyses={},
            cache=None,
        )
        pkg_files = payload["build_system"]["package_files"]
        assert "App.csproj" in pkg_files
        assert "obj/App.csproj" not in pkg_files

    def test_uppercase_suffix_detected(self, tmp_path: Path, config: ProjectConfig) -> None:
        # Windows-style casing: the suffix filter must be case-insensitive.
        _write(tmp_path / "Legacy.CSPROJ", "<Project/>")
        _git(tmp_path, "init", "-q")
        walked = _walk_files(tmp_path, config)
        csprojs = [p for p, _rel in walked if p.suffix.lower() == ".csproj"]
        assert len(csprojs) == 1


def _changes(*paths: str) -> list[FileChange]:
    return [FileChange(path=p, status="new", new_hash="x") for p in paths]


class TestEnvDetection:
    def test_no_env_usage_detects_nothing(self, tmp_path: Path, config: ProjectConfig) -> None:
        _write(tmp_path / "clean.py", "x = 1\n")
        assert detect_env_vars_for_changes(tmp_path, config, _changes("clean.py")) == {}

    def test_python_env_detected(self, tmp_path: Path, config: ProjectConfig) -> None:
        _write(tmp_path / "settings.py", 'import os\nDB = os.environ.get("DATABASE_URL")\n')
        result = detect_env_vars_for_changes(tmp_path, config, _changes("settings.py"))
        assert result == {"settings.py": ["DATABASE_URL"]}

    def test_js_ts_go_detected(self, tmp_path: Path, config: ProjectConfig) -> None:
        _write(tmp_path / "a.js", "const k = process.env.JS_KEY;\n")
        _write(tmp_path / "b.ts", "const t = process.env.TS_KEY;\n")
        _write(tmp_path / "c.go", 'v := os.Getenv("GO_KEY")\n')
        result = detect_env_vars_for_changes(
            tmp_path, config, _changes("a.js", "b.ts", "c.go")
        )
        assert result == {"a.js": ["JS_KEY"], "b.ts": ["TS_KEY"], "c.go": ["GO_KEY"]}

    def test_only_changed_files_scanned(self, tmp_path: Path, config: ProjectConfig) -> None:
        _write(tmp_path / "changed.py", 'import os\nA = os.environ.get("CHANGED_KEY")\n')
        _write(tmp_path / "unchanged.py", 'import os\nB = os.environ.get("UNCHANGED_KEY")\n')
        result = detect_env_vars_for_changes(tmp_path, config, _changes("changed.py"))
        assert result == {"changed.py": ["CHANGED_KEY"]}

    def test_deleted_changes_skipped(self, tmp_path: Path, config: ProjectConfig) -> None:
        changes = [FileChange(path="gone.py", status="deleted", old_hash="x")]
        assert detect_env_vars_for_changes(tmp_path, config, changes) == {}

    def test_guard_actually_skips_regex(self, tmp_path: Path, config: ProjectConfig, monkeypatch) -> None:
        # Prove the fast path: a file without guard substrings must never
        # reach finditer.
        from agents_md_mcp import project_scanner as ps

        calls: list[str] = []
        real_patterns = ps._ENV_PATTERNS

        class SpyPattern:
            def __init__(self, inner):
                self._inner = inner

            def finditer(self, content):
                calls.append(content)
                return self._inner.finditer(content)

        monkeypatch.setattr(
            ps, "_ENV_PATTERNS", {k: SpyPattern(v) for k, v in real_patterns.items()}
        )
        _write(tmp_path / "clean.py", "x = 1\n")
        _write(tmp_path / "uses.py", 'import os\nY = os.environ.get("REAL_KEY")\n')
        result = detect_env_vars_for_changes(
            tmp_path, config, _changes("clean.py", "uses.py")
        )
        assert result == {"uses.py": ["REAL_KEY"]}
        assert len(calls) == 1  # only uses.py was regex-scanned

    def test_oversized_file_skipped(self, tmp_path: Path, config: ProjectConfig) -> None:
        f = _write(tmp_path / "big.py", 'import os\nX = os.environ.get("BIG_KEY")\n')
        config.max_file_size_bytes = 10
        assert _scan_file_env_vars(f, "python", config) == set()


class TestPayloadCache:
    @pytest.fixture(autouse=True)
    def _clean_cache(self):
        from agents_md_mcp import server as srv
        srv._payload_cache.clear()
        yield
        srv._payload_cache.clear()

    @pytest.mark.asyncio
    async def test_rewrite_while_cached_serves_new_payload(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        """Multi-chunk payload stays cached after a non-final chunk; a rewrite
        must be observed on the next read (identity includes size)."""
        import os
        from agents_md_mcp import server as srv
        from agents_md_mcp.models import ReadPayloadChunkInput

        monkeypatch.setattr(srv, "get_project_cache_dir", lambda _p: tmp_path)
        payload_path = tmp_path / srv.PAYLOAD_FILENAME

        old = "A" * (srv.CHUNK_CHARS + 10)  # 2 chunks
        payload_path.write_text(old, encoding="utf-8")
        os.utime(payload_path, ns=(1_000_000_000, 1_000_000_000))
        out0 = json.loads(await srv.read_payload_chunk(
            ReadPayloadChunkInput(project_path=str(tmp_path), chunk_index=0)
        ))
        assert out0["has_more"] is True
        assert payload_path in srv._payload_cache

        # Rewrite with SAME mtime but different size → must not serve stale text
        new = "B" * (srv.CHUNK_CHARS + 20)
        payload_path.write_text(new, encoding="utf-8")
        os.utime(payload_path, ns=(1_000_000_000, 1_000_000_000))
        out0b = json.loads(await srv.read_payload_chunk(
            ReadPayloadChunkInput(project_path=str(tmp_path), chunk_index=0)
        ))
        assert out0b["data"][0] == "B"

    def test_same_mtime_same_size_rewrite_needs_explicit_invalidation(
        self, tmp_path: Path
    ) -> None:
        """The pathological collision (same mtime_ns AND size) is handled by
        _run_pipeline's explicit pop after writing — mirror that here."""
        import os
        from agents_md_mcp import server as srv

        payload_path = tmp_path / "payload.json"
        payload_path.write_text("old-payload", encoding="utf-8")
        os.utime(payload_path, ns=(1_000_000_000, 1_000_000_000))
        assert srv._read_payload_cached(payload_path) == "old-payload"

        payload_path.write_text("new-payload", encoding="utf-8")  # same length
        os.utime(payload_path, ns=(1_000_000_000, 1_000_000_000))
        srv._payload_cache.pop(payload_path, None)  # what _run_pipeline does
        assert srv._read_payload_cached(payload_path) == "new-payload"

    def test_cache_is_bounded(self, tmp_path: Path) -> None:
        from agents_md_mcp import server as srv

        for i in range(srv._PAYLOAD_CACHE_MAX_ENTRIES + 3):
            p = tmp_path / f"payload{i}.json"
            p.write_text(f"payload-{i}", encoding="utf-8")
            srv._read_payload_cached(p)
        assert len(srv._payload_cache) <= srv._PAYLOAD_CACHE_MAX_ENTRIES

    @pytest.mark.asyncio
    async def test_last_chunk_deletes_and_evicts(self, tmp_path: Path, monkeypatch) -> None:
        from agents_md_mcp import server as srv
        from agents_md_mcp.models import ReadPayloadChunkInput

        monkeypatch.setattr(srv, "get_project_cache_dir", lambda _p: tmp_path)
        payload_path = tmp_path / srv.PAYLOAD_FILENAME
        payload_path.write_text('{"v":1}', encoding="utf-8")
        out = json.loads(await srv.read_payload_chunk(
            ReadPayloadChunkInput(project_path=str(tmp_path), chunk_index=0)
        ))
        assert out["has_more"] is False
        assert not payload_path.exists()
        assert payload_path not in srv._payload_cache
