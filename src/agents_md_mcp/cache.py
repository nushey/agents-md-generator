"""Cache manager: reads/writes per-project cache in ~/.cache/agents-md-generator/."""

import hashlib
import json
import logging
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from .models import CACHE_VERSION, CacheData, CachedFile

logger = logging.getLogger(__name__)

CACHE_FILENAME = "cache.json"


def get_project_cache_dir(project_path: str | Path) -> Path:
    """Return ~/.cache/agents-md-generator/<project-hash>/, creating it if needed.

    The project hash is a SHA-256 of the absolute project path — unique per
    project, stable as long as the directory doesn't move.
    """
    abs_path = str(Path(project_path).resolve())
    project_hash = hashlib.sha256(abs_path.encode()).hexdigest()[:16]
    cache_dir = Path.home() / ".cache" / "agents-md-generator" / project_hash
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir


def load_cache(project_path: str | Path) -> CacheData | None:
    """Load cache from disk. Returns None if missing or corrupt."""
    cache_path = get_project_cache_dir(project_path) / CACHE_FILENAME
    if not cache_path.exists():
        return None
    try:
        raw = json.loads(cache_path.read_text(encoding="utf-8"))
        if raw.get("version") != CACHE_VERSION:
            logger.warning(
                "Cache at %s has version %s (expected %s), will do cold start",
                cache_path, raw.get("version"), CACHE_VERSION,
            )
            return None
        return CacheData.model_validate(raw)
    except Exception as exc:
        logger.warning("Cache at %s is corrupt (%s), will do cold start", cache_path, exc)
        return None


def save_cache(project_path: str | Path, data: CacheData) -> None:
    """Persist cache to disk."""
    cache_path = get_project_cache_dir(project_path) / CACHE_FILENAME
    try:
        # Compact JSON: at tens of thousands of entries, indentation multiplies
        # both file size and parse time for zero benefit (machine-only file).
        # exclude_defaults would drop `version` (it equals its default), so it
        # is re-added explicitly — load_cache rejects caches without it.
        payload = data.model_dump(mode="json", exclude_defaults=True)
        payload["version"] = data.version
        temporary_path = cache_path.with_suffix(".tmp")
        temporary_path.write_text(
            json.dumps(payload, separators=(",", ":"), ensure_ascii=False),
            encoding="utf-8",
        )
        temporary_path.replace(cache_path)
        logger.debug("Cache saved to %s", cache_path)
    except OSError as exc:
        logger.error("Could not write cache to %s: %s", cache_path, exc)


def is_cache_valid(cache: CacheData, project_path: str | Path) -> bool:
    """Return True if the base_commit stored in cache still exists in the repo."""
    if cache.base_commit is None:
        return True  # No commit tracking — cache is structurally valid
    try:
        result = subprocess.run(
            ["git", "cat-file", "-t", cache.base_commit],
            cwd=str(project_path),
            capture_output=True,
            text=True,
            timeout=10,
        )
        return result.returncode == 0 and result.stdout.strip() == "commit"
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False


def make_empty_cache(base_commit: str | None = None) -> CacheData:
    """Create a fresh empty cache."""
    return CacheData(
        last_run=datetime.now(timezone.utc).isoformat(),
        base_commit=base_commit,
        files={},
    )


def get_current_commit(project_path: str | Path) -> str | None:
    """Return HEAD commit SHA, or None if not a git repo."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(project_path),
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass
    return None
