"""Shared sender exception types."""

from __future__ import annotations


class PermanentSendError(Exception):
    """Raised when a message delivery failure is permanent and unrecoverable.

    Unlike transient failures (timeouts, 5xx), these errors will not resolve
    on retry — the event should be immediately marked dead.
    """

    def __init__(self, error_code: int | None, description: str) -> None:
        self.error_code = error_code
        self.description = description
        super().__init__(f"[{error_code}] {description}")
