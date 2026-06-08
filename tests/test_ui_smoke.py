import os
import tkinter as tk
import unittest
from unittest.mock import patch

from helpers import workspace_tempdir

from codex_switch.models import (
    HealthResult,
    PROFILE_CATEGORY_IMAGE_GENERATION,
    PROFILE_CATEGORY_LABELS,
    Profile,
    SkillDefinition,
    SkillGroup,
    VENDOR_CODEX,
)
from codex_switch.ui.app import CodexSwitchApp
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

                    self.assertTrue(app.skill_repo_tree.winfo_exists())
                    self.assertTrue(app.skill_group_tree.winfo_exists())
                    self.assertTrue(app.skill_project_tree.winfo_exists())
                    self.assertTrue(app.hot_update_log_text.winfo_exists())
                    self.assertIn("热更新", app.hot_update_status_var.get())
                    self.assertTrue(app.store.storage_path.is_file())
        finally:
            destroy_widget(app_root)

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
