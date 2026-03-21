"""ConfigLoader: reads .agents-config.json or returns defaults."""

import json
import logging
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

CONFIG_FILENAME = ".agents-config.json"

DEFAULT_CONFIG: dict[str, Any] = {
    "exclude": [
        "**/node_modules/**",
        "**/bin/**",
        "**/obj/**",
        "**/.git/**",
        "**/dist/**",
        "**/build/**",
        "**/__pycache__/**",
        "**/*.min.js",
        "**/*.min.css",
        "**/vendor/**",
        "**/packages/**",
        "**/.venv/**",
        "**/venv/**",
    ],
    "include": [],
    "languages": "auto",
    "impact_threshold": "medium",
    "agents_md_path": "./AGENTS.md",
    "base_ref": None,
    "max_file_size_bytes": 1_048_576,  # 1MB
}

# Extension → tree-sitter language key
EXTENSION_TO_LANGUAGE: dict[str, str] = {
    ".py": "python",
    ".cs": "c_sharp",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".js": "javascript",
    ".jsx": "javascript",
    ".go": "go",
    ".java": "java",
    ".rs": "rust",
    ".rb": "ruby",
}


class ProjectConfig:
    """Resolved configuration for a project scan."""

    def __init__(self, raw: dict[str, Any]) -> None:
        self.exclude: list[str] = raw.get("exclude", DEFAULT_CONFIG["exclude"])
        self.include: list[str] = raw.get("include", DEFAULT_CONFIG["include"])
        self.languages: str | list[str] = raw.get("languages", DEFAULT_CONFIG["languages"])
        self.impact_threshold: str = raw.get("impact_threshold", DEFAULT_CONFIG["impact_threshold"])
        self.agents_md_path: str = raw.get("agents_md_path", DEFAULT_CONFIG["agents_md_path"])
        self.base_ref: Optional[str] = raw.get("base_ref", DEFAULT_CONFIG["base_ref"])
        self.max_file_size_bytes: int = raw.get(
            "max_file_size_bytes", DEFAULT_CONFIG["max_file_size_bytes"]
        )

    def language_for_extension(self, ext: str) -> Optional[str]:
        """Return the tree-sitter language key for a file extension, or None if unsupported."""
        if self.languages == "auto":
            return EXTENSION_TO_LANGUAGE.get(ext.lower())
        # If explicit list, only allow those languages
        lang = EXTENSION_TO_LANGUAGE.get(ext.lower())
        if lang and lang in self.languages:
            return lang
        return None

    def is_extension_supported(self, ext: str) -> bool:
        return self.language_for_extension(ext) is not None


def load_config(project_path: str | Path) -> ProjectConfig:
    """Load .agents-config.json from project_path, falling back to defaults."""
    config_file = Path(project_path) / CONFIG_FILENAME
    if config_file.exists():
        try:
            raw = json.loads(config_file.read_text(encoding="utf-8"))
            # Merge with defaults so partial configs work
            merged = {**DEFAULT_CONFIG, **raw}
            logger.debug("Loaded config from %s", config_file)
            return ProjectConfig(merged)
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Could not read %s (%s), using defaults", config_file, exc)

    return ProjectConfig(DEFAULT_CONFIG)
