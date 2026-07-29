"""Guards for the pruned-walk performance fixes.

Covers: walk equivalence against the old rglob implementation, pruned
.gitignore discovery, csproj artifact exclusion, the payload chunk cache,
and the env-regex substring pre-filter.
"""

import json
from pathlib import Path

import pytest

from agents_md_mcp.build_system import _detect_build_systems
from agents_md_mcp.change_detector import _fs_walk, _is_excluded
from agents_md_mcp.config import ProjectConfig, DEFAULT_CONFIG
from agents_md_mcp.gitignore import is_gitignored, load_gitignore_spec
from agents_md_mcp.path_utils import rel_posix
from agents_md_mcp.project_scanner import _detect_env_vars, _walk_files


def _write(path: Path, content: str = "") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


@pytest.fixture
def config() -> ProjectConfig:
    return ProjectConfig(dict(DEFAULT_CONFIG))


@pytest.fixture
def tree(tmp_path: Path) -> Path:
    """Project tree with dependency dirs, nested gitignore, and a negation."""
    _write(tmp_path / "src" / "main.py", "print('hi')\n")
    _write(tmp_path / "src" / "app.ts", "export {}\n")
    # Multi-segment exclude: "**/wwwroot/lib/**" needs a parent segment to
    # match (fnmatch's leading **/ is not optional) — same as the old filter.
    _write(tmp_path / "app" / "wwwroot" / "lib" / "jquery.js")
    _write(tmp_path / "node_modules" / "react" / "index.js")
    _write(tmp_path / "node_modules" / "react" / ".gitignore", "*.py\n")
    _write(tmp_path / "bin" / "Debug" / "App.dll")
    _write(tmp_path / "obj" / "App.csproj", "<Project/>")
    _write(tmp_path / "App.csproj", "<Project/>")
    # Root gitignore ignores logs/ but re-includes keep.log via negation
    _write(tmp_path / ".gitignore", "logs/\n!logs/keep.log\n")
    _write(tmp_path / "logs" / "debug.log")
    _write(tmp_path / "logs" / "keep.log")
    _write(tmp_path / "src" / ".gitignore", "generated.py\n")
    _write(tmp_path / "src" / "generated.py")
    return tmp_path


def _reference_rglob_walk(root: Path, config: ProjectConfig) -> list[tuple[Path, str]]:
    """The pre-fix rglob implementation, kept as the equivalence oracle."""
    gitignore_spec = load_gitignore_spec(root)
    files = []
    for item in root.rglob("*"):
        if not item.is_file():
            continue
        rel = rel_posix(item, root)
        if is_gitignored(rel, gitignore_spec):
            continue
        if _is_excluded(rel, config):
            continue
        files.append((item, rel))
    return files


class TestWalkEquivalence:
    def test_pruned_walk_matches_rglob_reference(self, tree: Path, config: ProjectConfig) -> None:
        new = sorted(rel for _p, rel in _walk_files(tree, config))
        old = sorted(rel for _p, rel in _reference_rglob_walk(tree, config))
        assert new == old

    def test_negation_reincludes_file(self, tree: Path, config: ProjectConfig) -> None:
        rels = {rel for _p, rel in _walk_files(tree, config)}
        assert "logs/keep.log" in rels
        assert "logs/debug.log" not in rels

    def test_dependency_dirs_excluded(self, tree: Path, config: ProjectConfig) -> None:
        rels = {rel for _p, rel in _walk_files(tree, config)}
        assert not any(r.startswith(("node_modules/", "bin/", "obj/")) for r in rels)
        assert "app/wwwroot/lib/jquery.js" not in rels
        assert "src/main.py" in rels

    def test_fs_walk_prunes_with_config(self, tree: Path, config: ProjectConfig) -> None:
        spec = load_gitignore_spec(tree)
        rels = set(_fs_walk(tree, spec, config))
        assert "src/main.py" in rels
        assert not any(r.startswith("node_modules/") for r in rels)
        # Without config the walk still works (pruning simply off)
        rels_uncfg = set(_fs_walk(tree, spec))
        assert "src/main.py" in rels_uncfg


class TestGitignoreDiscovery:
    def test_nested_project_gitignore_honored(self, tree: Path, config: ProjectConfig) -> None:
        spec = load_gitignore_spec(tree, config)
        assert is_gitignored("src/generated.py", spec)

    def test_dependency_gitignore_ignored(self, tree: Path, config: ProjectConfig) -> None:
        # node_modules/react/.gitignore contains "*.py" — it must not
        # contribute patterns that filter project files.
        spec = load_gitignore_spec(tree, config)
        assert not is_gitignored("node_modules/react/anything.py", spec)

    def test_user_override_reenables_nested_gitignores(self, tree: Path) -> None:
        # A user who clears the exclude list re-enables node_modules — its
        # nested .gitignore must be honored again, like the pre-fix loader.
        cfg = ProjectConfig({"exclude": []})
        spec = load_gitignore_spec(tree, cfg)
        assert is_gitignored("node_modules/react/anything.py", spec)

    def test_no_config_means_no_pruning(self, tree: Path) -> None:
        # Bare call (old signature) keeps full-discovery behavior.
        spec = load_gitignore_spec(tree)
        assert is_gitignored("node_modules/react/anything.py", spec)


class TestWalkDeterminism:
    def test_walk_order_is_lexicographic_top_down(self, tree: Path, config: ProjectConfig) -> None:
        rels = [rel for _p, rel in _walk_files(tree, config)]
        by_dir_then_name = sorted(rels, key=lambda r: (r.rsplit("/", 1)[0] if "/" in r else "", r))
        # Root files come first (os.walk is top-down), then each subdir in
        # sorted order — verify stability across two runs and per-dir sorting.
        assert rels == [rel for _p, rel in _walk_files(tree, config)]
        groups: dict[str, list[str]] = {}
        for r in rels:
            groups.setdefault(r.rsplit("/", 1)[0] if "/" in r else ".", []).append(r)
        for names in groups.values():
            assert names == sorted(names)

    def test_fs_walk_order_deterministic(self, tree: Path, config: ProjectConfig) -> None:
        spec = load_gitignore_spec(tree, config)
        assert _fs_walk(tree, spec, config) == _fs_walk(tree, spec, config)


class TestPruningProof:
    def test_excluded_dirs_never_visited(self, tree: Path, config: ProjectConfig, monkeypatch) -> None:
        # The file-set assertions alone would pass with a filter-after-descend
        # implementation; prove the walk never ENTERS excluded trees.
        import os as _os
        import agents_md_mcp.project_scanner as ps

        visited: list[str] = []
        real_walk = _os.walk

        def spy_walk(top, *args, **kwargs):
            for dirpath, dirnames, filenames in real_walk(top, *args, **kwargs):
                visited.append(str(dirpath))
                yield dirpath, dirnames, filenames

        monkeypatch.setattr(ps.os, "walk", spy_walk)
        _walk_files(tree, config)
        inside_excluded = [
            v for v in visited
            if any(seg in ("node_modules", "bin", "obj") for seg in Path(v).parts)
        ]
        assert inside_excluded == []


class TestFsWalkNonRegularFiles:
    def test_fifo_is_skipped(self, tmp_path: Path, config: ProjectConfig) -> None:
        import os as _os
        if not hasattr(_os, "mkfifo"):
            pytest.skip("mkfifo not available")
        _write(tmp_path / "real.py", "x = 1\n")
        _os.mkfifo(tmp_path / "blocking.py")
        rels = _fs_walk(tmp_path, None, config)
        assert "real.py" in rels
        assert "blocking.py" not in rels


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
        walked = _walk_files(tmp_path, config)
        csprojs = [p for p, _rel in walked if p.suffix.lower() == ".csproj"]
        assert len(csprojs) == 1


class TestEnvGuards:
    def test_rust_var_without_env_literal(self, tmp_path: Path, config: ProjectConfig) -> None:
        # Exercises the var( branch of the rust pattern — a bare "env"
        # substring guard would silently skip this file.
        _write(tmp_path / "main.rs", 'let x = var("MY_SECRET_KEY").unwrap();\n')
        cfg_raw = dict(DEFAULT_CONFIG)
        cfg = ProjectConfig(cfg_raw)
        # rust isn't in EXTENSION_TO_LANGUAGE, so guard the guard-table directly
        from agents_md_mcp.project_scanner import _ENV_GUARDS, _ENV_PATTERNS
        content = (tmp_path / "main.rs").read_text()
        guards = _ENV_GUARDS["rust"]
        assert any(g in content for g in guards)
        match = _ENV_PATTERNS["rust"].search(content)
        assert match is not None

    def test_no_env_usage_detects_nothing(self, tmp_path: Path, config: ProjectConfig) -> None:
        _write(tmp_path / "clean.py", "x = 1\n")
        assert _detect_env_vars(tmp_path, config) == []

    def test_python_env_still_detected(self, tmp_path: Path, config: ProjectConfig) -> None:
        _write(tmp_path / "settings.py", 'import os\nDB = os.environ.get("DATABASE_URL")\n')
        assert _detect_env_vars(tmp_path, config) == ["DATABASE_URL"]

    def test_js_ts_go_still_detected(self, tmp_path: Path, config: ProjectConfig) -> None:
        _write(tmp_path / "a.js", "const k = process.env.JS_KEY;\n")
        _write(tmp_path / "b.ts", "const t = process.env.TS_KEY;\n")
        _write(tmp_path / "c.go", 'v := os.Getenv("GO_KEY")\n')
        assert _detect_env_vars(tmp_path, config) == ["GO_KEY", "JS_KEY", "TS_KEY"]

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
        assert _detect_env_vars(tmp_path, config) == ["REAL_KEY"]
        assert len(calls) == 1  # only uses.py was regex-scanned


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
