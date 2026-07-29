"""Path utilities: cross-platform normalization to forward slashes."""

import fnmatch
from pathlib import Path


def normalize_path(path: str) -> str:
    """Normalize path separators to forward slashes regardless of OS."""
    return path.replace("\\", "/")


def rel_posix(path: Path, root: Path) -> str:
    """Return the relative path from root as a forward-slash string."""
    return path.relative_to(root).as_posix()


def prune_dirnames(
    dirnames: list[str],
    rel_dir: str,
    tokens: set[str],
    globs: list[str] = (),
) -> None:
    """Drop excluded directories from an os.walk dirnames list, in place.

    A directory is pruned only when skipping it is provably equivalent to
    filtering each of its files individually:
    - its name is one of *tokens* (derived from plain ``**/<dir>/**`` excludes,
      which match exactly the paths containing that component), or
    - a glob of the form ``<prefix>/**`` matches the directory's relative path
      (``p + "/**"`` matches a file iff the file lies under a dir matching
      ``p``; fnmatch ``*`` crosses ``/``).

    Gitignore-matched directories are deliberately NOT pruned here: pathspec
    negation patterns can re-include files under an ignored directory, so
    gitignore filtering must stay per-file.
    """
    dir_globs = [g[:-3] for g in globs if g.endswith("/**")]
    kept = []
    for name in dirnames:
        if name in tokens:
            continue
        child_rel = f"{rel_dir}/{name}" if rel_dir != "." else name
        if any(fnmatch.fnmatch(child_rel, g) for g in dir_globs):
            continue
        kept.append(name)
    dirnames[:] = kept
