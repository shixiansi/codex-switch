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


if __name__ == "__main__":
    unittest.main()
