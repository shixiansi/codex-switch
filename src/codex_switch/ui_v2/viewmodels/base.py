"""Base classes for QML-facing view models.

View models never expose business objects and never mutate them directly: they
read a snapshot from the controller and rebuild display data on the main thread.
"""

from __future__ import annotations

from typing import Any, Callable

from ..qt_compat import Property, QObject, Signal, Slot


class BaseViewModel(QObject):
    """Busy flag, error channel and small helpers shared by every page model."""

    itemsChanged = Signal()
    busyChanged = Signal()
    errorRaised = Signal(str)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._items: list[dict[str, Any]] = []
        self._busy = False

    @Property("QVariantList", notify=itemsChanged)
    def items(self) -> list[dict[str, Any]]:
        return list(self._items)

    @Property(bool, notify=busyChanged)
    def busy(self) -> bool:
        return self._busy

    @Property(int, notify=itemsChanged)
    def count(self) -> int:
        return len(self._items)

    @Property(bool, notify=itemsChanged)
    def isEmpty(self) -> bool:
        return not self._items

    def set_items(self, items: Any) -> None:
        """Replace the row list, emitting only when the data actually changed.

        Emitting unconditionally forces the QML ListView to drop and rebuild
        every delegate, which resets the scroll position to the top. Skipping a
        no-op update avoids that rebuild when nothing the list shows has moved.
        """
        rows = [dict(item) for item in (items or [])]
        if rows == self._items:
            return
        self._items = rows
        self.itemsChanged.emit()

    def set_busy(self, value: bool) -> None:
        value = bool(value)
        if value != self._busy:
            self._busy = value
            self.busyChanged.emit()

    def report_error(self, message: object) -> None:
        self.errorRaised.emit(str(message) or "操作失败。")

    @Slot()
    def refresh(self) -> None:
        """Re-read the controller snapshot; subclasses override."""

    def dispose(self) -> None:
        """Release signal connections before the object is destroyed."""


class SnapshotViewModel(BaseViewModel):
    """A view model fed by a zero-argument producer returning display rows."""

    def __init__(self, producer: Callable[[], Any], parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._producer = producer

    @Slot()
    def refresh(self) -> None:
        try:
            self.set_items(self._producer())
        except Exception as exc:  # noqa: BLE001 - surface a safe UI message
            self.report_error(exc)

    def rebuild(self) -> None:
        """Rebuild display rows, surfacing a producer failure as an error."""
        try:
            self.set_items(self._producer())
        except Exception as exc:  # noqa: BLE001 - surfaced once, deduplicated upstream
            self.report_error(exc)


__all__ = ["BaseViewModel", "SnapshotViewModel"]
