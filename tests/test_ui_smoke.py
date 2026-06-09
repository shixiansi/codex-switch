import os
import tkinter as tk
from tkinter import ttk
import unittest
from unittest.mock import patch

from helpers import workspace_tempdir

from codex_switch.models import (
    HealthResult,
    HotUpdateEvent,
    PROFILE_CATEGORY_IMAGE_GENERATION,
    PROFILE_CATEGORY_LABELS,
    Profile,
    ProjectRecord,
    SkillDefinition,
    SkillGroup,
    SkillMarketRepo,
    VENDOR_CODEX,
)
from codex_switch.skills import SkillSource
from codex_switch.storage import ProfileStore
from codex_switch.ui.app import CodexSwitchApp, SkillMarketEntry
from codex_switch.ui.dialogs import ProfileDialog, ProjectDialog
from codex_switch.ui.styles import BOOTSTRAP_THEME, BootstrapWindow, PALETTE


def make_hidden_root() -> tk.Tk:
    try:
        root = BootstrapWindow(themename=BOOTSTRAP_THEME) if BootstrapWindow is not None else tk.Tk()
    except tk.TclError as exc:
        raise unittest.SkipTest(f"Tk is not available: {exc}") from exc
    root.withdraw()
    return root


def destroy_widget(widget: tk.Misc) -> None:
    try:
        if widget.winfo_exists():
            try:
                widget.grab_release()
            except tk.TclError:
                pass
            widget.destroy()
    except tk.TclError:
        pass


def assert_widget_area_visible(testcase: unittest.TestCase, widget: tk.Misc) -> None:
    testcase.assertGreater(widget.winfo_width(), 1)
    testcase.assertGreater(widget.winfo_height(), 1)


def find_child_widget(widget: tk.Misc, widget_type):
    if isinstance(widget, widget_type):
        return widget
    for child in widget.winfo_children():
        found = find_child_widget(child, widget_type)
        if found is not None:
            return found
    return None


def collect_child_widgets(widget: tk.Misc, widget_type):
    widgets = []
    if isinstance(widget, widget_type):
        widgets.append(widget)
    for child in widget.winfo_children():
        widgets.extend(collect_child_widgets(child, widget_type))
    return widgets


def widget_texts(widget: tk.Misc) -> list[str]:
    texts: list[str] = []
    try:
        value = widget.cget("text")
    except tk.TclError:
        value = ""
    if value:
        texts.append(str(value))
    for child in widget.winfo_children():
        texts.extend(widget_texts(child))
    return texts


class TkSmokeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.root = make_hidden_root()

    @classmethod
    def tearDownClass(cls) -> None:
        destroy_widget(cls.root)

    def test_profile_dialog_image_generation_hides_api_fields_by_default(self) -> None:
        dialog: ProfileDialog | None = None
        try:
            profile = Profile.create(
                "image-profile",
                "https://image.example.com",
                "sk-image",
            )
            dialog = ProfileDialog(self.root, profile=profile)
            self.root.update_idletasks()

            dialog.category_var.set(PROFILE_CATEGORY_LABELS[PROFILE_CATEGORY_IMAGE_GENERATION])
            dialog._toggle_api_fields()
            self.root.update_idletasks()

            self.assertFalse(dialog.api_provided_var.get())
            self.assertTrue(dialog.api_provided_check.instate(["!disabled"]))
            self.assertTrue(all(variable.get() == "" for variable in dialog.api_key_vars))
            self.assertTrue(all(widget.winfo_manager() == "" for widget in dialog.api_key_widgets))
            self.assertTrue(all(entry.instate(["disabled"]) for entry in dialog.api_key_entries))

            dialog._on_submit()

            self.assertIsNotNone(dialog.result)
            self.assertEqual(dialog.result["category"], PROFILE_CATEGORY_IMAGE_GENERATION)
            self.assertFalse(dialog.result["api_provided"])
            self.assertEqual(dialog.result["base_url"], "")
            self.assertEqual(dialog.result["api_keys"], [])
        finally:
            if dialog is not None:
                destroy_widget(dialog)

    def test_profile_dialog_manual_image_api_enable_restores_api_fields(self) -> None:
        dialog: ProfileDialog | None = None
        try:
            dialog = ProfileDialog(self.root, profile=Profile.create("image-profile", "", ""))
            dialog.category_var.set(PROFILE_CATEGORY_LABELS[PROFILE_CATEGORY_IMAGE_GENERATION])
            dialog._toggle_api_fields()
            dialog.api_provided_var.set(True)
            dialog._toggle_api_fields()
            dialog.base_url_var.set("https://image.example.com")
            self.root.update_idletasks()

            self.assertTrue(dialog.api_provided_var.get())
            self.assertTrue(all(widget.winfo_manager() == "grid" for widget in dialog.api_key_widgets))
            self.assertTrue(all(entry.instate(["!disabled"]) for entry in dialog.api_key_entries))

            with patch("codex_switch.ui.dialogs.messagebox.showerror") as showerror:
                dialog._on_submit()

            self.assertIsNone(dialog.result)
            showerror.assert_called_once()
            self.assertIn("请输入 API Key", showerror.call_args.args[1])

            dialog.api_key_vars[0].set("sk-image")
            dialog._on_submit()

            self.assertIsNotNone(dialog.result)
            self.assertTrue(dialog.result["api_provided"])
            self.assertEqual(dialog.result["base_url"], "https://image.example.com")
            self.assertEqual(dialog.result["api_keys"], ["sk-image"])
        finally:
            if dialog is not None:
                destroy_widget(dialog)

    def test_project_dialog_expands_skill_groups_and_keeps_github_settings(self) -> None:
        dialog: ProjectDialog | None = None
        try:
            with workspace_tempdir() as temp_dir:
                profile = Profile.create("api", "https://api.example.com", "sk-api")
                skill = SkillDefinition.create("prompt-helper", content="Use short answers.")
                group = SkillGroup.create("coding", skills=[skill])
                dialog = ProjectDialog(
                    self.root,
                    profiles=[profile],
                    skill_groups=[group],
                    initial_project_dir=str(temp_dir),
                )
                dialog.name_var.set("demo")
                dialog.github_repo_var.set("https://github.com/example/project")
                dialog.github_ref_var.set("release/v1")
                dialog.github_auto_update_var.set(True)

                selected_group_ids, selected_skills, selected_skill_names = dialog._selected_project_skills()
                self.assertEqual(selected_group_ids, [group.id])
                self.assertEqual(selected_skills, [skill])
                self.assertEqual(selected_skill_names, ["prompt-helper"])

                dialog._on_submit()

                self.assertIsNotNone(dialog.result)
                self.assertEqual(dialog.result["github_repo"], "https://github.com/example/project")
                self.assertEqual(dialog.result["github_ref"], "release/v1")
                self.assertTrue(dialog.result["github_auto_update"])
                self.assertEqual(dialog.result["skill_group_ids"], [group.id])
                self.assertEqual(dialog.result["skills"], [skill])
        finally:
            if dialog is not None:
                destroy_widget(dialog)

    def test_app_hidden_init_builds_skills_and_hot_update_controls(self) -> None:
        app_root = tk.Toplevel(self.root)
        app_root.withdraw()
        try:
            with workspace_tempdir() as temp_dir:
                with patch.dict(os.environ, {"APPDATA": str(temp_dir / "appdata")}, clear=False):
                    app = CodexSwitchApp(app_root)
                    app_root.update_idletasks()

                    self.assertTrue(app.skill_market_canvas.winfo_exists())
                    self.assertTrue(app.skill_repo_tree.winfo_exists())
                    self.assertTrue(app.skill_group_tree.winfo_exists())
                    self.assertTrue(app.skill_project_tree.winfo_exists())
                    self.assertTrue(app.hot_update_log_text.winfo_exists())
                    self.assertIn("Skills 仓库源管理", widget_texts(app.skills_tab))
                    self.assertIn("仓库同步", app.hot_update_status_var.get())
                    settings_texts = widget_texts(app.settings_tab)
                    self.assertIn("版本信息 / 系统信息", settings_texts)
                    self.assertIn("应用版本", settings_texts)
                    self.assertIn("Python", settings_texts)
                    self.assertIn("配置库", settings_texts)
                    self.assertIn("平台", settings_texts)
                    self.assertTrue(app.store.storage_path.is_file())
        finally:
            destroy_widget(app_root)

    def test_app_hidden_init_syncs_project_skills_from_groups(self) -> None:
        app_root = tk.Toplevel(self.root)
        app_root.withdraw()
        try:
            with workspace_tempdir() as temp_dir:
                old_skill = SkillDefinition.create("python-helper", content="old")
                fresh_skill = SkillDefinition.create("python-helper", content="new")
                extra_skill = SkillDefinition.create("review-helper", content="review")
                group = SkillGroup.create("coding", skills=[fresh_skill, extra_skill])
                profile = Profile.create("api", "https://api.example.com", "sk-api")
                project = ProjectRecord.create(
                    str(temp_dir),
                    profile.id,
                    skill_group_ids=[group.id],
                    skills=[old_skill],
                    skill_names=[old_skill.name],
                )

                with patch.dict(os.environ, {"APPDATA": str(temp_dir / "appdata")}, clear=False):
                    store = ProfileStore()
                    store.save(
                        [profile],
                        profile.id,
                        projects=[project],
                        selected_project_id=project.id,
                        skill_groups=[group],
                    )

                    app = CodexSwitchApp(app_root)
                    app_root.update_idletasks()

                    synced_project = app.projects[0]
                    self.assertEqual([skill.name for skill in synced_project.skills], ["python-helper", "review-helper"])
                    self.assertEqual([skill.content for skill in synced_project.skills], ["new", "review"])
                    self.assertEqual(synced_project.skill_names, ["python-helper", "review-helper"])

                    loaded_project = app.store.load()[2][0]
                    self.assertEqual([skill.content for skill in loaded_project.skills], ["new", "review"])
                    self.assertEqual(loaded_project.skill_names, ["python-helper", "review-helper"])
        finally:
            destroy_widget(app_root)

    def test_skill_market_cards_show_skill_author_install_and_wrap(self) -> None:
        frame = tk.Frame(self.root)
        canvas = tk.Canvas(self.root, width=560, height=260)
        window_id = canvas.create_window((0, 0), window=frame, anchor="nw")
        installed: list[str] = []
        try:
            with workspace_tempdir() as temp_dir:
                entries = [
                    SkillMarketEntry(
                        repo_id="repo-1",
                        repo_url="https://github.com/alpha/skills",
                        author="alpha",
                        source=SkillSource("prompt-helper", "Prompt Helper", temp_dir / "prompt-helper"),
                    ),
                    SkillMarketEntry(
                        repo_id="repo-1",
                        repo_url="https://github.com/alpha/skills",
                        author="alpha",
                        source=SkillSource("review-helper", "Review Helper", temp_dir / "review-helper"),
                    ),
                    SkillMarketEntry(
                        repo_id="repo-2",
                        repo_url="https://github.com/beta/skills",
                        author="beta",
                        source=SkillSource("test-helper", "Test Helper", temp_dir / "test-helper"),
                    ),
                ]
                app = CodexSwitchApp.__new__(CodexSwitchApp)
                app.section_font = ("Segoe UI", 10, "bold")
                app.small_font = ("Segoe UI", 9)
                app.body_font = ("Segoe UI", 10)
                app.skill_market_frame = frame
                app.skill_market_canvas = canvas
                app.skill_market_window = window_id
                app.install_skill_market_entry_to_group = lambda entry: installed.append(entry.source.name)

                app._render_skill_market_cards(entries)
                app._layout_skill_market_cards(type("Event", (), {"width": 560})())
                self.root.update_idletasks()

                cards = frame.winfo_children()
                self.assertEqual(len(cards), 3)
                self.assertIn("Prompt Helper", widget_texts(cards[0]))
                self.assertIn("作者：alpha", widget_texts(cards[0]))
                self.assertIn("https://github.com/alpha/skills", widget_texts(cards[0]))

                positions = [
                    (int(card.grid_info()["row"]), int(card.grid_info()["column"]))
                    for card in cards
                ]
                self.assertEqual(positions, [(0, 0), (0, 1), (1, 0)])

                install_buttons = [
                    button
                    for card in cards
                    for button in collect_child_widgets(card, ttk.Button)
                    if button.cget("text") == "安装"
                ]
                self.assertEqual(len(install_buttons), 3)
                install_buttons[1].invoke()
                self.assertEqual(installed, ["review-helper"])
        finally:
            destroy_widget(frame)
            destroy_widget(canvas)

    def test_skill_group_dialog_cards_target_specific_skill_actions_and_wrap(self) -> None:
        cards_frame = tk.Frame(self.root)
        edited: list[str] = []
        deleted: list[str] = []
        try:
            first_skill = SkillDefinition.create("prompt-helper", content="prompt")
            second_skill = SkillDefinition.create("review-helper", content="review")
            group = SkillGroup.create("coding", skills=[first_skill, second_skill])
            app = CodexSwitchApp.__new__(CodexSwitchApp)
            app.section_font = ("Segoe UI", 10, "bold")
            app.small_font = ("Segoe UI", 9)
            app.body_font = ("Segoe UI", 10)
            app.skill_groups = [group]
            app._skill_group_by_id = lambda group_id: group if group_id == group.id else None
            app.edit_skill_in_group = lambda selected_group, skill: edited.append(f"{selected_group.id}:{skill.name}")
            app.delete_skill_from_group = lambda selected_group, skill: deleted.append(f"{selected_group.id}:{skill.name}")

            app._render_skill_group_dialog_cards(group, cards_frame)
            self.root.update_idletasks()

            cards = cards_frame.winfo_children()
            self.assertEqual(len(cards), 2)
            self.assertIn("prompt-helper", widget_texts(cards[0]))
            self.assertIn("review-helper", widget_texts(cards[1]))

            class CanvasProbe:
                def __init__(self) -> None:
                    self.width = None

                def itemconfigure(self, _window_id, **kwargs) -> None:
                    self.width = kwargs.get("width")

            canvas_probe = CanvasProbe()
            app._layout_skill_group_dialog_cards(cards_frame, 520, 1, canvas_probe)
            self.assertEqual(canvas_probe.width, 520)
            positions = [
                (int(card.grid_info()["row"]), int(card.grid_info()["column"]))
                for card in cards
            ]
            self.assertEqual(positions, [(0, 0), (0, 1)])

            first_edit = next(
                button
                for button in collect_child_widgets(cards[0], ttk.Button)
                if button.cget("text") == "编辑"
            )
            first_edit.invoke()
            self.assertEqual(edited, [f"{group.id}:prompt-helper"])

            cards = cards_frame.winfo_children()
            second_delete = next(
                button
                for button in collect_child_widgets(cards[1], ttk.Button)
                if button.cget("text") == "删除"
            )
            second_delete.invoke()
            self.assertEqual(deleted, [f"{group.id}:review-helper"])
        finally:
            destroy_widget(cards_frame)

    def test_app_library_model_tags_render_stats_wrap_and_select(self) -> None:
        app_root = tk.Toplevel(self.root)
        app_root.withdraw()
        try:
            with workspace_tempdir() as temp_dir:
                models = (
                    [f"gpt-model-{index}" for index in range(8)]
                    + [f"claude-sonnet-{index}" for index in range(7)]
                    + [f"gemini-model-{index}" for index in range(6)]
                    + [f"local-model-{index}" for index in range(4)]
                )
                profile = Profile.create(
                    "model-api",
                    "https://api.example.com",
                    "sk-model",
                    vendor=VENDOR_CODEX,
                    codex_model="gpt-old",
                )
                profile.health = HealthResult(status="healthy", models=models)

                with patch.dict(os.environ, {"APPDATA": str(temp_dir / "appdata")}, clear=False):
                    app = CodexSwitchApp(app_root)
                    app.profiles = [profile]
                    app.selected_profile_id = profile.id
                    app.refresh_library_tab()
                    app_root.update_idletasks()

                    self.assertEqual(app.library_model_tag_models, models[:20])
                    self.assertEqual(len(app.library_model_tag_widgets), 20)
                    for _model, tag in app.library_model_tag_widgets:
                        self.assertEqual(int(tag.cget("width")), 172)
                        self.assertEqual(int(tag.cget("height")), 34)
                        self.assertEqual(tag.cget("cursor"), "hand2")

                    summary = app.library_models_summary_var.get()
                    self.assertIn("共 25 个模型", summary)
                    self.assertIn("隐藏 5 个", summary)
                    self.assertIn("OpenAI 8", summary)
                    self.assertIn("Anthropic 7", summary)
                    self.assertIn("Google 6", summary)
                    self.assertIn("其他 4", summary)

                    app._layout_library_model_tags(560)
                    wide_positions = [
                        (int(tag.grid_info()["row"]), int(tag.grid_info()["column"]))
                        for _model, tag in app.library_model_tag_widgets[:4]
                    ]
                    self.assertEqual(wide_positions, [(0, 0), (0, 1), (0, 2), (1, 0)])

                    app._layout_library_model_tags(190)
                    narrow_positions = [
                        (int(tag.grid_info()["row"]), int(tag.grid_info()["column"]))
                        for _model, tag in app.library_model_tag_widgets[:3]
                    ]
                    self.assertEqual(narrow_positions, [(0, 0), (1, 0), (2, 0)])

                    self.assertEqual(app.library_model_stats_text.winfo_manager(), "")
                    app._toggle_library_model_stats()
                    self.assertTrue(app.library_model_stats_expanded)
                    self.assertEqual(app.library_model_stats_button_var.get(), "收起统计")
                    self.assertEqual(app.library_model_stats_text.winfo_manager(), "grid")
                    stats_text = app.library_model_stats_text.get("1.0", "end")
                    self.assertIn("OpenAI（8）", stats_text)
                    self.assertIn("Anthropic（7）", stats_text)
                    self.assertIn("Google（6）", stats_text)
                    self.assertIn("其他（4）", stats_text)
                    self.assertIn("local-model-3", stats_text)

                    selected_model, selected_tag = app.library_model_tag_widgets[3]
                    selected_tag.event_generate("<Button-1>")
                    app_root.update()

                    updated_profile = app.get_selected_profile()
                    self.assertIsNotNone(updated_profile)
                    self.assertEqual(updated_profile.codex_model, selected_model)
                    self.assertEqual(updated_profile.model, selected_model)
                    self.assertEqual(app.status_var.get(), f"已选择模型：{selected_model}")

                    selected_canvas = next(
                        tag for model, tag in app.library_model_tag_widgets if model == selected_model
                    )
                    unselected_canvas = next(
                        tag for model, tag in app.library_model_tag_widgets if model != selected_model
                    )
                    selected_rect = selected_canvas.find_all()[0]
                    unselected_rect = unselected_canvas.find_all()[0]
                    self.assertEqual(selected_canvas.itemcget(selected_rect, "fill"), PALETTE["selection_bg"])
                    self.assertEqual(selected_canvas.itemcget(selected_rect, "outline"), PALETTE["accent"])
                    self.assertEqual(unselected_canvas.itemcget(unselected_rect, "fill"), PALETTE["neutral_soft"])
                    self.assertEqual(unselected_canvas.itemcget(unselected_rect, "outline"), PALETTE["card_border"])
        finally:
            destroy_widget(app_root)

    def test_app_visible_gui_capture_and_mouse_smoke(self) -> None:
        if os.environ.get("CODEX_SWITCH_RUN_VISIBLE_GUI") != "1":
            self.skipTest("set CODEX_SWITCH_RUN_VISIBLE_GUI=1 to run visible GUI capture smoke")
        try:
            from PIL import ImageGrab, ImageStat
        except ImportError as exc:
            self.skipTest(f"Pillow ImageGrab is not available: {exc}")

        app_root = tk.Toplevel(self.root)
        app_root.geometry("1360x900+20+20")
        app_root.deiconify()
        try:
            with workspace_tempdir() as temp_dir:
                models = (
                    [f"gpt-visual-{index}" for index in range(6)]
                    + [f"claude-visual-{index}" for index in range(4)]
                    + [f"gemini-visual-{index}" for index in range(3)]
                    + ["local-visual"]
                )
                profile = Profile.create(
                    "visible-api",
                    "https://api.example.com",
                    "sk-visible",
                    vendor=VENDOR_CODEX,
                    codex_model="gpt-visual-old",
                )
                profile.health = HealthResult(status="healthy", detail="ok", models=models)
                skill = SkillDefinition.create("visible-helper", content="visible content")
                group = SkillGroup.create("visible-group", skills=[skill])
                project = ProjectRecord.create(
                    str(temp_dir),
                    profile.id,
                    name="visible-project",
                    skill_group_ids=[group.id],
                    skills=[skill],
                    skill_names=[skill.name],
                    github_repo="https://github.com/example/project",
                    github_ref="main",
                    github_last_sync_commit="abc123def456",
                    github_auto_update=True,
                )
                repo = SkillMarketRepo.create(
                    "https://github.com/example/skills",
                    branch="main",
                    last_sync_commit="fedcba987654",
                    auto_update=True,
                    installed_group_id=group.id,
                )
                event = HotUpdateEvent.create(
                    scope="project",
                    target=project.name,
                    status="updated",
                    detail="visible smoke",
                    commit="abc123def456",
                )

                with patch.dict(os.environ, {"APPDATA": str(temp_dir / "appdata")}, clear=False):
                    app = CodexSwitchApp(app_root)
                    app.profiles = [profile]
                    app.selected_profile_id = profile.id
                    app.skill_groups = [group]
                    app.skill_market_repos = [repo]
                    app.projects = [project]
                    app.selected_project_id = project.id
                    app.hot_update_events = [event]
                    app.refresh_all()
                    app._show_tab("library")
                    app_root.lift()
                    app_root.focus_force()
                    app_root.update()

                    assert_widget_area_visible(self, app_root)
                    assert_widget_area_visible(self, app.profile_tree)
                    assert_widget_area_visible(self, app.library_models_canvas)
                    assert_widget_area_visible(self, app.library_model_tag_widgets[0][1])

                    selected_model, selected_tag = app.library_model_tag_widgets[2]
                    selected_tag.event_generate("<Button-1>", x=86, y=17)
                    app_root.update()
                    self.assertEqual(app.get_selected_profile().codex_model, selected_model)
                    self.assertEqual(app.status_var.get(), f"已选择模型：{selected_model}")

                    app._show_tab("skills")
                    app_root.update()
                    skills_notebook = find_child_widget(app.skills_tab, ttk.Notebook)
                    self.assertIsNotNone(skills_notebook)
                    skills_notebook.select(0)
                    app_root.update()
                    assert_widget_area_visible(self, app.skill_market_canvas)
                    assert_widget_area_visible(self, app.skill_repo_tree)
                    self.assertEqual(len(app.skill_repo_tree.get_children()), 1)
                    skills_notebook.select(1)
                    app_root.update()
                    assert_widget_area_visible(self, app.skill_group_tree)
                    skills_notebook.select(2)
                    app_root.update()
                    assert_widget_area_visible(self, app.skill_project_tree)
                    self.assertEqual(len(app.skill_group_tree.get_children()), 1)
                    self.assertEqual(len(app.skill_project_tree.get_children()), 1)

                    app._show_tab("settings")
                    app_root.update()
                    assert_widget_area_visible(self, app.hot_update_log_text)
                    self.assertIn("visible smoke", app.hot_update_log_text.get("1.0", "end"))

                    x = app_root.winfo_rootx()
                    y = app_root.winfo_rooty()
                    width = app_root.winfo_width()
                    height = app_root.winfo_height()
                    try:
                        image = ImageGrab.grab(bbox=(x, y, x + width, y + height))
                    except OSError as exc:
                        self.skipTest(f"screen capture is not available: {exc}")
                    self.assertGreaterEqual(image.width, 1180)
                    self.assertGreaterEqual(image.height, 780)
                    stats = ImageStat.Stat(image.convert("RGB"))
                    self.assertGreater(max(stats.stddev), 1.0)
        finally:
            destroy_widget(app_root)
