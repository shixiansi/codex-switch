from __future__ import annotations

from pathlib import Path
import unittest


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class EncodingTests(unittest.TestCase):
    def test_python_files_are_utf8_without_bom(self) -> None:
        checked = 0
        for root in (PROJECT_ROOT / "src", PROJECT_ROOT / "tests"):
            for path in root.rglob("*.py"):
                relative = path.relative_to(PROJECT_ROOT)
                data = path.read_bytes()
                checked += 1
                self.assertFalse(data.startswith(b"\xef\xbb\xbf"), f"{relative} has UTF-8 BOM")
                try:
                    data.decode("utf-8")
                except UnicodeDecodeError as exc:
                    self.fail(f"{relative} is not valid UTF-8: {exc}")
        self.assertGreater(checked, 0)

    def test_requirements_files_are_ascii_only(self) -> None:
        """回归：pip 用本地编码（中文 Windows 为 GBK）解码 requirements 文件。

        这些文件没有 BOM、pip 也不认 `# -*- coding: -*-`，所以只要出现中文注释，
        `pip install -r requirements.txt` 就会直接 UnicodeDecodeError 失败，
        整个构建随之中断。必须保持纯 ASCII。
        """
        for name in ("requirements.txt", "requirements-build.txt"):
            path = PROJECT_ROOT / name
            if not path.exists():
                continue
            data = path.read_bytes()
            offenders = sorted({byte for byte in data if byte > 127})
            self.assertFalse(
                offenders,
                f"{name} 含非 ASCII 字节 {offenders}，pip 在中文 Windows 上会解码失败",
            )


if __name__ == "__main__":
    unittest.main()
