"""Version-single-source tests.

Real problem: the version sat at 0.2.2 for three months while 203 commits
landed, because the number lived in two places (__init__.py and pyproject.toml)
and nothing tied them to reality. These tests make the drift impossible to
reintroduce silently.
"""

from __future__ import annotations

import re
import sys
import tomllib
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_SRC = _ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))


class VersionSourceTests(unittest.TestCase):
    def test_version_is_a_plain_semver(self) -> None:
        from codex_switch import __version__

        self.assertRegex(
            __version__,
            r"^\d+\.\d+\.\d+$",
            f"版本号格式不对：{__version__!r}",
        )

    def test_pyproject_reads_the_version_dynamically(self) -> None:
        """pyproject 不能再写死版本号，必须从单一来源读取。"""
        data = tomllib.loads((_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        project = data["project"]
        self.assertIn("version", project.get("dynamic", []), "版本号应为动态字段")
        self.assertNotIn(
            "version",
            project,
            "pyproject 里又写死了 version，会和 __init__.py 漂移",
        )
        self.assertEqual(
            data["tool"]["setuptools"]["dynamic"]["version"]["attr"],
            "codex_switch.__version__",
        )

    def test_build_spec_writes_version_into_the_exe(self) -> None:
        """spec 必须把版本写进 Windows 版本资源。

        以前 exe 的 FileVersion/ProductVersion 全是空的，只能靠界面文字判断版本。
        """
        spec = (_ROOT / "CodexSwitch.spec").read_text(encoding="utf-8")
        self.assertIn("version=str(VERSION_FILE)", spec, "EXE 没有写入版本资源")
        self.assertIn("_app_version", spec, "版本号没有取自 codex_switch.__version__")

    def test_ui_shows_the_single_source_version(self) -> None:
        """界面标题与关于信息都取自 __version__，不能再有别的常量。"""
        from codex_switch import __version__

        controller = (
            _ROOT / "src" / "codex_switch" / "ui_v2" / "controller.py"
        ).read_text(encoding="utf-8")
        self.assertIn("__version__", controller)
        # 版本号不应在界面层被硬编码。
        self.assertNotRegex(
            controller,
            r'version\s*=\s*"\d+\.\d+\.\d+"',
            "界面层硬编码了版本号",
        )
        self.assertTrue(__version__)

    def test_no_stale_version_literals_in_source(self) -> None:
        """源码里不该再散落旧版本号字面量。"""
        from codex_switch import __version__

        stale = "0.2.2"
        offenders = []
        for path in (_ROOT / "src").rglob("*.py"):
            text = path.read_text(encoding="utf-8")
            if stale in text and __version__ not in text:
                offenders.append(str(path.relative_to(_ROOT)))
        self.assertEqual(offenders, [], f"源码里残留旧版本号 {stale}：{offenders}")

    def test_release_notes_exist_for_current_version(self) -> None:
        from codex_switch import __version__

        note = _ROOT / "docs" / "releases" / f"v{__version__}.md"
        self.assertTrue(note.is_file(), f"缺少发布说明：{note.name}")


if __name__ == "__main__":
    unittest.main()
