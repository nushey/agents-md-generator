"""Gitignore support: load and apply .gitignore patterns via pathspec."""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import TYPE_CHECKING

from .path_utils import prune_dirnames, rel_posix

import pathspec

if TYPE_CHECKING:
    from .config import ProjectConfig

logger = logging.getLogger(__name__)

GITIGNORE_FILE = ".gitignore"


def _find_gitignores(root: Path, config: ProjectConfig | None) -> list[Path]:
    """Locate .gitignore files, pruning only directories the active config excludes.

    Pruning must follow the ACTIVE exclude list, not the defaults: a user who
    re-enables a normally excluded directory (e.g. `exclude: []`) expects its
    nested .gitignore files to be honored again. When *config* is None, no
    pruning happens — identical discovery to the original full walk.
    """
    tokens = config._exclude_dir_tokens if config is not None else set()
    globs = config._exclude_globs if config is not None else []
    found: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames.sort()
        prune_dirnames(dirnames, rel_posix(Path(dirpath), root), tokens, globs)
        if GITIGNORE_FILE in filenames:
            found.append(Path(dirpath) / GITIGNORE_FILE)
    return found


def load_gitignore_spec(
    project_path: str | Path, config: ProjectConfig | None = None,
) -> pathspec.PathSpec | None:
    """
    Parse all .gitignore files from project root and nested directories.

    When *config* is given, discovery skips directories its exclude list prunes
    — their files never reach the per-file filters, so their .gitignore
    patterns are irrelevant (and third-party ignore rules inside dependency
    trees must not filter project files anyway).

    Returns a PathSpec that matches any gitignored path, or None if no
    .gitignore files are found.
    """
    root = Path(project_path)
    all_patterns: list[str] = []

    for gitignore in _find_gitignores(root, config):
        rel_dir = rel_posix(gitignore.parent, root)

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
