"""Shared test helpers."""

import subprocess
from pathlib import Path


def git_init(root: Path) -> Path:
    """Make *root* a git repository — required since the pipeline is git-first."""
    subprocess.run(["git", "init", "-q"], cwd=str(root), capture_output=True, check=True)
    return root
