"""Tests for config.py — ConfigLoader."""

import json
from pathlib import Path

import pytest

from agents_md_mcp.config import (
    DEFAULT_CONFIG,
    EXTENSION_TO_LANGUAGE,
    load_config,
)


def test_load_config_defaults(tmp_path: Path) -> None:
    """No config file → defaults are returned."""
    cfg = load_config(tmp_path)
    assert cfg.impact_threshold == "medium"
    assert cfg.languages == "auto"
    assert len(cfg.exclude) > 0


def test_load_config_from_file(tmp_path: Path) -> None:
    """Partial config merges with defaults."""
    (tmp_path / ".agents-config.json").write_text(
        json.dumps({"impact_threshold": "high"}),
        encoding="utf-8",
    )
    cfg = load_config(tmp_path)
    assert cfg.impact_threshold == "high"
    # Defaults preserved
    assert cfg.languages == "auto"
    assert cfg.max_file_size_bytes == DEFAULT_CONFIG["max_file_size_bytes"]


def test_load_config_corrupt_file(tmp_path: Path) -> None:
    """Corrupt JSON falls back to defaults without raising."""
    (tmp_path / ".agents-config.json").write_text("{ not valid json", encoding="utf-8")
    cfg = load_config(tmp_path)
    assert cfg.impact_threshold == "medium"


def test_language_for_extension_auto() -> None:
    cfg = load_config("/tmp")
    assert cfg.language_for_extension(".py") == "python"
    assert cfg.language_for_extension(".ts") == "typescript"
    assert cfg.language_for_extension(".cs") == "c_sharp"
    assert cfg.language_for_extension(".xyz") is None


def test_is_extension_supported() -> None:
    cfg = load_config("/tmp")
    assert cfg.is_extension_supported(".go")
    assert cfg.is_extension_supported(".js")
    assert not cfg.is_extension_supported(".html")


def test_all_mapped_extensions_supported() -> None:
    cfg = load_config("/tmp")
    for ext in EXTENSION_TO_LANGUAGE:
        assert cfg.is_extension_supported(ext), f"{ext} should be supported"
