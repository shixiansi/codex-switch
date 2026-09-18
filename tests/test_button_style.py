"""按钮样式的回归测试。

这些用例锁定的是**观感缺陷**，不是功能缺陷——它们不会让程序崩溃，但会让
用户误判界面：

1. 禁用态原本与启用态**像素完全相同**：输入框为空时的「发送」、没有会话时的
   「载入项目历史」看起来仍然可以点。
2. 单字符按钮（↑ ↓ ← →）用标准宽度会变成空荡荡的方框。
3. 打开菜单/弹窗的按钮缺少"可展开"的视觉线索。

用真实 QML 组件渲染后按像素断言，而不是检查属性值——属性对但画不出来
正是这类问题的典型表现。
"""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_SRC = _ROOT / "src"
for _p in (_SRC, _ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

os.environ.setdefault("CODEX_SWITCH_DISABLE_OPEN_URL", "1")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from tests.helpers import workspace_tempdir  # noqa: E402


def _qt_ready() -> bool:
    try:
        from PySide6.QtQuick import QQuickWindow  # noqa: F401

        return True
    except Exception:  # pragma: no cover
        return False


# 组件要引用 Theme（它绑定 app.themeController），因此必须用真实引擎。
_QML = b"""
import QtQuick
import QtQuick.Controls
import theme
import components

Item {
    id: root
    width: 900; height: 120

    AppButton { id: b1; x: 8;   y: 12; text: "\xe5\x8f\x91\xe9\x80\x81";
                variant: "primary"; enabled: true }
    AppButton { id: b2; x: 130; y: 12; text: "\xe5\x8f\x91\xe9\x80\x81";
                variant: "primary"; enabled: false }
    AppButton { id: up;  x: 260; y: 12; text: "\xe2\x86\x91";
                variant: "secondary"; compact: true; implicitHeight: 28 }
    AppButton { id: wide; x: 320; y: 12; text: "\xe2\x86\x91";
                variant: "secondary"; implicitHeight: 28 }
    AppButton { id: chv; x: 440; y: 12; text: "\xe5\x9b\xbe\xe7\x89\x87";
                iconName: "image"; trailingIconName: "chevron-down" }
    AppButton { id: noChv; x: 620; y: 12; text: "\xe5\x9b\xbe\xe7\x89\x87";
                iconName: "image" }

    property alias wCompact: up.width
    property alias wStandard: wide.width
    property alias wWithChevron: chv.width
    property alias wWithoutChevron: noChv.width
}
"""


@unittest.skipUnless(_qt_ready(), "需要 Qt")
class ButtonStyleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        from codex_switch.storage import ProfileStore
        from codex_switch.ui_v2.app import build_application, build_engine
        from codex_switch.ui_v2.controller import AppController
        from codex_switch.ui_v2.workspace import Workspace

        cls._tmp = workspace_tempdir()
        root = cls._tmp.__enter__()
        cls.app = build_application(["t"])
        cls.controller = AppController(workspace=Workspace(store=ProfileStore(root)))
        cls.engine = build_engine(cls.controller)

    @classmethod
    def tearDownClass(cls) -> None:
        try:
            cls.controller.shutdownNotifier()
        except Exception:  # noqa: BLE001
            pass
        cls._tmp.__exit__(None, None, None)

    def setUp(self) -> None:
        """构建一份**每个用例独立**的组件实例。

        共享实例会在用例之间被 shiboken 回收（"Internal C++ object already
        deleted"），因为窗口与 QML 对象的生命周期不像看上去那么配合。
        每个用例重建一次最省心，也避免用例互相污染状态。
        """
        from PySide6.QtCore import QUrl
        from PySide6.QtQml import QQmlComponent
        from PySide6.QtQuick import QQuickWindow

        self._component = QQmlComponent(self.engine)
        self._component.setData(_QML, QUrl())
        self.assertEqual(
            self._component.status(),
            QQmlComponent.Status.Ready,
            self._component.errorString(),
        )
        self.item = self._component.create()
        self.assertIsNotNone(self.item, "AppButton 画布创建失败")

        self.window = QQuickWindow()
        self.window.setColor("white")
        self.window.resize(900, 120)
        self.item.setParentItem(self.window.contentItem())
        self.window.show()
        self._pump(4)

    def tearDown(self) -> None:
        try:
            self.window.close()
            self.window.deleteLater()
        except Exception:  # noqa: BLE001
            pass

    def _pump(self, rounds: int = 6) -> None:
        for _ in range(rounds):
            self.app.processEvents()

    @staticmethod
    def _fill(image, x: int, y: int) -> str:
        colour = image.pixelColor(x, y)
        return f"#{colour.red():02X}{colour.green():02X}{colour.blue():02X}"

    def test_disabled_button_is_visually_distinct(self) -> None:
        """禁用态必须看得出禁用。

        原先 `_fg` 与 `_bgSolid` 都不看 `enabled`，于是禁用按钮与启用按钮
        像素完全相同——用户会一直点一个点不动的按钮。
        """
        self._pump()
        image = self.window.grabWindow()
        enabled = self._fill(image, 40, 29)
        disabled = self._fill(image, 165, 29)
        self.assertNotEqual(
            enabled, disabled, "禁用按钮与启用按钮的填充色相同，看不出不可点"
        )

    def test_compact_is_narrower_than_standard(self) -> None:
        """compact 用于单字符按键：不该被撑成一个空方框。"""
        self._pump()
        compact = self.item.property("wCompact")
        standard = self.item.property("wStandard")
        self.assertGreater(compact, 0)
        self.assertLess(
            compact, standard, f"compact 宽度 {compact} 应小于标准 {standard}"
        )

    def test_trailing_chevron_widens_the_button(self) -> None:
        """尾部箭头要真的占位（证明它画出来了，而不是被静默忽略）。"""
        self._pump()
        with_chevron = self.item.property("wWithChevron")
        without = self.item.property("wWithoutChevron")
        self.assertGreater(
            with_chevron,
            without,
            "带尾部箭头的按钮没有变宽，说明箭头没生效",
        )

    def test_buttons_still_render_in_dark_theme(self) -> None:
        """深色主题下禁用态同样要可分辨（颜色来自 Python 主题表）。"""
        self.controller.setDarkMode(True)
        self._pump(8)
        image = self.window.grabWindow()
        enabled = self._fill(image, 40, 29)
        disabled = self._fill(image, 165, 29)
        self.assertNotEqual(enabled, disabled, "深色主题下禁用态不可分辨")
        self.controller.setDarkMode(False)
        self._pump(8)


if __name__ == "__main__":
    unittest.main()
