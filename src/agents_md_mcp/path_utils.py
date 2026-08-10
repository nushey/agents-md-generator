"""Path utilities: cross-platform normalization to forward slashes."""

from pathlib import Path


def normalize_path(path: str) -> str:
    """Normalize path separators to forward slashes regardless of OS."""
    return path.replace("\\", "/")


def rel_posix(path: Path, root: Path) -> str:
    """Return the relative path from root as a forward-slash string."""
    return path.relative_to(root).as_posix()
