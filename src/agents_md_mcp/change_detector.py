"""ChangeDetector: git-based detection of new/modified/deleted files since last scan.

Git is the source of truth: file identity comes from git blob SHAs (index for
clean files, `git hash-object` for dirty ones), so an incremental scan costs a
couple of git subprocess calls plus reads of only the files that actually
changed — never a full re-hash of the repository.
"""

import fnmatch
import json
import logging
import subprocess
from pathlib import Path

from .cache import CacheData
from .config import ProjectConfig
from .models import FileChange
from .path_utils import normalize_path

logger = logging.getLogger(__name__)


class NotAGitRepositoryError(RuntimeError):
    """Raised when the project path is not inside a git repository."""


class GitCommandError(RuntimeError):
    pass


_NOT_A_REPO_MSG = (
    "is not a git repository. agents-md-generator relies on git for change "
    "detection — run 'git init' in the project root (and commit your code) first."
)


def _run_git(project_path: Path, args: list[str], input_text: str | None = None) -> str | None:
    """Return stdout, or None outside a repository; raise on command failure."""
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=str(project_path),
            capture_output=True,
            text=True,
            input=input_text,
            timeout=120,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError) as exc:
        raise GitCommandError(f"git {args[0]} failed: {exc}") from exc
    if result.returncode != 0:
        if "not a git repository" in result.stderr.lower():
            return None
        raise GitCommandError(f"git {args[0]} failed: {result.stderr.strip()}")
    return result.stdout


def _git_index_hashes(root: Path) -> dict[str, str] | None:
    """Tracked files with their index blob SHAs — one git call, zero file reads."""
    out = _run_git(root, ["ls-files", "-s", "-z"])
    if out is None:
        return None
    hashes: dict[str, str] = {}
    for entry in out.split("\0"):
        if not entry:
            continue
        meta, _, path = entry.partition("\t")
        fields = meta.split()
        # "<mode> <sha> <stage>" — skip gitlinks (submodules, mode 160000)
        if len(fields) != 3 or fields[0] == "160000":
            continue
        hashes[normalize_path(path)] = fields[1]
    return hashes


def _git_worktree_overrides(root: Path) -> tuple[list[str], set[str]]:
    """Parse `git status` into (paths needing a fresh hash, worktree-deleted paths)."""
    out = _run_git(root, ["status", "--porcelain", "-uall", "-z"])
    if out is None:
        raise GitCommandError("git status failed; change detection is incomplete")
    dirty: list[str] = []
    deleted: set[str] = set()
    tokens = out.split("\0")
    i = 0
    while i < len(tokens):
        entry = tokens[i]
        i += 1
        if len(entry) < 4:
            continue
        status, path = entry[:2], normalize_path(entry[3:])
        # Rename/copy entries carry the original path as the next NUL token
        if status[0] in "RC":
            i += 1
        if status == "??" or status[1] in "MA":
            dirty.append(path)
        elif status[1] == "D":
            deleted.add(path)
    return dirty, deleted


def _git_blob_hashes(root: Path, paths: list[str]) -> dict[str, str]:
    """Batch-hash working-tree files with one `git hash-object` subprocess."""
    if not paths:
        return {}
    input_text = "\n".join(json.dumps(p, ensure_ascii=False) for p in paths) + "\n"
    out = _run_git(root, ["hash-object", "--stdin-paths"], input_text=input_text)
    if out is None:
        raise GitCommandError("git hash-object failed; change detection is incomplete")
    hashes = out.split()
    if len(hashes) != len(paths):
        raise GitCommandError("git hash-object returned an incomplete batch")
    return dict(zip(paths, hashes))


def git_file_hashes(root: Path, config: ProjectConfig | None = None) -> dict[str, str] | None:
    """Current content hash for every file git would scan (tracked + untracked).

    Clean files use their index blob SHA; dirty/untracked files are hashed via
    a single batched `git hash-object`. Returns None if not a git repo.
    """
    hashes = _git_index_hashes(root)
    if hashes is None:
        return None
    dirty, deleted = _git_worktree_overrides(root)
    if config is not None:
        hashes = {p: hashes[p] for p in _filter_paths(list(hashes), config)}
        dirty = _filter_paths(dirty, config)
    for path in deleted:
        hashes.pop(path, None)
    # hash-object fails the whole batch on a vanished path — filter first
    dirty_existing = [p for p in dirty if (root / p).is_file()]
    if config is not None:
        oversized = {p for p in dirty_existing if _is_too_large(root / p, config)}
        dirty_existing = [p for p in dirty_existing if p not in oversized]
        for path in oversized:
            hashes.pop(path, None)
    hashes.update(_git_blob_hashes(root, dirty_existing))
    return hashes


def git_list_all_files(root: Path) -> list[str] | None:
    """All project files (tracked + untracked, gitignore respected), any extension.

    Used by the structure scanners. Returns None if not a git repo.
    """
    out = _run_git(root, ["ls-files", "-z", "--cached", "--others", "--exclude-standard"])
    if out is None:
        return None
    return [normalize_path(p) for p in out.split("\0") if p]


def _is_excluded(path: str, config: ProjectConfig) -> bool:
    """Return True if the path matches any exclude pattern.

    Strategy:
    1. Direct fnmatch on the full path — handles **/*.ext patterns
       (fnmatch treats * as matching /, so ** works as a greedy wildcard)
       Path is normalized to forward slashes so patterns work on Windows too.
    2. Inner-segment check — handles **/dirname/** patterns where the path
       doesn't start with /: extract the middle token and match any component
    """
    normalized = normalize_path(path)
    path_parts = normalized.split("/")
    # Fast path: plain directory-name excludes (node_modules, dist, .git, …)
    # resolved by O(1) set membership instead of an fnmatch loop. Equivalent to
    # the inner-segment check below for these tokens, since "**/<dir>/**" only
    # matches when <dir> is an exact path component.
    if not config._exclude_dir_tokens.isdisjoint(path_parts):
        return True
    for pattern in config._exclude_globs:
        # 1. Direct fnmatch (works for **/*.min.js, **/dist/**, etc.)
        if fnmatch.fnmatch(normalized, pattern):
            return True
        # 2. Extract inner token between leading **/ and trailing /**
        #    e.g. "**/.venv/**" → ".venv", "**/node_modules/**" → "node_modules"
        inner = pattern
        if inner.startswith("**/"):
            inner = inner[3:]
        if inner.endswith("/**"):
            inner = inner[:-3]
        # Only apply the component check when we have a clean token (no wildcards
        # spanning path separators) — avoids false positives on patterns like *.min.js
        if inner and "/" not in inner and any(
            fnmatch.fnmatch(part, inner) for part in path_parts
        ):
            return True
    return False


def _is_included(path: str, config: ProjectConfig) -> bool:
    """If include list is non-empty, path must match at least one pattern."""
    if not config.include:
        return True
    return any(fnmatch.fnmatch(path, p) for p in config.include)


def _filter_paths(paths: list[str], config: ProjectConfig) -> list[str]:
    """Apply exclude/include filters and extension check."""
    result = []
    for p in paths:
        if _is_excluded(p, config):
            continue
        if not _is_included(p, config):
            continue
        if not config.is_extension_supported(Path(p).suffix):
            continue
        result.append(p)
    return result


def _is_too_large(path: Path, config: ProjectConfig) -> bool:
    try:
        return path.stat().st_size > config.max_file_size_bytes
    except OSError:
        return False


def detect_changes(
    project_path: str | Path,
    config: ProjectConfig,
    cache: CacheData | None,
) -> list[FileChange]:
    """
    Detect which files changed since the last scan, using git as source of truth.

    Cold start (no cache): all files → status "new".
    Incremental (cache exists): compare git content hashes against the cache —
    only changed files are ever stat'ed or read.

    Raises NotAGitRepositoryError when the project is not a git repository.
    """
    root = Path(project_path).resolve()

    hashes = git_file_hashes(root, config)
    if hashes is None:
        raise NotAGitRepositoryError(f"'{root}' {_NOT_A_REPO_MSG}")

    scannable = set(_filter_paths(list(hashes), config))
    current = {p: h for p, h in hashes.items() if p in scannable}

    # Auto profile resolution: this is the first (and only) point in the
    # pipeline where the supported-file count of the whole project is known.
    config.resolve_profile(len(current))

    cached_files = cache.files if cache is not None else {}
    changes: list[FileChange] = []

    for rel in sorted(cached_files):
        cached_file = cached_files[rel]
        if rel not in current:
            changes.append(FileChange(path=rel, status="deleted", old_hash=cached_file.hash))
            continue
        if current[rel] == cached_file.hash:
            continue
        if _is_too_large(root / rel, config):
            logger.warning("Skipping large file: %s", rel)
            continue
        changes.append(FileChange(
            path=rel, status="modified",
            old_hash=cached_file.hash, new_hash=current[rel],
        ))

    for rel in sorted(current.keys() - cached_files.keys()):
        if _is_too_large(root / rel, config):
            logger.warning("Skipping large file: %s", rel)
            continue
        changes.append(FileChange(path=rel, status="new", new_hash=current[rel]))

    return changes
