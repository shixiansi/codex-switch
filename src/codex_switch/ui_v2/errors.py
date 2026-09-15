"""Shared error types for the ui_v2 layer.

Defined in its own module so form validation and business orchestration can
share one user-facing error hierarchy without an import cycle.
"""

from __future__ import annotations


class WorkspaceError(RuntimeError):
    """A user-facing operation failure carrying a localised message."""


class FormError(WorkspaceError, ValueError):
    """A rejected form payload.

    Inherits ``WorkspaceError`` so the controller's generic error handling
    covers it, and ``ValueError`` for callers that validate values directly.
    """


__all__ = ["FormError", "WorkspaceError"]
