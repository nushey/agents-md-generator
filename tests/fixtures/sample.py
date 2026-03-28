"""Sample Python file for AST analysis tests."""

import os
from typing import Optional, Protocol
from abc import ABC, abstractmethod


class IRepository(Protocol):
    """Repository protocol."""

    def find_all(self) -> list:
        ...

    def find_by_id(self, id: int) -> Optional[dict]:
        ...


class UserService(IRepository, ABC):
    """Manages user operations."""

    def __init__(self, db_url: str) -> None:
        self.db_url = db_url

    def get_user(self, user_id: int) -> Optional[dict]:
        """Fetch a user by ID."""
        return None

    def find_all(self) -> list:
        return []

    def find_by_id(self, id: int) -> Optional[dict]:
        return None

    def _validate(self, data: dict) -> bool:
        return True


class SimpleModel:
    """A model with no base classes."""
    name: str = ""


def create_order(user_id: int, items: list) -> dict:
    """Create a new order."""
    return {}


def _internal_helper() -> None:
    pass
