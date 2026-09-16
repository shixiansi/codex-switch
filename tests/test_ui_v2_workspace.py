"""Unit tests for the headless ui_v2 Workspace (no Qt required).

These cover the business orchestration that the QML layer drives: profile,
project, proxy, pool, MCP, Skills, settings and update operations, plus the
snapshot contracts the view models consume.
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path
from unittest.mock import patch

from helpers import workspace_tempdir

from codex_switch.models import (
    AccountPoolChannel,
    HealthResult,
    HotUpdateEvent,
    Profile,
    ProjectRecord,
    RouteProxyRule,
    SkillDefinition,
    SkillGroup,
    SkillMarketRepo,
    VENDOR_CLAUDE,
    VENDOR_CODEX,
    today_iso,
)
from codex_switch.storage import ProfileStore
from codex_switch.ui_v2 import forms, snapshots
from codex_switch.ui_v2.session import AppSession
from codex_switch.ui_v2.workspace import (
    SIGN_IN_BATCH_PAUSE_MS,
    SIGN_IN_BATCH_SIZE,
    Workspace,
    WorkspaceError,
)


class WorkspaceTestCase(unittest.TestCase):
    """Shared fixture: a workspace bound to an isolated temp store."""

    def setUp(self) -> None:
        self._temp = workspace_tempdir()
        self.root: Path = self._temp.__enter__()
        self.addCleanup(self._temp.__exit__, None, None, None)
        self.store = ProfileStore(self.root)
        self.workspace = Workspace(store=self.store, project_root=self.root)

    # -- helpers ---------------------------------------------------------
    def add_profile(self, name: str = "主账号", vendor: str = VENDOR_CODEX, **kwargs):
        profile = Profile.create(
            name=name,
            base_url=kwargs.pop("base_url", "https://api.example.com"),
            api_key=kwargs.pop("api_key", "sk-test"),
            vendor=vendor,
            codex_model="gpt-5",
            claude_model="sonnet",
            claude_fallback_model="haiku",
            **kwargs,
        )
        session = self.workspace.session
        session.profiles.append(profile)
        session.selected_profile_id = profile.id
        self.workspace.persist()
        return profile

    def add_project(self, name: str = "示例项目", profile=None) -> ProjectRecord:
        profile = profile or self.add_profile()
        project = ProjectRecord.create(
            project_dir=str(self.root / name),
            profile_id=profile.id,
            name=name,
        )
        session = self.workspace.session
        session.projects.append(project)
        session.selected_project_id = project.id
        self.workspace.persist()
        return project


class SessionPersistenceTests(WorkspaceTestCase):
    def test_load_defaults_without_storage_file(self) -> None:
        self.assertEqual(self.workspace.session.profiles, [])
        self.assertEqual(self.workspace.session.projects, [])
        self.assertIsInstance(self.workspace.session.route_proxy.rules, list)

    def test_persist_keeps_storage_schema_version_and_keys(self) -> None:
        self.add_profile()
        payload = json.loads(self.store.storage_path.read_text(encoding="utf-8"))
        self.assertEqual(payload["version"], 21)
        self.assertEqual(
            sorted(payload.keys()),
            ["profiles", "projects", "selected_profile_id", "selected_project_id", "settings", "ui", "version"],
        )

    def test_round_trip_preserves_profiles_and_selection(self) -> None:
        profile = self.add_profile(name="往返配置")
        reloaded = Workspace(store=self.store, project_root=self.root)
        self.assertEqual([item.name for item in reloaded.session.profiles], ["往返配置"])
        self.assertEqual(reloaded.session.selected_profile_id, profile.id)

    def test_dark_mode_stored_outside_profiles_json(self) -> None:
        self.workspace.session.dark_mode = True
        self.workspace.persist()
        prefs = json.loads((self.root / "ui_prefs.json").read_text(encoding="utf-8"))
        self.assertTrue(prefs["dark_mode"])
        payload = json.loads(self.store.storage_path.read_text(encoding="utf-8"))
        self.assertNotIn("dark_mode", json.dumps(payload))

    def test_reload_reflects_external_changes(self) -> None:
        self.add_profile()
        result = self.workspace.reload()
        self.assertIn("刷新", result.message)
        self.assertEqual(len(self.workspace.session.profiles), 1)


class ProfileOperationTests(WorkspaceTestCase):
    def test_form_payload_creates_profile_with_all_fields(self) -> None:
        payload = {
            "name": "新配置",
            "vendor": VENDOR_CODEX,
            "category": "text",
            "providerName": "OpenAI",
            "baseUrl": "https://api.new.example.com/",
            "apiKeysText": "sk-one\nsk-two",
            "activeKeyIndex": "1",
            "wireApi": "responses",
            "codexModel": "gpt-5",
            "claudeModel": "sonnet",
            "claudeFallbackModel": "haiku",
            "customHeadersText": "X-Test: 1",
            "requiresOpenaiAuth": True,
            "apiProvided": True,
            "requiresSignIn": False,
            "signInUrl": "",
            "notes": "备注",
        }
        result = self.workspace.save_profile(payload)
        self.assertIn("新配置", result.message)
        profile = self.workspace.session.profiles[0]
        self.assertEqual(profile.base_url, "https://api.new.example.com")
        self.assertEqual(profile.api_keys, ["sk-one", "sk-two"])
        self.assertEqual(profile.effective_active_api_key_index, 1)
        self.assertEqual(profile.custom_headers, {"X-Test": "1"})
        self.assertEqual(profile.notes, "备注")
        self.assertEqual(self.workspace.session.selected_profile_id, profile.id)

    def test_edit_profile_updates_existing_record(self) -> None:
        profile = self.add_profile()
        fields = {field["key"]: field.get("value") for field in self.workspace.profile_form_fields(profile.id)}
        fields["name"] = "改名后"
        fields["apiKeysText"] = "\n".join(fields.get("apiKeysText", "").splitlines())
        result = self.workspace.save_profile(fields, profile_id=profile.id)
        self.assertIn("改名后", result.message)
        self.assertEqual(len(self.workspace.session.profiles), 1)
        self.assertEqual(self.workspace.session.profiles[0].name, "改名后")
        self.assertEqual(self.workspace.session.profiles[0].id, profile.id)

    def test_edit_missing_profile_raises(self) -> None:
        with self.assertRaises(WorkspaceError):
            self.workspace.save_profile({"name": "x", "baseUrl": "https://a.b", "apiKeysText": "k"},
                                        profile_id="does-not-exist")

    def test_delete_profile_clears_selection_and_cache(self) -> None:
        profile = self.add_profile()
        self.workspace.session.model_batch_cache_by_profile[profile.id] = object()
        result = self.workspace.delete_profile(profile.id)
        self.assertIn("已删除", result.message)
        self.assertEqual(self.workspace.session.profiles, [])
        self.assertIsNone(self.workspace.session.selected_profile_id)
        self.assertNotIn(profile.id, self.workspace.session.model_batch_cache_by_profile)

    def test_delete_profile_blocked_while_project_bound(self) -> None:
        profile = self.add_profile(name="被项目占用")
        self.add_project(name="示例项目", profile=profile)

        blocker = self.workspace.delete_profile_blocker(profile.id)
        self.assertIn("示例项目", blocker)
        with self.assertRaises(WorkspaceError) as ctx:
            self.workspace.delete_profile(profile.id)
        self.assertIn("示例项目", str(ctx.exception))
        # The profile must survive a refused delete.
        self.assertEqual(len(self.workspace.session.profiles), 1)

    def test_delete_profile_blocker_empty_when_deletable(self) -> None:
        profile = self.add_profile()
        self.assertEqual(self.workspace.delete_profile_blocker(profile.id), "")
        self.assertIn("不存在", self.workspace.delete_profile_blocker("missing-id"))

    def test_delete_profile_allowed_after_binding_removed(self) -> None:
        profile = self.add_profile()
        project = self.add_project(profile=profile)
        self.assertTrue(self.workspace.delete_profile_blocker(profile.id))

        self.workspace.delete_project(project.id)
        self.assertEqual(self.workspace.delete_profile_blocker(profile.id), "")
        self.workspace.delete_profile(profile.id)
        self.assertEqual(self.workspace.session.profiles, [])

    def test_delete_profile_blocked_by_claude_binding_only(self) -> None:
        """A project bound only as the Claude target still blocks deletion."""
        codex = self.add_profile(name="codex 侧", vendor=VENDOR_CODEX)
        claude = self.add_profile(name="claude 侧", vendor=VENDOR_CLAUDE)
        project_dir = self.root / "claude-bound"
        project_dir.mkdir()
        project = ProjectRecord.create(
            project_dir=str(project_dir),
            profile_id=codex.id,
            name="仅 Claude 绑定",
            codex_profile_id=codex.id,
            claude_profile_id=claude.id,
        )
        self.workspace.session.projects.append(project)
        self.workspace.persist()

        self.assertIn("仅 Claude 绑定", self.workspace.delete_profile_blocker(claude.id))
        self.assertIn("仅 Claude 绑定", self.workspace.delete_profile_blocker(codex.id))

    def test_invalid_payloads_are_rejected(self) -> None:
        cases = [
            ({"name": ""}, "请填写配置名称"),
            ({"name": "x", "apiProvided": True, "baseUrl": ""}, "请填写 API 地址"),
            ({"name": "x", "apiProvided": True, "baseUrl": "ftp://a"}, "http://"),
            ({"name": "x", "apiProvided": True, "baseUrl": "https://a.b", "apiKeysText": ""}, "API Key"),
        ]
        for payload, expected in cases:
            with self.subTest(payload=payload):
                with self.assertRaises(WorkspaceError) as ctx:
                    self.workspace.save_profile(payload)
                self.assertIn(expected, str(ctx.exception))

    def test_vendor_specific_model_requirements(self) -> None:
        base = {"name": "x", "baseUrl": "https://a.b", "apiKeysText": "k"}
        with self.assertRaises(WorkspaceError):
            self.workspace.save_profile({**base, "vendor": VENDOR_CODEX, "codexModel": ""})
        with self.assertRaises(WorkspaceError):
            self.workspace.save_profile({**base, "vendor": VENDOR_CLAUDE, "claudeModel": "sonnet"})
        ok = self.workspace.save_profile(
            {**base, "vendor": VENDOR_CLAUDE, "claudeModel": "sonnet", "claudeFallbackModel": "haiku"}
        )
        self.assertIn("已新增", ok.message)

    def test_invalid_custom_header_is_rejected(self) -> None:
        with self.assertRaises(WorkspaceError) as ctx:
            self.workspace.save_profile(
                {
                    "name": "x",
                    "baseUrl": "https://a.b",
                    "apiKeysText": "k",
                    "vendor": VENDOR_CODEX,
                    "codexModel": "gpt-5",
                    "customHeadersText": "bad header line",
                }
            )
        self.assertIn("自定义请求头无效", str(ctx.exception))

    def test_profile_form_fields_round_trip_for_edit_drawer(self) -> None:
        profile = self.add_profile()
        fields = self.workspace.profile_form_fields(profile.id)
        keys = {field["key"] for field in fields}
        self.assertIn("name", keys)
        self.assertIn("apiKeysText", keys)
        values = {field["key"]: field.get("value") for field in fields}
        self.assertEqual(values["name"], profile.name)
        self.assertEqual(values["baseUrl"], profile.base_url)

    def test_missing_profile_form_raises(self) -> None:
        with self.assertRaises(WorkspaceError):
            self.workspace.profile_form_fields("nope")

    def test_global_choice_can_be_set_and_cleared(self) -> None:
        profile = self.add_profile(vendor=VENDOR_CODEX)
        self.workspace.set_global_profile_choice(VENDOR_CODEX, profile.id)
        self.assertEqual(self.workspace.session.selected_codex_global_profile_id, profile.id)
        self.workspace.set_global_profile_choice(VENDOR_CODEX, "")
        self.assertIsNone(self.workspace.session.selected_codex_global_profile_id)

    def test_apply_profile_writes_codex_and_claude_config(self) -> None:
        profile = self.add_profile(name="通用配置", vendor="通用")
        codex_dir = self.root / "codex-home"
        claude_dir = self.root / "claude-home"
        with patch.object(self.workspace.codex_manager, "codex_dir", codex_dir), patch.object(
            self.workspace.codex_manager, "config_path", codex_dir / "config.toml"
        ), patch.object(self.workspace.codex_manager, "auth_path", codex_dir / "auth.json"), patch.object(
            self.workspace.codex_manager, "backup_root", codex_dir / "backups"
        ), patch.object(self.workspace.claude_manager, "claude_dir", claude_dir), patch.object(
            self.workspace.claude_manager, "settings_path", claude_dir / "settings.json"
        ), patch.object(self.workspace.claude_manager, "backup_root", claude_dir / "backups"):
            codex_dir.mkdir(parents=True, exist_ok=True)
            claude_dir.mkdir(parents=True, exist_ok=True)
            result = self.workspace.apply_profile(profile.id)

        self.assertIn("已切换全局配置", result.message)
        self.assertTrue((codex_dir / "config.toml").exists())
        self.assertTrue((codex_dir / "auth.json").exists())
        self.assertTrue((claude_dir / "settings.json").exists())
        self.assertEqual(self.workspace.session.selected_codex_global_profile_id, profile.id)
        self.assertEqual(self.workspace.session.selected_claude_global_profile_id, profile.id)

    def test_apply_global_profiles_requires_a_choice(self) -> None:
        self.add_profile()
        with self.assertRaises(WorkspaceError) as ctx:
            self.workspace.apply_global_profiles()
        self.assertIn("全局", str(ctx.exception))

    def test_mark_signed_in_records_today(self) -> None:
        profile = self.add_profile(requires_sign_in=True, sign_in_url="https://signin.example.com")
        result = self.workspace.mark_signed_in(profile.id)
        self.assertIn("签到", result.message)
        self.assertTrue(profile.last_signed_date)

    def test_open_sign_in_requires_url(self) -> None:
        profile = self.add_profile()
        with self.assertRaises(WorkspaceError):
            self.workspace.open_sign_in_url(profile.id)


class BatchSignInTests(WorkspaceTestCase):
    """一键签到：打开所有待签到页面并标记为今日已签到。"""

    def _add_sign_in_profiles(self, count: int = 3) -> list[Profile]:
        profiles = []
        for index in range(count):
            profiles.append(
                self.add_profile(
                    name=f"站点{index}",
                    requires_sign_in=True,
                    sign_in_url=f"https://signin{index}.example.com/checkin",
                )
            )
        return profiles

    def test_pending_excludes_profiles_without_url(self) -> None:
        with_url = self.add_profile(
            name="有地址", requires_sign_in=True, sign_in_url="https://a.example.com/signin"
        )
        self.add_profile(name="缺地址", requires_sign_in=True, sign_in_url="")
        self.add_profile(name="无需签到")

        pending = self.workspace.sign_in_pending()
        self.assertEqual([item.id for item in pending], [with_url.id])

    def test_summary_counts(self) -> None:
        first = self.add_profile(
            name="待签", requires_sign_in=True, sign_in_url="https://a.example.com/signin"
        )
        second = self.add_profile(
            name="已签", requires_sign_in=True, sign_in_url="https://b.example.com/signin"
        )
        second.last_signed_date = today_iso()
        self.add_profile(name="缺地址", requires_sign_in=True, sign_in_url="")
        self.add_profile(name="无需签到")

        summary = self.workspace.sign_in_summary()
        self.assertEqual(summary["required"], 3)
        self.assertEqual(summary["signedToday"], 1)
        self.assertEqual(summary["pending"], 1)
        self.assertEqual(summary["missingUrl"], 1)
        self.assertEqual(len(summary["urls"]), 2)

    def test_sign_in_batch_constants_match_the_agreed_pacing(self) -> None:
        """Five pages per batch, one second between batches."""
        self.assertEqual(SIGN_IN_BATCH_SIZE, 5)
        self.assertEqual(SIGN_IN_BATCH_PAUSE_MS, 1000)

    def test_open_sign_in_batch_opens_only_the_given_profiles(self) -> None:
        profiles = self._add_sign_in_profiles(7)
        opened: list[str] = []
        with patch("codex_switch.ui_v2.workspace._open_url", side_effect=opened.append):
            names, failed = self.workspace.open_sign_in_batch(profiles[:5])

        self.assertEqual(len(names), 5)
        self.assertEqual(failed, [])
        self.assertEqual(len(opened), 5)
        # Only the first batch is marked; the rest stay pending.
        self.assertEqual(self.workspace.sign_in_summary()["pending"], 2)

    def test_batch_failures_do_not_abort_the_batch(self) -> None:
        profiles = self._add_sign_in_profiles(3)

        def flaky(url: str) -> None:
            if "signin1." in url:
                raise OSError("no browser")

        with patch("codex_switch.ui_v2.workspace._open_url", side_effect=flaky):
            names, failed = self.workspace.open_sign_in_batch(profiles)

        self.assertEqual(len(names), 2, "the other profiles should still open")
        self.assertEqual(len(failed), 1)
        self.assertIn("打开失败", self.workspace.sign_in_result(names, failed).detail)

    def test_sign_in_result_reports_missing_urls(self) -> None:
        result = self.workspace.sign_in_result(["甲"], [], ["无地址"])
        self.assertEqual(result.level, "warning")
        self.assertIn("缺少签到地址", result.detail)
        self.assertIn("1 个配置缺少签到地址", result.message)

    def test_sign_in_result_all_failed_is_an_error(self) -> None:
        result = self.workspace.sign_in_result([], ["甲：boom"])
        self.assertEqual(result.level, "error")
        self.assertIn("未能打开", result.message)

    def test_sign_in_missing_url_returns_names(self) -> None:
        self.add_profile(name="缺地址", requires_sign_in=True, sign_in_url="")
        self.add_profile(name="有地址", requires_sign_in=True, sign_in_url="https://a.example.com/s")
        self.assertEqual(self.workspace.sign_in_missing_url(), ["缺地址"])

    def test_open_all_opens_pending_and_marks_them(self) -> None:
        profiles = self._add_sign_in_profiles(3)
        opened: list[str] = []
        with patch("codex_switch.ui_v2.workspace._open_url", side_effect=opened.append):
            result = self.workspace.open_all_sign_in_urls()

        self.assertIn("3", result.message)
        self.assertEqual(result.level, "success")
        self.assertEqual(len(opened), 3)
        # Every profile is now recorded as signed today.
        for profile in profiles:
            self.assertEqual(profile.last_signed_date, today_iso())
        self.assertEqual(self.workspace.sign_in_summary()["pending"], 0)

    def test_already_signed_profiles_are_skipped(self) -> None:
        profiles = self._add_sign_in_profiles(2)
        profiles[0].last_signed_date = today_iso()
        self.workspace.persist()

        opened: list[str] = []
        with patch("codex_switch.ui_v2.workspace._open_url", side_effect=opened.append):
            result = self.workspace.open_all_sign_in_urls()

        # Only the second profile still needed signing in.
        self.assertEqual(len(opened), 1)
        self.assertEqual(opened[0], profiles[1].sign_in_url)
        self.assertIn("1", result.message)

    def test_repeat_call_reports_nothing_to_do(self) -> None:
        self._add_sign_in_profiles(2)
        with patch("codex_switch.ui_v2.workspace._open_url"):
            self.workspace.open_all_sign_in_urls()
            again = self.workspace.open_all_sign_in_urls()

        self.assertEqual(again.level, "info")
        self.assertIn("都已签到", again.message)

    def test_no_sign_in_profiles_at_all(self) -> None:
        self.add_profile(name="普通配置")
        result = self.workspace.open_all_sign_in_urls()
        self.assertEqual(result.level, "info")
        self.assertIn("都已签到", result.message)

    def test_missing_url_is_reported_without_blocking_others(self) -> None:
        good = self.add_profile(
            name="有地址", requires_sign_in=True, sign_in_url="https://ok.example.com/signin"
        )
        self.add_profile(name="缺地址", requires_sign_in=True, sign_in_url="")

        opened: list[str] = []
        with patch("codex_switch.ui_v2.workspace._open_url", side_effect=opened.append):
            result = self.workspace.open_all_sign_in_urls()

        self.assertEqual(opened, [good.sign_in_url])
        self.assertEqual(result.level, "warning")
        self.assertIn("缺少签到地址", result.detail)
        self.assertIn("缺地址", result.detail)

    def test_open_failure_does_not_mark_signed_and_continues(self) -> None:
        first = self.add_profile(
            name="会失败", requires_sign_in=True, sign_in_url="https://fail.example.com/signin"
        )
        second = self.add_profile(
            name="正常", requires_sign_in=True, sign_in_url="https://ok.example.com/signin"
        )

        def flaky(url: str) -> None:
            if "fail" in url:
                raise OSError("no browser")

        with patch("codex_switch.ui_v2.workspace._open_url", side_effect=flaky):
            result = self.workspace.open_all_sign_in_urls()

        # The failing profile keeps its old state; the healthy one is marked.
        self.assertIsNone(first.last_signed_date)
        self.assertEqual(second.last_signed_date, today_iso())
        self.assertEqual(result.level, "warning")
        self.assertIn("打开失败", result.detail)

    def test_all_failures_reports_error(self) -> None:
        self._add_sign_in_profiles(2)
        with patch("codex_switch.ui_v2.workspace._open_url", side_effect=OSError("boom")):
            result = self.workspace.open_all_sign_in_urls()

        self.assertEqual(result.level, "error")
        self.assertIn("未能打开", result.message)

    def test_marking_survives_reload(self) -> None:
        profiles = self._add_sign_in_profiles(2)
        with patch("codex_switch.ui_v2.workspace._open_url"):
            self.workspace.open_all_sign_in_urls()

        reloaded = Workspace(store=self.store, project_root=self.root)
        for profile in profiles:
            stored = reloaded.session.profile_by_id(profile.id)
            self.assertEqual(stored.last_signed_date, today_iso())
        self.assertEqual(reloaded.sign_in_summary()["pending"], 0)

    def test_snapshot_exposes_sign_in_summary(self) -> None:
        self._add_sign_in_profiles(2)
        snapshot = self.workspace.snapshot()
        self.assertIn("sign_in", snapshot)
        self.assertEqual(snapshot["sign_in"]["pending"], 2)
        # Each row carries its own sign-in flags for list rendering.
        row = snapshot["profiles"][0]
        self.assertTrue(row["requiresSignIn"])
        self.assertFalse(row["signedToday"])
        self.assertEqual(row["signInStatus"], "未签到")


class HealthCheckTests(WorkspaceTestCase):
    def test_single_health_check_stores_result(self) -> None:
        profile = self.add_profile()
        fake = HealthResult(status="healthy", detail="ok", models=["m1"])
        with patch.object(self.workspace.health_checker, "check", return_value=fake):
            outcome = self.workspace.run_health_check(profile.id)
        self.assertIn(profile.id, outcome.results)
        self.assertEqual(profile.health.status, "healthy")

    def test_health_check_all_reports_summary(self) -> None:
        first = self.add_profile(name="a")
        second = self.add_profile(name="b")
        fake = HealthResult(status="error", detail="down")
        with patch.object(self.workspace.health_checker, "check", return_value=fake):
            outcome = self.workspace.run_health_check_all()
        self.assertEqual(len(outcome.results), 2)
        self.assertIn("2", outcome.summary)
        self.assertEqual(first.health.status, "error")
        self.assertEqual(second.health.status, "error")

    def test_health_check_without_selection_raises(self) -> None:
        with self.assertRaises(WorkspaceError):
            self.workspace.run_health_check("")


class SnapshotAggregationTests(WorkspaceTestCase):
    def test_dashboard_health_counts(self) -> None:
        healthy = self.add_profile(name="健康")
        broken = self.add_profile(name="异常")
        healthy.health.status = "healthy"
        broken.health.status = "error"
        state = self.workspace.snapshot()
        self.assertEqual(state["health"]["healthy"], 1)
        self.assertEqual(state["health"]["error"], 1)
        self.assertEqual(len(state["profiles"]), 2)

    def test_snapshot_exposes_all_view_model_contracts(self) -> None:
        self.add_profile()
        self.add_project()
        state = self.workspace.snapshot()
        for key in (
            "profiles",
            "profile_choices",
            "codex_choices",
            "claude_choices",
            "selected_profile_detail",
            "projects",
            "selected_project_detail",
            "proxy",
            "proxy_events",
            "account_pool",
            "account_pool_groups",
            "account_pool_channels",
            "model_batch",
            "chat",
            "mcp_servers",
            "mcp_detail",
            "skill_groups",
            "skill_repos",
            "settings",
            "activity",
            "storage_path",
            "version",
        ):
            with self.subTest(key=key):
                self.assertIn(key, state)

    def test_selected_detail_is_empty_without_selection(self) -> None:
        state = self.workspace.snapshot()
        self.assertEqual(state["selected_profile_detail"], {})
        self.assertEqual(state["selected_project_detail"], {})

    def test_profile_row_carries_health_tone(self) -> None:
        profile = self.add_profile()
        profile.health.status = "healthy"
        state = self.workspace.snapshot()
        row = state["profiles"][0]
        self.assertEqual(row["healthTone"], "success")
        # Selection is carried by the snapshot, not by each row: baking it into
        # the rows made every click replace the model and reset list scroll.
        self.assertNotIn("selected", row)
        self.assertEqual(state["selected_profile_id"], profile.id)

    def test_vendor_choices_partition_by_capability(self) -> None:
        codex = self.add_profile(name="c", vendor=VENDOR_CODEX)
        claude = self.add_profile(name="l", vendor=VENDOR_CLAUDE)
        state = self.workspace.snapshot()
        self.assertEqual([item["id"] for item in state["codex_choices"]], [codex.id])
        self.assertEqual([item["id"] for item in state["claude_choices"]], [claude.id])

    def test_activity_log_is_newest_first_and_capped(self) -> None:
        for index in range(5):
            self.workspace.session.record_event(source="app", level="info", message=f"事件 {index}")
        rows = self.workspace.snapshot()["activity"]
        self.assertEqual(rows[0]["message"], "事件 4")
        self.assertEqual(len(rows), 5)

    def test_event_log_limit_is_enforced(self) -> None:
        for index in range(320):
            self.workspace.session.record_event(source="app", level="info", message=str(index))
        # EVENT_LOG_LIMIT keeps the log bounded so memory cannot grow forever.
        self.assertLessEqual(len(self.workspace.session.event_log), 300)


class ProjectOperationTests(WorkspaceTestCase):
    def test_create_project_from_payload(self) -> None:
        profile = self.add_profile()
        project_dir = self.root / "proj-a"
        project_dir.mkdir()
        result = self.workspace.save_project(
            {
                "name": "项目 A",
                "projectDir": str(project_dir),
                "codexProfileId": profile.id,
                "claudeProfileId": profile.id,
                "runCommand": "npm run dev",
                "githubRepo": "",
                "githubRef": "HEAD",
                "githubAutoUpdate": False,
                "mcpServerNames": [],
                "skillGroupIds": [],
            }
        )
        self.assertIn("项目 A", result.message)
        project = self.workspace.session.projects[0]
        self.assertEqual(project.run_command, "npm run dev")
        self.assertEqual(self.workspace.session.selected_project_id, project.id)

    def test_duplicate_project_dir_is_rejected(self) -> None:
        profile = self.add_profile()
        project_dir = self.root / "dup"
        project_dir.mkdir()
        payload = {
            "name": "一",
            "projectDir": str(project_dir),
            "codexProfileId": profile.id,
            "claudeProfileId": profile.id,
        }
        self.workspace.save_project(payload)
        with self.assertRaises(WorkspaceError) as ctx:
            self.workspace.save_project({**payload, "name": "二"})
        self.assertIn("已经添加过", str(ctx.exception))

    def test_editing_same_project_keeps_its_dir_allowed(self) -> None:
        profile = self.add_profile()
        project_dir = self.root / "same"
        project_dir.mkdir()
        project = self.workspace.save_project(
            {
                "name": "原名",
                "projectDir": str(project_dir),
                "codexProfileId": profile.id,
                "claudeProfileId": profile.id,
            }
        )
        self.assertTrue(project.changed or project.message)
        target = self.workspace.session.projects[0]
        result = self.workspace.save_project(
            {
                "name": "新名",
                "projectDir": str(project_dir),
                "codexProfileId": profile.id,
                "claudeProfileId": profile.id,
            },
            project_id=target.id,
        )
        self.assertIn("新名", result.message)
        self.assertEqual(len(self.workspace.session.projects), 1)

    # -- project environment variables ----------------------------------
    def _make_project(self, name: str = "环境变量项目") -> tuple[Path, str]:
        """Create a project dir with a pre-existing local.env and return it."""
        profile = self.add_profile(name="环境配置")
        project_dir = self.root / "env-proj"
        project_dir.mkdir(parents=True, exist_ok=True)
        codex_dir = project_dir / ".codex"
        codex_dir.mkdir(parents=True, exist_ok=True)
        (codex_dir / "local.env").write_text(
            "PROJECT_API_KEY=sk-existing\nHAND_MADE=keep-me\n", encoding="utf-8"
        )
        self.workspace.save_project(
            {
                "name": name,
                "projectDir": str(project_dir),
                "codexProfileId": profile.id,
                "claudeProfileId": profile.id,
            }
        )
        project = self.workspace.session.projects[0]
        return project_dir, project.id

    def test_saving_project_writes_env_vars_into_local_env(self) -> None:
        project_dir, project_id = self._make_project()
        self.workspace.save_project(
            {
                "name": "环境变量项目",
                "projectDir": str(project_dir),
                "codexProfileId": self.workspace.session.profiles[0].id,
                "claudeProfileId": self.workspace.session.profiles[0].id,
                "envText": "MY_TOKEN=abc123\nDEBUG_MODE=true\n# 注释\n\nAPI_BASE=https://x.example.com",
            },
            project_id=project_id,
        )
        content = (project_dir / ".codex" / "local.env").read_text(encoding="utf-8")
        self.assertIn("MY_TOKEN=abc123", content)
        self.assertIn("DEBUG_MODE=true", content)
        self.assertIn("API_BASE=https://x.example.com", content)
        # Untouched lines survive, including the managed API key.
        self.assertIn("PROJECT_API_KEY=sk-existing", content)
        self.assertIn("HAND_MADE=keep-me", content)
        # Comments and blank lines from the editor are not copied over.
        self.assertNotIn("# 注释", content)

    def test_removing_an_env_var_deletes_it_from_local_env(self) -> None:
        project_dir, project_id = self._make_project()
        profile_id = self.workspace.session.profiles[0].id
        self.workspace.save_project(
            {
                "name": "x", "projectDir": str(project_dir),
                "codexProfileId": profile_id, "claudeProfileId": profile_id,
                "envText": "KEEP=1\nDROP=2",
            },
            project_id=project_id,
        )
        self.assertIn("DROP=2", (project_dir / ".codex" / "local.env").read_text(encoding="utf-8"))

        self.workspace.save_project(
            {
                "name": "x", "projectDir": str(project_dir),
                "codexProfileId": profile_id, "claudeProfileId": profile_id,
                "envText": "KEEP=9",
            },
            project_id=project_id,
        )
        content = (project_dir / ".codex" / "local.env").read_text(encoding="utf-8")
        self.assertIn("KEEP=9", content)
        self.assertNotIn("DROP", content, "deleted variable must be removed")
        self.assertIn("PROJECT_API_KEY=sk-existing", content)

    def test_env_editor_rejects_malformed_lines(self) -> None:
        profile = self.add_profile()
        with self.assertRaises(WorkspaceError) as ctx:
            self.workspace.save_project(
                {
                    "name": "x", "projectDir": str(self.root / "bad"),
                    "codexProfileId": profile.id, "claudeProfileId": profile.id,
                    "envText": "NO_EQUALS_SIGN",
                }
            )
        self.assertIn("等号", str(ctx.exception))

    def test_env_editor_rejects_reserved_api_key_variable(self) -> None:
        profile = self.add_profile()
        with self.assertRaises(WorkspaceError) as ctx:
            self.workspace.save_project(
                {
                    "name": "x", "projectDir": str(self.root / "res"),
                    "codexProfileId": profile.id, "claudeProfileId": profile.id,
                    "envText": "PROJECT_API_KEY=my-own-key",
                }
            )
        self.assertIn("PROJECT_API_KEY", str(ctx.exception))

    def test_env_text_is_persisted_on_the_project(self) -> None:
        project_dir, project_id = self._make_project()
        profile_id = self.workspace.session.profiles[0].id
        self.workspace.save_project(
            {
                "name": "x", "projectDir": str(project_dir),
                "codexProfileId": profile_id, "claudeProfileId": profile_id,
                "envText": "A=1\nB=2",
            },
            project_id=project_id,
        )
        self.assertEqual(self.workspace.session.project_by_id(project_id).env_text, "A=1\nB=2")
        # Reopening the form shows what was saved.
        fields = {item["key"]: item for item in self.workspace.project_form_fields(project_id)}
        self.assertEqual(fields["envText"]["value"], "A=1\nB=2")

    def test_project_requires_a_profile(self) -> None:
        with self.assertRaises(WorkspaceError):
            self.workspace.save_project({"name": "x", "projectDir": str(self.root / "p")})

    def test_invalid_github_url_is_rejected(self) -> None:
        profile = self.add_profile()
        with self.assertRaises(WorkspaceError) as ctx:
            self.workspace.save_project(
                {
                    "name": "x",
                    "projectDir": str(self.root / "g"),
                    "codexProfileId": profile.id,
                    "githubRepo": "https://gitlab.com/a/b",
                }
            )
        self.assertIn("github.com", str(ctx.exception))

    def test_delete_project_clears_selection(self) -> None:
        project = self.add_project()
        result = self.workspace.delete_project(project.id)
        self.assertIn("已删除", result.message)
        self.assertEqual(self.workspace.session.projects, [])
        self.assertIsNone(self.workspace.session.selected_project_id)

    def test_project_binding_update_validates_capability(self) -> None:
        codex = self.add_profile(name="c", vendor=VENDOR_CODEX)
        claude = self.add_profile(name="l", vendor=VENDOR_CLAUDE)
        project = self.add_project(profile=codex)

        with self.assertRaises(WorkspaceError):
            # A Codex-only profile cannot be bound as the Claude target.
            self.workspace.set_project_binding(VENDOR_CLAUDE, codex.id, project_id=project.id)

        result = self.workspace.set_project_binding(VENDOR_CLAUDE, claude.id, project_id=project.id)
        self.assertIn("Claude", result.message)
        updated = self.workspace.session.project_by_id(project.id)
        self.assertEqual(updated.claude_profile_id, claude.id)

    def test_template_generation_reports_generated_files(self) -> None:
        profile = self.add_profile(vendor="通用")
        project_dir = self.root / "tpl"
        project_dir.mkdir()
        project = self.add_project(name="tpl", profile=profile)
        project.project_dir = str(project_dir)
        self.workspace.persist()

        result = self.workspace.generate_template(client="codex", project_id=project.id)
        self.assertIn("生成", result.message)
        self.assertTrue((project_dir / ".codex").exists() or (project_dir / "AGENTS.md").exists())

    def test_claude_template_for_missing_profile_raises(self) -> None:
        codex = self.add_profile(vendor=VENDOR_CODEX)
        project_dir = self.root / "tpl2"
        project_dir.mkdir()
        project = ProjectRecord.create(project_dir=str(project_dir), profile_id=codex.id, name="tpl2")
        # Simulate a project whose bound Claude profile was deleted.
        project.claude_profile_id = "deleted-profile"
        self.workspace.session.projects.append(project)
        self.workspace.session.selected_project_id = project.id
        self.workspace.persist()
        with self.assertRaises(WorkspaceError) as ctx:
            self.workspace.generate_template(client="claude", project_id=project.id)
        self.assertIn("Claude", str(ctx.exception))

    def test_open_missing_project_folder_fails_cleanly(self) -> None:
        project = self.add_project()
        project.project_dir = str(self.root / "nope")
        self.workspace.persist()
        with self.assertRaises(WorkspaceError):
            self.workspace.open_project_folder(project.id)

    def test_launch_unsupported_action_raises(self) -> None:
        self.add_project()
        with self.assertRaises(WorkspaceError):
            self.workspace.launch_project("nonsense")

    def test_sync_repo_requires_github_config(self) -> None:
        self.add_project()
        with self.assertRaises(WorkspaceError) as ctx:
            self.workspace.sync_project_repo()
        self.assertIn("GitHub", str(ctx.exception))


class ProxyOperationTests(WorkspaceTestCase):
    def test_proxy_status_snapshot_defaults(self) -> None:
        status = self.workspace.snapshot()["proxy"]
        self.assertFalse(status["enabled"])
        self.assertFalse(status["running"])
        self.assertEqual(status["host"], "127.0.0.1")
        self.assertEqual(status["port"], 15721)

    def test_save_proxy_settings_normalizes_values(self) -> None:
        result = self.workspace.save_proxy_settings(
            {"host": "0.0.0.0", "port": "18080", "upstreamTimeoutSeconds": "120"}
        )
        self.assertIn("保存", result.message)
        settings = self.workspace.session.route_proxy
        self.assertEqual(settings.host, "0.0.0.0")
        self.assertEqual(settings.port, 18080)
        self.assertEqual(settings.upstream_timeout_seconds, 120)

    def test_save_proxy_settings_rejects_bad_port(self) -> None:
        with self.assertRaises(WorkspaceError) as ctx:
            self.workspace.save_proxy_settings({"port": "not-a-port"})
        self.assertIn("数字", str(ctx.exception))

    def test_start_and_stop_proxy(self) -> None:
        self.workspace.session.route_proxy.port = 0  # let the OS pick a free port
        result = self.workspace.start_proxy()
        self.assertIn("启动", result.message)
        self.assertTrue(self.workspace.proxy_running)
        self.assertTrue(self.workspace.session.route_proxy.enabled)

        stop = self.workspace.stop_proxy()
        self.assertIn("停止", stop.message)
        self.assertFalse(self.workspace.proxy_running)
        self.assertFalse(self.workspace.session.route_proxy.enabled)

    def test_toggle_proxy_round_trip(self) -> None:
        self.workspace.session.route_proxy.port = 0
        self.workspace.toggle_proxy()
        self.assertTrue(self.workspace.proxy_running)
        self.workspace.toggle_proxy()
        self.assertFalse(self.workspace.proxy_running)

    def test_start_proxy_failure_is_reported_and_reverted(self) -> None:
        with patch.object(self.workspace.route_proxy_server, "start", side_effect=OSError("port busy")):
            with self.assertRaises(WorkspaceError) as ctx:
                self.workspace.start_proxy()
        self.assertIn("启动失败", str(ctx.exception))
        self.assertFalse(self.workspace.session.route_proxy.enabled)

    def test_enable_and_disable_project_rules(self) -> None:
        profile = self.add_profile(vendor="通用")
        project = self.add_project(profile=profile)
        result = self.workspace.set_project_proxy_enabled(True, project.id)
        self.assertTrue(result.message)
        self.assertTrue(self.workspace.session.route_proxy.project_enabled(project.id))

        self.workspace.set_project_proxy_enabled(False, project.id)
        self.assertFalse(self.workspace.session.route_proxy.project_enabled(project.id))

    def test_enable_project_rules_requires_bound_profiles(self) -> None:
        profile = self.add_profile()
        project = self.add_project(profile=profile)
        project.claude_profile_id = "missing"
        self.workspace.persist()
        with self.assertRaises(WorkspaceError):
            self.workspace.set_project_proxy_enabled(True, project.id)

    def test_proxy_event_recording_is_thread_safe_deferred(self) -> None:
        from codex_switch.models import RouteProxyEvent

        event = RouteProxyEvent.create(level="info", message="proxy log", project_id="p1")
        self.workspace._record_proxy_event(event)
        # Buffered only; the event loop flushes and persists it.
        self.assertEqual(self.workspace.session.event_log, [])
        self.assertTrue(self.workspace.flush_proxy_state())
        self.assertEqual(len(self.workspace.session.event_log), 1)
        self.assertFalse(self.workspace.flush_proxy_state())

    def test_clear_events(self) -> None:
        self.workspace.session.record_event(source="app", level="info", message="x")
        self.workspace.clear_events()
        self.assertEqual(self.workspace.session.event_log, [])

    def test_route_proxy_rules_refresh_for_project(self) -> None:
        profile = self.add_profile(vendor="通用")
        project = self.add_project(profile=profile)
        self.workspace.set_project_proxy_enabled(True, project.id)
        self.assertTrue(self.workspace.refresh_route_proxy_rules(project))
        self.assertTrue(self.workspace.session.route_proxy.rules_for_project(project.id))


class AccountPoolTests(WorkspaceTestCase):
    def test_default_group_is_created(self) -> None:
        self.assertTrue(self.workspace.session.account_pool.groups)

    def test_group_crud(self) -> None:
        created = self.workspace.save_pool_group(
            {"name": "新组", "enabled": True, "poolType": "codex", "defaultModel": "gpt-5"}
        )
        self.assertIn("新组", created.message)
        groups = self.workspace.session.account_pool.groups
        self.assertEqual([group.name for group in groups], ["默认号池", "新组"])

        target = next(group for group in groups if group.name == "新组")
        self.workspace.save_pool_group(
            {"name": "改名组", "enabled": False, "poolType": "claude", "claudeModel": "sonnet"},
            group_id=target.id,
        )
        updated = self.workspace.session.account_pool.group_by_id(target.id)
        self.assertEqual(updated.name, "改名组")
        self.assertFalse(updated.enabled)

    def test_group_requires_name(self) -> None:
        with self.assertRaises(WorkspaceError):
            self.workspace.save_pool_group({"name": ""})

    def test_channel_crud_and_validation(self) -> None:
        group_id = self.workspace.session.account_pool.selected_group_id
        self.workspace.select_pool_group(group_id)
        created = self.workspace.save_pool_channel(
            {
                "name": "渠道 A",
                "baseUrl": "https://api.a.com/",
                "apiKey": "sk-a",
                "wireApi": "responses",
                "defaultModel": "gpt-5",
            }
        )
        self.assertIn("渠道 A", created.message)
        channel = self.workspace.session.account_pool.channels[0]
        self.assertEqual(channel.base_url, "https://api.a.com")

        self.workspace.save_pool_channel(
            {"name": "渠道 A2", "baseUrl": "https://api.a.com", "apiKey": "sk-a2"},
            channel_id=channel.id,
        )
        updated = self.workspace.session.account_pool.channels[0]
        self.assertEqual(updated.name, "渠道 A2")
        self.assertEqual(updated.id, channel.id)

        self.workspace.delete_pool_channel(channel.id)
        self.assertEqual(self.workspace.session.account_pool.channels, [])

    def test_channel_payload_validation(self) -> None:
        for payload, expected in (
            ({"name": "", "baseUrl": "https://a.b", "apiKey": "k"}, "渠道名称"),
            ({"name": "n", "baseUrl": "", "apiKey": "k"}, "API 地址"),
            ({"name": "n", "baseUrl": "ftp://a", "apiKey": "k"}, "http://"),
            ({"name": "n", "baseUrl": "https://a.b", "apiKey": ""}, "API Key"),
        ):
            with self.subTest(payload=payload):
                with self.assertRaises(WorkspaceError) as ctx:
                    self.workspace.save_pool_channel(payload)
                self.assertIn(expected, str(ctx.exception))

    def test_profile_sourced_channel_cannot_be_deleted(self) -> None:
        pool = self.workspace.session.account_pool
        group_id = pool.selected_group_id
        channel = AccountPoolChannel.create(
            name="来自配置",
            base_url="https://a.b",
            api_key="k",
            group_id=group_id,
            source_type="profile",
            source_profile_id="p1",
        )
        pool.channels.append(channel)
        with self.assertRaises(WorkspaceError):
            self.workspace.delete_pool_channel(channel.id)

    def test_test_pool_channel_success_and_failure(self) -> None:
        group_id = self.workspace.session.account_pool.selected_group_id
        channel = AccountPoolChannel.create(
            name="c", base_url="https://a.b", api_key="k", group_id=group_id
        )
        self.workspace.session.account_pool.channels.append(channel)

        healthy = HealthResult(status="healthy", detail="ok")
        with patch("codex_switch.ui_v2.workspace.check_account_pool_channel", return_value=healthy):
            result = self.workspace.test_pool_channel(channel.id)
        self.assertIn("可用", result.message)
        self.assertEqual(channel.status, "normal")

        broken = HealthResult(status="error", detail="401")
        with patch("codex_switch.ui_v2.workspace.check_account_pool_channel", return_value=broken):
            with self.assertRaises(WorkspaceError):
                self.workspace.test_pool_channel(channel.id)
        self.assertEqual(channel.status, "error")
        self.assertEqual(channel.failure_reason, "401")

    def test_test_all_channels_needs_channels(self) -> None:
        with self.assertRaises(WorkspaceError):
            self.workspace.test_all_pool_channels()

    def test_group_delete_blocked_when_project_uses_it(self) -> None:
        profile = self.add_profile(vendor="通用")
        project = self.add_project(profile=profile)
        group_id = self.workspace.session.account_pool.selected_group_id
        self.workspace.session.route_proxy.rules.append(
            RouteProxyRule.create(
                project_id=project.id,
                client_type="codex",
                primary_profile_id=profile.id,
                account_pool_group_id=group_id,
                upstream_source="account_pool",
            )
        )
        self.workspace.persist()
        with self.assertRaises(WorkspaceError) as ctx:
            self.workspace.delete_pool_group(group_id)
        self.assertIn("仍在使用", str(ctx.exception))


class McpOperationTests(WorkspaceTestCase):
    def test_default_servers_are_listed(self) -> None:
        names = self.workspace.available_mcp_server_names()
        self.assertGreater(len(names), 0)
        self.assertEqual([row["name"] for row in self.workspace.snapshot()["mcp_servers"]], sorted(names))

    def test_add_edit_delete_server(self) -> None:
        created = self.workspace.save_mcp(
            {
                "name": "my-mcp",
                "type": "stdio",
                "command": "npx",
                "argsText": "-y\nsome-server",
                "cwd": "",
                "envText": "TOKEN=abc",
            }
        )
        self.assertIn("my-mcp", created.message)
        self.assertIn("my-mcp", self.workspace.available_mcp_server_names())

        self.workspace.save_mcp(
            {"name": "my-mcp", "type": "stdio", "command": "node", "argsText": "server.js", "envText": ""},
            current_name="my-mcp",
        )
        row = next(item for item in self.workspace.snapshot()["mcp_servers"] if item["name"] == "my-mcp")
        self.assertEqual(row["command"], "node")
        self.assertEqual(row["argsCount"], 1)

        self.workspace.delete_mcp("my-mcp")
        self.assertNotIn("my-mcp", self.workspace.available_mcp_server_names())

    def test_duplicate_name_is_rejected(self) -> None:
        existing = self.workspace.available_mcp_server_names()[0]
        with self.assertRaises(WorkspaceError) as ctx:
            self.workspace.save_mcp({"name": existing, "command": "x"})
        self.assertIn("已经存在", str(ctx.exception))

    def test_mcp_payload_validation(self) -> None:
        with self.assertRaises(WorkspaceError):
            self.workspace.save_mcp({"name": "", "command": "x"})
        with self.assertRaises(WorkspaceError):
            self.workspace.save_mcp({"name": "n", "command": ""})

    def test_restore_default_mcp(self) -> None:
        self.workspace.save_mcp({"name": "temp", "command": "x", "argsText": "", "envText": ""})
        self.workspace.restore_default_mcp()
        self.assertNotIn("temp", self.workspace.available_mcp_server_names())
        self.assertGreater(len(self.workspace.available_mcp_server_names()), 0)

    def test_delete_missing_server_raises(self) -> None:
        with self.assertRaises(WorkspaceError):
            self.workspace.delete_mcp("no-such-server")


class SkillsOperationTests(WorkspaceTestCase):
    def test_group_crud_and_project_sync(self) -> None:
        created = self.workspace.save_skill_group({"name": "前端组", "description": "d"})
        self.assertIn("前端组", created.message)
        group = self.workspace.session.skill_groups[0]

        self.workspace.save_skill_group({"name": "改名组", "description": "d2"}, group_id=group.id)
        self.assertEqual(self.workspace.session.skill_groups[0].name, "改名组")

        self.workspace.delete_skill_group(group.id)
        self.assertEqual(self.workspace.session.skill_groups, [])

    def test_skill_crud(self) -> None:
        self.workspace.save_skill_group({"name": "组"})
        group = self.workspace.session.skill_groups[0]

        self.workspace.save_skill(
            {"name": "my-skill", "type": "script", "version": "1.0.0", "content": "echo hi"},
            group_id=group.id,
        )
        skill = self.workspace.session.skill_groups[0].skills[0]
        self.assertEqual(skill.name, "my-skill")

        self.workspace.save_skill(
            {"name": "my-skill-2", "type": "config", "version": "2.0.0", "content": "x"},
            group_id=group.id,
            skill_id=skill.id,
        )
        updated = self.workspace.session.skill_groups[0].skills[0]
        self.assertEqual(updated.name, "my-skill-2")
        self.assertEqual(updated.id, skill.id)

        self.workspace.delete_skill(group.id, skill.id)
        self.assertEqual(self.workspace.session.skill_groups[0].skills, [])

    def test_skill_group_requires_name(self) -> None:
        with self.assertRaises(WorkspaceError):
            self.workspace.save_skill_group({"name": "  "})

    def test_skill_operations_require_valid_group(self) -> None:
        with self.assertRaises(WorkspaceError):
            self.workspace.save_skill({"name": "x"}, group_id="missing")
        with self.assertRaises(WorkspaceError):
            self.workspace.delete_skill("missing", "also-missing")

    def test_repo_crud(self) -> None:
        created = self.workspace.save_skill_repo(
            {"url": "https://github.com/owner/repo", "branch": "main", "autoUpdate": True}
        )
        self.assertIn("repo", created.message)
        repo = self.workspace.session.skill_market_repos[0]
        self.assertTrue(repo.auto_update)

        self.workspace.save_skill_repo(
            {"url": "https://github.com/owner/repo2", "branch": "dev", "autoUpdate": False},
            repo_id=repo.id,
        )
        self.assertEqual(self.workspace.session.skill_market_repos[0].url, "https://github.com/owner/repo2")

        self.workspace.delete_skill_repo(repo.id)
        self.assertEqual(self.workspace.session.skill_market_repos, [])

    def test_repo_url_validation(self) -> None:
        with self.assertRaises(WorkspaceError):
            self.workspace.save_skill_repo({"url": "", "branch": "main"})
        with self.assertRaises(WorkspaceError):
            self.workspace.save_skill_repo({"url": "https://gitlab.com/a/b", "branch": "main"})

    def test_deleting_group_unbinds_repos_and_projects(self) -> None:
        self.workspace.save_skill_group({"name": "组"})
        group = self.workspace.session.skill_groups[0]
        repo = SkillMarketRepo.create("https://github.com/o/r", installed_group_id=group.id)
        self.workspace.session.skill_market_repos.append(repo)
        profile = self.add_profile()
        project = self.add_project(profile=profile)
        project.skill_group_ids = [group.id]
        self.workspace.persist()

        self.workspace.delete_skill_group(group.id)
        self.assertEqual(self.workspace.session.skill_groups, [])
        self.assertEqual(self.workspace.session.skill_market_repos[0].installed_group_id, "")
        self.assertNotIn(group.id, self.workspace.session.project_by_id(project.id).skill_group_ids or [])

    def test_install_repo_surfaces_network_failure(self) -> None:
        self.workspace.save_skill_repo({"url": "https://github.com/owner/repo", "branch": "main"})
        repo = self.workspace.session.skill_market_repos[0]
        with patch("codex_switch.ui_v2.workspace.git_remote_commit", side_effect=RuntimeError("offline")):
            with self.assertRaises(WorkspaceError) as ctx:
                self.workspace.install_skill_repo(repo.id)
        self.assertIn("远端", str(ctx.exception))


class ModelBatchAndChatTests(WorkspaceTestCase):
    def test_batch_requires_selection(self) -> None:
        with self.assertRaises(WorkspaceError):
            self.workspace.run_model_batch()

    def test_batch_requires_models(self) -> None:
        self.add_profile()
        with self.assertRaises(WorkspaceError) as ctx:
            self.workspace.run_model_batch()
        self.assertIn("健康检测", str(ctx.exception))

    def test_batch_records_results_and_persists(self) -> None:
        profile = self.add_profile()
        profile.health.models = ["m1", "m2"]

        def fake_run(_tester, _profile, models, _wire, _payload, on_start, on_result, max_workers=3):
            for model in models:
                on_start(model)
                on_result(model, "success", "ok", 12)

        with patch("codex_switch.ui_v2.workspace.run_model_batch_requests", side_effect=fake_run):
            result = self.workspace.run_model_batch()

        self.assertIn("2/2", result.message)
        cache = self.workspace.session.model_batch_cache(profile.id)
        self.assertTrue(cache.completed)
        self.assertEqual(sorted(cache.results), ["m1", "m2"])

        snapshot = self.workspace.snapshot()["model_batch"]
        self.assertTrue(snapshot["exists"])
        self.assertEqual(snapshot["successCount"], 2)

    def test_batch_cancellation_is_reported(self) -> None:
        profile = self.add_profile()
        profile.health.models = ["m1"]
        with patch("codex_switch.ui_v2.workspace.run_model_batch_requests"):
            with self.assertRaises(WorkspaceError) as ctx:
                self.workspace.run_model_batch(should_cancel=lambda: True)
        self.assertIn("取消", str(ctx.exception))
        self.assertFalse(self.workspace.session.model_batch_cache(profile.id).completed)

    def test_chat_requires_selection_and_prompt(self) -> None:
        with self.assertRaises(WorkspaceError):
            self.workspace.send_chat("hi")
        self.add_profile()
        with self.assertRaises(WorkspaceError):
            self.workspace.send_chat("   ")

    def test_chat_success_and_failure_are_recorded(self) -> None:
        self.add_profile()
        ok = type("R", (), {"ok": True, "text": "pong", "model": "gpt-5", "endpoint": "e", "detail": None})()
        with patch.object(self.workspace.chat_tester, "send_message", return_value=ok):
            result = self.workspace.send_chat("ping")
        self.assertIn("成功", result.message)
        self.assertEqual(len(self.workspace.session.chat_messages), 2)

        bad = type("R", (), {"ok": False, "text": "HTTP 500", "model": "gpt-5", "endpoint": "e", "detail": "boom"})()
        with patch.object(self.workspace.chat_tester, "send_message", return_value=bad):
            result = self.workspace.send_chat("ping")
        self.assertEqual(result.level, "error")

    def test_clear_chat(self) -> None:
        self.add_profile()
        ok = type("R", (), {"ok": True, "text": "p", "model": "m", "endpoint": "e", "detail": None})()
        with patch.object(self.workspace.chat_tester, "send_message", return_value=ok):
            self.workspace.send_chat("ping")
        self.workspace.clear_chat()
        self.assertEqual(self.workspace.session.chat_messages, [])

    def test_chat_snapshot_exposes_models_and_wire_apis(self) -> None:
        profile = self.add_profile()
        profile.health.models = ["m1", "m2"]
        chat = self.workspace.snapshot()["chat"]
        self.assertTrue(chat["available"])
        self.assertEqual(chat["models"], ["m1", "m2"])
        self.assertIn("responses", chat["wireApiChoices"])


class SettingsAndUpdateTests(WorkspaceTestCase):
    def test_save_general_settings_clamps_values(self) -> None:
        result = self.workspace.save_general_settings(
            {"hotUpdateEnabled": True, "hotUpdateIntervalMinutes": "99999", "modelBatchConcurrency": "99"}
        )
        self.assertIn("保存", result.message)
        session = self.workspace.session
        self.assertTrue(session.hot_update_enabled)
        self.assertLessEqual(session.hot_update_interval_minutes, 1440)
        self.assertLessEqual(session.model_batch_concurrency, 5)

    def test_agents_doc_save_and_restore(self) -> None:
        self.workspace.save_agents_doc("# 自定义")
        self.assertEqual(self.workspace.session.agents_doc_text, "# 自定义")
        self.workspace.restore_agents_doc()
        self.assertTrue(self.workspace.session.agents_doc_text)

    def test_settings_snapshot_contains_environment_info(self) -> None:
        settings = self.workspace.snapshot()["settings"]
        self.assertIn("storagePath", settings)
        self.assertIn("python", settings)
        self.assertIn("version", settings)
        self.assertIn("modelBatchConcurrency", settings)

    def test_software_update_available_and_current(self) -> None:
        info_new = type("I", (), {"update_available": True, "version": "9.9.9", "download_url": "u", "release_url": "r", "notes": ""})()
        with patch.object(self.workspace.update_checker, "check", return_value=info_new):
            result = self.workspace.check_software_update()
        self.assertIn("新版本", result.message)
        self.assertTrue(self.workspace.snapshot()["software_update"]["updateAvailable"])

        info_same = type("I", (), {"update_available": False, "version": "0.2.2", "download_url": "", "release_url": "", "notes": ""})()
        with patch.object(self.workspace.update_checker, "check", return_value=info_same):
            result = self.workspace.check_software_update()
        self.assertIn("最新", result.message)

    def test_software_update_failure_is_reported(self) -> None:
        with patch.object(self.workspace.update_checker, "check", side_effect=RuntimeError("no network")):
            with self.assertRaises(WorkspaceError) as ctx:
                self.workspace.check_software_update()
        self.assertIn("失败", str(ctx.exception))

    def test_hot_update_check_without_targets(self) -> None:
        result = self.workspace.check_hot_updates()
        self.assertIn("检查完成", result.message)

    def test_hot_update_records_pending_event(self) -> None:
        repo = SkillMarketRepo.create("https://github.com/o/r", branch="main", auto_update=False)
        self.workspace.session.skill_market_repos.append(repo)
        update = type(
            "U",
            (),
            {
                "has_update": lambda self=None: True,
                "short_latest": lambda self=None: "abc123",
                "latest_commit": "abc123",
            },
        )()
        with patch("codex_switch.ui_v2.workspace.skill_repo_remote_update", return_value=update):
            result = self.workspace.check_hot_updates()
        self.assertIn("待处理", result.message)
        self.assertTrue(self.workspace.session.hot_update_events)
        self.assertEqual(self.workspace.session.hot_update_events[-1].status, "pending")

    def test_hot_update_error_is_reported(self) -> None:
        repo = SkillMarketRepo.create("https://github.com/o/r", branch="main")
        self.workspace.session.skill_market_repos.append(repo)
        with patch("codex_switch.ui_v2.workspace.skill_repo_remote_update", side_effect=RuntimeError("boom")):
            result = self.workspace.check_hot_updates()
        self.assertEqual(result.level, "error")
        self.assertIn("失败", result.message)

    def test_open_missing_local_path_raises(self) -> None:
        with self.assertRaises(WorkspaceError):
            self.workspace.open_local_path(str(self.root / "not-here"))


class FormPayloadTests(unittest.TestCase):
    """Pure payload conversion helpers, independent of any workspace."""

    def test_profile_payload_normalizes_base_url_and_keys(self) -> None:
        data = forms.profile_payload(
            {
                "name": "n",
                "baseUrl": "https://a.b/",
                "apiKeysText": " k1 \n\nk2 ",
                "activeKeyIndex": "5",
                "vendor": "codex",
                "codexModel": "gpt-5",
            }
        )
        self.assertEqual(data["base_url"], "https://a.b")
        self.assertEqual(data["api_keys"], ["k1", "k2"])
        self.assertEqual(data["active_api_key_index"], 1)

    def test_image_category_without_api_clears_keys(self) -> None:
        data = forms.profile_payload(
            {
                "name": "n",
                "category": "image_generation",
                "apiProvided": False,
                "baseUrl": "",
                "apiKeysText": "k",
                "vendor": "codex",
                "codexModel": "gpt-5",
            }
        )
        self.assertEqual(data["base_url"], "")
        self.assertEqual(data["api_keys"], [])

    def test_project_payload_defaults_profile_id_from_codex(self) -> None:
        data = forms.project_payload({"name": "p", "projectDir": "C:/x", "codexProfileId": "cid"})
        self.assertEqual(data["profile_id"], "cid")
        self.assertEqual(data["github_ref"], "HEAD")

    def test_project_payload_requires_dir_and_profile(self) -> None:
        with self.assertRaises(forms.FormError):
            forms.project_payload({"projectDir": "C:/x"})
        with self.assertRaises(forms.FormError):
            forms.project_payload({"name": "p"})

    def test_mcp_payload_parses_env_lines(self) -> None:
        name, config = forms.mcp_payload(
            {"name": "m", "command": "npx", "argsText": "a\nb", "envText": "K=V\n# comment\nBAD\nK2=v2"}
        )
        self.assertEqual(name, "m")
        self.assertEqual(config["args"], ["a", "b"])
        self.assertEqual(config["env"], {"K": "V", "K2": "v2"})

    def test_skill_repo_payload_validates_url(self) -> None:
        data = forms.skill_repo_payload({"url": "https://github.com/o/r", "branch": "dev"})
        self.assertEqual(data["branch"], "dev")
        with self.assertRaises(forms.FormError):
            forms.skill_repo_payload({"url": "http://example.com/x"})


class SnapshotHelperTests(unittest.TestCase):
    def test_health_tone_mapping(self) -> None:
        self.assertEqual(snapshots.health_tone("healthy"), "success")
        self.assertEqual(snapshots.health_tone("error"), "danger")
        self.assertEqual(snapshots.health_tone("degraded"), "warning")
        self.assertEqual(snapshots.health_tone("weird"), "unknown")

    def test_batch_cache_snapshot_without_cache(self) -> None:
        data = snapshots.batch_cache_snapshot(None)
        self.assertFalse(data["exists"])
        self.assertEqual(data["results"], [])

    def test_event_row_normalizes_level_to_tone(self) -> None:
        event = HotUpdateEvent.create(scope="project", target="t", status="error", detail="d")
        row = snapshots.event_row(event, source="update")
        self.assertEqual(row["tone"], "danger")
        self.assertEqual(row["source"], "update")

    def test_usage_rows_sorted_by_tokens(self) -> None:
        class Bucket:
            def __init__(self, key, tokens):
                self.key = key
                self.label = key
                self.total_tokens = tokens
                self.input_tokens = 1
                self.output_tokens = 2
                self.requests = 3

        rows = snapshots.usage_rows({"a": Bucket("a", 5), "b": Bucket("b", 50)})
        self.assertEqual([row["key"] for row in rows], ["b", "a"])

    def test_account_pool_summary_counts(self) -> None:
        from codex_switch.models import AccountPoolSettings

        pool = AccountPoolSettings()
        pool.ensure_default_group()
        summary = snapshots.account_pool_summary(pool, project_count=2)
        self.assertEqual(summary["groupCount"], 1)
        self.assertEqual(summary["projectCount"], 2)


class ManualHealthAndFilterTests(WorkspaceTestCase):
    """手动健康状态与隐藏异常配置。"""

    def _add(self, name: str, status: str) -> Profile:
        profile = self.add_profile(name=name)
        profile.health = HealthResult(status=status, detail=status)
        self.workspace.persist()
        return profile

    def test_manual_status_overrides_automatic_result(self) -> None:
        profile = self._add("正常站", "healthy")
        self.assertEqual(profile.effective_health_status, "healthy")

        result = self.workspace.set_manual_health_status(profile.id, "error")
        self.assertIn("标记", result.message)
        self.assertEqual(profile.effective_health_status, "error")
        self.assertTrue(profile.has_manual_health_override)

    def test_clearing_manual_status_restores_automatic(self) -> None:
        profile = self._add("正常站", "healthy")
        self.workspace.set_manual_health_status(profile.id, "error")
        result = self.workspace.set_manual_health_status(profile.id, "")
        self.assertIn("自动", result.message)
        self.assertEqual(profile.effective_health_status, "healthy")
        self.assertFalse(profile.has_manual_health_override)

    def test_manual_status_survives_reload(self) -> None:
        profile = self._add("正常站", "healthy")
        self.workspace.set_manual_health_status(profile.id, "degraded")
        reloaded = Workspace(store=self.store, project_root=self.root)
        stored = reloaded.session.profile_by_id(profile.id)
        self.assertEqual(stored.effective_health_status, "degraded")
        self.assertTrue(stored.has_manual_health_override)

    def test_manual_status_rejects_unknown_value(self) -> None:
        profile = self._add("正常站", "healthy")
        with self.assertRaises(WorkspaceError):
            self.workspace.set_manual_health_status(profile.id, "banana")

    def test_manual_status_requires_existing_profile(self) -> None:
        with self.assertRaises(WorkspaceError):
            self.workspace.set_manual_health_status("missing", "healthy")

    def test_manual_status_marks_label_in_snapshot(self) -> None:
        profile = self._add("正常站", "healthy")
        self.workspace.set_manual_health_status(profile.id, "error")
        row = next(
            item for item in self.workspace.snapshot()["profiles"] if item["id"] == profile.id
        )
        self.assertEqual(row["healthLabel"], "异常（手动）")
        self.assertEqual(row["healthTone"], "danger")

    def test_hide_error_profiles_filters_listing_only(self) -> None:
        ok = self._add("正常站", "healthy")
        self._add("坏站A", "error")
        self._add("坏站B", "error")

        result = self.workspace.set_hide_error_profiles(True)
        self.assertIn("隐藏", result.message)
        state = self.workspace.snapshot()
        names = [row["name"] for row in state["profiles"]]
        self.assertEqual(names, ["正常站"])
        # Counts still reflect every profile, so nothing is silently lost.
        self.assertEqual(state["health"]["error"], 2)
        self.assertTrue(state["hide_error_profiles"])
        # A hidden profile is still addressable.
        self.assertIsNotNone(self.workspace.session.profile_by_id(ok.id))

    def test_hide_error_profiles_persists(self) -> None:
        self._add("坏站", "error")
        self.workspace.set_hide_error_profiles(True)
        reloaded = Workspace(store=self.store, project_root=self.root)
        self.assertTrue(reloaded.session.hide_error_profiles)

    def test_unhiding_restores_every_profile(self) -> None:
        self._add("坏站", "error")
        self.workspace.set_hide_error_profiles(True)
        result = self.workspace.set_hide_error_profiles(False)
        self.assertIn("显示全部", result.message)
        self.assertEqual(len(self.workspace.snapshot()["profiles"]), 1)

    def test_manual_healthy_hides_nothing_when_filter_on(self) -> None:
        """A profile manually marked healthy stays visible under the filter."""
        profile = self._add("被误判的站", "error")
        self.workspace.set_manual_health_status(profile.id, "healthy")
        self.workspace.set_hide_error_profiles(True)
        names = [row["name"] for row in self.workspace.snapshot()["profiles"]]
        self.assertEqual(names, ["被误判的站"])


class SelectionNotInRowsTests(WorkspaceTestCase):
    """Selection must live in the snapshot, never inside each row.

    Baking ``selected`` into the row dicts made the whole row list change on
    every click. The QML ListView then dropped and rebuilt every delegate and
    the scroll position snapped back to the top.
    """

    def test_profile_rows_do_not_carry_selection(self) -> None:
        first = self.add_profile(name="甲")
        second = self.add_profile(name="乙")
        self.workspace.session.selected_profile_id = second.id
        state = self.workspace.snapshot()
        for row in state["profiles"]:
            self.assertNotIn("selected", row, "row payload carries selection state")
        self.assertEqual(state["selected_profile_id"], second.id)
        self.assertNotEqual(first.id, second.id)

    def test_project_rows_do_not_carry_selection(self) -> None:
        project = self.add_project()
        state = self.workspace.snapshot()
        for row in state["projects"]:
            self.assertNotIn("selected", row)
        self.assertEqual(state["selected_project_id"], project.id)

    def test_pool_group_rows_do_not_carry_selection(self) -> None:
        state = self.workspace.snapshot()
        for row in state["account_pool_groups"]:
            self.assertNotIn("selected", row)
        # The selected group still travels in the pool summary.
        self.assertIn("selectedGroupId", state["account_pool"])

    def test_selecting_a_profile_keeps_row_payload_identical(self) -> None:
        """The essential guarantee: clicking must not change the row list."""
        first = self.add_profile(name="甲")
        second = self.add_profile(name="乙")
        self.workspace.session.selected_profile_id = first.id
        before = self.workspace.snapshot()["profiles"]

        self.workspace.select_profile(second.id)
        after = self.workspace.snapshot()["profiles"]

        self.assertEqual(
            before,
            after,
            "selecting changed the row payload; the list would rebuild and lose scroll",
        )
        self.assertEqual(self.workspace.snapshot()["selected_profile_id"], second.id)


class ViewModelContractTests(WorkspaceTestCase):
    """View models must find every key they read in the snapshot."""

    def test_view_model_snapshot_keys_are_all_present(self) -> None:
        self.add_profile()
        self.add_project()
        state = self.workspace.snapshot()
        # Keys consumed by each view model's builder.
        required = {
            "profiles",
            "selected_profile_id",
            "selected_profile_detail",
            "health",
            "codex_choices",
            "claude_choices",
            "global_codex_profile_id",
            "global_claude_profile_id",
            "projects",
            "selected_project_id",
            "selected_project_detail",
            "proxy",
            "proxy_events",
            "model_batch",
            "chat",
            "account_pool",
            "account_pool_groups",
            "account_pool_channels",
            "mcp_servers",
            "mcp_detail",
            "skill_groups",
            "skill_repos",
            "settings",
            "software_update",
            "activity",
        }
        missing = sorted(required - set(state))
        self.assertEqual(missing, [], f"snapshot is missing keys: {missing}")

    def test_session_accessors_resolve_selection(self) -> None:
        profile = self.add_profile()
        project = self.add_project(profile=profile)
        session = self.workspace.session
        self.assertEqual(session.selected_profile().id, profile.id)
        self.assertEqual(session.selected_project().id, project.id)
        self.assertEqual(session.profile_by_id(profile.id).name, profile.name)
        self.assertIsNone(session.profile_by_id("missing"))

    def test_global_selection_is_dropped_when_profile_deleted(self) -> None:
        profile = self.add_profile(vendor=VENDOR_CODEX)
        self.workspace.set_global_profile_choice(VENDOR_CODEX, profile.id)
        self.workspace.delete_profile(profile.id)
        self.assertIsNone(self.workspace.session.selected_codex_global_profile_id)


if __name__ == "__main__":
    unittest.main()
