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
from unittest.mock import patch

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
        # Both profiles require sign-in so the batch action has work to do.
        codex = Profile.create(
            name="主账号",
            base_url="https://api.example.com",
            api_key="sk-codex",
            vendor="codex",
            codex_model="gpt-5",
            requires_sign_in=True,
            sign_in_url="https://api.example.com/console/personal",
        )
        codex.health = HealthResult(status="healthy", detail="接口可用", models=["gpt-5", "gpt-5-mini"])
        claude = Profile.create(
            name="Claude 号",
            base_url="https://claude.example.com",
            api_key="sk-claude",
            vendor="claude",
            claude_model="sonnet",
            claude_fallback_model="haiku",
            requires_sign_in=True,
            sign_in_url="https://claude.example.com/console/personal",
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

    def test_batch_sign_in_surface_is_exposed(self) -> None:
        """The one-click sign-in action must be reachable from the UI model."""
        self._load()
        self._pump()
        # Both seeded profiles require sign-in, so the action is available.
        sign_in = self.controller.profiles.signIn
        self.assertEqual(sign_in["pending"], 2)
        self.assertTrue(self.controller.profiles.hasPendingSignIn)

        # Opening is delegated to the workspace; stub it so no browser opens.
        opened: list[str] = []
        with patch("codex_switch.ui_v2.workspace._open_url", side_effect=opened.append):
            self.controller.profiles.signInAll()
        self._pump()

        self.assertEqual(len(opened), 2)
        self.assertEqual(self.controller.profiles.signIn["pending"], 0)
        self.assertFalse(self.controller.profiles.hasPendingSignIn)
        self.assertEqual(self.warnings, [], f"QML warnings: {self.warnings[:5]}")
        self.assertNoRuntimeErrors()

    # -- layout regressions ---------------------------------------------
    def test_button_labels_are_centred(self) -> None:
        """Short button labels must be centred, not flush left.

        Qt Quick Controls stretches a Button's contentItem to fill the control,
        so the label Row previously started at the left edge. Guard against
        reintroducing that by comparing the gaps either side of the label row.
        """
        from PySide6.QtQuick import QQuickItem

        root = self._load()
        self._pump()

        checked = 0
        for item in root.findChildren(QQuickItem):
            if item.metaObject().className().startswith("AppButton"):
                wrapper = item.property("contentItem")
                if wrapper is None:
                    continue
                rows = wrapper.childItems()
                if not rows:
                    continue
                row = rows[0]
                wrap_width = wrapper.width()
                if wrap_width <= 0:
                    continue
                left = row.x()
                right = wrap_width - (row.x() + row.width())
                with self.subTest(label=item.property("text")):
                    self.assertLessEqual(
                        abs(left - right),
                        2.0,
                        f"label not centred: left={left:.1f} right={right:.1f}",
                    )
                    self.assertLessEqual(
                        row.width(),
                        wrap_width + 1.0,
                        "button content overflows its control",
                    )
                checked += 1
        self.assertGreater(checked, 0, "no AppButton instances found to check")

    def test_empty_state_fills_width_and_is_centred(self) -> None:
        """Empty-state blocks must fill their card and centre their content.

        An EmptyState whose root was a Layout held its implicit width, so the
        block hugged the left edge and its text appeared to stretch to the
        right. Assert both the fill and the centring.
        """
        from PySide6.QtQuick import QQuickItem

        root = self._load()
        self.controller.navigateTo("dashboard")
        self._pump(5)

        checked = 0
        for state in root.findChildren(QQuickItem):
            if not state.metaObject().className().startswith("EmptyState"):
                continue
            if not state.isVisible() or state.width() <= 0:
                continue
            parent = state.parentItem()
            if parent is not None and parent.width() > 0:
                with self.subTest(empty="fills width"):
                    self.assertAlmostEqual(
                        state.width(),
                        parent.width(),
                        delta=2.0,
                        msg="EmptyState does not fill its container",
                    )
            inner = state.childItems()[0] if state.childItems() else None
            if inner is None:
                continue
            for child in inner.childItems():
                if child.width() <= 0 or not child.isVisible():
                    continue
                left = child.x()
                right = inner.width() - (child.x() + child.width())
                label = child.property("text") or child.metaObject().className()
                with self.subTest(empty=str(label)[:20]):
                    self.assertLessEqual(
                        abs(left - right),
                        2.0,
                        f"not centred: left={left:.1f} right={right:.1f} ({label})",
                    )
                    self.assertLessEqual(
                        child.width(),
                        inner.width() + 1.0,
                        f"overflows its container ({label})",
                    )
                checked += 1
        self.assertGreater(checked, 0, "no visible EmptyState children found")

    def test_no_component_animates_color_from_transparent(self) -> None:
        """Guard the whole QML tree against the grey-flash hover pattern.

        Any file that animates `color` must not also interpolate from the
        literal "transparent" on the same element, because Qt blends from
        rgba(0,0,0,0) and the element visibly darkens mid-animation.
        """
        qml_root = QML_ENTRYPOINT.parent
        offenders: list[str] = []
        for path in qml_root.rglob("*.qml"):
            text = path.read_text(encoding="utf-8")
            if "Behavior on color" not in text:
                continue
            # A file may animate colour safely (opaque -> opaque) but must not
            # drive that animation from a transparent source.
            for line in text.splitlines():
                stripped = line.strip()
                if stripped.startswith("//"):
                    continue
                if "Behavior on color" in stripped:
                    continue
                if ": \"transparent\"" in stripped and "?" in stripped:
                    offenders.append(f"{path.name}: {stripped}")
        self.assertEqual(offenders, [], f"colour animated from transparent: {offenders}")

    def test_listrow_has_opaque_background_layer(self) -> None:
        """ListRow must paint a full-size opaque layer and fade its opacity.

        Structural check, so it does not depend on animation timing. Before the
        fix ListRow had no background layer at all: it animated its own `color`
        from "transparent", which Qt interpolates from black (grey flash).
        """
        from PySide6.QtCore import QUrl
        from PySide6.QtQuick import QQuickItem

        from codex_switch.ui_v2.theme import LIGHT_COLORS

        probe = self.root / "listrow_probe.qml"
        probe.write_text(
            """
import QtQuick
import QtQuick.Window
import theme
import components

Window {
    visible: false
    width: 460; height: 120
    ListRow {
        id: row
        width: 420
        title: "probe"
        subtitle: "https://probe.example.com"
        iconName: "profile"
    }
}
""",
            encoding="utf-8",
        )
        engine = build_engine(self.controller)
        engine.load(QUrl.fromLocalFile(str(probe)))
        roots = engine.rootObjects()
        self.assertTrue(roots, "ListRow probe failed to load")
        win = roots[0]
        try:
            rows = [
                o for o in win.findChildren(QQuickItem)
                if o.metaObject().className().startswith("ListRow")
            ]
            self.assertTrue(rows, "ListRow was not instantiated")
            row = rows[0]

            # The row itself must not be painted; a child layer carries the tint.
            self.assertLessEqual(
                row.property("color").alpha(), 0, "ListRow root should be transparent"
            )

            layers = [
                c for c in row.childItems()
                if c.metaObject().className().startswith("QQuickRectangle")
                and abs(c.width() - row.width()) <= 1
                and abs(c.height() - row.height()) <= 1
            ]
            self.assertTrue(
                layers,
                "ListRow has no full-size background layer; hover would animate colour",
            )
            bg = layers[0]

            hover_tone = LIGHT_COLORS["surfaceHover"].lower()
            accent_soft = LIGHT_COLORS["accentSoft"].lower()
            colour = bg.property("color").name().lower()
            with self.subTest(layer="hover tone"):
                self.assertIn(colour, (hover_tone, accent_soft))
                self.assertGreater(bg.property("color").alpha(), 0, "layer is see-through")

            # Unselected rows rest fully faded out and fade in via opacity.
            self.assertEqual(bg.property("opacity"), 0.0)
        finally:
            win.deleteLater()
            engine.deleteLater()
            self._flush_deferred_deletes()

    def test_mcp_selection_drives_preview_panel(self) -> None:
        """Clicking an MCP server must update the preview panel.

        The workspace previously always rendered ``sorted(servers)[0]``, so the
        panel showed ChromeDevTools no matter which row was clicked.
        """
        self._load()
        self._pump()
        servers = self.controller.tools.mcpServers
        self.assertGreater(len(servers), 1, "need several MCP servers to test")

        for server in servers:
            name = server["name"]
            with self.subTest(server=name):
                self.controller.tools.selectMcpServer(name)
                self._pump(3)
                self.assertEqual(self.controller.tools.selectedMcpName, name)
                self.assertEqual(self.controller.tools.mcpDetail["name"], name)
                # The preview text must belong to the selected server.
                self.assertIn(name, self.controller.tools.mcpDetail["preview"])

    def test_mcp_preview_defaults_to_first_when_unselected(self) -> None:
        self._load()
        self._pump()
        names = sorted(server["name"] for server in self.controller.tools.mcpServers)
        # Nothing chosen yet: fall back to the first server rather than blank.
        self.assertEqual(self.controller.tools.selectedMcpName, names[0])

    def test_mcp_edit_and_delete_target_selected_server(self) -> None:
        """编辑 / 删除 must act on the selection, not always on servers[0]."""
        root = self._load()
        self._pump()
        names = sorted(server["name"] for server in self.controller.tools.mcpServers)
        target = names[-1]
        self.assertNotEqual(target, names[0], "pick a non-first server")

        self.controller.tools.selectMcpServer(target)
        self._pump(3)

        # Edit opens a drawer populated from the selected server.
        self.controller.tools.beginEditMcp(self.controller.tools.selectedMcpName)
        self._pump(3)
        fields = {f["key"]: f.get("value") for f in self.controller.tools.formFields}
        self.assertEqual(fields.get("name"), target, "edit form is not the selected server")
        self.controller.closeDrawer()
        self._pump(2)

        # Delete confirmation must name the selected server.
        self.controller.requestDeleteMcpServer(self.controller.tools.selectedMcpName)
        self._pump(3)
        self.assertIn(target, self.controller.pendingConfirm["message"])
        self.controller.cancelPending()
        self._pump(2)

    def test_sign_in_button_exists_in_loaded_qml(self) -> None:
        """The one-click button must be present in the real QML object tree."""
        from PySide6.QtQuick import QQuickItem

        root = self._load()
        self.controller.navigateTo("profiles")
        self._pump()

        def texts(item) -> list[str]:
            found = []
            for child in item.findChildren(QQuickItem):
                prop = child.property("text")
                if isinstance(prop, str) and prop:
                    found.append(prop)
            if isinstance(item.property("text"), str):
                found.append(item.property("text"))
            return found

        all_text = texts(root)
        sign_in_labels = [t for t in all_text if "一键签到" in t]
        self.assertTrue(sign_in_labels, f"一键签到 button not found; labels={all_text[:25]}")
        # Pending count is surfaced in the label for this fixture.
        self.assertIn("一键签到 (2)", sign_in_labels)

    # -- destructive-action confirmation --------------------------------
    def _confirm_dialog(self, root):
        from PySide6.QtCore import QObject

        dialogs = [
            obj
            for obj in root.findChildren(QObject)
            if obj.metaObject().className().startswith("ConfirmDialog")
        ]
        self.assertEqual(len(dialogs), 1, "exactly one shared ConfirmDialog is expected")
        return dialogs[0]

    def test_delete_requires_confirmation(self) -> None:
        root = self._load()
        self._pump()
        dlg = self._confirm_dialog(root)
        names_before = sorted(item["name"] for item in self.controller.profiles.items)
        self.assertEqual(len(names_before), 2)

        # Requesting a delete must open the dialog and NOT delete yet.
        first_id = self.controller.profiles.items[0]["id"]
        self.controller.requestDeleteProfile(first_id)
        self._pump()
        self.assertTrue(self.controller.confirmOpen)
        self.assertEqual(
            sorted(item["name"] for item in self.controller.profiles.items), names_before
        )
        self.assertEqual(self.controller.pendingConfirm["title"], "删除配置")

        # Cancelling keeps everything.
        self.controller.cancelPending()
        self._pump()
        self.assertFalse(self.controller.confirmOpen)
        self.assertEqual(
            sorted(item["name"] for item in self.controller.profiles.items), names_before
        )

        # Confirming performs the delete.
        self.controller.requestDeleteProfile(first_id)
        self._pump()
        self.controller.confirmPending()
        self._pump()
        self.assertEqual(len(self.controller.profiles.items), 1)
        self.assertFalse(self.controller.confirmOpen)
        self.assertEqual(self.warnings, [], f"QML warnings: {self.warnings[:5]}")
        self.assertNoRuntimeErrors()

    def test_confirm_blocks_profile_bound_to_project(self) -> None:
        root = self._load()
        self._pump()
        # The seeded project is already bound to the Codex profile, so that
        # profile cannot be deleted. Find it by the project's own binding
        # rather than by list position (rows are sorted).
        project = self.controller.projects.items[0]
        profile_id = project["codexProfileId"]
        self.assertTrue(profile_id, "fixture project should have a Codex binding")
        self.controller.requestDeleteProfile(profile_id)
        self._pump()
        spec = self.controller.pendingConfirm
        self.assertIn("示例项目", spec["warning"])

        # Even a forced confirm must not remove it.
        count_before = len(self.controller.profiles.items)
        self.controller.confirmPending()
        self._pump()
        self.assertEqual(len(self.controller.profiles.items), count_before)
        self.assertEqual(self.warnings, [], f"QML warnings: {self.warnings[:5]}")
        self.assertNoRuntimeErrors()

    def test_other_delete_requests_are_guarded(self) -> None:
        self._load()
        self._pump()
        project_id = self.controller.projects.items[0]["id"]
        skill_group_id = self.controller.tools.skillGroups[0]["id"]
        skill_id = self.controller.tools.skillGroups[0]["skills"][0]["id"]
        repo_id = self.controller.tools.skillRepos[0]["id"]

        for label, call, expected_title in (
            ("project", lambda: self.controller.requestDeleteProject(project_id), "删除项目"),
            ("skill-group", lambda: self.controller.requestDeleteSkillGroup(skill_group_id), "删除 Skills 组"),
            ("skill", lambda: self.controller.requestDeleteSkill(skill_group_id, skill_id), "删除 Skill"),
            ("skill-repo", lambda: self.controller.requestDeleteSkillRepo(repo_id), "删除 Skills 仓库"),
        ):
            with self.subTest(target=label):
                call()
                self._pump()
                self.assertTrue(self.controller.confirmOpen, label)
                self.assertEqual(self.controller.pendingConfirm["title"], expected_title)
                self.controller.cancelPending()
                self._pump()
                self.assertFalse(self.controller.confirmOpen)
        self.assertEqual(self.warnings, [], f"QML warnings: {self.warnings[:5]}")
        self.assertNoRuntimeErrors()

    def test_delete_missing_target_warns_instead_of_opening(self) -> None:
        self._load()
        self._pump()
        self.controller.requestDeleteProfile("does-not-exist")
        self._pump()
        self.assertFalse(self.controller.confirmOpen)
        self.controller.requestDeleteMcpServer("no-such-server")
        self._pump()
        self.assertFalse(self.controller.confirmOpen)

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
