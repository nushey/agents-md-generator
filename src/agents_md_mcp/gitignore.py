"""Gitignore support: load and apply .gitignore patterns via pathspec."""

import logging
from pathlib import Path

from .path_utils import normalize_path

import pathspec

logger = logging.getLogger(__name__)

GITIGNORE_FILE = ".gitignore"


def load_gitignore_spec(project_path: str | Path) -> pathspec.PathSpec | None:
    """
    Parse all .gitignore files from project root and nested directories.

    Returns a PathSpec that matches any gitignored path, or None if no
    .gitignore files are found.
    """
    root = Path(project_path)
    all_patterns: list[str] = []

    # Walk all .gitignore files in the project
    for gitignore in root.rglob(GITIGNORE_FILE):
        # Skip .gitignore files inside .git/ or other hidden dirs
        try:
            gitignore.relative_to(root)
        except ValueError:
            continue
        rel_dir = normalize_path(str(gitignore.parent.relative_to(root)))

        try:
            lines = gitignore.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError as exc:
            logger.debug("Could not read %s: %s", gitignore, exc)
            continue

        for line in lines:
            stripped = line.strip()
            # Skip comments and empty lines
            if not stripped or stripped.startswith("#"):
                continue
            # Prefix patterns from subdirectory gitignores
            if rel_dir != ".":
                pattern = f"{rel_dir}/{stripped}"
            else:
                pattern = stripped
            all_patterns.append(pattern)

    if not all_patterns:
        return None

    return pathspec.PathSpec.from_lines("gitignore", all_patterns)


def is_gitignored(path: str, spec: pathspec.PathSpec | None) -> bool:
    """Return True if the path is matched by the gitignore spec."""
    if spec is None:
        return False
    return spec.match_file(path)
