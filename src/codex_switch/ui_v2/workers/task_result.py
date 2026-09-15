"""Uniform task state/result types shared by all background work."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class TaskState(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    CANCELLED = "cancelled"

    @property
    def is_terminal(self) -> bool:
        return self in {TaskState.SUCCESS, TaskState.FAILED, TaskState.CANCELLED}


@dataclass(frozen=True)
class TaskResult:
    """Outcome of one background operation, already safe to show in the UI."""

    state: TaskState
    value: Any = None
    error: str = ""
    detail: str = ""
    progress: float | None = None

    @property
    def ok(self) -> bool:
        return self.state is TaskState.SUCCESS


__all__ = ["TaskResult", "TaskState"]
