import os
import tkinter as tk
import unittest
from unittest.mock import patch

from helpers import workspace_tempdir

from codex_switch.models import (
    PROFILE_CATEGORY_IMAGE_GENERATION,
    PROFILE_CATEGORY_LABELS,
    Profile,
    SkillDefinition,
    SkillGroup,
)
from codex_switch.ui.app import CodexSwitchApp
from codex_switch.ui.dialogs import ProfileDialog, ProjectDialog
from codex_switch.ui.styles import BOOTSTRAP_THEME, BootstrapWindow


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
            self.root.update_idletasks()

            self.assertTrue(dialog.api_provided_var.get())
            self.assertTrue(all(widget.winfo_manager() == "grid" for widget in dialog.api_key_widgets))
            self.assertTrue(all(entry.instate(["!disabled"]) for entry in dialog.api_key_entries))
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
