"""Workspace.terminal_launch_spec 测试：按项目打开时自动导入环境与配置。

覆盖：Codex 走 start-codex.cmd 且 cwd 指向项目根；Claude 带上 profile 派生的
运行时环境变量；未选择项目 / 目录不存在时给出可读错误。
"""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
for _p in (_ROOT / "src", _ROOT, _ROOT / "tests"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from helpers import workspace_tempdir  # noqa: E402

from codex_switch.models import Profile, ProjectRecord, VENDOR_CLAUDE, VENDOR_CODEX  # noqa: E402
from codex_switch.storage import ProfileStore  # noqa: E402
from codex_switch.ui_v2.workspace import Workspace, WorkspaceError  # noqa: E402


class TerminalLaunchSpecTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temp = workspace_tempdir()
        self.root: Path = self._temp.__enter__()
        self.addCleanup(self._temp.__exit__, None, None, None)
        self.store = ProfileStore(self.root)
        self.workspace = Workspace(store=self.store, project_root=self.root)
        self.addCleanup(self.workspace.script_runs.shutdown)

    def _add_profile(self, vendor: str = VENDOR_CODEX) -> Profile:
        profile = Profile.create(
            name="主账号",
            base_url="https://api.example.com",
            api_key="sk-test",
            vendor=vendor,
            codex_model="gpt-5",
            claude_model="sonnet",
            claude_fallback_model="haiku",
        )
        self.workspace.session.profiles.append(profile)
        self.workspace.session.selected_profile_id = profile.id
        self.workspace.persist()
        return profile

    def _add_project(self, profile: Profile, *, create_dir: bool = True) -> ProjectRecord:
        project_dir = self.root / "proj"
        if create_dir:
            project_dir.mkdir(parents=True, exist_ok=True)
        project = ProjectRecord.create(
            project_dir=str(project_dir),
            profile_id=profile.id,
            claude_profile_id=profile.id,
            name="示例项目",
        )
        self.workspace.session.projects.append(project)
        self.workspace.session.selected_project_id = project.id
        self.workspace.persist()
        return project

    def test_codex_spec_uses_project_script_and_cwd(self) -> None:
        profile = self._add_profile(VENDOR_CODEX)
        project = self._add_project(profile)
        # 生成 start-codex.cmd，让 required_path 检查通过。
        scripts = self.root / "proj" / "codex_scripts"
        scripts.mkdir(parents=True, exist_ok=True)
        (scripts / "start-codex.cmd").write_text("@echo off\r\n", encoding="utf-8")

        spec = self.workspace.terminal_launch_spec("codex", project.id)
        self.assertIn("start-codex.cmd", spec["command"])
        self.assertEqual(Path(spec["cwd"]).resolve(), (self.root / "proj").resolve())
        self.assertTrue(spec["title"].endswith("Codex"))

    def test_codex_spec_requires_generated_template(self) -> None:
        profile = self._add_profile(VENDOR_CODEX)
        project = self._add_project(profile)
        with self.assertRaises(WorkspaceError) as ctx:
            self.workspace.terminal_launch_spec("codex", project.id)
        self.assertIn("模板", str(ctx.exception))

    def test_claude_spec_carries_runtime_env(self) -> None:
        profile = self._add_profile(VENDOR_CLAUDE)
        project = self._add_project(profile)
        spec = self.workspace.terminal_launch_spec("claude", project.id)
        self.assertIn("claude", spec["command"].lower())
        # Claude 运行时环境变量由 profile 派生，必须随会话注入。
        self.assertTrue(spec["env"])
        self.assertIn("ANTHROPIC_BASE_URL", spec["env"])
        self.assertTrue(spec["title"].endswith("Claude"))

    def test_missing_project_dir_raises(self) -> None:
        profile = self._add_profile(VENDOR_CODEX)
        project = self._add_project(profile, create_dir=False)
        with self.assertRaises(WorkspaceError) as ctx:
            self.workspace.terminal_launch_spec("codex", project.id)
        self.assertIn("项目目录不存在", str(ctx.exception))

    def test_unknown_client_raises(self) -> None:
        profile = self._add_profile(VENDOR_CODEX)
        project = self._add_project(profile)
        with self.assertRaises(WorkspaceError):
            self.workspace.terminal_launch_spec("gemini", project.id)

    def test_no_project_raises(self) -> None:
        self._add_profile(VENDOR_CODEX)
        with self.assertRaises(WorkspaceError):
            self.workspace.terminal_launch_spec("codex", "")


if __name__ == "__main__":
    unittest.main()
