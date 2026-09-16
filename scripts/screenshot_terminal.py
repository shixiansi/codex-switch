"""渲染 AI 终端页面截图，用于人工核对样式。

用法（开发期辅助脚本，非产品代码）：
    python scripts/screenshot_terminal.py
"""

from __future__ import annotations

import os
from pathlib import Path
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QUICK_CONTROLS_STYLE", "Basic")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from PySide6.QtCore import QMetaObject, QTimer  # noqa: E402
from PySide6.QtGui import QGuiApplication  # noqa: E402

from codex_switch.ui_v2.app import QML_ENTRYPOINT, build_engine, configure_style, load_qml  # noqa: E402
from codex_switch.ui_v2.controller import AppController  # noqa: E402
from codex_switch.ui_v2.workspace import Workspace  # noqa: E402


def main() -> int:
    app = QGuiApplication([])
    configure_style()
    controller = AppController(workspace=Workspace())
    engine = build_engine(controller)
    if not load_qml(engine, QML_ENTRYPOINT):
        print("QML 加载失败")
        return 1

    root = engine.rootObjects()[0]
    controller.navigateTo("terminal")

    out_dir = ROOT / "artifacts"
    out_dir.mkdir(exist_ok=True)

    def shoot_main() -> None:
        image = root.grabWindow()
        image.save(str(out_dir / "terminal_main.png"))
        print("saved", out_dir / "terminal_main.png")
        QTimer.singleShot(300, shoot_dialog)

    def shoot_dialog() -> None:
        panel = root.findChild(object, "terminalDashboard")
        if panel is not None:
            QMetaObject.invokeMethod(panel, "openCreateDialog")
        QTimer.singleShot(500, finish)

    def finish() -> None:
        image = root.grabWindow()
        image.save(str(out_dir / "terminal_dialog.png"))
        print("saved", out_dir / "terminal_dialog.png")
        app.quit()

    QTimer.singleShot(600, shoot_main)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
