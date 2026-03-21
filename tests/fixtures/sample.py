"""Sample Python file for AST analysis tests."""

import os
from typing import Optional


class UserService:
    """Manages user operations."""

    def __init__(self, db_url: str) -> None:
        self.db_url = db_url

    def get_user(self, user_id: int) -> Optional[dict]:
        """Fetch a user by ID."""
        return None

    def _validate(self, data: dict) -> bool:
        return True


def create_order(user_id: int, items: list) -> dict:
    """Create a new order."""
    return {}


def _internal_helper() -> None:
    pass
