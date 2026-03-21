"""Base interface for language-specific AST analyzers."""

from abc import ABC, abstractmethod
from pathlib import Path

from ..models import FileAnalysis


class LanguageAnalyzer(ABC):
    """Extract semantic information from a source file."""

    @property
    @abstractmethod
    def language_key(self) -> str:
        """The tree-sitter language identifier (e.g. 'python', 'c_sharp')."""

    @abstractmethod
    def analyze(self, path: Path, source: bytes) -> FileAnalysis:
        """
        Parse source bytes and return a FileAnalysis.

        Args:
            path: Relative path of the file (for FileAnalysis.path).
            source: Raw file bytes.

        Returns:
            FileAnalysis with symbols, imports, and exports populated.
        """
