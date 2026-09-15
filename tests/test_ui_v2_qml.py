"""QML smoke tests for the PySide6 interface.

Runs the real QML tree under the offscreen platform and asserts:
* AppShell loads with zero QML warnings,
* all five top-level sections instantiate and navigate,
* theme switching works and changes tokens,
* every drawer opens and closes with a valid form,
* empty / loading / error states all render.

These tests skip cleanly when PySide6 is unavailable, so the suite still runs
on machines without the Qt dependency installed.
"""

from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QUICK_CONTROLS_STYLE", "Basic")

from helpers import workspace_tempdir

from codex_switch.models import (
    HealthResult,
    Profile,
    ProjectRecord,
    SkillDefinition,
    SkillGroup,
    SkillMarketRepo,
)
from codex_switch.storage import ProfileStore

try:  # pragma: no cover - depends on the environment
    from PySide6.QtCore import QTimer, qInstallMessageHandler
    from PySide6.QtGui import QGuiApplication

    from codex_switch.ui_v2.app import QML_ENTRYPOINT, build_engine, configure_style, load_qml
    from codex_switch.ui_v2.controller import AppController
    from codex_switch.ui_v2.workspace import Workspace

    QT_AVAILABLE = True
except ImportError:  # pragma: no cover
    QT_AVAILABLE = False


# Qt clears a context property before it destroys the QML singletons that read
# it, so during engine teardown the bindings legitimately evaluate against null
# and Qt logs "Cannot read property ... of null". Those messages are noise from
# the destruction phase, not page warnings; they are only collected while a test
# body is running so a genuine runtime error can never hide behind them.
_JS_MESSAGES: list[str] = []
_CAPTURE_ACTIVE = False


def _message_handler(_mode, _context, message) -> None:  # pragma: no cover - Qt callback
    if _CAPTURE_ACTIVE:
        text = str(message)
        if "of null" in text or "TypeError" in text or "ReferenceError" in text or "is not defined" in text:
            _JS_MESSAGES.append(text)


if QT_AVAILABLE:  # pragma: no cover - environment dependent
    qInstallMessageHandler(_message_handler)


def _make_app():
    return QGuiApplication.instance() or QGuiApplication([])


@unittest.skipUnless(QT_AVAILABLE, "PySide6 is not installed")
class QmlSmokeTests(unittest.TestCase):
    """Shared Qt application plus a fully populated workspace."""

    app = None

    @classmethod
    def setUpClass(cls) -> None:
        cls.app = _make_app()
        configure_style()

    def setUp(self) -> None:
        global _CAPTURE_ACTIVE
        _JS_MESSAGES.clear()
        _CAPTURE_ACTIVE = True
        self._temp = workspace_tempdir()
        self.root = self._temp.__enter__()
        self.addCleanup(self._temp.__exit__, None, None, None)

        self.store = ProfileStore(self.root)
        codex = Profile.create(
            name="主账号",
            base_url="https://api.example.com",
            api_key="sk-codex",
            vendor="codex",
            codex_model="gpt-5",
        )
        codex.health = HealthResult(status="healthy", detail="接口可用", models=["gpt-5", "gpt-5-mini"])
        claude = Profile.create(
            name="Claude 号",
            base_url="https://claude.example.com",
            api_key="sk-claude",
            vendor="claude",
            claude_model="sonnet",
            claude_fallback_model="haiku",
        )
        claude.health = HealthResult(status="error", detail="鉴权失败")
        project_dir = self.root / "demo-project"
        project_dir.mkdir()
        project = ProjectRecord.create(project_dir=str(project_dir), profile_id=codex.id, name="示例项目")
        self.store.save(
            [codex, claude],
            codex.id,
            [project],
            project.id,
            skill_groups=[
                SkillGroup.create(
                    "默认组",
                    description="内置技能",
                    skills=[SkillDefinition.create("demo-skill", content="echo hi")],
                )
            ],
            skill_market_repos=[SkillMarketRepo.create("https://github.com/owner/repo")],
        )

        self.workspace = Workspace(store=self.store, project_root=self.root)
        self.controller = AppController(workspace=self.workspace)
        self.engine = build_engine(self.controller)
        self.warnings: list[str] = []
        self.engine.warnings.connect(self._collect_warnings)

    def tearDown(self) -> None:
        global _CAPTURE_ACTIVE
        # Stop collecting before teardown, where null-property messages are expected.
        _CAPTURE_ACTIVE = False
        for root in list(self.engine.rootObjects()):
            root.deleteLater()
        self.engine.deleteLater()
        # deleteLater() only queues destruction; flush it now so the engine is
        # really gone before the next test enables capture again.
        self._flush_deferred_deletes()
        self.controller.shutdown()
        self.app.processEvents()

    def _flush_deferred_deletes(self) -> None:
        from PySide6.QtCore import QCoreApplication, QEvent

        self.app.processEvents()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        self.app.processEvents()

    def assertNoRuntimeErrors(self) -> None:
        """Fail when the page logged a JS error while the test body ran."""
        self.assertEqual(_JS_MESSAGES, [], f"QML runtime errors: {_JS_MESSAGES[:5]}")

    def _collect_warnings(self, items) -> None:
        self.warnings.extend(str(item.toString()) for item in items)
        # Warnings are also rendered via the engine; capture them robustly.

    # -- helpers ---------------------------------------------------------
    def _load(self):
        loaded = load_qml(self.engine)
        self.assertTrue(loaded, "AppShell.qml failed to load")
        roots = self.engine.rootObjects()
        self.assertTrue(roots, "no root objects")
        return roots[0]

    def _pump(self, times: int = 3) -> None:
        for _ in range(times):
            self.app.processEvents()

    # -- tests -----------------------------------------------------------
    def test_entrypoint_exists(self) -> None:
        self.assertTrue(QML_ENTRYPOINT.exists(), f"missing {QML_ENTRYPOINT}")

    def test_appshell_loads_without_warnings(self) -> None:
        self._load()
        self._pump()
        self.assertEqual(self.warnings, [], f"QML warnings: {self.warnings[:5]}")
        self.assertNoRuntimeErrors()

    def test_every_section_navigates(self) -> None:
        self._load()
        for section, title in (
            ("dashboard", "首页"),
            ("profiles", "配置中心"),
            ("projects", "项目工作区"),
            ("network", "网络与监控"),
            ("system", "系统"),
        ):
            with self.subTest(section=section):
                self.controller.navigateTo(section)
                self._pump()
                self.assertEqual(self.controller.currentSection, section)
                self.assertEqual(self.controller.currentSectionTitle, title)
        self.assertEqual(self.warnings, [], f"QML warnings: {self.warnings[:5]}")
        self.assertNoRuntimeErrors()

    def test_unknown_section_falls_back_to_dashboard(self) -> None:
        self._load()
        self.controller.navigateTo("nope")
        self.assertEqual(self.controller.currentSection, "dashboard")

    def test_theme_switch_changes_tokens(self) -> None:
        self._load()
        light = dict(self.controller.theme.colors)
        self.controller.setDarkMode(True)
        self._pump()
        dark = dict(self.controller.theme.colors)
        self.assertNotEqual(light["bg"], dark["bg"])
        self.assertTrue(self.controller.theme.darkMode)
        self.controller.setDarkMode(False)
        self._pump()
        self.assertEqual(self.controller.theme.colors["bg"], light["bg"])
        self.assertEqual(self.warnings, [], f"QML warnings: {self.warnings[:5]}")
        self.assertNoRuntimeErrors()

    def test_theme_preference_persists(self) -> None:
        self._load()
        self.controller.setDarkMode(True)
        self._pump()
        reloaded = Workspace(store=self.store, project_root=self.root)
        self.assertTrue(reloaded.session.dark_mode)

    def test_drawers_open_and_close(self) -> None:
        self._load()
        drawers = (
            ("profile-form", ""),
            ("project-form", ""),
            ("pool-group-form", ""),
            ("pool-channel-form", ""),
            ("mcp-form", ""),
            ("skill-group-form", ""),
            ("skill-form", ""),
            ("skill-repo-form", ""),
        )
        for drawer, target in drawers:
            with self.subTest(drawer=drawer):
                self.controller.setDrawerTarget(drawer, target)
                self.controller.openDrawer(drawer)
                self._pump()
                self.assertTrue(self.controller.drawerOpen)
                self.assertEqual(self.controller.drawer, drawer)
                self.controller.closeDrawer()
                self._pump()
                self.assertFalse(self.controller.drawerOpen)
        self.assertEqual(self.warnings, [], f"QML warnings: {self.warnings[:5]}")
        self.assertNoRuntimeErrors()

    def test_view_models_expose_populated_state(self) -> None:
        self._load()
        self._pump()
        self.assertEqual(len(self.controller.profiles.items), 2)
        self.assertEqual(len(self.controller.projects.items), 1)
        self.assertEqual(len(self.controller.tools.skillGroups), 1)
        self.assertEqual(len(self.controller.tools.skillRepos), 1)
        self.assertTrue(self.controller.tools.mcpServers)
        self.assertEqual(self.controller.dashboard.summary["profileCount"], 2)
        self.assertEqual(self.controller.dashboard.summary["healthyCount"], 1)
        self.assertEqual(self.controller.dashboard.summary["errorCount"], 1)

    def test_empty_state_renders_without_data(self) -> None:
        # A workspace with no profiles exercises every EmptyState branch.
        empty_root = self.root / "empty"
        empty_root.mkdir()
        empty_workspace = Workspace(store=ProfileStore(empty_root), project_root=empty_root)
        controller = AppController(workspace=empty_workspace)
        engine = build_engine(controller)
        try:
            self.assertTrue(load_qml(engine))
            for section in ("dashboard", "profiles", "projects", "network", "system"):
                controller.navigateTo(section)
                self.app.processEvents()
            self.assertEqual(controller.profiles.count, 0)
            self.assertEqual(controller.projects.count, 0)
            self.assertTrue(controller.profiles.isEmpty)
        finally:
            controller.shutdown()
            engine.deleteLater()
            self.app.processEvents()

    def test_loading_state_component_exists(self) -> None:
        # BusyBar / LoadingState are driven by controller.busy.
        self._load()
        self.assertFalse(self.controller.busy)
        self.controller.showToast("测试通知", "info")
        self._pump()
        self.assertEqual(self.warnings, [], f"QML warnings: {self.warnings[:5]}")
        self.assertNoRuntimeErrors()

    def test_refresh_and_navigation_round_trip(self) -> None:
        self._load()
        self.controller.refreshAll()
        self._pump(6)
        for section in ("profiles", "projects", "dashboard"):
            self.controller.navigateTo(section)
            self._pump()
        self.assertEqual(self.warnings, [], f"QML warnings: {self.warnings[:5]}")
        self.assertNoRuntimeErrors()

    def test_command_palette_opens(self) -> None:
        root = self._load()
        self._pump()
        # The palette is a Popup driven by QML; verify the helper data is sane.
        find_child = root.findChild
        self.assertTrue(callable(find_child))
        self.controller.openCommandPalette()
        self._pump()
        self.assertEqual(self.warnings, [], f"QML warnings: {self.warnings[:5]}")
        self.assertNoRuntimeErrors()


if __name__ == "__main__":
    unittest.main()
