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


if __name__ == "__main__":
    unittest.main()
