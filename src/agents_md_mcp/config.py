"""ConfigLoader: reads .agents-config.json or returns defaults."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

CONFIG_FILENAME = ".agents-config.json"


# ── Size profiles ────────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class SizeProfile:
    """Tuning knobs derived from project_size."""

    max_methods_per_symbol: int
    max_symbols_per_file: int
    dir_aggregation_threshold: int
    max_files_per_layer: int
    aggregation_sample_size: int
    max_route_controllers: int
    max_routes_per_controller: int
    max_go_handlers: int
    max_dir_depth: int
    impact_filter: str  # "medium" | "high" — derived, not user-facing


SIZE_PROFILES: dict[str, SizeProfile] = {
    "small": SizeProfile(
        max_methods_per_symbol=30,
        max_symbols_per_file=40,
        dir_aggregation_threshold=20,
        max_files_per_layer=15,
        aggregation_sample_size=5,
        max_route_controllers=30,
        max_routes_per_controller=15,
        max_go_handlers=15,
        max_dir_depth=4,
        impact_filter="medium",
    ),
    "medium": SizeProfile(
        max_methods_per_symbol=12,
        max_symbols_per_file=20,
        dir_aggregation_threshold=10,
        max_files_per_layer=8,
        aggregation_sample_size=4,
        max_route_controllers=15,
        max_routes_per_controller=8,
        max_go_handlers=8,
        max_dir_depth=3,
        impact_filter="medium",
    ),
    "large": SizeProfile(
        max_methods_per_symbol=8,
        max_symbols_per_file=10,
        dir_aggregation_threshold=5,
        max_files_per_layer=5,
        aggregation_sample_size=3,
        max_route_controllers=10,
        max_routes_per_controller=5,
        max_go_handlers=5,
        max_dir_depth=2,
        impact_filter="high",
    ),
}

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
        "**/*.bundle.js",
        "**/vendor/**",
        "**/packages/**",
        "**/.venv/**",
        "**/venv/**",
        # Frontend vendor directories (AngularJS bower, ASP.NET wwwroot, etc.)
        "**/bower_components/**",
        "**/app/lib/**",
        "**/wwwroot/lib/**",
        "**/wwwroot/libs/**",
        "**/static/vendor/**",
        "**/public/vendor/**",
        "**/assets/vendor/**",
        # Python deps installed inside the repo (non-standard venv layouts)
        "**/site-packages/**",
    ],
    "include": [],
    "languages": "auto",
    "project_size": "medium",
    "agents_md_path": "./AGENTS.md",
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
}


class ProjectConfig:
    """Resolved configuration for a project scan."""

    def __init__(self, raw: dict[str, Any]) -> None:
        self.exclude: list[str] = raw.get("exclude", DEFAULT_CONFIG["exclude"])
        self.include: list[str] = raw.get("include", DEFAULT_CONFIG["include"])
        self.languages: str | list[str] = raw.get("languages", DEFAULT_CONFIG["languages"])
        self.project_size: str = raw.get("project_size", DEFAULT_CONFIG["project_size"])
        self.agents_md_path: str = raw.get("agents_md_path", DEFAULT_CONFIG["agents_md_path"])
        self.max_file_size_bytes: int = raw.get(
            "max_file_size_bytes", DEFAULT_CONFIG["max_file_size_bytes"]
        )
        self.profile: SizeProfile = SIZE_PROFILES.get(
            self.project_size, SIZE_PROFILES["medium"]
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
