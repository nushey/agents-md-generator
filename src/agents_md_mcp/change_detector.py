"""ChangeDetector: detects new/modified/deleted files since last scan."""

import hashlib
import logging
import subprocess
from pathlib import Path

import fnmatch

from .cache import CacheData
from .config import ProjectConfig
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


def _fs_walk(project_path: Path) -> list[str]:
    """Fallback: walk filesystem when not a git repo."""
    files = []
    for p in project_path.rglob("*"):
        if p.is_file():
            files.append(str(p.relative_to(project_path)))
    return files


def _matches_any(path: str, patterns: list[str]) -> bool:
    for pattern in patterns:
        if fnmatch.fnmatch(path, pattern):
            return True
        # Also match against individual path components
        if fnmatch.fnmatch(Path(path).name, pattern.lstrip("*/")):
            pass
    return False


def _is_excluded(path: str, config: ProjectConfig) -> bool:
    """Return True if the path matches any exclude pattern."""
    for pattern in config.exclude:
        if fnmatch.fnmatch(path, pattern):
            return True
        # Handle patterns like **/node_modules/** by checking each segment
        parts = Path(pattern).parts
        path_parts = Path(path).parts
        for i in range(len(path_parts)):
            sub = str(Path(*path_parts[i:]))
            if fnmatch.fnmatch(sub, pattern.lstrip("*/")):
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
    """
    root = Path(project_path).resolve()

    raw_files = _git_ls_files(root)
    is_git_repo = raw_files is not None
    if raw_files is None:
        logger.warning("Not a git repo, falling back to filesystem walk")
        raw_files = _fs_walk(root)

    filtered = _filter_paths(raw_files, config)

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
