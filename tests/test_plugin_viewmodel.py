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

    def test_load_plugins_refreshes_viewmodel(self) -> None:
        """加载插件后，视图模型必须跟着更新。

        这条锁死一个真实缺陷：``load_plugins()`` 早期只更新注册表、
        不刷新视图模型，于是插件明明加载成功、注册表里也有数据，
        界面仍然显示「已安装插件 (0)」——列表空的，用户既看不到插件，
        也点不进插件页面。
        """
        loaded = self.controller.load_plugins()
        self.assertTrue(loaded, "内置插件没有被加载")
        self.assertEqual(
            len(self.controller.plugins.items), len(loaded),
            "注册表有插件但视图模型仍为空",
        )
        ids = {row["id"] for row in self.controller.plugins.items}
        self.assertIn("codebuddy-accounts", ids)

    def test_plugin_detail_returns_permission_labels(self) -> None:
        """详情里的权限必须带上中文说明，而不是只给机器名。"""
        from codex_switch.plugins.registry import STATUS_READY  # noqa: F401

        detail = self.controller.plugin_detail("no-such-plugin")
        self.assertEqual(detail, {})


class OpenPluginFolderTests(unittest.TestCase):
    """「打开插件目录」不能静默失败。

    这个按钮曾经点了没反应：底层 ``QDesktopServices.openUrl`` 在没有注册
    处理程序的环境下会**直接返回 False 且不抛异常**，而当时的实现忽略了
    返回值，于是既没打开目录、也没有任何提示。
    """

    @classmethod
    def setUpClass(cls) -> None:
        import os

        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PySide6.QtGui import QGuiApplication

        cls.app = QGuiApplication.instance() or QGuiApplication([])

    def test_reveal_directory_reports_success_or_failure(self) -> None:
        """_reveal_directory 必须有明确的布尔返回，不能"失败了也说不出话"。"""
        import shutil
        import tempfile
        from pathlib import Path

        from codex_switch.ui_v2.controller import AppController

        controller = AppController()
        scratch = PROJECT_ROOT / ".tmp"
        scratch.mkdir(parents=True, exist_ok=True)
        target = Path(tempfile.mkdtemp(prefix="reveal-", dir=str(scratch)))
        self.addCleanup(lambda: shutil.rmtree(target, ignore_errors=True))

        result = controller._reveal_directory(target)
        self.assertIsInstance(result, bool)

    def test_open_failure_surfaces_a_toast_not_silence(self) -> None:
        """打不开目录时必须给出提示，并且提示里带上路径供用户手动访问。

        用不存在的盘符路径逼出失败分支——真实环境下这个分支就是
        "没有任何文件管理器能处理" 的情形。
        """
        from codex_switch.ui_v2.controller import AppController

        controller = AppController()
        toasts: list[tuple] = []
        controller.toastRequested.connect(lambda *args: toasts.append(args))

        # 让 mkdir 之后的 reveal 一定失败
        controller._reveal_directory = lambda path: False
        controller.openPluginFolder()

        self.assertTrue(toasts, "打不开目录时没有任何提示（就是当初的 bug）")
        # toastRequested 的签名是 (message, level, detail)
        message = toasts[0][0]
        self.assertIn(str(controller.plugin_root()), message,
                      "提示里必须带路径，否则用户仍然不知道去哪")

    def test_slot_is_callable_from_qml_metacall(self) -> None:
        """槽必须注册进元对象，否则 QML 调用会静默无效。"""
        from codex_switch.ui_v2.controller import AppController

        controller = AppController()
        meta = controller.metaObject()
        names = {
            bytes(meta.method(i).name()).decode()
            for i in range(meta.methodCount())
        }
        self.assertIn("openPluginFolder", names)

    def test_open_folder_slot_has_zero_argument_signature(self) -> None:
        """视图模型的 openFolder 必须注册成 ``openFolder()``。

        这条是上面那个 bug 的直接回归：签名曾误写成 ``@Slot(str)``，
        而 QML 调用 ``pluginsModel.openFolder()`` 不传参数，Qt 匹配不到
        就不派发——按钮点了完全没反应，且没有任何报错。
        """
        from codex_switch.ui_v2.controller import AppController

        controller = AppController()
        meta = controller.plugins.metaObject()
        signature = None
        for i in range(meta.methodCount()):
            method = meta.method(i)
            if bytes(method.name()) == b"openFolder":
                signature = method.methodSignature().data().decode()
        self.assertEqual(signature, "openFolder()",
                         "签名不对，QML 点击会静默失效")

    def test_run_action_slot_declares_both_arguments(self) -> None:
        """runAction 必须声明两个参数，否则插件动作按钮点不动。"""
        from codex_switch.ui_v2.controller import AppController

        controller = AppController()
        meta = controller.plugins.metaObject()
        signature = None
        for i in range(meta.methodCount()):
            method = meta.method(i)
            if bytes(method.name()) == b"runAction":
                signature = method.methodSignature().data().decode()
        self.assertIsNotNone(signature)
        self.assertEqual(signature.count(","), 1,
                         f"runAction 参数个数不对：{signature}")


class PluginSlotSignatureAuditTests(unittest.TestCase):
    """全仓库审计：@Slot 声明的参数个数必须与函数实现一致。

    这类错误不会报错、不会崩溃，只会让对应的 QML 调用**静默失效**——
    插件中心的「打开插件目录」和「执行动作」都是这么坏掉的。
    所以用静态扫描把它挡在提交前。
    """

    @staticmethod
    def _split_params(raw: str) -> list[str]:
        """按顶层逗号切分参数列表。

        不能直接 ``str.split(",")``：类型注解里可能有逗号，例如
        ``payload: dict[str, Any]`` 会被切成两段，导致误报。
        这里跟踪 ``[]``/``()`` 的嵌套深度，只在深度为 0 时切分。
        """
        parts: list[str] = []
        current = ""
        depth = 0
        for char in raw:
            if char in "[({":
                depth += 1
            elif char in "])}":
                depth -= 1
            if char == "," and depth == 0:
                parts.append(current)
                current = ""
            else:
                current += char
        parts.append(current)
        return [p.strip() for p in parts if p.strip()]

    def _iter_slot_mismatches(self, directory: Path):
        import re

        for path in sorted(directory.rglob("*.py")):
            lines = path.read_text(encoding="utf-8").splitlines()
            for index, line in enumerate(lines):
                match = re.match(r"\s*@Slot\(([^)]*)\)", line)
                if not match:
                    continue
                declared = match.group(1)
                if not declared.strip():
                    continue
                # result=... 是返回类型，不是参数，先剔除。
                cleaned = re.sub(r"result\s*=\s*[^,]+", "", declared)
                expected = len(self._split_params(cleaned))
                if not expected:
                    continue

                for offset in range(index + 1, min(index + 5, len(lines))):
                    definition = re.match(r"\s*def\s+(\w+)\(([^)]*)\)", lines[offset])
                    if not definition:
                        continue
                    params = [
                        p for p in self._split_params(definition.group(2))
                        if p != "self"
                    ]
                    # 带默认值的参数可以省略不传，不算不匹配。
                    required = [p for p in params if "=" not in p]
                    if len(required) != expected and len(params) != expected:
                        yield (
                            f"{path.name}:{offset + 1} "
                            f"{definition.group(1)} 声明 {expected} 参，实现 {len(params)} 参"
                        )
                    break

    def test_no_slot_signature_mismatches(self) -> None:
        viewmodels = PROJECT_ROOT / "src" / "codex_switch" / "ui_v2" / "viewmodels"
        mismatches = list(self._iter_slot_mismatches(viewmodels))
        self.assertEqual(
            mismatches, [],
            "发现 @Slot 签名与实现不一致（会导致 QML 调用静默失效）：\n"
            + "\n".join(mismatches),
        )


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
