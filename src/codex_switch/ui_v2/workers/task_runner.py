"""Background task execution on Qt's global thread pool.

Every operation runs off the UI thread and reports back through queued Qt
signals, so view models only ever mutate state on the main thread.
"""

from __future__ import annotations

from typing import Any, Callable

from ..qt_compat import QObject, QRunnable, QThreadPool, Qt, Signal
from .task_result import TaskResult, TaskState


class TaskCancelled(Exception):
    """Raised inside a task body when the user cancelled it."""


class TaskContext:
    """Cooperative cancellation and progress handle handed to a task body."""

    def __init__(self, on_progress: Callable[[float | None, str], None], is_cancelled: Callable[[], bool]) -> None:
        self._on_progress = on_progress
        self._is_cancelled = is_cancelled

    @property
    def cancelled(self) -> bool:
        return self._is_cancelled()

    def raise_if_cancelled(self) -> None:
        if self.cancelled:
            raise TaskCancelled()

    def report(self, progress: float | None = None, detail: str = "") -> None:
        self._on_progress(progress, detail)


TaskBody = Callable[[TaskContext], Any]


class _TaskSignals(QObject):
    """Lives in the main thread so worker emissions are queued onto it."""

    started = Signal()
    progress = Signal(object, str)
    finished = Signal(object)


class _Runnable(QRunnable):
    def __init__(self, body: TaskBody, context: TaskContext, signals: _TaskSignals) -> None:
        super().__init__()
        self._body = body
        self._context = context
        self._signals = signals
        self.setAutoDelete(True)

    def run(self) -> None:
        self._signals.started.emit()
        try:
            value = self._body(self._context)
        except TaskCancelled:
            result = TaskResult(TaskState.CANCELLED, error="任务已取消。")
        except Exception as exc:  # noqa: BLE001 - converted to a user-facing message
            result = TaskResult(TaskState.FAILED, error=str(exc) or "后台任务执行失败。")
        else:
            result = TaskResult(TaskState.SUCCESS, value=value)
        self._signals.finished.emit(result)


class TaskRunner(QObject):
    """Submit work to the global thread pool and expose uniform task states.

    A task id may only be in flight once; a duplicate ``submit`` returns
    ``False`` instead of queueing a second copy of the same work.
    """

    taskStarted = Signal(str, str)
    taskProgress = Signal(str, object, str)
    taskFinished = Signal(str, object)
    activeCountChanged = Signal()

    def __init__(self, parent: QObject | None = None, pool: QThreadPool | None = None) -> None:
        super().__init__(parent)
        self._pool = pool or QThreadPool.globalInstance()
        self._active: set[str] = set()
        self._cancelled: set[str] = set()
        self._labels: dict[str, str] = {}
        self._keepalive: list[_TaskSignals] = []

    # -- queries ---------------------------------------------------------
    @property
    def active_tasks(self) -> frozenset[str]:
        return frozenset(self._active)

    @property
    def active_count(self) -> int:
        return len(self._active)

    def is_active(self, task_id: str) -> bool:
        return task_id in self._active

    def label_for(self, task_id: str) -> str:
        return self._labels.get(task_id, task_id)

    # -- commands --------------------------------------------------------
    def submit(self, task_id: str, body: TaskBody, *, label: str = "") -> bool:
        """Queue ``body`` unless the same task id is already running."""
        task_id = str(task_id or "").strip()
        if not task_id or task_id in self._active:
            return False

        queued = getattr(Qt, "QueuedConnection", 0)
        signals = _TaskSignals(self)
        self._keepalive.append(signals)
        signals.started.connect(lambda: self._on_started(task_id), queued)
        signals.progress.connect(
            lambda progress, detail: self.taskProgress.emit(task_id, progress, detail), queued
        )
        signals.finished.connect(lambda result: self._on_finished(task_id, result), queued)

        context = TaskContext(
            on_progress=lambda progress, detail: signals.progress.emit(progress, detail),
            is_cancelled=lambda: task_id in self._cancelled,
        )

        self._active.add(task_id)
        self._cancelled.discard(task_id)
        self._labels[task_id] = label or task_id
        self.activeCountChanged.emit()
        self._pool.start(_Runnable(body, context, signals))
        return True

    def cancel(self, task_id: str) -> bool:
        """Request cooperative cancellation of a running task."""
        task_id = str(task_id or "")
        if task_id not in self._active:
            return False
        self._cancelled.add(task_id)
        return True

    def cancel_all(self) -> None:
        for task_id in tuple(self._active):
            self.cancel(task_id)

    # -- signal handlers (main thread) -----------------------------------
    def _on_started(self, task_id: str) -> None:
        self.taskStarted.emit(task_id, self.label_for(task_id))

    def _on_finished(self, task_id: str, result: TaskResult) -> None:
        self._active.discard(task_id)
        self._cancelled.discard(task_id)
        self._labels.pop(task_id, None)
        self.taskFinished.emit(task_id, result)
        self.activeCountChanged.emit()


__all__ = ["TaskCancelled", "TaskContext", "TaskRunner", "TaskResult", "TaskState"]
