"""ChangeDetector: detects new/modified/deleted files since last scan."""

import fnmatch
import hashlib
import logging
import subprocess
from pathlib import Path

from .cache import CacheData
from .config import ProjectConfig
from .gitignore import is_gitignored, load_gitignore_spec
from .models import FileChange

logger = logging.getLogger(__name__)


def _hash_file(path: Path) -> str:
    """Return SHA-256 hex digest of file contents."""
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()


def _git_ls_files(project_path: Path) -> list[str] | None:
    """Return list of git-tracked file paths (relative). None if not a git repo."""
    try:
        result = subprocess.run(
            ["git", "ls-files"],
            cwd=str(project_path),
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode == 0:
            return [p for p in result.stdout.splitlines() if p]
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass
    return None


def _fs_walk(project_path: Path, gitignore_spec=None) -> list[str]:
    """Fallback: walk filesystem when not a git repo, respecting .gitignore."""
    files = []
    for p in project_path.rglob("*"):
        if not p.is_file():
            continue
        rel = str(p.relative_to(project_path))
        if gitignore_spec and is_gitignored(rel, gitignore_spec):
            continue
        files.append(rel)
    return files


def _is_excluded(path: str, config: ProjectConfig) -> bool:
    """Return True if the path matches any exclude pattern.

    Strategy:
    1. Direct fnmatch on the full path — handles **/*.ext patterns
       (fnmatch treats * as matching /, so ** works as a greedy wildcard)
       Path is normalized to forward slashes so patterns work on Windows too.
    2. Inner-segment check — handles **/dirname/** patterns where the path
       doesn't start with /: extract the middle token and match any component
    """
    # Normalize to forward slashes so patterns like **/app/lib/** work on Windows
    normalized = path.replace("\\", "/")
    path_parts = Path(path).parts
    for pattern in config.exclude:
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


def _filter_paths(
    paths: list[str],
    config: ProjectConfig,
    gitignore_spec=None,
) -> list[str]:
    """Apply gitignore, exclude/include filters, and extension check."""
    result = []
    for p in paths:
        if gitignore_spec and is_gitignored(p, gitignore_spec):
            continue
        if _is_excluded(p, config):
            continue
        if not _is_included(p, config):
            continue
        ext = Path(p).suffix
        if not config.is_extension_supported(ext):
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
    Detect which files changed since the last scan.

    Cold start (no cache): all tracked files → status "new".
    Incremental (cache exists): hash-compare each file.

    For git repos, uses git ls-files (already respects .gitignore).
    For non-git repos, parses .gitignore via pathspec.
    """
    root = Path(project_path).resolve()

    raw_files = _git_ls_files(root)
    is_git_repo = raw_files is not None

    if is_git_repo:
        # git ls-files already respects .gitignore — no need to parse it ourselves
        gitignore_spec = None
    else:
        logger.warning("Not a git repo, falling back to filesystem walk")
        gitignore_spec = load_gitignore_spec(root)
        raw_files = _fs_walk(root, gitignore_spec)

    filtered = _filter_paths(raw_files, config, gitignore_spec)

    if cache is None:
        return _cold_start(root, filtered, config)
    return _incremental(root, filtered, config, cache)


def _cold_start(
    root: Path,
    filtered_paths: list[str],
    config: ProjectConfig,
) -> list[FileChange]:
    changes = []
    for rel in filtered_paths:
        abs_path = root / rel
        if not abs_path.exists():
            continue
        if _is_too_large(abs_path, config):
            logger.warning("Skipping large file: %s", rel)
            continue
        try:
            new_hash = _hash_file(abs_path)
        except OSError as exc:
            logger.warning("Cannot read %s: %s", rel, exc)
            continue
        changes.append(FileChange(path=rel, status="new", new_hash=new_hash))
    return changes


def _incremental(
    root: Path,
    filtered_paths: list[str],
    config: ProjectConfig,
    cache: CacheData,
) -> list[FileChange]:
    changes: list[FileChange] = []
    current_set = set(filtered_paths)
    cached_set = set(cache.files.keys())

    # Modified or deleted
    for rel, cached_file in cache.files.items():
        abs_path = root / rel
        if not abs_path.exists():
            changes.append(FileChange(
                path=rel,
                status="deleted",
                old_hash=cached_file.hash,
            ))
            continue
        if _is_too_large(abs_path, config):
            logger.warning("Skipping large file: %s", rel)
            continue
        try:
            new_hash = _hash_file(abs_path)
        except OSError as exc:
            logger.warning("Cannot read %s: %s", rel, exc)
            continue
        if new_hash != cached_file.hash:
            changes.append(FileChange(
                path=rel,
                status="modified",
                old_hash=cached_file.hash,
                new_hash=new_hash,
            ))

    # New files not in cache
    for rel in current_set - cached_set:
        abs_path = root / rel
        if not abs_path.exists():
            continue
        if _is_too_large(abs_path, config):
            logger.warning("Skipping large file: %s", rel)
            continue
        try:
            new_hash = _hash_file(abs_path)
        except OSError as exc:
            logger.warning("Cannot read %s: %s", rel, exc)
            continue
        changes.append(FileChange(path=rel, status="new", new_hash=new_hash))

    return changes
