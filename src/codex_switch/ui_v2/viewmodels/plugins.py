"""插件中心视图模型。

只负责把注册表状态渲染成行、并把用户操作转成对宿主的调用；
真正的扫描/加载/卸载在 ``codex_switch.plugins`` 里，视图模型不碰文件系统。
"""

from __future__ import annotations

from typing import Any

from ..qt_compat import Property, Signal, Slot
from .base import SnapshotViewModel


class PluginsViewModel(SnapshotViewModel):
    """插件中心: installed plugins, permissions, enable/disable."""

    selectedIdChanged = Signal()
    detailChanged = Signal()
    # 必须在本类作用域内声明 notify 用的信号，并用**裸名字**引用。
    #
    # Qt 的元对象系统无法解析 `notify=SnapshotViewModel.itemsChanged` 这种
    # 限定名：读取该属性时不会报错，而是直接死循环卡住整个界面。
    # base.py 里的 `notify=itemsChanged` 能工作，正是因为那个名字定义在
    # 它自己的类作用域内。这里复制同样的写法。
    issuesChanged = Signal()

    def __init__(self, controller, parent=None) -> None:
        self._controller = controller
        self._selected_id = ""
        self._detail: dict[str, Any] = {}
        # 缓存问题行：见 _rebuild_issues。
        self._issues: list[dict[str, Any]] = []
        super().__init__(self._build_items, parent)

    # -- properties ------------------------------------------------------
    @Property(str, notify=detailChanged)
    def selectedId(self) -> str:
        return self._selected_id

    @Property("QVariantMap", notify=detailChanged)
    def selectedDetail(self) -> dict[str, Any]:
        return dict(self._detail)

    @Property(str, notify=detailChanged)
    def pluginRoot(self) -> str:
        return str(self._controller.plugin_root())

    @Property("QVariant", notify=detailChanged)
    def selectedPluginInstance(self):
        """选中插件的实例，注入给插件自己的页面。

        返回 None 是正常的：插件未加载、未选中等情况下页面会显示占位内容。
        """
        if not self._selected_id:
            return None
        return self._controller.pluginInstance(self._selected_id)

    @Property(int, notify=issuesChanged)
    def issueCount(self) -> int:
        return len(self._issues)

    @Property("QVariantList", notify=issuesChanged)
    def issues(self) -> list[dict[str, Any]]:
        return list(self._issues)

    # -- data ------------------------------------------------------------
    def _build_items(self) -> list[dict[str, Any]]:
        return self._controller.plugin_rows()

    def _rebuild_issues(self) -> None:
        """刷新问题列表，且只在内容真的变化时才发信号。

        无条件的 emit 会让 Repeater 反复重建；这里与基类 set_items 同思路。
        """
        rows = [dict(item) for item in self._controller.plugin_issue_rows()]
        if rows == self._issues:
            return
        self._issues = rows
        self.issuesChanged.emit()

    @Slot()
    def refresh(self) -> None:
        # 先取问题列表：_rebuild_issues 可能 emit itemsChanged，
        # 放在 super().refresh() 之前可以合并成一次界面刷新。
        self._rebuild_issues()
        super().refresh()
        self._build_detail()

    def rebuild(self) -> None:
        self._rebuild_issues()
        super().rebuild()
        self._build_detail()

    def _build_detail(self) -> None:
        detail = self._controller.plugin_detail(self._selected_id)
        if detail != self._detail:
            self._detail = detail
            self.detailChanged.emit()

    # -- actions ---------------------------------------------------------
    @Slot(str)
    def select(self, plugin_id: str) -> None:
        value = str(plugin_id or "")
        if value == self._selected_id:
            return
        self._selected_id = value
        self.selectedIdChanged.emit()
        self._build_detail()

    @Slot()
    def rescan(self) -> None:
        """重新扫描插件目录。用户往目录里放了新插件后点这个。"""
        self._controller.rescanPlugins()

    @Slot(str, bool)
    def setEnabled(self, plugin_id: str, enabled: bool) -> None:
        self._controller.setPluginEnabled(str(plugin_id), bool(enabled))

    @Slot(str)
    def openFolder(self) -> None:
        """打开插件目录，方便用户手动放入插件。"""
        self._controller.openPluginFolder()

    @Slot(str)
    def runAction(self, plugin_id: str, action_key: str) -> None:
        self._controller.runPluginAction(str(plugin_id), str(action_key))


__all__ = ["PluginsViewModel"]
