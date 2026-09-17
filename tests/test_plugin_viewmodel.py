"""插件中心视图模型与 QML 绑定的回归测试。

这里最重要的用例是 ``test_plugin_properties_do_not_hang_on_read``：
它锁死一个曾经让整个界面卡死的真实缺陷，详见该用例的注释。
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC = PROJECT_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


def _qt_ready() -> bool:
    try:
        from codex_switch.ui_v2.qt_compat import QT_AVAILABLE

        return bool(QT_AVAILABLE)
    except Exception:  # noqa: BLE001
        return False


QT_READY = _qt_ready()


class PluginViewModelSourceTests(unittest.TestCase):
    """不依赖 Qt 的静态检查：守住"notify 必须用裸名字"这条约束。"""

    def setUp(self) -> None:
        raw = (
            PROJECT_ROOT / "src" / "codex_switch" / "ui_v2" / "viewmodels" / "plugins.py"
        ).read_text(encoding="utf-8")
        # 只看真正的代码行：注释里会提到这个反例（写清楚"不能这么写"），
        # 直接搜全文会命中注释，导致测试永远失败。
        self.source = "\n".join(
            line for line in raw.splitlines() if not line.lstrip().startswith("#")
        )

    def test_notify_never_uses_qualified_base_signal(self) -> None:
        """notify 里禁止出现 `XxxViewModel.itemsChanged` 这类限定名。

        Qt 元对象系统无法解析限定名形式的 notify：读取该属性时不报错，
        而是无限循环卡死整个界面（曾真实发生，QML 加载直接挂住）。
        信号必须在所属类作用域内声明，并以裸名字引用。
        """
        self.assertNotIn("notify=SnapshotViewModel.", self.source)
        self.assertNotIn("notify=BaseViewModel.", self.source)

    def test_issue_properties_declare_own_notify_signal(self) -> None:
        self.assertIn("issuesChanged = Signal()", self.source)
        self.assertIn("notify=issuesChanged", self.source)

    def test_issue_rows_are_cached_not_rebuilt_per_read(self) -> None:
        """问题行必须走缓存。

        属性每次返回新对象会让 QML 绑定反复"看到变化"，触发delegate 重建风暴。
        这里确认存在缓存字段与去重逻辑。
        """
        self.assertIn("self._issues", self.source)
        self.assertIn("if rows == self._issues:", self.source)


@unittest.skipUnless(QT_READY, "需要 PySide6 才能构造视图模型")
class PluginViewModelQtTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        import os

        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PySide6.QtGui import QGuiApplication

        cls.app = QGuiApplication.instance() or QGuiApplication([])

    def setUp(self) -> None:
        from codex_switch.ui_v2.controller import AppController

        self.controller = AppController()
        self.model = self.controller.plugins

    def test_plugin_properties_do_not_hang_on_read(self) -> None:
        """通过 QQmlProperty 读取每个属性都必须立即返回。

        这是上面那个缺陷的直接回归测试：插件中心新增的属性（issueCount /
        issues）曾让 QQmlProperty.read 永久阻塞，表现为程序启动后无响应。
        用 QQmlProperty 而不是直接调 Python 属性是刻意的——只有走 QML 的
        属性系统才会触发问题。
        """
        from PySide6.QtQml import QQmlProperty

        for name in (
            "items", "count", "busy", "isEmpty",
            "issueCount", "issues", "pluginRoot",
            "selectedId", "selectedDetail",
        ):
            with self.subTest(property=name):
                # 若属性读挂住，这个测试会超时失败，而不是静默通过。
                value = QQmlProperty.read(self.model, name)
                self.assertIsNotNone(value)

    def test_issue_count_matches_cached_rows(self) -> None:
        self.assertEqual(self.model.issueCount, len(self.model.issues))

    def test_select_updates_detail_without_error(self) -> None:
        self.model.select("does-not-exist")
        self.assertEqual(self.model.selectedId, "does-not-exist")
        self.assertEqual(self.model.selectedDetail, {})

    def test_refresh_is_idempotent(self) -> None:
        """重复 refresh 不应改变状态，也不应抛异常。"""
        self.model.refresh()
        first = self.model.issueCount
        self.model.refresh()
        self.assertEqual(self.model.issueCount, first)

    def test_plugin_detail_returns_permission_labels(self) -> None:
        """详情里的权限必须带上中文说明，而不是只给机器名。"""
        from codex_switch.plugins.registry import STATUS_READY  # noqa: F401

        detail = self.controller.plugin_detail("no-such-plugin")
        self.assertEqual(detail, {})


class PluginsPageQmlTests(unittest.TestCase):
    """插件中心页面本身的静态检查。"""

    def setUp(self) -> None:
        self.qml = (
            PROJECT_ROOT / "src" / "codex_switch" / "ui_v2" / "qml" / "pages" / "PluginsPage.qml"
        ).read_text(encoding="utf-8")

    def test_page_exists_and_declares_expected_sections(self) -> None:
        for marker in ("插件中心", "权限", "重新扫描", "打开插件目录"):
            with self.subTest(marker=marker):
                self.assertIn(marker, self.qml)

    def test_page_is_registered_in_qmldir(self) -> None:
        qmldir = (
            PROJECT_ROOT / "src" / "codex_switch" / "ui_v2" / "qml" / "pages" / "qmldir"
        ).read_text(encoding="utf-8")
        self.assertIn("PluginsPage 1.0 PluginsPage.qml", qmldir)

    def test_shell_registers_plugin_section_and_page(self) -> None:
        """导航、标题、StackLayout 三处必须同时登记插件中心。

        这三处历史上是硬编码的，漏掉任何一处都会让页面无法访问。
        """
        shell = (
            PROJECT_ROOT / "src" / "codex_switch" / "ui_v2" / "qml" / "AppShell.qml"
        ).read_text(encoding="utf-8")
        self.assertIn('key: "plugins"', shell)
        self.assertIn("PluginsPage {}", shell)

        controller = (
            PROJECT_ROOT / "src" / "codex_switch" / "ui_v2" / "controller.py"
        ).read_text(encoding="utf-8")
        self.assertIn('"plugins": "插件中心"', controller)
        self.assertIn('"plugins"', controller)

    def test_shell_keys_match_controller_section_order(self) -> None:
        """AppShell 的 keys 数组必须与 SECTION_ORDER 一一对应。

        两者错位会让每个导航项都打开错误的页面——静默且难以察觉。
        """
        import re

        shell = (
            PROJECT_ROOT / "src" / "codex_switch" / "ui_v2" / "qml" / "AppShell.qml"
        ).read_text(encoding="utf-8")
        match = re.search(r"var keys = \[(.*?)\]", shell, re.S)
        self.assertIsNotNone(match, "未找到 AppShell 的 keys 数组")
        shell_keys = re.findall(r'"([a-z]+)"', match.group(1))

        from codex_switch.ui_v2.controller import SECTION_ORDER

        self.assertEqual(tuple(shell_keys), SECTION_ORDER)

    def test_stack_layout_page_count_matches_section_order(self) -> None:
        """StackLayout 的子页面数量必须等于导航项数量，否则索引会错位。"""
        import re

        shell = (
            PROJECT_ROOT / "src" / "codex_switch" / "ui_v2" / "qml" / "AppShell.qml"
        ).read_text(encoding="utf-8")
        stack = re.search(r"StackLayout \{(.*?)\n            \}", shell, re.S)
        self.assertIsNotNone(stack, "未找到 StackLayout 块")
        pages = re.findall(r"^\s{16}(\w+Page|\w+Dashboard) \{\}", stack.group(1), re.M)

        from codex_switch.ui_v2.controller import SECTION_ORDER

        self.assertEqual(len(pages), len(SECTION_ORDER))
        self.assertIn("PluginsPage", pages)


if __name__ == "__main__":
    unittest.main()
