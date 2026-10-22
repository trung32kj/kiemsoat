"""Deduplicate active-window changes."""
from __future__ import annotations


class ChangeTracker:
    """Reports True only when (app, title) differs from the last accepted pair."""

    def __init__(self) -> None:
        self._last: tuple[str, str] | None = None

    def changed(self, app: str, title: str) -> bool:
        app = (app or "").strip()
        title = (title or "").strip()
        if not app:
            return False
        key = (app.lower(), title.lower())
        if key == self._last:
            return False
        self._last = key
        return True
