"""系统通知与提示音（唯一的 Qt 系统集成点）。

自动应答被审查拦下或降级时，用户可能在别的窗口里——只弹应用内提示条是不够的。
这里提供两条独立的触达通道：

* **系统通知**：托盘气泡（Windows 通知中心 / macOS 通知中心 / Linux 各 DE）。
* **提示音**：让声音把注意力拉回来。

两者都**只做尽力而为**：任何一步失败都只记日志，绝不抛给调用方。原因很直接——
这条路径的职责是"通知用户有个按键被拦下了"，它自己失败不该连带影响终端会话。

线程约束：本模块的对象持有 Qt 对象，**必须在 GUI 线程调用**。调用方
（TerminalViewModel）已经通过 ``QMetaObject.invokeMethod(QueuedConnection)``
把后台事件搬回 GUI 线程，这里不再自建线程机制。

打包约束：本机装的是 ``PySide6-Essentials``，**没有 QtMultimedia**，
因此提示音走标准库 ``winsound``（Windows）而不是 QSoundEffect。
"""

from __future__ import annotations

from pathlib import Path

from .logging_setup import get_logger

log = get_logger()

# 托盘图标用的资源。与 QML 的 AppIcon 取同一份 SVG，避免多维护一套素材。
_ICON_DIR = Path(__file__).resolve().parent.parent / "assets" / "icons"
_ICON_NAME = "warning.svg"

# 托盘图标的展示时长：最后一个通知解决后延迟这么久再隐藏。
# 立刻隐藏会把刚弹出的气泡一起带走。
_HIDE_DELAY_MS = 5000


def icon_path() -> Path:
    """托盘图标路径（供测试断言与排查"图标没显示"）。"""
    return _ICON_DIR / _ICON_NAME


class SystemNotifier:
    """托盘气泡通知。

    ``QSystemTrayIcon`` 必须由 Python 侧持有强引用，否则会被 GC 回收，
    表现为"通知偶尔不出现"这种极难排查的问题。因此图标对象挂在本实例上。
    """

    def __init__(self) -> None:
        self._tray = None
        self._icon = None
        self._hide_timer = None
        self._available: bool | None = None
        self._unavailable_reason = ""
        self._click_callback = None

    # -- 可用性 --------------------------------------------------------
    @staticmethod
    def _has_application() -> bool:
        """是否已有一个 **QApplication**（而不只是 QGuiApplication）。

        **必须先查这一步**，因为不满足时调用 ``QSystemTrayIcon.showMessage``
        在 Windows 上会**直接把进程打崩**（访问违例 0xC0000005），而不是抛
        Python 异常——try/except 完全兜不住。实测：

        * ``QGuiApplication`` + ``showMessage`` → 崩溃；
        * ``QApplication``    + ``showMessage`` → 正常。

        ``QSystemTrayIcon`` 属于 QtWidgets，它发气泡依赖 widgets 那套窗口后端，
        因此这里用 ``isinstance`` 而不是 ``instance() is not None`` 来判断：
        只有 ``QGuiApplication`` 存在时，``QApplication.instance()`` 返回的**不是
        None**，而是那个 QGuiApplication 实例本身。
        """
        try:
            from PySide6.QtWidgets import QApplication

            return isinstance(QApplication.instance(), QApplication)
        except Exception:  # noqa: BLE001 - 导入失败等同于没有可用的应用
            return False

    def is_available(self) -> bool:
        """托盘是否可用；不可用时返回 False 并记录原因。

        远程桌面、精简系统与 offscreen 平台都可能没有托盘。此时调用方应退回
        应用内 toast，而不是让用户什么都收不到。
        """
        if self._available is not None:
            return self._available
        if not self._has_application():
            self._available = False
            self._unavailable_reason = "尚无图形应用实例"
            return self._available
        try:
            from PySide6.QtWidgets import QSystemTrayIcon
        except ImportError:
            self._available = False
            self._unavailable_reason = "未安装 PySide6.QtWidgets"
            return self._available
        try:
            supported = bool(QSystemTrayIcon.isSystemTrayAvailable())
        except Exception as exc:  # noqa: BLE001 - 探测失败按不可用处理
            self._available = False
            self._unavailable_reason = f"托盘探测失败：{exc}"
            return self._available
        self._available = supported
        if not supported:
            self._unavailable_reason = "当前桌面环境没有系统托盘"
        return self._available

    @property
    def unavailable_reason(self) -> str:
        return self._unavailable_reason

    def set_click_callback(self, callback) -> None:
        """点击通知时的回调（通常用于切到终端页并聚焦会话）。"""
        self._click_callback = callback

    # -- 通知 ----------------------------------------------------------
    def notify(self, title: str, body: str, *, urgent: bool = False) -> bool:
        """弹一条系统通知；返回是否真的弹出了。"""
        if not self.is_available():
            log.debug("系统通知不可用，跳过：%s", self._unavailable_reason)
            return False
        tray = self._ensure_tray()
        if tray is None:
            return False
        try:
            from PySide6.QtWidgets import QSystemTrayIcon

            icon = QSystemTrayIcon.MessageIcon.Warning if urgent else QSystemTrayIcon.MessageIcon.Information
            # 先 show()：图标未显示时部分平台会丢弃气泡。
            if not tray.isVisible():
                tray.show()
            tray.showMessage(str(title), str(body), icon, 10000)
            self._schedule_hide()
            log.info("已发出系统通知：%s", title)
            return True
        except Exception:  # noqa: BLE001 - 通知失败不该影响主流程
            log.exception("系统通知发送失败")
            return False

    def _ensure_tray(self):
        """惰性创建托盘图标（首次需要时才建，避免无谓占用托盘）。"""
        if self._tray is not None:
            return self._tray
        if not self._has_application():
            return None
        try:
            from PySide6.QtGui import QIcon
            from PySide6.QtWidgets import QSystemTrayIcon

            self._tray = QSystemTrayIcon()
            path = icon_path()
            if path.exists():
                self._icon = QIcon(str(path))
                if not self._icon.isNull():
                    self._tray.setIcon(self._icon)
            self._tray.setToolTip("Codex Switch · AI 终端")
            if self._click_callback is not None:
                self._tray.messageClicked.connect(self._on_clicked)
            return self._tray
        except Exception:  # noqa: BLE001
            log.exception("创建托盘图标失败")
            self._tray = None
            self._available = False
            self._unavailable_reason = "托盘图标创建失败"
            return None

    def _on_clicked(self) -> None:
        callback = self._click_callback
        if callback is None:
            return
        try:
            callback()
        except Exception:  # noqa: BLE001
            log.exception("通知点击回调失败")

    def _schedule_hide(self) -> None:
        """安排延迟隐藏托盘图标。"""
        try:
            from PySide6.QtCore import QTimer

            if self._hide_timer is not None:
                self._hide_timer.stop()
            self._hide_timer = QTimer()
            self._hide_timer.setSingleShot(True)
            self._hide_timer.timeout.connect(self.hide)
            self._hide_timer.start(_HIDE_DELAY_MS)
        except Exception:  # noqa: BLE001 - 隐藏失败只是留个图标，不影响功能
            log.debug("安排托盘隐藏失败")

    def hide(self) -> None:
        """隐藏托盘图标（没有待处理通知时调用）。"""
        if self._tray is None:
            return
        try:
            self._tray.hide()
        except Exception:  # noqa: BLE001
            pass


__all__ = ["SystemNotifier", "icon_path"]
