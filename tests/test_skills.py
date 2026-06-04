from __future__ import annotations

from pathlib import Path
import unittest

from helpers import workspace_tempdir

from codex_switch.skills import (
    PROJECT_SKILLS_RELATIVE_DIR,
    SKILL_MANAGED_MARKER,
    SkillSource,
    discover_skill_sources,
    skill_selection_summary,
    sync_project_skills,
)


class SkillSourceTests(unittest.TestCase):
    def test_discover_skill_sources_filters_sorts_and_disambiguates_names(self) -> None:
        with workspace_tempdir() as temp_dir:
            first_root = temp_dir / "codex-skills"
            second_root = temp_dir / "agent-skills"
            (first_root / "foo").mkdir(parents=True)
            (first_root / "foo" / "SKILL.md").write_text("---\nname: foo\n---\n", encoding="utf-8")
            (first_root / "ignored").mkdir()
            (second_root / "pack" / "foo").mkdir(parents=True)
            (second_root / "pack" / "foo" / "SKILL.md").write_text("---\nname: foo\n---\n", encoding="utf-8")
            (second_root / "bar").mkdir()
            (second_root / "bar" / "SKILL.md").write_text("---\nname: bar\n---\n", encoding="utf-8")

            sources = discover_skill_sources([first_root, second_root, temp_dir / "missing"])

            self.assertEqual([source.name for source in sources], ["bar", "foo", "pack__foo"])
            self.assertEqual([source.display_name for source in sources], ["bar", "foo (foo)", "foo (pack/foo)"])
            self.assertEqual([source.source_path.name for source in sources], ["bar", "foo", "foo"])

    def test_skill_selection_summary_defaults_to_all_available_skills(self) -> None:
        sources = [
            SkillSource("frontend-dev", "frontend-dev", Path(__file__)),
            SkillSource("fullstack-dev", "fullstack-dev", Path(__file__)),
        ]

        self.assertEqual(skill_selection_summary(sources, None), "2 个技能：frontend-dev, fullstack-dev")
        self.assertEqual(skill_selection_summary(sources, ["fullstack-dev"]), "1 个技能：fullstack-dev")
        self.assertEqual(skill_selection_summary(sources, []), "未启用")

    def test_sync_project_skills_copies_selected_sources_and_skips_missing_sources(self) -> None:
        with workspace_tempdir() as temp_dir:
            source_root = temp_dir / "sources"
            alpha = source_root / "alpha"
            alpha.mkdir(parents=True)
            (alpha / "SKILL.md").write_text("alpha", encoding="utf-8")
            (alpha / "assets").mkdir()
            (alpha / "assets" / "note.txt").write_text("asset", encoding="utf-8")
            beta = source_root / "beta"
            beta.mkdir()
            (beta / "SKILL.md").write_text("beta", encoding="utf-8")
            project_root = temp_dir / "project"
            backup_dir = project_root / ".codex" / "template-backups" / "backup"

            generated = sync_project_skills(
                project_root,
                [
                    SkillSource("alpha", "alpha", alpha),
                    SkillSource("beta", "beta", beta),
                    SkillSource("missing", "missing", source_root / "missing"),
                ],
                ["alpha", "missing"],
                backup_dir=backup_dir,
            )

            target = project_root / PROJECT_SKILLS_RELATIVE_DIR / "alpha"
            self.assertEqual(generated, [target])
            self.assertEqual((target / "SKILL.md").read_text(encoding="utf-8"), "alpha")
            self.assertEqual((target / "assets" / "note.txt").read_text(encoding="utf-8"), "asset")
            self.assertTrue((target / SKILL_MANAGED_MARKER).exists())
            self.assertFalse((project_root / PROJECT_SKILLS_RELATIVE_DIR / "beta").exists())
            self.assertFalse((project_root / PROJECT_SKILLS_RELATIVE_DIR / "missing").exists())

    def test_sync_project_skills_removes_unselected_managed_dirs_and_backs_them_up(self) -> None:
        with workspace_tempdir() as temp_dir:
            source = temp_dir / "source" / "alpha"
            source.mkdir(parents=True)
            (source / "SKILL.md").write_text("new", encoding="utf-8")
            project_root = temp_dir / "project"
            skills_root = project_root / PROJECT_SKILLS_RELATIVE_DIR
            old_target = skills_root / "old"
            old_target.mkdir(parents=True)
            (old_target / "SKILL.md").write_text("old", encoding="utf-8")
            (old_target / SKILL_MANAGED_MARKER).write_text("managed by codex-switch\n", encoding="utf-8")
            manual_target = skills_root / "manual"
            manual_target.mkdir()
            (manual_target / "SKILL.md").write_text("manual", encoding="utf-8")
            backup_dir = project_root / ".codex" / "template-backups" / "backup"

            sync_project_skills(
                project_root,
                [SkillSource("alpha", "alpha", source)],
                ["alpha"],
                backup_dir=backup_dir,
            )

            self.assertFalse(old_target.exists())
            self.assertTrue(manual_target.exists())
            self.assertTrue((skills_root / "alpha" / "SKILL.md").exists())
            self.assertEqual(
                (backup_dir / PROJECT_SKILLS_RELATIVE_DIR / "old" / "SKILL.md").read_text(encoding="utf-8"),
                "old",
            )


if __name__ == "__main__":
    unittest.main()
