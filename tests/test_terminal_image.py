"""附加图片功能测试（无 Qt 依赖部分 + 剪贴板接线）。

AI CLI 收图只有一条通道：**图片进系统剪贴板 + 向 PTY 发 Ctrl+V**，由 CLI
自己读剪贴板。本文件覆盖这条链路里能在无头环境验证的部分：

* 选图前的校验（格式、体积、路径）——这是用户唯一会看到的错误来源；
* Ctrl+V 的字节序列确实进了按键表（CLI 靠它触发读剪贴板）；
* 附加**不会自动回车**（否则会把图片连带半句话直接发给模型）；
* view model 的剪贴板/发键接线（用替身，不依赖真实剪贴板）。
"""

from __future__ import annotations

import os
import sys
import time
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
from tests.test_terminal import _FakeBackend  # noqa: E402

from codex_switch.ui_v2.terminal.image_attach import (  # noqa: E402
    FILE_DIALOG_FILTER,
    MAX_IMAGE_BYTES,
    SUPPORTED_EXTENSIONS,
    prepare_image,
)
from codex_switch.ui_v2.terminal.manager import SPECIAL_KEYS, TerminalManager  # noqa: E402


class PrepareImageTests(unittest.TestCase):
    """选图校验：错误必须说清原因。"""

    def setUp(self) -> None:
        self._tmp = workspace_tempdir()
        self.root = self._tmp.__enter__()
        self.addCleanup(lambda: self._tmp.__exit__(None, None, None))

    def _make(self, name: str, size: int = 32) -> Path:
        p = self.root / name
        p.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * max(0, size - 8))
        return p

    def test_accepts_supported_formats(self) -> None:
        for ext in SUPPORTED_EXTENSIONS:
            with self.subTest(ext=ext):
                image = prepare_image(self._make(f"shot{ext}"))
                self.assertEqual(image.extension, ext)
                self.assertGreater(image.size_bytes, 0)

    def test_rejects_unsupported_format_with_reason(self) -> None:
        path = self._make("notes.txt")
        with self.assertRaises(ValueError) as ctx:
            prepare_image(path)
        message = str(ctx.exception)
        self.assertIn("不支持", message)
        # 要告诉用户能用什么，否则等于没说。
        self.assertIn("png", message)

    def test_rejects_missing_file(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            prepare_image(self.root / "nope.png")
        self.assertIn("不存在", str(ctx.exception))

    def test_rejects_directory(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            prepare_image(self.root)
        self.assertIn("不是一个文件", str(ctx.exception))

    def test_rejects_empty_file(self) -> None:
        p = self.root / "empty.png"
        p.write_bytes(b"")
        with self.assertRaises(ValueError) as ctx:
            prepare_image(p)
        self.assertIn("空文件", str(ctx.exception))

    def test_rejects_oversized_file(self) -> None:
        p = self.root / "huge.png"
        with open(p, "wb") as fh:
            fh.truncate(MAX_IMAGE_BYTES + 1)
        with self.assertRaises(ValueError) as ctx:
            prepare_image(p)
        self.assertIn("太大", str(ctx.exception))

    def test_accepts_file_uri(self) -> None:
        """QML 的 FileDialog 给出的是 file:// URL，必须能直接用。"""
        path = self._make("uri.png")
        image = prepare_image(path.resolve().as_uri())
        self.assertEqual(image.name, "uri.png")

    def test_accepts_quoted_path(self) -> None:
        path = self._make("quoted.png")
        self.assertEqual(prepare_image(f'"{path}"').name, "quoted.png")

    def test_size_label_is_readable(self) -> None:
        image = prepare_image(self._make("label.png", size=2048))
        self.assertIn("KB", image.size_label())

    def test_to_dict_exposes_ui_fields(self) -> None:
        data = prepare_image(self._make("ui.png")).to_dict()
        for key in ("path", "name", "sizeBytes", "sizeLabel", "extension"):
            self.assertIn(key, data)

    def test_dialog_filter_lists_all_supported(self) -> None:
        for ext in SUPPORTED_EXTENSIONS:
            self.assertIn(ext, FILE_DIALOG_FILTER)


class PasteKeyTests(unittest.TestCase):
    """Ctrl+V 是整条链路的触发点，必须真的存在且字节正确。"""

    def test_ctrl_v_is_in_the_key_table(self) -> None:
        self.assertIn("ctrl-v", SPECIAL_KEYS)
        # 0x16 = ASCII SYN，即终端里的 Ctrl+V。
        self.assertEqual(SPECIAL_KEYS["ctrl-v"], "\x16")

    def test_paste_writes_ctrl_v_and_nothing_else(self) -> None:
        """附加只发一个 Ctrl+V：不得顺带回车，否则会直接把消息发出去。"""
        store: dict[str, _FakeBackend] = {}

        def make(command, cwd, env):
            b = _FakeBackend(command, cwd, env)
            store["b"] = b
            return b

        mgr = TerminalManager(poll_interval=0.05)
        mgr.start()
        try:
            sid = mgr.create_session("t", "codex", "", backend_factory=make)
            self.assertTrue(mgr.paste_clipboard_image(sid))
            time.sleep(0.3)
            written = "".join(store["b"].write_calls())
            self.assertEqual(written, "\x16", f"只应发送 Ctrl+V，实际 {written!r}")
            self.assertNotIn("\r", written, "不得自动回车")
        finally:
            mgr.shutdown()

    def test_paste_on_unknown_session_is_false(self) -> None:
        mgr = TerminalManager(poll_interval=0.05)
        mgr.start()
        try:
            self.assertFalse(mgr.paste_clipboard_image("does-not-exist"))
        finally:
            mgr.shutdown()


class _StubController:
    def __init__(self) -> None:
        self.toasts: list[tuple[str, str]] = []

    def showToast(self, message: str, level: str = "info") -> None:
        self.toasts.append((str(message), str(level)))

    def notifyTerminalReview(self, *a) -> None:
        pass

    def pendingTerminalReview(self) -> dict:
        return {}

    def presentTerminalReview(self, r) -> None:
        pass

    def clearTerminalReview(self) -> None:
        pass

    def applyTerminalAudioPolicy(self, p) -> None:
        pass


class ViewModelAttachTests(unittest.TestCase):
    """view model 的接线：校验失败要提示，成功要发 Ctrl+V。"""

    def _vm(self):
        from PySide6.QtWidgets import QApplication

        from codex_switch.ui_v2.viewmodels.terminal import TerminalViewModel

        self.app = QApplication.instance() or QApplication([])
        ctrl = _StubController()
        vm = TerminalViewModel(ctrl)
        self.addCleanup(vm.dispose)
        return vm, ctrl

    def _session(self, vm):
        store: dict[str, _FakeBackend] = {}

        def make(command, cwd, env):
            b = _FakeBackend(command, cwd, env)
            store["b"] = b
            return b

        sid = vm._manager.create_session("t", "codex", "", backend_factory=make)
        vm.focus(sid)
        self.app.processEvents()
        return sid, store["b"]

    def test_unsupported_file_reports_reason_and_sends_nothing(self) -> None:
        with workspace_tempdir() as root:
            vm, ctrl = self._vm()
            _sid, backend = self._session(vm)
            bad = Path(root) / "notes.txt"
            bad.write_text("not an image", encoding="utf-8")

            self.assertFalse(vm.attachImage(str(bad)))
            self.assertTrue(ctrl.toasts, "应给出可见提示")
            self.assertIn("不支持", ctrl.toasts[-1][0])
            self.assertEqual("".join(backend.write_calls()), "", "不应发送任何按键")

    def test_attach_without_session_is_rejected(self) -> None:
        with workspace_tempdir() as root:
            vm, ctrl = self._vm()
            png = Path(root) / "a.png"
            png.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 32)
            self.assertFalse(vm.attachImage(str(png)))
            self.assertTrue(ctrl.toasts)

    def test_clipboard_without_image_reports_clearly(self) -> None:
        vm, ctrl = self._vm()
        self._session(vm)
        # 清空剪贴板里的图片，确保走"没有图片"分支。
        clipboard = self.app.clipboard()
        clipboard.clear()
        self.assertFalse(vm.attachImageFromClipboard())
        self.assertTrue(ctrl.toasts)
        self.assertIn("剪贴板", ctrl.toasts[-1][0])

    def test_valid_file_is_written_to_clipboard_and_pasted(self) -> None:
        """成功路径：图片进剪贴板 + 只发 Ctrl+V。"""
        from PySide6.QtGui import QImage

        with workspace_tempdir() as root:
            vm, ctrl = self._vm()
            _sid, backend = self._session(vm)

            png = Path(root) / "shot.png"
            img = QImage(24, 24, QImage.Format.Format_RGB32)
            img.fill(0x00AA88)
            self.assertTrue(img.save(str(png), "PNG"))

            self.assertTrue(vm.attachImage(str(png)))
            # 剪贴板里应当是图片（CLI 就是从这里取）。
            self.assertTrue(self.app.clipboard().mimeData().hasImage())

            deadline = time.time() + 2.0
            while time.time() < deadline and not backend.write_calls():
                self.app.processEvents()
                time.sleep(0.02)
            written = "".join(backend.write_calls())
            self.assertEqual(written, "\x16", f"应只发 Ctrl+V，实际 {written!r}")
            self.assertTrue(any("已附加" in m for m, _ in ctrl.toasts))

    def test_data_url_is_accepted(self) -> None:
        """拖拽/粘贴进来的 data: URL 也要能附加。"""
        from PySide6.QtCore import QBuffer, QByteArray
        from PySide6.QtGui import QImage

        vm, ctrl = self._vm()
        _sid, backend = self._session(vm)

        img = QImage(16, 16, QImage.Format.Format_RGB32)
        img.fill(0x884400)
        buf = QBuffer()
        buf.open(QBuffer.OpenModeFlag.ReadWrite)
        img.save(buf, "PNG")
        b64 = bytes(buf.data().toBase64()).decode("ascii")
        data_url = f"data:image/png;base64,{b64}"

        self.assertTrue(vm.attachImageFromDataUrl(data_url))
        deadline = time.time() + 2.0
        while time.time() < deadline and not backend.write_calls():
            self.app.processEvents()
            time.sleep(0.02)
        self.assertEqual("".join(backend.write_calls()), "\x16")

    def test_non_image_data_url_is_rejected(self) -> None:
        vm, ctrl = self._vm()
        self._session(vm)
        self.assertFalse(vm.attachImageFromDataUrl("data:text/plain;base64,aGk="))
        self.assertTrue(ctrl.toasts)


if __name__ == "__main__":
    unittest.main()
