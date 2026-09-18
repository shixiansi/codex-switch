"""按键行为的回归测试：↑↓ 必须真的被截获。

TextField 自带"方向键移动光标"的行为，很容易把按键吃掉，
导致 Keys.onUpPressed 不触发——"按了没反应"。这类问题只看代码
看不出来，必须发真实按键事件。

这里直接构造 QKeyEvent 发给输入框（QTest.keyClick 只支持 QWidget/QWindow，
对 QML item 无效）。
"""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_SRC = _ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("CODEX_SWITCH_DISABLE_OPEN_URL", "1")

KEY_UP = 0x01000013
KEY_DOWN = 0x01000015
KEY_TAB = 0x01000001
KEY_ESC = 0x01000000


def _qt_ready() -> bool:
    try:
        from codex_switch.ui_v2.qt_compat import QT_AVAILABLE

        return bool(QT_AVAILABLE)
    except Exception:  # noqa: BLE001
        return False


@unittest.skipUnless(_qt_ready(), "需要 Qt")
class TerminalViewKeyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QGuiApplication
        from PySide6.QtQml import QQmlComponent, QQmlEngine

        from codex_switch.ui_v2.app import QML_IMPORT_PATHS, QML_ROOT

        cls.app = QGuiApplication.instance() or QGuiApplication([])
        cls.engine = QQmlEngine()
        for path in QML_IMPORT_PATHS:
            cls.engine.addImportPath(str(path))

        component = QQmlComponent(cls.engine, QUrl.fromLocalFile(
            str(QML_ROOT / "components" / "TerminalView.qml")
        ))
        assert component.status() == QQmlComponent.Status.Ready, component.errorString()
        cls.component = component

    def setUp(self) -> None:
        self.view = self.component.create()
        self.assertIsNotNone(self.view, "TerminalView 创建失败")
        self.addCleanup(self.view.deleteLater)
        self.received: list[tuple] = []
        self.view.historyRequested.connect(lambda older: self.received.append(("history", older)))
        self.view.hintMoved.connect(lambda index: self.received.append(("hintMoved", index)))
        self.view.hintAccepted.connect(lambda index: self.received.append(("hintAccepted", index)))
        self.view.hintsClosed.connect(lambda: self.received.append(("hintsClosed", None)))
        self.view.inputEdited.connect(lambda text: self.received.append(("edited", text)))
        self.field = self._find_input(self.view)
        self.assertIsNotNone(self.field, "没找到输入框")

    def _find_input(self, item):
        for child in item.children():
            try:
                if child.metaObject().className().startswith("AppTextField"):
                    return child
            except Exception:  # noqa: BLE001
                pass
            found = self._find_input(child)
            if found is not None:
                return found
        return None

    def _send(self, key: int, text: str = "") -> bool:
        from PySide6.QtCore import QCoreApplication, QEvent, Qt
        from PySide6.QtGui import QKeyEvent

        event = QKeyEvent(QEvent.Type.KeyPress, key, Qt.KeyboardModifier.NoModifier, text)
        QCoreApplication.sendEvent(self.field, event)
        return event.isAccepted()

    def _set_hints(self, visible: bool, items=None) -> None:
        self.view.setProperty("inputEnabled", True)
        self.view.setProperty("hintVisible", visible)
        self.view.setProperty("hintItems", items or [])
        self.view.setProperty("hintSelected", 0)

    def test_arrow_keys_are_not_swallowed_by_the_text_field(self) -> None:
        """核心回归：TextField 默认会用方向键移动光标，若没被截获，
        ↑↓ 就永远不会触发历史翻页——用户的感受就是"按了没反应"。
        """
        self._set_hints(False)
        up_accepted = self._send(KEY_UP)
        down_accepted = self._send(KEY_DOWN)
        self.assertTrue(up_accepted, "↑ 被 TextField 吃掉了")
        self.assertTrue(down_accepted, "↓ 被 TextField 吃掉了")
        self.assertIn(("history", True), self.received)
        self.assertIn(("history", False), self.received)

    def test_arrows_navigate_hints_when_visible(self) -> None:
        self._set_hints(True, [
            {"name": "/model", "description": "切换模型"},
            {"name": "/new", "description": "新会话"},
        ])
        self._send(KEY_DOWN)
        self.assertIn(("hintMoved", 1), self.received)
        self.assertFalse(
            any(item[0] == "history" for item in self.received),
            "候选条开着时不应同时翻历史",
        )

    def test_tab_accepts_and_escape_closes(self) -> None:
        self._set_hints(True, [{"name": "/model", "description": "切换模型"}])
        self._send(KEY_TAB)
        self._send(KEY_ESC)
        self.assertIn(("hintAccepted", 0), self.received)
        self.assertIn(("hintsClosed", None), self.received)

    def test_apply_history_does_not_emit_input_edited(self) -> None:
        """程序化填入历史不能被当成"用户在编辑"，否则翻页状态立刻被重置。"""
        self._set_hints(False)
        self.received.clear()
        self.view.applyHistory("历史内容")
        self.assertEqual(self.field.property("text"), "历史内容")
        self.assertFalse(
            any(item[0] == "edited" for item in self.received),
            "applyHistory 不应触发 inputEdited",
        )

    def test_typing_emits_input_edited(self) -> None:
        """手打字符要触发 inputEdited，候选条才能跟着刷新。"""
        self._set_hints(False)
        self.received.clear()
        self._send(0x2F, "/")
        self.assertTrue(any(item[0] == "edited" for item in self.received))

    # -- 按键条必须始终可用 ------------------------------------------------
    def _key_buttons(self):
        """找出按键条里的按钮（按文字识别）。"""
        from PySide6.QtQuick import QQuickItem

        found = {}
        for item in self.view.findChildren(QQuickItem):
            try:
                if not item.metaObject().className().startswith("AppButton"):
                    continue
                text = str(item.property("text") or "")
            except Exception:  # noqa: BLE001
                continue
            if text in ("↑", "↓", "←", "→", "Enter", "Esc"):
                found[text] = item
        return found

    def _key_row(self):
        """定位按键条那个 RowLayout（以其中的"按键"标签为锚点）。"""
        from PySide6.QtQuick import QQuickItem

        for item in self.view.findChildren(QQuickItem):
            try:
                if not item.metaObject().className().startswith("QQuickRowLayout"):
                    continue
                for child in item.children():
                    if hasattr(child, "property") and child.property("text") == "按键":
                        return item
            except Exception:  # noqa: BLE001
                continue
        return None

    def test_key_row_has_bottom_margin(self) -> None:
        """回归：按键条与下方输出框之间必须有间距，不能贴死。

        外层 ColumnLayout 的 spacing 是 0，各区块只靠自己的 margin 撑开间距。
        按键条原先只有 topMargin（管上方），下方没有任何区块补 topMargin，
        于是按键与内容框直接贴在一起——用户一眼就看出来了。

        这里断言真实几何（按键条底边与输出框顶边之间的空隙），而不是只看
        属性值，因为"属性写了但布局没生效"正是这个坑的形态。
        """
        self.view.setProperty("inputEnabled", True)
        # QQuickItem 没有 resize()；用宽高属性给布局一个确定的尺寸，
        # 否则各区块高度为 0，几何断言没有意义。
        self.view.setWidth(900)
        self.view.setHeight(700)
        for _ in range(6):
            self.app.processEvents()

        row = self._key_row()
        self.assertIsNotNone(row, "没找到按键条")

        # 输出框：ColumnLayout 里紧跟在按键条之后的那个矩形。
        #
        # 按"颜色 == codeBg"去找并不可靠：这个用例只创建 TerminalView 本身，
        # 主题色在不同上下文下的取值/命名可能不同。改为按布局顺序定位——
        # 结构关系才是这里真正要断言的东西。
        from PySide6.QtQuick import QQuickItem

        output_box = None
        siblings = [
            ch
            for ch in row.parent().children()
            if isinstance(ch, QQuickItem) and ch.metaObject().className().startswith("QQuickRectangle")
        ]
        # 取 y 坐标在按键条之下、且最靠近的那个矩形。
        row_bottom_y = row.y() + row.height()
        below = [s for s in siblings if s.y() >= row_bottom_y - 1 and s.height() > 40]
        if below:
            output_box = min(below, key=lambda s: s.y())
        self.assertIsNotNone(output_box, "按键条下方没找到输出框")

        row_bottom = row.y() + row.height()
        gap = output_box.y() - row_bottom
        self.assertGreaterEqual(
            gap, 4, f"按键条与输出框之间只有 {gap:.0f}px，几乎贴在一起"
        )

    def test_key_buttons_visible_even_without_a_detected_menu(self) -> None:
        """回归：识别不出菜单时，用户仍必须能手动发方向键与回车。

        旧实现把这几个键放在"检测到选择菜单"的面板里，于是一旦菜单没被识别
        （例如只剩一个历史会话的 resume 列表），整屏就卡死——菜单明明在等按键，
        界面却一个键都发不出去。按键条现在与会话存在与否挂钩，不再依赖识别结果。
        """
        self.view.setProperty("inputEnabled", True)
        self.view.setProperty("awaitingChoice", False)
        self.view.setProperty("choices", [])
        self.view.setProperty("forceActiveFocus", True)
        buttons = self._key_buttons()
        for label in ("↑", "↓", "Enter", "Esc"):
            self.assertIn(label, buttons, f"缺少按键按钮 {label}")
            self.assertTrue(
                buttons[label].property("visible"), f"{label} 在没有菜单时也应可见"
            )

    def test_key_buttons_emit_key_sent(self) -> None:
        """按键条要真的发出 keySent，而不是只摆在那里。"""
        from PySide6.QtQuick import QQuickItem

        self.view.setProperty("inputEnabled", True)
        self.view.setProperty("awaitingChoice", False)
        self.view.setProperty("choices", [])
        sent: list[str] = []
        self.view.keySent.connect(lambda key: sent.append(str(key)))

        buttons = self._key_buttons()
        for label, expected in (("↑", "up"), ("↓", "down"), ("Enter", "enter"), ("Esc", "esc")):
            self.assertIn(label, buttons, f"缺少按键按钮 {label}")
            buttons[label].clicked.emit()
        self.assertEqual(sent, ["up", "down", "enter", "esc"])

    def test_key_buttons_hidden_when_no_session(self) -> None:
        """没有会话时按键条不该出现（否则点了没有接收方）。"""
        self.view.setProperty("inputEnabled", False)
        buttons = self._key_buttons()
        for label in ("↑", "↓", "Enter", "Esc"):
            self.assertIn(label, buttons, f"缺少按键按钮 {label}")
            self.assertFalse(
                buttons[label].property("visible"), f"没有会话时 {label} 不该可见"
            )


@unittest.skipUnless(_qt_ready(), "需要 Qt")
class EnterSendsFullCommandTests(unittest.TestCase):
    """回车必须发送**完整命令名**，而不是会被 codex 误匹配的前缀。

    这是用户实际踩到的坑：输入 ``/re``，界面高亮 ``/resume``，
    但发出去的是 ``/re``——codex 用它自己的规则取**第一个**匹配项
    ``/review``，于是"选了 resume，起来的却是 review 菜单"。
    """

    @classmethod
    def setUpClass(cls) -> None:
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QGuiApplication
        from PySide6.QtQml import QQmlComponent, QQmlEngine

        from codex_switch.ui_v2.app import QML_IMPORT_PATHS, QML_ROOT

        cls.app = QGuiApplication.instance() or QGuiApplication([])
        cls.engine = QQmlEngine()
        for path in QML_IMPORT_PATHS:
            cls.engine.addImportPath(str(path))
        cls.component = QQmlComponent(cls.engine, QUrl.fromLocalFile(
            str(QML_ROOT / "components" / "TerminalView.qml")
        ))

    def setUp(self) -> None:
        self.view = self.component.create()
        self.addCleanup(self.view.deleteLater)
        self.sent: list[str] = []
        self.view.inputSubmitted.connect(lambda text: self.sent.append(text))
        self.field = self._find_input(self.view)
        self.view.setProperty("inputEnabled", True)

    def _find_input(self, item):
        for child in item.children():
            try:
                if child.metaObject().className().startswith("AppTextField"):
                    return child
            except Exception:  # noqa: BLE001
                pass
            found = self._find_input(child)
            if found is not None:
                return found
        return None

    def _press_enter(self) -> None:
        from PySide6.QtCore import QCoreApplication, QEvent, Qt
        from PySide6.QtGui import QKeyEvent

        event = QKeyEvent(
            QEvent.Type.KeyPress, Qt.Key.Key_Return,
            Qt.KeyboardModifier.NoModifier, "\r",
        )
        QCoreApplication.sendEvent(self.field, event)

    def _with_hints(self, text: str, selected: int) -> None:
        from codex_switch.ui_v2.terminal.input_assist import command_hints

        hint = command_hints(text)
        self.view.setProperty("hintVisible", hint.visible)
        self.view.setProperty("hintItems", hint.items)
        self.view.setProperty("hintSelected", selected)
        self.field.setProperty("text", text)

    def test_enter_sends_the_highlighted_command_not_the_prefix(self) -> None:
        self._with_hints("/re", 0)
        self._press_enter()
        self.assertEqual(self.sent, ["/resume"],
                         f"发送了前缀而不是完整命令：{self.sent}")

    def test_enter_sends_whichever_command_is_highlighted(self) -> None:
        self._with_hints("/re", 1)
        self._press_enter()
        self.assertEqual(self.sent, ["/review"])

    def test_plain_text_is_sent_unchanged(self) -> None:
        self.view.setProperty("hintVisible", False)
        self.view.setProperty("hintItems", [])
        self.field.setProperty("text", "帮我重构这段代码")
        self._press_enter()
        self.assertEqual(self.sent, ["帮我重构这段代码"])

    def test_command_with_arguments_is_not_rewritten(self) -> None:
        """已输入参数时不再提示，也不能把内容改掉。"""
        self._with_hints("/model gpt-5", 0)
        self._press_enter()
        self.assertEqual(self.sent, ["/model gpt-5"])

    def test_send_button_uses_the_same_payload(self) -> None:
        self.view.setProperty("hintVisible", True)
        self.view.setProperty("hintItems", [{"name": "/resume", "description": "恢复"}])
        self.view.setProperty("hintSelected", 0)
        self.assertEqual(self.view.payloadFor("/re"), "/resume")


class HistoryThroughUiTests(unittest.TestCase):
    """↑ 翻历史必须**逐条往回**，不能一直停在同一句。

    真实缺陷：处理 ↑ 时每次末尾都调用了 ``resetHistoryCursor()``，
    翻页位置被清零，于是每次 ↑ 都从最新一条重新开始——用户按多少次
    ↑ 都只能看到最后发的那一句，感觉"按了没反应/填不进历史"。
    """

    @classmethod
    def setUpClass(cls) -> None:
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QGuiApplication

        from codex_switch.ui_v2.app import QML_ENTRYPOINT, build_engine, configure_style
        from codex_switch.ui_v2.controller import AppController

        cls.app = QGuiApplication.instance() or QGuiApplication([])
        configure_style()
        cls.controller = AppController()
        cls.engine = build_engine(cls.controller)
        cls.engine.load(QUrl.fromLocalFile(str(QML_ENTRYPOINT)))
        cls.root = cls.engine.rootObjects()[0]
        cls.controller.navigateTo("terminal")

        from PySide6.QtCore import QEventLoop, QTimer

        loop = QEventLoop()
        QTimer.singleShot(500, loop.quit)
        loop.exec()

    def setUp(self) -> None:
        from PySide6.QtCore import QEventLoop, QTimer

        from codex_switch.ui_v2.terminal.pty_session import _Backend

        class _FakeBackend(_Backend):
            def __init__(self, *_args):
                pass

            def read(self):
                return b""

            def write(self, _data):
                pass

            def is_alive(self):
                return True

            def pid(self):
                return 1

            def kill(self):
                pass

        model = self.controller.terminal
        self.session_id = model._manager.create_session(
            "history-test", "codex", "",
            backend_factory=lambda c, w, e: _FakeBackend(c, w, e),
        )
        model._refresh_sessions()
        model.focus(self.session_id)
        for text in ("第一", "第二", "第三"):
            model.sendInput(text)
        self.model = model

        view = self._visible_view()
        self.field = self._find(view, "AppTextField")[0]
        self.field.forceActiveFocus()
        self.field.setProperty("text", "")

    def tearDown(self) -> None:
        self.model.removeSession(self.session_id)

    def _visible_view(self):
        for view in self._find(self.root, "TerminalView"):
            if view.property("visible"):
                return view
        raise AssertionError("没有可见的 TerminalView")

    def _find(self, item, cls):
        found = []

        def walk(node):
            try:
                name = node.metaObject().className()
            except Exception:  # noqa: BLE001
                return
            if name.startswith(cls):
                found.append(node)
                return
            for child in node.children():
                walk(child)

        walk(item)
        return found

    def _press(self, key, text="") -> str:
        from PySide6.QtCore import (
            QCoreApplication, QEvent, QEventLoop, Qt, QTimer,
        )
        from PySide6.QtGui import QKeyEvent

        event = QKeyEvent(QEvent.Type.KeyPress, key, Qt.KeyboardModifier.NoModifier, text)
        QCoreApplication.sendEvent(self.field, event)
        loop = QEventLoop()
        QTimer.singleShot(100, loop.quit)
        loop.exec()
        return self.field.property("text")

    def test_up_walks_back_through_history(self) -> None:
        """这条是本次缺陷的直接回归。"""
        from PySide6.QtCore import Qt

        self.assertEqual(self._press(Qt.Key.Key_Up), "第三")
        self.assertEqual(self._press(Qt.Key.Key_Up), "第二",
                         "第二次 ↑ 仍停在同一句——翻页位置被错误重置了")
        self.assertEqual(self._press(Qt.Key.Key_Up), "第一")

    def test_down_walks_forward_and_restores_draft(self) -> None:
        from PySide6.QtCore import Qt

        self._press(Qt.Key.Key_Up)
        self._press(Qt.Key.Key_Up)
        self.assertEqual(self._press(Qt.Key.Key_Down), "第三")
        self.assertEqual(self._press(Qt.Key.Key_Down), "", "越过最新应回到空草稿")

    def test_typing_exits_history_navigation(self) -> None:
        """翻历史后手动编辑，应退出翻页状态（下次 ↑ 从最新开始）。"""
        from PySide6.QtCore import Qt

        self._press(Qt.Key.Key_Up)
        self._press(Qt.Key.Key_Up)
        typed = self._press(0x58, "X")
        self.assertIn("X", typed)
        self.assertEqual(self._press(Qt.Key.Key_Up), "第三",
                         "编辑后没有退出翻页状态")


if __name__ == "__main__":
    unittest.main()
