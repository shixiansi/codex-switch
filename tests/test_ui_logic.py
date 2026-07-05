from __future__ import annotations

from dataclasses import replace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import hashlib
import json
import os
from pathlib import Path
import subprocess
import threading
import time
import unittest
from urllib import error as url_error
from unittest.mock import patch

from helpers import start_test_server, workspace_tempdir

from codex_switch import main
from codex_switch.chat import ChatResult
from codex_switch.health import HealthChecker, build_candidate_urls
from codex_switch.models import (
    AccountPoolChannel,
    AccountPoolSettings,
    HealthResult,
    HotUpdateEvent,
    Profile,
    ProjectRecord,
    RouteProxyEvent,
    RouteProxyRule,
    RouteProxySettings,
    ROUTE_PROXY_ACCOUNT_POOL_STRATEGY_FAILOVER,
    ROUTE_PROXY_CLIENT_CLAUDE,
    ROUTE_PROXY_CLIENT_CODEX,
    ROUTE_PROXY_PROTOCOL_ANTHROPIC,
    ROUTE_PROXY_PROTOCOL_ANTHROPIC_TO_OPENAI,
    ROUTE_PROXY_PROTOCOL_OPENAI,
    ROUTE_PROXY_PROTOCOL_OPENAI_CHAT_TO_RESPONSES,
    ROUTE_PROXY_PROTOCOL_OPENAI_RESPONSES_TO_CHAT,
    ROUTE_PROXY_UPSTREAM_SOURCE_ACCOUNT_POOL,
    ROUTE_PROXY_UPSTREAM_SOURCE_PROFILE,
    ACCOUNT_POOL_GROUP_TYPE_CLAUDE,
    PROFILE_CATEGORY_IMAGE_GENERATION,
    PROFILE_CATEGORY_TEXT,
    SkillDefinition,
    SkillGroup,
    SkillMarketRepo,
    SKILL_TYPE_CONFIG,
    SKILL_TYPE_SCRIPT,
    VENDOR_CLAUDE,
    VENDOR_CODEX,
    VENDOR_GENERIC,
    VENDOR_OTHER,
    normalize_profile_vendor,
    profile_supports_claude,
    profile_supports_codex,
    today_iso,
)
from codex_switch.project_template import (
    CODEX_SCRIPT_DIRNAME,
    CLAUDE_BASE_URL_ENV_KEY,
    CLAUDE_FALLBACK_MODEL_ENV_KEY,
    CLAUDE_MODEL_ENV_KEY,
    ProjectTemplateResult,
    ProjectTemplateStatus,
)
from codex_switch.codex_config import PROJECT_ROOT_PLACEHOLDER
from codex_switch.storage import DEFAULT_MODEL_BATCH_CONCURRENCY
from codex_switch.skills import SkillSource
from codex_switch.software_update import (
    DEFAULT_SOFTWARE_UPDATE_REPO,
    SoftwareUpdateChecker,
    SoftwareUpdateInfo,
    github_latest_release_api_url,
    github_latest_release_page_url,
    is_newer_version,
    preferred_release_download_url,
    software_update_info_from_github_release,
    software_update_info_from_release_url,
    version_key,
)
from codex_switch.ui.app import (
    CodexSwitchApp,
    GitRemoteUpdate,
    LIBRARY_VIEW_ALL,
    ModelBatchCache,
    ModelBatchResult,
    checksum_manifest_entries,
    git_fetch_ref_candidates,
    git_remote_ref_patterns,
    remote_commit_from_ls_remote,
    same_git_commit,
    model_batch_caches_from_payload,
    model_batch_caches_to_payload,
    model_batch_targets,
    ordered_model_batch_models,
    profile_library_sort_key,
    profiles_for_library_view,
    run_model_batch_requests,
    run_app,
    software_update_error_detail,
    successful_model_batch_models,
    visible_profiles_for_filter,
)
from codex_switch.ui.dialogs import next_api_provided_state_for_category
from codex_switch.ui.global_logic import (
    claude_settings_env_values,
    global_profile_choice_names,
    profile_for_choice_index,
    resolve_global_mcp_server_names,
    resolve_global_profile_id,
)
from codex_switch.ui.account_pool_logic import (
    account_pool_channel_rows,
    account_pool_detail_display,
    account_pool_group_delete_error,
    account_pool_group_choices_display,
    account_pool_summary_text,
    prepare_account_pool_channel_submission,
    resolve_account_pool_group_settings_update,
)
from codex_switch.ui.hot_update_logic import (
    HotUpdateDecisionTexts,
    PROJECT_HOT_UPDATE_TEXTS,
    SKILL_REPO_HOT_UPDATE_TEXTS,
    append_hot_update_event,
    hot_update_event_line,
    hot_update_summary_text,
    process_hot_update_candidate,
)
from codex_switch.ui.library_logic import (
    build_library_detail_display,
    build_library_tab_display,
    build_test_detail_display,
    build_test_tab_display,
    current_status_counts,
    health_override_note,
    health_status_text,
    profile_key_summary,
    profile_library_model_summary,
    profile_library_sort_key,
    profile_model_summary,
    profiles_for_library_view,
    visible_profiles_for_filter,
)
from codex_switch.ui.model_batch_logic import model_batch_counts, model_batch_health_summary
from codex_switch.ui.mcp_logic import (
    mcp_detail_display,
    mcp_contains_project_root,
    mcp_env_summary,
    mcp_list_summary,
    mcp_server_rows,
    mcp_summary,
    mcp_tab_display,
    render_mcp_preview,
    safe_mcp_server_names,
)
from codex_switch.ui.skills_logic import build_skills_tab_display
from codex_switch.ui.project_logic import (
    build_project_edit_application,
    build_project_binding_sync_plan,
    project_binding_sync_tasks,
    build_claude_template_run_spec,
    build_claude_template_execution_plan,
    build_codex_template_run_spec,
    build_codex_template_execution_plan,
    claude_template_success_message,
    claude_project_template_options,
    codex_template_success_message,
    codex_project_template_options,
    preferred_project_script_path,
    project_add_prerequisite_error,
    project_binding_sync_status,
    project_bound_profile_ids,
    project_claude_binding_changed,
    project_claude_cmd_launch_plan,
    project_claude_cmd_command,
    project_claude_settings_edit_plan,
    project_claude_profile_id,
    project_codex_cmd_launch_plan,
    project_codex_config_edit_plan,
    project_codex_cmd_command,
    project_codex_binding_changed,
    project_codex_profile_id,
    project_codex_script_paths,
    project_codex_vscode_launch_plan,
    project_codex_vscode_command,
    project_collection_after_add,
    project_collection_after_delete,
    project_collection_after_replace,
    project_custom_run_command,
    project_custom_run_launch_plan,
    project_duplicate_dir_error,
    project_from_dialog_result,
    project_detail_display,
    project_tab_display,
    project_template_display,
    project_root_path,
    project_text_file_path,
    project_with_metadata_update,
    updated_project_from_dialog,
    project_vscode_launch_plan,
    project_vscode_open_command,
)
from codex_switch.ui.route_proxy_logic import (
    build_route_proxy_project_enable_plan,
    route_proxy_account_pool_choices,
    refresh_route_proxy_rules_for_project,
    route_proxy_base_url_for_project,
    route_proxy_codex_protocol_for_profile,
    route_proxy_detail_display,
    route_proxy_tab_display,
    resolve_route_proxy_project_rule_form,
    route_proxy_rules_for_project,
    route_proxy_rules_for_project_profiles,
)
from codex_switch.ui import windowing
from codex_switch.ui.utils import is_github_repo_url, resolve_mcp_editor_text
from codex_switch.ui.windowing import install_windows_drag_redraw_guard


class _ValueVar:
    def __init__(self, value: str) -> None:
        self.value = value

    def get(self) -> str:
        return self.value

    def set(self, value: str) -> None:
        self.value = value


class _FakeTree:
    def __init__(self) -> None:
        self.rows: list[tuple[str, tuple[str, ...]]] = []

    def delete(self, *items: object) -> None:
        self.rows = []

    def get_children(self) -> list[str]:
        return [item_id for item_id, _values in self.rows]

    def insert(self, _parent: str, _index: str, iid: str | None = None, values: tuple[str, ...] = ()) -> None:
        self.rows.append((iid or str(len(self.rows)), values))


class _DelayedRoot:
    def __init__(self) -> None:
        self.callbacks: list[tuple[int, object]] = []

    def winfo_exists(self) -> bool:
        return True

    def after(self, delay_ms: int, callback) -> None:
        self.callbacks.append((delay_ms, callback))


class _FakeTabFrame:
    def __init__(self) -> None:
        self.grid_calls: list[dict] = []
        self.remove_count = 0
        self.raise_count = 0

    def grid(self, **kwargs) -> None:
        self.grid_calls.append(kwargs)

    def grid_remove(self) -> None:
        self.remove_count += 1

    def tkraise(self) -> None:
        self.raise_count += 1


class _FakeTopNav:
    def __init__(self) -> None:
        self.selected: list[str] = []

    def select(self, key: str) -> None:
        self.selected.append(key)


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _make_minimal_app() -> CodexSwitchApp:
    app = CodexSwitchApp.__new__(CodexSwitchApp)
    app.root = None
    app.profiles = []
    app.projects = []
    app.skill_groups = []
    app.skill_market_repos = []
    app.model_vendor_keywords = {}
    app.hot_update_events = []
    app.status_var = _ValueVar("")
    app.software_update_status_var = _ValueVar("")
    app.software_update_check_running = False
    app.software_update_checked_once = False
    app.skill_market_force_sync = False
    app.skill_repo_preview_var = _ValueVar("")
    app.skill_repo_preview_filter_var = _ValueVar("")
    app.skill_market_filter_var = _ValueVar("")
    app.skill_repo_preview_sources = []
    app.skill_repo_preview_repo_id = ""
    app.persist_count = 0
    app.persist_state = lambda: setattr(app, "persist_count", app.persist_count + 1)
    app.refresh_project_tab = lambda: None
    app.refresh_skills_tab = lambda: None
    app.refresh_library_tab = lambda: None
    return app


class WindowingTests(unittest.TestCase):
    def test_drag_redraw_guard_is_noop_outside_windows(self) -> None:
        with patch("codex_switch.ui.windowing.os.name", "posix"):
            self.assertFalse(install_windows_drag_redraw_guard(object()))

    def test_drag_redraw_guard_is_idempotent_after_install(self) -> None:
        class Widget:
            pass

        widget = Widget()
        setattr(widget, "_codex_switch_drag_redraw_guard", {"installed": True})

        with patch("codex_switch.ui.windowing.os.name", "nt"):
            self.assertTrue(install_windows_drag_redraw_guard(widget))

    def test_drag_redraw_guard_redraw_flags_skip_sync_repaint(self) -> None:
        self.assertEqual(
            windowing._REDRAW_FLAGS,
            windowing._RDW_INVALIDATE | windowing._RDW_ALLCHILDREN,
        )


class SoftwareUpdateTests(unittest.TestCase):
    def test_version_comparison_ignores_prefix_and_prerelease_suffix(self) -> None:
        self.assertEqual(version_key("v1.2.3-beta.1"), (1, 2, 3))
        self.assertTrue(is_newer_version("v1.2.4", "1.2.3"))
        self.assertFalse(is_newer_version("1.2.3", "1.2.3"))

    def test_github_latest_release_url_requires_https_github_repo(self) -> None:
        self.assertEqual(
            github_latest_release_api_url(f"{DEFAULT_SOFTWARE_UPDATE_REPO}.git"),
            "https://api.github.com/repos/shixiansi/codex-switch/releases/latest",
        )
        self.assertEqual(
            github_latest_release_page_url(f"{DEFAULT_SOFTWARE_UPDATE_REPO}.git"),
            "https://github.com/shixiansi/codex-switch/releases/latest",
        )
        with self.assertRaises(ValueError):
            github_latest_release_api_url("http://github.com/shixiansi/codex-switch")

    def test_release_payload_selects_windows_download_asset(self) -> None:
        payload = {
            "tag_name": "v0.3.0",
            "name": "Codex Switch v0.3.0",
            "html_url": "https://github.com/shixiansi/codex-switch/releases/tag/v0.3.0",
            "assets": [
                {
                    "name": "CodexSwitch-linux-x64.tar.gz",
                    "browser_download_url": "https://github.com/shixiansi/codex-switch/releases/download/v0.3.0/CodexSwitch-linux-x64.tar.gz",
                },
                {
                    "name": "CodexSwitch-windows-x64.zip",
                    "browser_download_url": "https://github.com/shixiansi/codex-switch/releases/download/v0.3.0/CodexSwitch-windows-x64.zip",
                },
            ],
        }

        info = software_update_info_from_github_release(payload, "0.2.2")

        self.assertTrue(info.update_available)
        self.assertEqual(info.latest_version, "v0.3.0")
        self.assertEqual(
            info.download_url,
            "https://github.com/shixiansi/codex-switch/releases/download/v0.3.0/CodexSwitch-windows-x64.zip",
        )
        self.assertEqual(
            preferred_release_download_url(payload["assets"]),
            "https://github.com/shixiansi/codex-switch/releases/download/v0.3.0/CodexSwitch-windows-x64.zip",
        )

    def test_release_page_url_extracts_latest_tag(self) -> None:
        info = software_update_info_from_release_url(
            "https://github.com/shixiansi/codex-switch/releases/tag/v0.3.0",
            "0.2.2",
        )

        self.assertTrue(info.update_available)
        self.assertEqual(info.latest_version, "v0.3.0")
        self.assertEqual(info.release_name, "v0.3.0")

    def test_software_update_available_prompts_and_opens_download(self) -> None:
        app = _make_minimal_app()
        info = SoftwareUpdateInfo(
            current_version="0.2.2",
            latest_version="v0.3.0",
            release_url="https://github.com/shixiansi/codex-switch/releases/tag/v0.3.0",
            download_url="https://github.com/shixiansi/codex-switch/releases/download/v0.3.0/CodexSwitch-windows-x64.zip",
            release_name="Codex Switch v0.3.0",
        )

        with (
            patch("codex_switch.ui.app.messagebox.askyesno", return_value=True) as askyesno,
            patch("codex_switch.ui.app.webbrowser.open") as web_open,
        ):
            app._finish_software_update_check(info, "", automatic=True)

        askyesno.assert_called_once()
        web_open.assert_called_once_with("https://github.com/shixiansi/codex-switch/releases/download/v0.3.0/CodexSwitch-windows-x64.zip")
        self.assertIn("发现新版本", app.software_update_status_var.get())
        self.assertEqual([event.status for event in app.hot_update_events], ["available", "opened"])
        self.assertEqual(app.persist_count, 2)

    def test_software_update_current_records_without_prompt_on_startup(self) -> None:
        app = _make_minimal_app()
        info = SoftwareUpdateInfo(
            current_version="0.2.2",
            latest_version="0.2.2",
            release_url="https://github.com/shixiansi/codex-switch/releases/tag/v0.2.2",
        )

        with patch("codex_switch.ui.app.messagebox.askyesno") as askyesno:
            app._finish_software_update_check(info, "", automatic=True)

        askyesno.assert_not_called()
        self.assertIn("当前已是最新版本", app.software_update_status_var.get())
        self.assertEqual([event.status for event in app.hot_update_events], ["current"])

    def test_software_update_error_detail_does_not_record_none(self) -> None:
        app = _make_minimal_app()

        app._finish_software_update_check(None, "None", automatic=True)

        self.assertIn("未能获取 GitHub 最新版本信息", app.software_update_status_var.get())
        self.assertEqual(app.hot_update_events[0].status, "error")
        self.assertNotIn("None", app._hot_update_event_line(app.hot_update_events[0]))

    def test_existing_software_update_none_error_renders_readable_detail(self) -> None:
        app = _make_minimal_app()
        event = HotUpdateEvent.create(
            scope="software",
            target="Codex Switch",
            status="error",
            detail="None",
            automatic=True,
        )

        line = app._hot_update_event_line(event)

        self.assertIn("[自动][软件][错误] Codex Switch", line)
        self.assertIn("未能获取 GitHub 最新版本信息", line)
        self.assertNotIn(" - None", line)

    def test_software_update_checker_handles_empty_url_error_reason(self) -> None:
        checker = SoftwareUpdateChecker(DEFAULT_SOFTWARE_UPDATE_REPO)

        with (
            patch("codex_switch.software_update.request.urlopen", side_effect=url_error.URLError(None)),
            self.assertRaisesRegex(RuntimeError, "unknown network error"),
        ):
            checker.check("0.2.2")

        self.assertEqual(
            software_update_error_detail(None),
            "未能获取 GitHub 最新版本信息，请检查网络或稍后重试。",
        )
        self.assertEqual(
            software_update_error_detail("GitHub update check failed: None"),
            "未能获取 GitHub 最新版本信息，请检查网络或稍后重试。",
        )

    def test_software_update_checker_falls_back_to_release_page_on_api_403(self) -> None:
        class FakeResponse:
            def __init__(self, url: str, body: bytes = b"") -> None:
                self.url = url
                self.body = body

            def __enter__(self):
                return self

            def __exit__(self, *_args) -> None:
                return None

            def read(self) -> bytes:
                return self.body

            def geturl(self) -> str:
                return self.url

        calls: list[str] = []

        def fake_urlopen(req, timeout):
            calls.append(req.full_url)
            if "api.github.com" in req.full_url:
                raise url_error.HTTPError(req.full_url, 403, "rate limited", hdrs=None, fp=None)
            return FakeResponse("https://github.com/shixiansi/codex-switch/releases/tag/v0.3.0")

        checker = SoftwareUpdateChecker(DEFAULT_SOFTWARE_UPDATE_REPO)

        with patch("codex_switch.software_update.request.urlopen", side_effect=fake_urlopen):
            info = checker.check("0.2.2")

        self.assertEqual(
            calls,
            [
                "https://api.github.com/repos/shixiansi/codex-switch/releases/latest",
                "https://github.com/shixiansi/codex-switch/releases/latest",
            ],
        )
        self.assertEqual(info.latest_version, "v0.3.0")
        self.assertTrue(info.update_available)

    def test_startup_software_update_check_runs_once(self) -> None:
        class FakeRoot:
            def winfo_exists(self) -> bool:
                return True

            def after(self, _delay_ms: int, callback) -> None:
                callback()

        app = _make_minimal_app()
        app.root = FakeRoot()
        calls: list[bool] = []
        app._run_software_update_check = lambda *, automatic: calls.append(automatic)

        app._schedule_startup_software_update_check()
        app._schedule_startup_software_update_check()

        self.assertEqual(calls, [True])

    def test_run_app_stops_when_single_instance_exists(self) -> None:
        calls: list[str] = []

        with (
            patch("codex_switch.ui.app._acquire_single_instance", return_value=False),
            patch("codex_switch.ui.app._show_single_instance_message", side_effect=lambda: calls.append("message")),
            patch("codex_switch.ui.app.CodexSwitchApp", side_effect=AssertionError("should not create app")),
        ):
            run_app()

        self.assertEqual(calls, ["message"])


class UiFilterTests(unittest.TestCase):
    def test_github_repo_url_validation_requires_trusted_https_repo(self) -> None:
        accepted = (
            "https://github.com/example/skills",
            "https://github.com/example/skills.git",
            "https://www.github.com/example/project",
        )
        rejected = (
            "http://github.com/example/skills",
            "https://gitlab.com/example/skills",
            "https://github.com.evil/example/skills",
            "https://github.com/example",
            "https://github.com/example/skills/tree/main",
            "https://github.com/example/skills?tab=readme",
            "not-a-url",
        )

        for url in accepted:
            self.assertTrue(is_github_repo_url(url), url)
        for url in rejected:
            self.assertFalse(is_github_repo_url(url), url)

    def test_checksum_manifest_rejects_unsafe_paths(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "unsafe path"):
            checksum_manifest_entries({"sha256": {"../outside.txt": "0" * 64}})

        with self.assertRaisesRegex(RuntimeError, "unsafe path"):
            checksum_manifest_entries({"files": [{"path": "C:/outside.txt", "sha256": "0" * 64}]})

    def test_git_ref_helpers_support_branches_tags_and_commits(self) -> None:
        self.assertEqual(
            git_remote_ref_patterns("main"),
            ["refs/heads/main", "refs/tags/main^{}", "refs/tags/main", "main"],
        )
        self.assertEqual(git_fetch_ref_candidates("v1.0.0"), ["v1.0.0", "refs/heads/v1.0.0", "refs/tags/v1.0.0"])
        self.assertEqual(
            remote_commit_from_ls_remote(
                "tag-object refs/tags/v1.0.0\ncommit-object refs/tags/v1.0.0^{}\n",
                "v1.0.0",
            ),
            "commit-object",
        )
        commit_hash = "a" * 40
        self.assertEqual(git_remote_ref_patterns(commit_hash), [])
        self.assertEqual(git_fetch_ref_candidates(commit_hash), [commit_hash])
        self.assertTrue(same_git_commit(commit_hash, commit_hash.upper()))

    def test_other_vendor_is_not_a_codex_or_claude_binding(self) -> None:
        profile = Profile.create("other", "https://other.example.com", "sk-other", vendor=VENDOR_OTHER)

        self.assertEqual(normalize_profile_vendor("other"), VENDOR_OTHER)
        self.assertEqual(profile.vendor, VENDOR_OTHER)
        self.assertEqual(profile.vendor_label, "其他")
        self.assertFalse(profile_supports_codex(profile))
        self.assertFalse(profile_supports_claude(profile))

    def test_image_generation_without_api_is_not_bindable(self) -> None:
        profile = Profile.create(
            "image",
            "",
            "",
            category=PROFILE_CATEGORY_IMAGE_GENERATION,
            api_provided=False,
        )

        self.assertFalse(profile.api_provided)
        self.assertFalse(profile_supports_codex(profile))
        self.assertFalse(profile_supports_claude(profile))

    def test_image_generation_category_defaults_to_no_api(self) -> None:
        self.assertFalse(
            next_api_provided_state_for_category(
                PROFILE_CATEGORY_TEXT,
                PROFILE_CATEGORY_IMAGE_GENERATION,
                True,
            )
        )
        self.assertTrue(
            next_api_provided_state_for_category(
                PROFILE_CATEGORY_IMAGE_GENERATION,
                PROFILE_CATEGORY_TEXT,
                False,
            )
        )
        self.assertTrue(
            next_api_provided_state_for_category(
                PROFILE_CATEGORY_IMAGE_GENERATION,
                PROFILE_CATEGORY_IMAGE_GENERATION,
                True,
            )
        )

    def test_visible_profiles_for_filter_hides_error_profiles(self) -> None:
        healthy = Profile.create("healthy", "https://healthy.example.com", "sk-healthy")
        healthy.health = HealthResult(status="healthy")
        error = Profile.create("error", "https://error.example.com", "sk-error")
        error.health = HealthResult(status="error")
        manual_error = Profile.create("manual-error", "https://manual.example.com", "sk-manual")
        manual_error.health = HealthResult(status="healthy")
        manual_error.manual_health_status = "error"

        profiles = [healthy, error, manual_error]

        self.assertEqual(visible_profiles_for_filter(profiles, False), profiles)
        self.assertEqual(visible_profiles_for_filter(profiles, True), [healthy])

    def test_profiles_for_library_view_filters_all_codex_claude_and_other(self) -> None:
        codex = Profile.create("codex", "https://codex.example.com", "sk-codex", vendor=VENDOR_CODEX)
        claude = Profile.create("claude", "https://claude.example.com", "sk-claude", vendor=VENDOR_CLAUDE)
        generic = Profile.create("generic", "https://generic.example.com", "sk-generic", vendor=VENDOR_GENERIC)
        other = Profile.create("other", "https://other.example.com", "sk-other", vendor=VENDOR_OTHER)
        profiles = [codex, claude, generic, other]

        self.assertEqual(profiles_for_library_view(profiles, LIBRARY_VIEW_ALL), profiles)
        self.assertEqual(profiles_for_library_view(profiles, VENDOR_CODEX), [codex, generic])
        self.assertEqual(profiles_for_library_view(profiles, VENDOR_CLAUDE), [claude, generic])
        self.assertEqual(profiles_for_library_view(profiles, VENDOR_OTHER), [other])

    def test_library_logic_helpers_build_tab_and_detail_display(self) -> None:
        codex = Profile.create("codex", "https://codex.example.com", "sk-codex", vendor=VENDOR_CODEX)
        codex.health = HealthResult(status="healthy", models=["gpt-5"])
        claude = Profile.create("claude", "https://claude.example.com", "sk-claude", vendor=VENDOR_CLAUDE)
        claude.health = HealthResult(status="degraded", models=["sonnet"])
        claude.manual_health_status = "degraded"

        tab = build_library_tab_display(
            [codex, claude],
            hide_error_profiles=False,
            library_profile_view=LIBRARY_VIEW_ALL,
            selected_profile_id="missing",
            library_view_all=LIBRARY_VIEW_ALL,
            library_tree_columns=("name", "base_url", "model", "sign_in", "health"),
            library_tree_columns_with_vendor=("name", "vendor", "base_url", "model", "sign_in", "health"),
            profile_tree_iid=lambda scope, profile: f"{scope}:{profile.id}",
            scope_label_map={LIBRARY_VIEW_ALL: "全部"},
            status_text={"healthy": "健康", "degraded": "降级", "error": "异常", "unknown": "未知"},
        )
        detail = build_library_detail_display(
            claude,
            status_text={"healthy": "健康", "degraded": "降级", "error": "异常", "unknown": "未知"},
        )

        self.assertEqual(current_status_counts([codex, claude]), (2, 1, 1, 0))
        self.assertEqual(tab.selected_profile_id, codex.id)
        self.assertEqual(tab.display_columns, ("name", "vendor", "base_url", "model", "sign_in", "health"))
        self.assertEqual({row.item_id for row in tab.rows}, {f"{LIBRARY_VIEW_ALL}:{codex.id}", f"{LIBRARY_VIEW_ALL}:{claude.id}"})
        self.assertIn("全部 共 2 个配置", tab.hint_text)
        self.assertIn("降级", health_status_text(claude, {"degraded": "降级"}))
        self.assertIn("手动", health_status_text(claude, {"degraded": "降级"}))
        self.assertIn("*", profile_key_summary(codex))
        self.assertIn("Claude", profile_model_summary(claude))
        self.assertEqual(profile_library_model_summary(codex, LIBRARY_VIEW_ALL), codex.codex_display_model)
        self.assertIn("自动健康状态", health_override_note(None))
        self.assertEqual(detail.selected_name, claude.name)
        self.assertEqual(detail.badge_state, "degraded")
        self.assertEqual(detail.model_tags, ["sonnet"])

    def test_library_logic_build_test_detail_display_formats_health_details(self) -> None:
        profile = Profile.create("api", "https://api.example.com", "sk-api", vendor=VENDOR_CODEX)
        profile.health = HealthResult(
            status="healthy",
            detail="all good",
            models=["gpt-5"],
            endpoint="/models",
            checked_at="2026-07-05T12:00:00",
            latency_ms=120,
        )
        profile.notes = "note"
        profile.manual_health_status = "healthy"

        detail = build_test_detail_display(
            profile,
            status_text={"healthy": "健康", "degraded": "降级", "error": "异常", "unknown": "未知"},
            key_summary=profile_key_summary,
            model_summary=profile_model_summary,
            success_models_text="gpt-5",
            health_override_display_map={"": "自动", "healthy": "健康"},
        )

        self.assertEqual(detail.selected_name, profile.name)
        self.assertIn("健康", detail.health_text)
        self.assertEqual(detail.endpoint_text, "/models")
        self.assertIn("120 ms", detail.checked_text)
        self.assertEqual(detail.result_text, "all good")
        self.assertEqual(detail.success_models_text, "gpt-5")
        self.assertEqual(detail.health_override_value, "健康")
        self.assertEqual(detail.health_override_state, "readonly")

    def test_library_logic_build_test_tab_display_selects_first_visible_profile(self) -> None:
        healthy = Profile.create("healthy", "https://healthy.example.com", "sk-healthy", vendor=VENDOR_CODEX)
        healthy.health = HealthResult(status="healthy")
        hidden = Profile.create("hidden", "https://hidden.example.com", "sk-hidden", vendor=VENDOR_CODEX)
        hidden.health = HealthResult(status="error")

        display = build_test_tab_display(
            [healthy, hidden],
            hide_error_profiles=True,
            selected_profile_id="missing",
            status_text={"healthy": "健康", "degraded": "降级", "error": "异常", "unknown": "未知"},
        )

        self.assertEqual(display.selected_profile_id, healthy.id)
        self.assertEqual(len(display.rows), 1)
        self.assertEqual(display.rows[0].profile_id, healthy.id)
        self.assertEqual(display.rows[0].values[0], "healthy")
        self.assertIn("健康", display.rows[0].values[1])

    def test_library_model_tags_show_first_twenty_and_summary(self) -> None:
        app = _make_minimal_app()
        app.selected_profile_id = None
        app.library_models_summary_var = _ValueVar("")
        app.library_model_stats_button_var = _ValueVar("")
        app.library_model_stats_expanded = False
        models = [f"gpt-model-{index}" for index in range(25)]

        app._render_library_model_tags(models, "empty")

        self.assertEqual(app.library_model_tag_models, models[:20])
        self.assertIn("共 25 个模型", app.library_models_summary_var.get())
        self.assertIn("隐藏 5 个", app.library_models_summary_var.get())
        self.assertIn("OpenAI 25", app.library_models_summary_var.get())

    def test_library_model_tag_layout_wraps_by_width(self) -> None:
        class FakeFrame:
            def __init__(self) -> None:
                self.columns: list[int] = []

            def columnconfigure(self, column: int, weight: int) -> None:
                self.columns.append(column)

        class FakeTag:
            def __init__(self) -> None:
                self.grid_calls: list[dict] = []

            def grid(self, **kwargs) -> None:
                self.grid_calls.append(kwargs)

        app = _make_minimal_app()
        tags = [FakeTag() for _ in range(5)]
        app.library_model_tags_frame = FakeFrame()
        app.library_model_tag_widgets = [(f"model-{index}", tag) for index, tag in enumerate(tags)]

        app._layout_library_model_tags(560)

        self.assertEqual([tag.grid_calls[-1]["row"] for tag in tags], [0, 0, 0, 1, 1])
        self.assertEqual([tag.grid_calls[-1]["column"] for tag in tags], [0, 1, 2, 0, 1])
        grid_counts = [len(tag.grid_calls) for tag in tags]

        app._layout_library_model_tags(600)

        self.assertEqual([len(tag.grid_calls) for tag in tags], grid_counts)

        app._layout_library_model_tags(190)

        self.assertEqual([tag.grid_calls[-1]["row"] for tag in tags], [0, 1, 2, 3, 4])
        self.assertEqual([tag.grid_calls[-1]["column"] for tag in tags], [0, 0, 0, 0, 0])

    def test_show_tab_grids_only_selected_frame(self) -> None:
        app = _make_minimal_app()
        app.top_nav = _FakeTopNav()
        app.tab_frames = {
            "global": _FakeTabFrame(),
            "library": _FakeTabFrame(),
            "settings": _FakeTabFrame(),
        }

        app._show_tab("library")

        self.assertEqual(app.tab_frames["library"].grid_calls, [{"row": 0, "column": 0, "sticky": "nsew"}])
        self.assertEqual(app.tab_frames["library"].raise_count, 1)
        self.assertEqual(app.tab_frames["global"].remove_count, 1)
        self.assertEqual(app.tab_frames["settings"].remove_count, 1)
        self.assertEqual(app.top_nav.selected, ["library"])

    def test_global_profile_ids_are_resolved_per_target(self) -> None:
        codex = Profile.create("codex", "https://codex.example.com", "sk-codex", vendor=VENDOR_CODEX)
        claude = Profile.create("claude", "https://claude.example.com", "sk-claude", vendor=VENDOR_CLAUDE)
        generic = Profile.create("generic", "https://generic.example.com", "sk-generic", vendor=VENDOR_GENERIC)
        profiles = [codex, claude, generic]

        self.assertEqual(resolve_global_profile_id(None, generic.id, profiles, profile_supports_codex), generic.id)
        self.assertEqual(resolve_global_profile_id(claude.id, generic.id, profiles, profile_supports_codex), generic.id)
        self.assertEqual(resolve_global_profile_id(claude.id, codex.id, profiles, profile_supports_claude), claude.id)

    def test_global_mcp_selection_filters_saved_names(self) -> None:
        available = ["filesystem", "serena", "context7"]

        self.assertEqual(resolve_global_mcp_server_names(None, opt_out=False, available_names=available), available)
        self.assertEqual(
            resolve_global_mcp_server_names(["serena", "missing"], opt_out=False, available_names=available),
            ["serena"],
        )
        self.assertEqual(resolve_global_mcp_server_names(["serena"], opt_out=True, available_names=available), [])

    def test_global_profile_choice_names_show_only_names_and_keep_index_identity(self) -> None:
        first = Profile.create("same", "https://first.example.com", "sk-first", vendor=VENDOR_CODEX)
        second = Profile.create("same", "https://second.example.com", "sk-second", vendor=VENDOR_CODEX)
        profiles = [first, second]

        self.assertEqual(global_profile_choice_names(profiles), ("same", "same"))
        self.assertIs(profile_for_choice_index(profiles, 1), second)
        self.assertIsNone(profile_for_choice_index(profiles, -1))
        self.assertIsNone(profile_for_choice_index(profiles, 2))

    def test_claude_settings_env_values_read_api_and_models(self) -> None:
        settings = {
            "env": {
                CLAUDE_BASE_URL_ENV_KEY: "https://claude.example.com",
                CLAUDE_MODEL_ENV_KEY: "sonnet",
                CLAUDE_FALLBACK_MODEL_ENV_KEY: "haiku",
            }
        }

        self.assertEqual(
            claude_settings_env_values(
                settings,
                base_url_key=CLAUDE_BASE_URL_ENV_KEY,
                model_key=CLAUDE_MODEL_ENV_KEY,
                fallback_model_key=CLAUDE_FALLBACK_MODEL_ENV_KEY,
            ),
            ("https://claude.example.com", "sonnet", "haiku"),
        )
        self.assertEqual(
            claude_settings_env_values(
                {},
                base_url_key=CLAUDE_BASE_URL_ENV_KEY,
                model_key=CLAUDE_MODEL_ENV_KEY,
                fallback_model_key=CLAUDE_FALLBACK_MODEL_ENV_KEY,
            ),
            ("-", "-", "-"),
        )

    def test_profile_library_sort_key_prioritizes_unsigned_profiles(self) -> None:
        signed = Profile.create(
            "b-signed",
            "https://signed.example.com",
            "sk-signed",
            requires_sign_in=True,
            last_signed_date=today_iso(),
        )
        no_sign_in = Profile.create("a-no-sign", "https://no-sign.example.com", "sk-no-sign")
        unsigned = Profile.create(
            "c-unsigned",
            "https://unsigned.example.com",
            "sk-unsigned",
            requires_sign_in=True,
        )

        profiles = sorted([no_sign_in, signed, unsigned], key=profile_library_sort_key)

        self.assertEqual([profile.name for profile in profiles], ["c-unsigned", "b-signed", "a-no-sign"])

    def test_model_batch_targets_use_latest_health_models(self) -> None:
        profile = Profile.create("api", "https://api.example.com", "sk-api")
        profile.health = HealthResult(status="healthy", models=["gpt-5.5", " ", "gpt-5.5", "gpt-5.4"])

        self.assertEqual(model_batch_targets(profile), ["gpt-5.5", "gpt-5.4"])
        self.assertEqual(model_batch_targets(None), [])

    def test_model_batch_completed_results_sort_success_first(self) -> None:
        models = ["gpt-5.5", "gpt-5.4", "gpt-4.1"]
        results = {
            "gpt-5.5": ModelBatchResult(status="error"),
            "gpt-5.4": ModelBatchResult(status="success"),
            "gpt-4.1": ModelBatchResult(status="success"),
        }

        self.assertEqual(ordered_model_batch_models(models, results, completed=True), ["gpt-5.4", "gpt-4.1", "gpt-5.5"])
        self.assertEqual(ordered_model_batch_models(models, results, completed=False), models)

    def test_successful_model_batch_models_return_success_only(self) -> None:
        cache = ModelBatchCache(
            models=["m1", "m2", "m3"],
            results={
                "m1": ModelBatchResult(status="error"),
                "m2": ModelBatchResult(status="success"),
                "m3": ModelBatchResult(status="pending"),
            },
            completed=True,
        )

        self.assertEqual(successful_model_batch_models(cache), ["m2"])
        cache.completed = False
        self.assertEqual(successful_model_batch_models(cache), [])

    def test_model_batch_logic_helpers_render_summary_and_counts(self) -> None:
        running = ModelBatchCache(
            models=["m1", "m2"],
            results={
                "m1": ModelBatchResult(status="success"),
                "m2": ModelBatchResult(status="running"),
            },
            completed=False,
        )
        completed = ModelBatchCache(
            models=["m1", "m2"],
            results={
                "m1": ModelBatchResult(status="success"),
                "m2": ModelBatchResult(status="error"),
            },
            completed=True,
        )

        self.assertEqual(model_batch_health_summary(None), "未执行测试")
        self.assertIn("完成 1/2", model_batch_health_summary(running))
        self.assertEqual(model_batch_health_summary(completed), "m1")
        self.assertEqual(model_batch_counts(completed), (1, 1))

    def test_model_batch_cache_payload_roundtrip_completed_only(self) -> None:
        caches = {
            "done": ModelBatchCache(
                models=["m1", "m2"],
                results={
                    "m1": ModelBatchResult(status="success", detail="ok", duration_ms=120),
                    "m2": ModelBatchResult(status="error", detail="bad", duration_ms=30_000),
                },
                completed=True,
                tested_at="2026-05-20T12:00:00",
            ),
            "running": ModelBatchCache(
                models=["m3"],
                results={"m3": ModelBatchResult(status="running")},
                completed=False,
            ),
        }

        payload = model_batch_caches_to_payload(caches)
        self.assertEqual(set(payload.keys()), {"done"})

        restored = model_batch_caches_from_payload(payload)
        self.assertEqual(restored["done"].models, ["m1", "m2"])
        self.assertTrue(restored["done"].completed)
        self.assertEqual(restored["done"].results["m1"].status, "success")
        self.assertEqual(restored["done"].results["m2"].detail, "bad")
        self.assertEqual(restored["done"].results["m1"].duration_ms, 120)
        self.assertEqual(restored["done"].results["m2"].duration_ms, 30_000)

    def test_run_model_batch_requests_uses_three_concurrent_requests(self) -> None:
        class FakeChatTester:
            def __init__(self) -> None:
                self.active = 0
                self.max_active = 0
                self.lock = threading.Lock()

            def send_message(self, profile, prompt, model_override=None, wire_api_override=None, payload_override_text=None):
                with self.lock:
                    self.active += 1
                    self.max_active = max(self.max_active, self.active)
                try:
                    time.sleep(0.03)
                    return ChatResult(ok=True, text=f"ok {model_override}")
                finally:
                    with self.lock:
                        self.active -= 1

        profile = Profile.create("api", "https://api.example.com", "sk-api")
        models = [f"model-{index}" for index in range(8)]
        tester = FakeChatTester()
        started: list[str] = []
        results: list[tuple[str, str, str, int]] = []

        run_model_batch_requests(
            tester,
            profile,
            models,
            "responses",
            None,
            started.append,
            lambda model, status, detail, duration_ms: results.append((model, status, detail, duration_ms)),
        )

        self.assertEqual(set(started), set(models))
        self.assertEqual({model for model, _, _, _ in results}, set(models))
        self.assertTrue(all(status == "success" for _, status, _, _ in results))
        self.assertTrue(all(duration_ms >= 0 for _, _, _, duration_ms in results))
        self.assertEqual(tester.max_active, 3)

    def test_project_binding_helpers_keep_legacy_profile_fallback(self) -> None:
        project = ProjectRecord.create(
            str(Path.cwd()),
            "legacy-profile",
            codex_profile_id="codex-profile",
            claude_profile_id="claude-profile",
        )
        legacy_project = replace(project, codex_profile_id="", claude_profile_id="")

        self.assertEqual(project_codex_profile_id(project), "codex-profile")
        self.assertEqual(project_claude_profile_id(project), "claude-profile")
        self.assertEqual(project_codex_profile_id(legacy_project), "legacy-profile")
        self.assertEqual(project_claude_profile_id(legacy_project), "legacy-profile")
        self.assertEqual(project_bound_profile_ids(project), {"legacy-profile", "codex-profile", "claude-profile"})

    def test_project_binding_change_helpers_match_sync_boundaries(self) -> None:
        project = ProjectRecord.create(
            str(Path.cwd()),
            "codex-profile",
            codex_profile_id="codex-profile",
            claude_profile_id="claude-profile",
        )

        self.assertFalse(project_codex_binding_changed(project, replace(project, name="renamed")))
        self.assertFalse(project_claude_binding_changed(project, replace(project, name="renamed")))
        self.assertTrue(project_codex_binding_changed(project, replace(project, codex_profile_id="new-codex")))
        self.assertFalse(project_claude_binding_changed(project, replace(project, codex_profile_id="new-codex")))
        self.assertFalse(project_codex_binding_changed(project, replace(project, claude_profile_id="new-claude")))
        self.assertTrue(project_claude_binding_changed(project, replace(project, claude_profile_id="new-claude")))
        self.assertTrue(project_codex_binding_changed(project, replace(project, project_dir=str(Path.cwd() / "next"))))
        self.assertTrue(project_claude_binding_changed(project, replace(project, project_dir=str(Path.cwd() / "next"))))

    def test_project_edit_update_and_binding_sync_helpers_build_expected_data(self) -> None:
        project = ProjectRecord.create(
            str(Path.cwd()),
            "legacy-profile",
            codex_profile_id="codex-profile",
            claude_profile_id="claude-profile",
            github_repo="https://github.com/example/project",
            github_ref="main",
            github_last_sync_commit="oldcommit",
        )
        result = {
            "name": "renamed",
            "project_dir": str(Path.cwd() / "next"),
            "profile_id": "legacy-profile",
            "codex_profile_id": "new-codex",
            "claude_profile_id": "new-claude",
            "run_command": "npm run dev",
            "mcp_server_names": ["alpha"],
            "skill_names": ["frontend-dev"],
            "skill_group_ids": [],
            "skills": [],
            "github_repo": "https://github.com/example/project",
            "github_ref": "release",
            "github_auto_update": True,
        }

        update = updated_project_from_dialog(project, result, updated_at="2026-07-05T00:00:00")
        codex_profile = Profile.create("codex", "https://codex.example.com", "sk-codex")
        claude_profile = Profile.create("claude", "https://claude.example.com", "sk-claude", vendor=VENDOR_CLAUDE)
        plan = build_project_binding_sync_plan(
            update.project,
            route_proxy_base_url="http://proxy.local",
            codex_profile=codex_profile,
            codex_model_override="gpt-5",
            claude_profile=claude_profile,
            claude_model_override="sonnet",
            claude_fallback_model_override="haiku",
            sync_codex=True,
            sync_claude=False,
        )

        self.assertEqual(update.project.name, "renamed")
        self.assertEqual(update.project.github_last_sync_commit, "")
        self.assertTrue(update.codex_binding_changed)
        self.assertTrue(update.claude_binding_changed)
        self.assertEqual(plan.project_root, Path(result["project_dir"]))
        self.assertEqual(plan.route_proxy_base_url, "http://proxy.local")
        self.assertEqual(plan.codex_profile, codex_profile)
        self.assertEqual(plan.codex_model_override, "gpt-5")
        self.assertEqual(plan.claude_profile, claude_profile)
        self.assertFalse(plan.sync_claude)
        tasks = project_binding_sync_tasks(plan)
        self.assertEqual([task.target for task in tasks], ["codex"])
        self.assertEqual(tasks[0].failure_status, "Codex API 配置同步失败")
        self.assertEqual(project_binding_sync_status("Demo", [Path("a.txt")]), "已同步项目配置：Demo")

    def test_project_add_prerequisite_error_requires_profiles_and_both_clients(self) -> None:
        codex_profile = Profile.create("codex", "https://codex.example.com", "sk-codex", vendor=VENDOR_CODEX)
        claude_profile = Profile.create("claude", "https://claude.example.com", "sk-claude", vendor=VENDOR_CLAUDE)

        self.assertEqual(
            project_add_prerequisite_error([], supports_codex=profile_supports_codex, supports_claude=profile_supports_claude),
            "请先添加至少一套可用配置。",
        )
        self.assertEqual(
            project_add_prerequisite_error(
                [codex_profile],
                supports_codex=profile_supports_codex,
                supports_claude=profile_supports_claude,
            ),
            "请先准备可用于 Codex 和 Claude 的配置。通用配置可同时用于两侧。",
        )
        self.assertIsNone(
            project_add_prerequisite_error(
                [codex_profile, claude_profile],
                supports_codex=profile_supports_codex,
                supports_claude=profile_supports_claude,
            )
        )

        other_project = ProjectRecord.create(str(Path.cwd() / "other"), "profile-x", name="Other")
        self.assertEqual(project_duplicate_dir_error(other_project), "该项目目录已经添加过了。")
        self.assertEqual(
            project_duplicate_dir_error(other_project, current_project_id="current-id"),
            "该项目目录已经绑定到另一个项目。",
        )
        self.assertIsNone(project_duplicate_dir_error(other_project, current_project_id=other_project.id))

    def test_project_from_dialog_result_creates_project_with_expected_fields(self) -> None:
        result = {
            "project_dir": str(Path.cwd() / "demo"),
            "profile_id": "profile-id",
            "name": "Demo",
            "run_command": "npm run dev",
            "mcp_server_names": ["alpha"],
            "skill_names": ["frontend-dev"],
            "skill_group_ids": ["group-1"],
            "skills": [],
            "github_repo": "https://github.com/example/project",
            "github_ref": "release",
            "github_auto_update": True,
            "codex_profile_id": "codex-profile",
            "claude_profile_id": "claude-profile",
        }

        project = project_from_dialog_result(result)

        self.assertEqual(project.project_dir, result["project_dir"])
        self.assertEqual(project.profile_id, "profile-id")
        self.assertEqual(project.name, "Demo")
        self.assertEqual(project.run_command, "npm run dev")
        self.assertEqual(project.github_repo, result["github_repo"])
        self.assertEqual(project.github_ref, "release")
        self.assertTrue(project.github_auto_update)
        self.assertEqual(project.codex_profile_id, "codex-profile")
        self.assertEqual(project.claude_profile_id, "claude-profile")

    def test_project_collection_helpers_update_selected_project(self) -> None:
        first = ProjectRecord.create(str(Path.cwd() / "first"), "profile-a", name="First")
        second = ProjectRecord.create(str(Path.cwd() / "second"), "profile-b", name="Second")
        third = replace(second, name="Third")

        add_update = project_collection_after_add([first], second)
        replace_update = project_collection_after_replace([first, second], third)

        delete_update = project_collection_after_delete(
            [first, second],
            selected_project_id=first.id,
            deleted_project_id=first.id,
        )

        self.assertEqual(add_update.projects, [first, second])
        self.assertEqual(add_update.selected_project_id, second.id)
        self.assertEqual(replace_update.projects, [first, third])
        self.assertEqual(replace_update.selected_project_id, third.id)
        self.assertEqual(delete_update.projects, [second])
        self.assertEqual(delete_update.selected_project_id, second.id)
        self.assertEqual(project_binding_sync_status("Demo", []), "已更新项目：Demo")

    def test_build_project_edit_application_uses_binding_change_flags(self) -> None:
        project = ProjectRecord.create(
            str(Path.cwd()),
            "legacy-profile",
            codex_profile_id="codex-profile",
            claude_profile_id="claude-profile",
        )
        result = {
            "name": "renamed",
            "project_dir": str(Path.cwd() / "next"),
            "profile_id": "legacy-profile",
            "codex_profile_id": "new-codex",
            "claude_profile_id": "new-claude",
            "run_command": "npm run dev",
            "mcp_server_names": ["alpha"],
            "skill_names": ["frontend-dev"],
            "skill_group_ids": [],
            "skills": [],
            "github_repo": "",
            "github_ref": "HEAD",
            "github_auto_update": False,
        }

        application = build_project_edit_application(project, result, updated_at="2026-07-05T00:00:00")

        self.assertEqual(application.project.name, "renamed")
        self.assertTrue(application.sync_codex)
        self.assertTrue(application.sync_claude)

    def test_project_with_metadata_update_returns_none_when_nothing_changes(self) -> None:
        skill = SkillDefinition.create("helper", content="content")
        project = ProjectRecord.create(
            str(Path.cwd()),
            "codex-profile",
            codex_profile_id="codex-profile",
            claude_profile_id="claude-profile",
            skill_group_ids=["group-1"],
            skills=[skill],
            skill_names=[skill.name],
        )

        unchanged = project_with_metadata_update(
            project,
            skill_group_ids=["group-1"],
            skills=[skill],
            skill_names=[skill.name],
            codex_profile_id="codex-profile",
            claude_profile_id="claude-profile",
            updated_at="2026-07-05T00:00:00",
        )
        updated = project_with_metadata_update(
            project,
            skill_group_ids=["group-2"],
            skills=[],
            skill_names=[],
            codex_profile_id="new-codex",
            claude_profile_id="new-claude",
            updated_at="2026-07-05T00:00:00",
        )

        self.assertIsNone(unchanged)
        self.assertIsNotNone(updated)
        self.assertEqual(updated.skill_group_ids, ["group-2"])
        self.assertEqual(updated.profile_id, "new-codex")

    def test_project_detail_display_covers_empty_and_filled_states(self) -> None:
        empty = project_detail_display(None)
        self.assertEqual(empty.selected_name_text, "未选择项目")
        self.assertEqual(empty.badge_text, "未生成")

        project = ProjectRecord.create(str(Path.cwd()), "profile-id", name="Demo")
        filled = project_detail_display(
            project,
            github_text="repo@HEAD",
            github_update_text="auto / abc",
            script_text="start.ps1",
            run_text="npm run dev",
            mcp_text="mcp summary",
            skills_text="skills summary",
            codex_profile_texts=("codex", "gpt-5", "key"),
            claude_profile_texts=("claude", "sonnet", "key"),
            template_display=project_template_display(project_root_exists=True, status=None),
        )

        self.assertEqual(filled.selected_name_text, "Demo")
        self.assertEqual(filled.github_text, "repo@HEAD")
        self.assertEqual(filled.script_text, "start.ps1")
        self.assertEqual(filled.selected_codex_model_text, "gpt-5")
        self.assertEqual(filled.selected_claude_model_text, "sonnet")

    def test_project_launch_helpers_build_paths_and_commands(self) -> None:
        with workspace_tempdir() as temp_dir:
            project = ProjectRecord.create(str(temp_dir), "profile-id")
            ps1_path, cmd_path = project_codex_script_paths(project)
            script_root = temp_dir / CODEX_SCRIPT_DIRNAME

            self.assertEqual(project_root_path(project), temp_dir)
            self.assertEqual(
                project_text_file_path(project, ".codex/home/config.toml"),
                temp_dir / ".codex" / "home" / "config.toml",
            )
            self.assertEqual(ps1_path, script_root / "start-codex.ps1")
            self.assertEqual(cmd_path, script_root / "start-codex.cmd")
            self.assertEqual(preferred_project_script_path(project), ps1_path)

            cmd_path.parent.mkdir(parents=True, exist_ok=True)
            cmd_path.write_text("@echo off\n", encoding="utf-8")

            self.assertEqual(preferred_project_script_path(project), cmd_path)
            self.assertEqual(project_vscode_open_command(project), ("cmd.exe", "/c", "code.cmd", str(temp_dir)))
            self.assertIsNone(project_custom_run_command(project))
            self.assertEqual(
                project_custom_run_command(replace(project, run_command=" npm run dev ")),
                ("cmd.exe", "/k", "npm run dev"),
            )
            self.assertEqual(
                project_codex_vscode_command(ps1_path),
                ("powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(ps1_path)),
            )
            self.assertEqual(project_codex_cmd_command(cmd_path), ("cmd.exe", "/k", str(cmd_path)))
            self.assertEqual(project_claude_cmd_command(), ("cmd.exe", "/k", "claude"))

            codex_edit = project_codex_config_edit_plan(project)
            claude_edit = project_claude_settings_edit_plan(project)
            self.assertEqual(codex_edit.path, temp_dir / ".codex" / "home" / "config.toml")
            self.assertEqual(claude_edit.path, temp_dir / ".claude" / "settings.local.json")

            vscode_plan = project_vscode_launch_plan(project)
            custom_plan = project_custom_run_launch_plan(replace(project, run_command=" npm run dev "))
            codex_vscode_plan = project_codex_vscode_launch_plan(project)
            codex_cmd_plan = project_codex_cmd_launch_plan(project)
            claude_cmd_plan = project_claude_cmd_launch_plan(project)

            self.assertEqual(vscode_plan.command, ("cmd.exe", "/c", "code.cmd", str(temp_dir)))
            self.assertEqual(vscode_plan.cwd, temp_dir)
            self.assertEqual(vscode_plan.success_status, f"使用 VS Code 打开项目：{project.name}")
            self.assertIsNotNone(custom_plan)
            self.assertEqual(custom_plan.command, ("cmd.exe", "/k", "npm run dev"))
            self.assertEqual(custom_plan.cwd, temp_dir)
            self.assertEqual(codex_vscode_plan.required_path, ps1_path)
            self.assertEqual(codex_vscode_plan.command, ("powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(ps1_path)))
            self.assertEqual(codex_cmd_plan.required_path, cmd_path)
            self.assertEqual(codex_cmd_plan.command, ("cmd.exe", "/k", str(cmd_path)))
            self.assertEqual(claude_cmd_plan.command, ("cmd.exe", "/k", "claude"))
            self.assertEqual(claude_cmd_plan.cwd, temp_dir)

    def test_mcp_logic_helpers_summarize_and_preview(self) -> None:
        raw_toml = """
[mcp_servers.alpha]
command = "python"
args = ["-m", "alpha"]

[mcp_servers.beta]
command = "node"
""".strip()

        self.assertEqual(safe_mcp_server_names(raw_toml), ["alpha", "beta"])
        self.assertEqual(mcp_summary(raw_toml), "2 个服务：alpha, beta")
        self.assertTrue(mcp_contains_project_root({"cwd": PROJECT_ROOT_PLACEHOLDER}))
        self.assertEqual(mcp_list_summary(["a", "b"], limit=20), "a b")
        self.assertEqual(mcp_env_summary({"A": "1", "B": "2"}, limit=20), "A, B")
        preview = render_mcp_preview("alpha", {"alpha": {"command": "python", "args": ["-m", "alpha"]}})
        self.assertIn("[mcp_servers.alpha]", preview)
        self.assertEqual(render_mcp_preview(None, {}), "")

    def test_mcp_tab_display_and_detail_helpers_build_rows_and_selection(self) -> None:
        page_servers = {
            "beta": {"type": "stdio", "command": "node", "args": ["beta"], "cwd": "/tmp", "env": {"A": "1"}},
            "alpha": {"type": "stdio", "command": "python", "args": ["-m", "alpha"], "cwd": "", "env": {}},
        }

        rows = mcp_server_rows(page_servers)
        display = mcp_tab_display(page_servers, selected_name="missing", global_mcp_opt_out=False)
        detail = mcp_detail_display("alpha", page_servers)

        self.assertEqual([row.server_name for row in rows], ["alpha", "beta"])
        self.assertEqual(display.selected_name, "alpha")
        self.assertEqual(display.hint_text, "共 2 个 MCP 服务。")
        self.assertEqual(display.rows[0].values[0], "alpha")
        self.assertEqual(detail.selected_name_text, "alpha")
        self.assertIn("type: stdio", detail.summary_text)
        self.assertIn("[mcp_servers.alpha]", detail.preview_text)

    def test_skills_tab_display_builds_repo_group_project_rows_and_hints(self) -> None:
        group = SkillGroup.create("frontend", skills=[SkillDefinition.create("skill-a", content="a")], description="UI helpers")
        repo_a = SkillMarketRepo.create("https://github.com/example/a", branch="main", last_sync_commit="abcdef123456", auto_update=True)
        repo_b = SkillMarketRepo.create("https://github.com/example/b", branch="release", auto_update=False)
        project = ProjectRecord.create(
            str(Path.cwd()),
            "profile-id",
            skill_group_ids=[group.id],
            skills=[SkillDefinition.create("skill-a", content="a")],
            skill_names=["skill-a"],
        )

        display = build_skills_tab_display(
            all_repos=[repo_a, repo_b],
            visible_repos=[repo_b],
            groups=[group],
            projects=[project],
            market_entries_count=3,
            market_errors_count=1,
            repo_filter_active=True,
        )

        self.assertEqual([row.repo_id for row in display.repo_rows], [repo_b.id])
        self.assertEqual(display.group_rows[0].group_id, group.id)
        self.assertEqual(display.project_rows[0].project_id, project.id)
        self.assertIn("仓库筛选 1/2", display.hint_text)
        self.assertIn("1 个本地组", display.hint_text)
        self.assertIn("市场显示 3 个 Skills", display.preview_status_text)
        self.assertIn("1 个仓库读取失败", display.preview_status_text)

    def test_hot_update_logic_helpers_append_render_and_summarize(self) -> None:
        events = append_hot_update_event(
            [],
            scope="software",
            target="Codex Switch",
            status="error",
            detail="None",
            automatic=True,
        )
        self.assertEqual(len(events), 1)
        line = hot_update_event_line(events[0])
        self.assertIn("[自动][软件][错误] Codex Switch", line)
        self.assertIn("未能获取 GitHub 最新版本信息", line)
        summary = hot_update_summary_text(
            repo_updates=1,
            project_updates=2,
            pending_repo_updates=1,
            pending_project_updates=0,
            error_count=3,
        )
        self.assertIn("仓库 1、项目 2", summary)
        self.assertIn("待确认仓库 1、项目 0", summary)
        self.assertIn("错误 3 条", summary)

    def test_process_hot_update_candidate_handles_manual_and_auto_paths(self) -> None:
        commits = []
        texts = HotUpdateDecisionTexts(
            current="current",
            auto_updated="auto updated",
            auto_pending="auto pending",
            manual_updated="manual updated",
            manual_pending="manual pending",
            declined="declined",
            auto_disabled="auto disabled",
        )

        current = process_hot_update_candidate(
            has_update=False,
            latest_commit="abc",
            automatic=False,
            auto_update_enabled=False,
            texts=texts,
            apply_update=lambda: True,
            set_current_commit=commits.append,
        )
        auto_pending = process_hot_update_candidate(
            has_update=True,
            latest_commit="def",
            automatic=True,
            auto_update_enabled=False,
            texts=texts,
            apply_update=lambda: False,
        )
        manual_declined = process_hot_update_candidate(
            has_update=True,
            latest_commit="ghi",
            automatic=False,
            auto_update_enabled=False,
            texts=texts,
            apply_update=lambda: False,
            confirm_update=lambda: False,
        )

        self.assertEqual(commits, ["abc"])
        self.assertEqual(current.event_status, "current")
        self.assertEqual(current.event_detail, "current")
        self.assertEqual(auto_pending.event_status, "pending")
        self.assertEqual(auto_pending.event_detail, "auto disabled")
        self.assertTrue(auto_pending.event_automatic)
        self.assertEqual(manual_declined.event_status, "pending")
        self.assertEqual(manual_declined.event_detail, "declined")
        self.assertFalse(manual_declined.event_automatic)

    def test_check_selected_skill_repo_update_records_current_commit_via_shared_decision(self) -> None:
        repo = SkillMarketRepo.create("https://github.com/example/skills")
        app = _make_minimal_app()
        app.skill_market_repos = [repo]
        app._selected_skill_repo = lambda: repo
        update = GitRemoteUpdate(latest_commit="a" * 40, previous_commit="a" * 40)
        app._skill_repo_remote_update = lambda _repo: update

        with patch("codex_switch.ui.app.messagebox.showinfo") as showinfo:
            app.check_selected_skill_repo_update()

        self.assertEqual(app.skill_market_repos[0].last_sync_commit, update.latest_commit)
        self.assertEqual(app.hot_update_events[-1].status, "current")
        self.assertEqual(app.hot_update_events[-1].detail, SKILL_REPO_HOT_UPDATE_TEXTS.current)
        self.assertEqual(app.persist_count, 1)
        showinfo.assert_called_once()

    def test_check_selected_project_update_decline_records_pending_without_applying(self) -> None:
        project = ProjectRecord.create(
            str(Path.cwd()),
            "profile-id",
            github_repo="https://github.com/example/project",
            github_last_sync_commit="oldcommit",
        )
        app = _make_minimal_app()
        app.projects = [project]
        app.get_selected_project = lambda: project
        update = GitRemoteUpdate(latest_commit="b" * 40, previous_commit="a" * 40)
        app._project_remote_update = lambda _project: update

        def fail_apply(*_args, **_kwargs):
            raise AssertionError("should not apply project update when user declines")

        app._apply_project_update = fail_apply

        with patch("codex_switch.ui.app.messagebox.askyesno", return_value=False) as askyesno:
            app.check_selected_project_update()

        self.assertEqual(app.hot_update_events[-1].status, "pending")
        self.assertEqual(app.hot_update_events[-1].detail, PROJECT_HOT_UPDATE_TEXTS.declined)
        self.assertIn(update.short_latest, app.status_var.get())
        self.assertEqual(app.persist_count, 1)
        askyesno.assert_called_once()

    def test_project_tab_display_builds_rows_and_generated_count(self) -> None:
        with workspace_tempdir() as temp_dir:
            first = ProjectRecord.create(str(temp_dir / "first"), "codex-a", claude_profile_id="claude-a")
            second = ProjectRecord.create(str(temp_dir / "second"), "codex-b", claude_profile_id="claude-b")
            codex_a = Profile.create("Codex A", "https://a.example.com", "sk-a")
            codex_a.id = "codex-a"
            claude_a = Profile.create("Claude A", "https://claude-a.example.com", "sk-ca", vendor=VENDOR_CLAUDE)
            claude_a.id = "claude-a"

            def profile_by_id(profile_id: str | None) -> Profile | None:
                return {
                    "codex-a": codex_a,
                    "claude-a": claude_a,
                }.get(profile_id)

            generated_status = ProjectTemplateStatus(
                generated_paths=[temp_dir / "first" / "generated.txt"],
                backup_dir=None,
                project_root=temp_dir / "first",
                start_script_path=temp_dir / "first" / CODEX_SCRIPT_DIRNAME / "start-codex.ps1",
            )

            display = project_tab_display(
                [first, second],
                selected_project_id="missing-project",
                profile_by_id=profile_by_id,
                project_codex_profile_id=project_codex_profile_id,
                project_claude_profile_id=project_claude_profile_id,
                project_mcp_summary=lambda project: f"mcp:{project.name}",
                project_status=lambda project: generated_status if project.id == first.id else None,
            )

            self.assertEqual(display.selected_project_id, first.id)
            self.assertEqual(display.generated_count, 1)
            self.assertEqual(display.hint_text, "共 2 个项目，已生成模板 1 个。")
            self.assertEqual(display.rows[0].project_id, first.id)
            self.assertEqual(display.rows[0].values[0], first.name)
            self.assertIn("Codex A", display.rows[0].values[2])
            self.assertIn("Claude A", display.rows[0].values[3])
            self.assertEqual(display.rows[1].project_id, second.id)
            self.assertIn("绑定配置已删除", display.rows[1].values[2])

    def test_project_template_option_helpers_build_service_inputs(self) -> None:
        project_skill = SkillDefinition.create("prompt-helper", content="Use short answers.")
        project = ProjectRecord.create(
            str(Path.cwd()),
            "profile-id",
            skill_names=["frontend-dev"],
            skills=[project_skill],
        )
        frontend_skill = SkillSource("frontend-dev", "frontend-dev", Path.cwd() / "frontend-dev")
        fullstack_skill = SkillSource("fullstack-dev", "fullstack-dev", Path.cwd() / "fullstack-dev")

        codex_options = codex_project_template_options(
            project,
            project_mcp_toml="mcp-toml",
            agents_doc_text="# Agents\n",
            route_proxy_base_url="http://127.0.0.1:15721/project/p1",
            available_skill_sources=[frontend_skill, fullstack_skill],
        )
        claude_options = claude_project_template_options(
            project,
            project_mcp_toml="mcp-toml",
            agents_doc_text="# Agents\n",
            route_proxy_base_url="http://127.0.0.1:15721/project/p1",
        )

        self.assertEqual(codex_options.project_root, Path.cwd())
        self.assertEqual(codex_options.global_mcp_toml, "mcp-toml")
        self.assertEqual(codex_options.project_mcp_toml, "mcp-toml")
        self.assertEqual(codex_options.agents_doc_text, "# Agents\n")
        self.assertEqual(codex_options.route_proxy_base_url, "http://127.0.0.1:15721/project/p1")
        self.assertEqual(codex_options.skill_sources, [frontend_skill])
        self.assertEqual(codex_options.skill_definitions, [project_skill])
        self.assertEqual(claude_options.project_root, Path.cwd())
        self.assertEqual(claude_options.project_mcp_toml, "mcp-toml")
        self.assertEqual(claude_options.agents_doc_text, "# Agents\n")
        self.assertEqual(claude_options.route_proxy_base_url, "http://127.0.0.1:15721/project/p1")

    def test_project_template_execution_plan_helpers_package_generation_inputs(self) -> None:
        project_skill = SkillDefinition.create("prompt-helper", content="Use short answers.")
        project = ProjectRecord.create(
            str(Path.cwd()),
            "codex-profile",
            claude_profile_id="claude-profile",
            skill_names=["frontend-dev"],
            skills=[project_skill],
        )
        codex_profile = Profile.create("codex", "https://codex.example.com", "sk-codex")
        codex_profile.id = "codex-profile"
        claude_profile = Profile.create(
            "claude",
            "https://claude.example.com",
            "sk-claude",
            vendor=VENDOR_CLAUDE,
        )
        claude_profile.id = "claude-profile"
        frontend_skill = SkillSource("frontend-dev", "frontend-dev", Path.cwd() / "frontend-dev")

        codex_plan = build_codex_template_execution_plan(
            project,
            codex_profile,
            claude_profile,
            project_mcp_toml="mcp = true",
            agents_doc_text="AGENTS",
            route_proxy_base_url="http://proxy.local",
            available_skill_sources=[frontend_skill],
            codex_model_override="gpt-5",
            claude_model_override="sonnet",
            claude_fallback_model_override="haiku",
        )
        claude_plan = build_claude_template_execution_plan(
            project,
            claude_profile,
            project_mcp_toml="mcp = true",
            agents_doc_text="AGENTS",
            route_proxy_base_url="http://proxy.local",
            model_override="sonnet",
            fallback_model_override="haiku",
        )

        self.assertEqual(codex_plan.project_name, project.name)
        self.assertEqual(codex_plan.codex_profile, codex_profile)
        self.assertEqual(codex_plan.claude_profile, claude_profile)
        self.assertEqual(codex_plan.route_proxy_base_url, "http://proxy.local")
        self.assertEqual(codex_plan.codex_model_override, "gpt-5")
        self.assertEqual(codex_plan.claude_model_override, "sonnet")
        self.assertEqual(codex_plan.claude_fallback_model_override, "haiku")
        self.assertEqual([skill.name for skill in codex_plan.skill_definitions], ["prompt-helper"])
        self.assertEqual([source.name for source in codex_plan.skill_sources], ["frontend-dev"])
        self.assertEqual(claude_plan.project_name, project.name)
        self.assertEqual(claude_plan.claude_profile, claude_profile)
        self.assertEqual(claude_plan.model_override, "sonnet")
        self.assertEqual(claude_plan.fallback_model_override, "haiku")

        codex_spec = build_codex_template_run_spec(codex_plan)
        claude_spec = build_claude_template_run_spec(claude_plan)

        self.assertEqual(codex_spec.method_name, "generate")
        self.assertEqual(codex_spec.args, (codex_plan.project_root, codex_plan.codex_profile))
        self.assertEqual(codex_spec.failure_status, "项目模板生成失败")
        self.assertEqual(codex_spec.kwargs["route_proxy_base_url"], "http://proxy.local")
        self.assertEqual(claude_spec.method_name, "generate_claude_template")
        self.assertEqual(claude_spec.args, (claude_plan.project_root, claude_plan.claude_profile))
        self.assertEqual(claude_spec.failure_status, "Claude 项目模板生成失败")
        self.assertEqual(claude_spec.kwargs["model_override"], "sonnet")

    def test_project_template_success_message_helpers_format_artifacts(self) -> None:
        result = ProjectTemplateResult(
            generated_paths=[Path("a.txt"), Path("b.txt")],
            backup_dir=Path("backup"),
            project_root=Path("project"),
            start_script_path=Path("project/start-codex.ps1"),
        )

        codex_message = codex_template_success_message("Demo", result)
        claude_message = claude_template_success_message("Demo", result)

        self.assertIn("Demo", codex_message)
        self.assertIn("start-codex.ps1", codex_message)
        self.assertIn("backup", codex_message)
        self.assertIn("Demo", claude_message)
        self.assertIn("a.txt", claude_message)
        self.assertIn("b.txt", claude_message)
        self.assertIn("backup", claude_message)

    def test_route_proxy_rules_keep_claude_binding_for_openai_conversion(self) -> None:
        project = ProjectRecord.create(
            str(Path.cwd()),
            "codex-profile",
            codex_profile_id="codex-profile",
            claude_profile_id="claude-profile",
        )
        codex_profile = Profile.create(
            "codex",
            "https://codex.example.com",
            "sk-codex",
            vendor=VENDOR_CODEX,
            codex_model="gpt-codex",
        )
        codex_profile.id = "codex-profile"
        claude_profile = Profile.create(
            "joverna",
            "https://joverna.example.com",
            "sk-claude",
            vendor=VENDOR_CLAUDE,
            claude_model="mimo-v2.5-pro",
        )
        claude_profile.id = "claude-profile"

        rules = route_proxy_rules_for_project(
            project,
            codex_profile,
            claude_profile,
            ROUTE_PROXY_PROTOCOL_OPENAI_CHAT_TO_RESPONSES,
            ROUTE_PROXY_PROTOCOL_ANTHROPIC_TO_OPENAI,
        )

        self.assertEqual(rules[0].primary_profile_id, "codex-profile")
        self.assertEqual(rules[0].upstream_protocol, ROUTE_PROXY_PROTOCOL_OPENAI_CHAT_TO_RESPONSES)
        self.assertEqual(rules[0].upstream_model, "gpt-codex")
        self.assertEqual(rules[1].primary_profile_id, "claude-profile")
        self.assertEqual(rules[1].upstream_protocol, ROUTE_PROXY_PROTOCOL_ANTHROPIC_TO_OPENAI)
        self.assertEqual(rules[1].upstream_model, "mimo-v2.5-pro")

    def test_route_proxy_rules_for_project_can_use_codex_and_claude_account_pools(self) -> None:
        project = ProjectRecord.create(
            str(Path.cwd()),
            "codex-profile",
            codex_profile_id="codex-profile",
            claude_profile_id="claude-profile",
        )
        codex_profile = Profile.create("codex", "https://codex.example.com", "sk-codex")
        codex_profile.id = "codex-profile"
        claude_profile = Profile.create("claude", "https://claude.example.com", "sk-claude", vendor=VENDOR_CLAUDE)
        claude_profile.id = "claude-profile"

        rules = route_proxy_rules_for_project(
            project,
            codex_profile,
            claude_profile,
            ROUTE_PROXY_PROTOCOL_OPENAI,
            ROUTE_PROXY_PROTOCOL_ANTHROPIC,
            codex_upstream_source=ROUTE_PROXY_UPSTREAM_SOURCE_ACCOUNT_POOL,
            codex_account_pool_group_id="codex-group",
            claude_upstream_source=ROUTE_PROXY_UPSTREAM_SOURCE_ACCOUNT_POOL,
            claude_account_pool_group_id="claude-group",
        )

        self.assertEqual(rules[0].upstream_source, ROUTE_PROXY_UPSTREAM_SOURCE_ACCOUNT_POOL)
        self.assertEqual(rules[0].account_pool_group_id, "codex-group")
        self.assertEqual(rules[1].upstream_source, ROUTE_PROXY_UPSTREAM_SOURCE_ACCOUNT_POOL)
        self.assertEqual(rules[1].account_pool_group_id, "claude-group")

    def test_route_proxy_codex_protocol_tracks_upstream_wire_api(self) -> None:
        responses_profile = Profile.create("responses", "https://responses.example.com", "sk-responses", wire_api="responses")
        chat_profile = Profile.create("chat", "https://chat.example.com", "sk-chat", wire_api="chat_completions")

        self.assertEqual(route_proxy_codex_protocol_for_profile(responses_profile), ROUTE_PROXY_PROTOCOL_OPENAI)
        self.assertEqual(route_proxy_codex_protocol_for_profile(chat_profile), ROUTE_PROXY_PROTOCOL_OPENAI_RESPONSES_TO_CHAT)

    def test_route_proxy_rules_for_project_profiles_bridge_chat_upstream(self) -> None:
        project = ProjectRecord.create(str(Path.cwd()), "chat-profile")
        chat_profile = Profile.create("chat", "https://chat.example.com/v1", "sk-chat", wire_api="chat_completions")
        chat_profile.id = "chat-profile"
        claude_profile = Profile.create("claude", "https://claude.example.com", "sk-claude", vendor=VENDOR_CLAUDE)

        rules = route_proxy_rules_for_project_profiles(project, chat_profile, claude_profile)

        codex_rule = next(rule for rule in rules if rule.client_type == ROUTE_PROXY_CLIENT_CODEX)
        self.assertEqual(codex_rule.primary_profile_id, "chat-profile")
        self.assertEqual(codex_rule.upstream_protocol, ROUTE_PROXY_PROTOCOL_OPENAI_RESPONSES_TO_CHAT)
        self.assertEqual(codex_rule.upstream_model, "gpt-5.4")
        self.assertEqual(codex_rule.upstream_source, ROUTE_PROXY_UPSTREAM_SOURCE_PROFILE)

    def test_build_route_proxy_project_enable_plan_replaces_project_rules_and_keeps_other_projects(self) -> None:
        project = ProjectRecord.create(
            str(Path.cwd()),
            "chat-project",
            codex_profile_id="chat-profile",
            claude_profile_id="claude-profile",
        )
        chat_profile = Profile.create("chat", "https://chat.example.com/v1", "sk-chat", wire_api="chat_completions")
        chat_profile.id = "chat-profile"
        claude_profile = Profile.create("claude", "https://claude.example.com", "sk-claude", vendor=VENDOR_CLAUDE)
        claude_profile.id = "claude-profile"
        stale_codex_rule = RouteProxyRule.create(
            project_id=project.id,
            client_type=ROUTE_PROXY_CLIENT_CODEX,
            primary_profile_id="old-codex",
            upstream_protocol=ROUTE_PROXY_PROTOCOL_OPENAI,
        )
        stale_claude_rule = RouteProxyRule.create(
            project_id=project.id,
            client_type=ROUTE_PROXY_CLIENT_CLAUDE,
            primary_profile_id="old-claude",
            upstream_protocol=ROUTE_PROXY_PROTOCOL_ANTHROPIC,
        )
        other_rule = RouteProxyRule.create(
            project_id="other-project",
            client_type=ROUTE_PROXY_CLIENT_CODEX,
            primary_profile_id="other-profile",
        )
        settings = RouteProxySettings(rules=[stale_codex_rule, stale_claude_rule, other_rule])
        account_pool_settings = AccountPoolSettings()
        default_group = account_pool_settings.ensure_default_group()
        account_pool_settings.selected_group_id = default_group.id

        plan = build_route_proxy_project_enable_plan(
            settings,
            account_pool_settings,
            project,
            chat_profile,
            claude_profile,
        )

        project_rules = plan.settings.rules_for_project(project.id)
        codex_rule = next(rule for rule in project_rules if rule.client_type == ROUTE_PROXY_CLIENT_CODEX)
        claude_rule = next(rule for rule in project_rules if rule.client_type == ROUTE_PROXY_CLIENT_CLAUDE)
        self.assertEqual(plan.codex_protocol, ROUTE_PROXY_PROTOCOL_OPENAI_RESPONSES_TO_CHAT)
        self.assertEqual(plan.claude_protocol, ROUTE_PROXY_PROTOCOL_ANTHROPIC)
        self.assertEqual(codex_rule.primary_profile_id, "chat-profile")
        self.assertEqual(codex_rule.account_pool_group_id, default_group.id)
        self.assertEqual(codex_rule.upstream_model, "gpt-5.4")
        self.assertEqual(claude_rule.primary_profile_id, "claude-profile")
        self.assertEqual(claude_rule.upstream_model, "")
        self.assertEqual(plan.settings.rules_for_project("other-project")[0].primary_profile_id, "other-profile")

    def test_route_proxy_project_helpers_follow_enabled_codex_rule(self) -> None:
        project = ProjectRecord.create(str(Path.cwd()), "profile-id")
        disabled_rule = RouteProxyRule.create(
            project_id=project.id,
            client_type=ROUTE_PROXY_CLIENT_CODEX,
            primary_profile_id="profile-id",
            upstream_protocol=ROUTE_PROXY_PROTOCOL_OPENAI_CHAT_TO_RESPONSES,
            enabled=False,
        )
        enabled_rule = RouteProxyRule.create(
            project_id=project.id,
            client_type=ROUTE_PROXY_CLIENT_CODEX,
            primary_profile_id="profile-id",
            upstream_protocol=ROUTE_PROXY_PROTOCOL_OPENAI_RESPONSES_TO_CHAT,
        )
        settings = RouteProxySettings(rules=[disabled_rule, enabled_rule])

        self.assertEqual(route_proxy_base_url_for_project(settings, project), settings.project_base_url(project.id))
        self.assertIsNone(route_proxy_base_url_for_project(RouteProxySettings(), project))

    def test_refresh_route_proxy_rules_for_project_uses_latest_bindings(self) -> None:
        project = ProjectRecord.create(
            str(Path.cwd()),
            "old-codex",
            codex_profile_id="old-codex",
            claude_profile_id="old-claude",
        )
        codex_rule = RouteProxyRule.create(
            project_id=project.id,
            client_type=ROUTE_PROXY_CLIENT_CODEX,
            primary_profile_id="old-codex",
            upstream_protocol=ROUTE_PROXY_PROTOCOL_OPENAI_CHAT_TO_RESPONSES,
        )
        claude_rule = RouteProxyRule.create(
            project_id=project.id,
            client_type=ROUTE_PROXY_CLIENT_CLAUDE,
            primary_profile_id="old-claude",
            upstream_protocol=ROUTE_PROXY_PROTOCOL_ANTHROPIC_TO_OPENAI,
        )
        other_rule = RouteProxyRule.create(
            project_id="other-project",
            client_type=ROUTE_PROXY_CLIENT_CODEX,
            primary_profile_id="other-profile",
        )
        settings = RouteProxySettings(
            account_pool_strategy=ROUTE_PROXY_ACCOUNT_POOL_STRATEGY_FAILOVER,
            upstream_timeout_seconds=12,
            rules=[codex_rule, claude_rule, other_rule],
        )
        updated_project = replace(
            project,
            profile_id="new-codex",
            codex_profile_id="new-codex",
            claude_profile_id="new-claude",
        )
        codex_profile = Profile.create("new-codex", "https://codex.example.com", "sk-codex", codex_model="gpt-new")
        codex_profile.id = "new-codex"
        claude_profile = Profile.create("new-claude", "https://claude.example.com", "sk-claude", claude_model="sonnet-new")
        claude_profile.id = "new-claude"

        refreshed = refresh_route_proxy_rules_for_project(settings, updated_project, codex_profile, claude_profile)
        project_rules = refreshed.rules_for_project(project.id)

        self.assertEqual(len(project_rules), 2)
        self.assertEqual(project_rules[0].primary_profile_id, "new-codex")
        self.assertEqual(project_rules[0].upstream_protocol, ROUTE_PROXY_PROTOCOL_OPENAI)
        self.assertEqual(project_rules[0].upstream_model, "")
        self.assertEqual(project_rules[1].primary_profile_id, "new-claude")
        self.assertEqual(project_rules[1].upstream_protocol, ROUTE_PROXY_PROTOCOL_ANTHROPIC_TO_OPENAI)
        self.assertEqual(project_rules[1].upstream_model, "sonnet-new")
        self.assertEqual(refreshed.rules_for_project("other-project"), [other_rule])
        self.assertEqual(refreshed.account_pool_strategy, ROUTE_PROXY_ACCOUNT_POOL_STRATEGY_FAILOVER)
        self.assertEqual(refreshed.upstream_timeout_seconds, 12)

    def test_refresh_route_proxy_rules_for_project_bridges_new_chat_api(self) -> None:
        project = ProjectRecord.create(str(Path.cwd()), "old-profile")
        old_rule = RouteProxyRule.create(
            project_id=project.id,
            client_type=ROUTE_PROXY_CLIENT_CODEX,
            primary_profile_id="old-profile",
            upstream_protocol=ROUTE_PROXY_PROTOCOL_OPENAI,
        )
        settings = RouteProxySettings(rules=[old_rule])
        chat_profile = Profile.create("chat", "https://chat.example.com", "sk-chat", wire_api="chat_completions")
        chat_profile.id = "chat-profile"
        claude_profile = Profile.create("claude", "https://claude.example.com", "sk-claude", vendor=VENDOR_CLAUDE)
        claude_profile.id = "claude-profile"
        updated_project = replace(project, profile_id="chat-profile", codex_profile_id="chat-profile", claude_profile_id="claude-profile")

        refreshed = refresh_route_proxy_rules_for_project(settings, updated_project, chat_profile, claude_profile)

        codex_rule = next(rule for rule in refreshed.rules_for_project(project.id) if rule.client_type == ROUTE_PROXY_CLIENT_CODEX)
        self.assertEqual(codex_rule.primary_profile_id, "chat-profile")
        self.assertEqual(codex_rule.upstream_protocol, ROUTE_PROXY_PROTOCOL_OPENAI_RESPONSES_TO_CHAT)

    def test_refresh_route_proxy_rules_for_project_preserves_manual_protocols_and_compact_model(self) -> None:
        project = ProjectRecord.create(
            str(Path.cwd()),
            "old-codex",
            codex_profile_id="old-codex",
            claude_profile_id="old-claude",
        )
        codex_rule = RouteProxyRule.create(
            project_id=project.id,
            client_type=ROUTE_PROXY_CLIENT_CODEX,
            primary_profile_id="old-codex",
            upstream_source=ROUTE_PROXY_UPSTREAM_SOURCE_ACCOUNT_POOL,
            upstream_protocol=ROUTE_PROXY_PROTOCOL_OPENAI,
            compact_model="gpt-4.1-compact",
            manual_upstream_protocol=True,
        )
        claude_rule = RouteProxyRule.create(
            project_id=project.id,
            client_type=ROUTE_PROXY_CLIENT_CLAUDE,
            primary_profile_id="old-claude",
            upstream_source=ROUTE_PROXY_UPSTREAM_SOURCE_ACCOUNT_POOL,
            account_pool_group_id="claude-group",
            upstream_protocol=ROUTE_PROXY_PROTOCOL_ANTHROPIC,
            manual_upstream_protocol=True,
        )
        settings = RouteProxySettings(rules=[codex_rule, claude_rule])
        chat_profile = Profile.create("chat", "https://chat.example.com", "sk-chat", wire_api="chat_completions")
        chat_profile.id = "new-codex"
        claude_profile = Profile.create("claude", "https://claude.example.com", "sk-claude", vendor=VENDOR_CLAUDE)
        claude_profile.id = "new-claude"
        updated_project = replace(
            project,
            profile_id="new-codex",
            codex_profile_id="new-codex",
            claude_profile_id="new-claude",
        )

        refreshed = refresh_route_proxy_rules_for_project(settings, updated_project, chat_profile, claude_profile)

        refreshed_codex = next(rule for rule in refreshed.rules_for_project(project.id) if rule.client_type == ROUTE_PROXY_CLIENT_CODEX)
        refreshed_claude = next(rule for rule in refreshed.rules_for_project(project.id) if rule.client_type == ROUTE_PROXY_CLIENT_CLAUDE)
        self.assertEqual(refreshed_codex.primary_profile_id, "new-codex")
        self.assertEqual(refreshed_codex.upstream_source, ROUTE_PROXY_UPSTREAM_SOURCE_ACCOUNT_POOL)
        self.assertEqual(refreshed_codex.upstream_protocol, ROUTE_PROXY_PROTOCOL_OPENAI)
        self.assertEqual(refreshed_codex.upstream_model, "")
        self.assertEqual(refreshed_codex.compact_model, "gpt-4.1-compact")
        self.assertTrue(refreshed_codex.manual_upstream_protocol)
        self.assertEqual(refreshed_claude.primary_profile_id, "new-claude")
        self.assertEqual(refreshed_claude.upstream_source, ROUTE_PROXY_UPSTREAM_SOURCE_ACCOUNT_POOL)
        self.assertEqual(refreshed_claude.account_pool_group_id, "claude-group")
        self.assertEqual(refreshed_claude.upstream_protocol, ROUTE_PROXY_PROTOCOL_ANTHROPIC)
        self.assertEqual(refreshed_claude.upstream_model, "")
        self.assertTrue(refreshed_claude.manual_upstream_protocol)

    def test_save_selected_route_proxy_project_rules_updates_protocols_and_compact_model(self) -> None:
        project = ProjectRecord.create(
            str(Path.cwd()),
            "codex-profile",
            codex_profile_id="codex-profile",
            claude_profile_id="claude-profile",
        )
        codex_profile = Profile.create(
            "codex",
            "https://codex.example.com",
            "sk-codex",
            codex_model="gpt-real",
        )
        codex_profile.id = "codex-profile"
        claude_profile = Profile.create(
            "claude",
            "https://claude.example.com",
            "sk-claude",
            vendor=VENDOR_CLAUDE,
            claude_model="sonnet-real",
        )
        claude_profile.id = "claude-profile"
        app = CodexSwitchApp.__new__(CodexSwitchApp)
        app.projects = [project]
        app.profiles = [codex_profile, claude_profile]
        app.selected_project_id = project.id
        app.route_proxy_settings = RouteProxySettings(
            rules=[
                RouteProxyRule.create(
                    project_id=project.id,
                    client_type=ROUTE_PROXY_CLIENT_CODEX,
                    primary_profile_id=codex_profile.id,
                ),
                RouteProxyRule.create(
                    project_id=project.id,
                    client_type=ROUTE_PROXY_CLIENT_CLAUDE,
                    primary_profile_id=claude_profile.id,
                ),
            ]
        )
        app.proxy_codex_protocol_var = _ValueVar(ROUTE_PROXY_PROTOCOL_OPENAI_RESPONSES_TO_CHAT)
        app.proxy_codex_upstream_source_var = _ValueVar(ROUTE_PROXY_UPSTREAM_SOURCE_ACCOUNT_POOL)
        app.proxy_claude_upstream_source_var = _ValueVar(ROUTE_PROXY_UPSTREAM_SOURCE_ACCOUNT_POOL)
        app.proxy_claude_protocol_var = _ValueVar(ROUTE_PROXY_PROTOCOL_ANTHROPIC_TO_OPENAI)
        app.proxy_codex_compact_model_var = _ValueVar("gpt-4.1-compact")
        app.account_pool_settings = AccountPoolSettings()
        group = app.account_pool_settings.ensure_default_group()
        group.default_model = "pool-codex"
        claude_group = app.account_pool_settings.add_group(
            "claude-pool",
            pool_type=ACCOUNT_POOL_GROUP_TYPE_CLAUDE,
            claude_model="pool-sonnet",
        )
        app.proxy_account_pool_group_var = _ValueVar("default")
        app.proxy_claude_account_pool_group_var = _ValueVar("claude")
        app.proxy_account_pool_group_choices = {"default": group.id}
        app.proxy_claude_account_pool_group_choices = {"claude": claude_group.id}

        app._save_selected_route_proxy_project_rules()

        codex_rule = next(rule for rule in app.route_proxy_settings.rules_for_project(project.id) if rule.client_type == ROUTE_PROXY_CLIENT_CODEX)
        claude_rule = next(rule for rule in app.route_proxy_settings.rules_for_project(project.id) if rule.client_type == ROUTE_PROXY_CLIENT_CLAUDE)
        self.assertEqual(codex_rule.upstream_source, ROUTE_PROXY_UPSTREAM_SOURCE_ACCOUNT_POOL)
        self.assertEqual(codex_rule.account_pool_group_id, group.id)
        self.assertEqual(codex_rule.upstream_protocol, ROUTE_PROXY_PROTOCOL_OPENAI_RESPONSES_TO_CHAT)
        self.assertEqual(codex_rule.upstream_model, "pool-codex")
        self.assertEqual(codex_rule.compact_model, "gpt-4.1-compact")
        self.assertTrue(codex_rule.manual_upstream_protocol)
        self.assertEqual(claude_rule.upstream_source, ROUTE_PROXY_UPSTREAM_SOURCE_ACCOUNT_POOL)
        self.assertEqual(claude_rule.account_pool_group_id, claude_group.id)
        self.assertEqual(claude_rule.upstream_protocol, ROUTE_PROXY_PROTOCOL_ANTHROPIC_TO_OPENAI)
        self.assertEqual(claude_rule.upstream_model, "pool-sonnet")
        self.assertTrue(claude_rule.manual_upstream_protocol)

    def test_save_route_proxy_settings_updates_pool_strategy_and_timeout(self) -> None:
        app = CodexSwitchApp.__new__(CodexSwitchApp)
        app.route_proxy_settings = RouteProxySettings()
        app.proxy_host_var = _ValueVar("127.0.0.1")
        app.proxy_port_var = _ValueVar("15722")
        app.proxy_account_pool_strategy_var = _ValueVar("失败后切换")
        app.proxy_upstream_timeout_var = _ValueVar("12")
        app.persist_state = lambda: None
        app.refresh_proxy_tab = lambda: None
        app.status_var = _ValueVar("")

        saved = app.save_route_proxy_settings(save_project_rules=False)

        self.assertTrue(saved)
        self.assertEqual(app.route_proxy_settings.host, "127.0.0.1")
        self.assertEqual(app.route_proxy_settings.port, 15722)
        self.assertEqual(app.route_proxy_settings.account_pool_strategy, ROUTE_PROXY_ACCOUNT_POOL_STRATEGY_FAILOVER)
        self.assertEqual(app.route_proxy_settings.upstream_timeout_seconds, 12)

    def test_route_proxy_account_pool_choices_separates_codex_and_claude_groups(self) -> None:
        settings = AccountPoolSettings()
        default_group = settings.ensure_default_group()
        second_codex = settings.add_group("backup-codex")
        claude_group = settings.add_group("claude-pool", pool_type=ACCOUNT_POOL_GROUP_TYPE_CLAUDE)

        choices = route_proxy_account_pool_choices(settings)

        self.assertIn(default_group.id, choices.codex_choices.values())
        self.assertIn(second_codex.id, choices.codex_choices.values())
        self.assertIn(claude_group.id, choices.claude_choices.values())
        self.assertEqual(choices.selected_codex_label, choices.codex_labels[0])
        self.assertEqual(choices.selected_claude_label, choices.claude_labels[0])

    def test_resolve_route_proxy_project_rule_form_uses_selected_groups_and_defaults(self) -> None:
        settings = AccountPoolSettings()
        default_group = settings.ensure_default_group()
        default_group.default_model = "pool-codex"
        claude_group = settings.add_group("claude-pool", pool_type=ACCOUNT_POOL_GROUP_TYPE_CLAUDE, claude_model="pool-sonnet")

        form = resolve_route_proxy_project_rule_form(
            settings,
            codex_protocol=ROUTE_PROXY_PROTOCOL_OPENAI_RESPONSES_TO_CHAT,
            codex_source_label=ROUTE_PROXY_UPSTREAM_SOURCE_ACCOUNT_POOL,
            codex_source_values={"号池": ROUTE_PROXY_UPSTREAM_SOURCE_ACCOUNT_POOL},
            codex_group_label="",
            codex_group_choices={},
            claude_protocol=ROUTE_PROXY_PROTOCOL_ANTHROPIC_TO_OPENAI,
            claude_source_label=ROUTE_PROXY_UPSTREAM_SOURCE_ACCOUNT_POOL,
            claude_source_values={"号池": ROUTE_PROXY_UPSTREAM_SOURCE_ACCOUNT_POOL},
            claude_group_label="claude",
            claude_group_choices={"claude": claude_group.id},
            compact_model="gpt-4.1-compact",
        )

        self.assertEqual(form.codex_account_pool_group_id, default_group.id)
        self.assertEqual(form.codex_pool_model, "pool-codex")
        self.assertEqual(form.claude_account_pool_group_id, claude_group.id)
        self.assertEqual(form.claude_pool_model, "pool-sonnet")
        self.assertEqual(form.compact_model, "gpt-4.1-compact")

    def test_route_proxy_detail_display_uses_account_pool_labels_and_group_names(self) -> None:
        project = ProjectRecord.create(
            str(Path.cwd()),
            "codex-profile",
            codex_profile_id="codex-profile",
            claude_profile_id="claude-profile",
        )
        codex_profile = Profile.create("codex", "https://codex.example.com", "sk-codex", codex_model="gpt-real")
        codex_profile.id = "codex-profile"
        claude_profile = Profile.create(
            "claude",
            "https://claude.example.com",
            "sk-claude",
            vendor=VENDOR_CLAUDE,
            claude_model="sonnet-real",
        )
        claude_profile.id = "claude-profile"
        proxy_settings = RouteProxySettings(
            rules=[
                RouteProxyRule.create(
                    project_id=project.id,
                    client_type=ROUTE_PROXY_CLIENT_CODEX,
                    primary_profile_id=codex_profile.id,
                    upstream_source=ROUTE_PROXY_UPSTREAM_SOURCE_ACCOUNT_POOL,
                    account_pool_group_id="codex-group",
                    upstream_protocol=ROUTE_PROXY_PROTOCOL_OPENAI_RESPONSES_TO_CHAT,
                    compact_model="gpt-4.1-compact",
                ),
                RouteProxyRule.create(
                    project_id=project.id,
                    client_type=ROUTE_PROXY_CLIENT_CLAUDE,
                    primary_profile_id=claude_profile.id,
                    upstream_source=ROUTE_PROXY_UPSTREAM_SOURCE_ACCOUNT_POOL,
                    account_pool_group_id="claude-group",
                    upstream_protocol=ROUTE_PROXY_PROTOCOL_ANTHROPIC_TO_OPENAI,
                ),
            ]
        )
        account_pool_settings = AccountPoolSettings()
        codex_group = account_pool_settings.ensure_default_group()
        codex_group.id = "codex-group"
        codex_group.name = "codex-pool"
        claude_group = account_pool_settings.add_group("claude-pool", pool_type=ACCOUNT_POOL_GROUP_TYPE_CLAUDE)
        claude_group.id = "claude-group"

        choices = route_proxy_account_pool_choices(account_pool_settings)
        profiles = {codex_profile.id: codex_profile, claude_profile.id: claude_profile}
        detail = route_proxy_detail_display(
            project,
            proxy_settings,
            account_pool_settings,
            profile_by_id=lambda profile_id: profiles.get(profile_id),
            codex_choices=choices.codex_choices,
            claude_choices=choices.claude_choices,
        )

        self.assertEqual(detail.selected_project_text, f"{project.name}    {project.project_dir}")
        self.assertEqual(detail.codex_protocol, ROUTE_PROXY_PROTOCOL_OPENAI_RESPONSES_TO_CHAT)
        self.assertEqual(detail.claude_protocol, ROUTE_PROXY_PROTOCOL_ANTHROPIC_TO_OPENAI)
        self.assertEqual(detail.codex_compact_model, "gpt-4.1-compact")
        self.assertEqual(detail.codex_group_label, choices.codex_labels[0])
        self.assertEqual(detail.claude_group_label, choices.claude_labels[0])
        self.assertIn("codex-pool", detail.selected_rules_text)
        self.assertIn("claude-pool", detail.selected_rules_text)

    def test_route_proxy_tab_display_builds_status_and_rows(self) -> None:
        project = ProjectRecord.create(
            str(Path.cwd()),
            "codex-profile",
            codex_profile_id="codex-profile",
            claude_profile_id="claude-profile",
        )
        codex_profile = Profile.create("codex", "https://codex.example.com", "sk-codex")
        codex_profile.id = "codex-profile"
        claude_profile = Profile.create("claude", "https://claude.example.com", "sk-claude", vendor=VENDOR_CLAUDE)
        claude_profile.id = "claude-profile"
        settings = RouteProxySettings(port=15721)

        display = route_proxy_tab_display(
            settings,
            [project],
            is_running=True,
            profile_by_id=lambda profile_id: {
                "codex-profile": codex_profile,
                "claude-profile": claude_profile,
            }.get(profile_id),
            project_codex_profile_id=project_codex_profile_id,
            project_claude_profile_id=project_claude_profile_id,
            project_account_pool_group_name=lambda _project_id: "否",
        )

        self.assertEqual(display.host, settings.host)
        self.assertEqual(display.port_text, "15721")
        self.assertIn("代理运行中", display.status_text)
        self.assertEqual(len(display.rows), 1)
        self.assertEqual(display.rows[0].values[0], project.name)

    def test_refresh_stats_tab_renders_token_usage_summary(self) -> None:
        app = _make_minimal_app()
        app.route_proxy_settings = RouteProxySettings()
        app.stats_total_tokens_var = _ValueVar("")
        app.stats_today_tokens_var = _ValueVar("")
        app.stats_project_count_var = _ValueVar("")
        app.stats_api_count_var = _ValueVar("")
        app.stats_day_tree = _FakeTree()
        app.stats_project_tree = _FakeTree()
        app.stats_api_tree = _FakeTree()
        app.route_proxy_settings.token_usage.record(
            project_id="project-1",
            project_name="Demo Project",
            api_id="profile:api-1",
            api_name="代理: Main API",
            input_tokens=1200,
            output_tokens=34,
            total_tokens=1234,
            timestamp=f"{today_iso()}T09:30:00",
        )

        app.refresh_stats_tab()

        self.assertEqual(app.stats_total_tokens_var.get(), "1,234")
        self.assertEqual(app.stats_today_tokens_var.get(), "1,234")
        self.assertEqual(app.stats_project_count_var.get(), "1")
        self.assertEqual(app.stats_api_count_var.get(), "1")
        self.assertEqual(app.stats_day_tree.rows[0][1][0], today_iso())
        self.assertEqual(app.stats_project_tree.rows[0][1][0], "Demo Project")
        self.assertEqual(app.stats_api_tree.rows[0][1][0], "代理: Main API")

    def test_route_proxy_events_coalesce_log_renders(self) -> None:
        app = _make_minimal_app()
        app.root = _DelayedRoot()
        app.route_proxy_settings = RouteProxySettings()
        render_count = 0

        def render_proxy_log() -> None:
            nonlocal render_count
            render_count += 1
            app._proxy_log_render_pending = False

        app._render_proxy_log = render_proxy_log

        app._record_route_proxy_event(RouteProxyEvent.create(level="info", message="first"))
        app._record_route_proxy_event(RouteProxyEvent.create(level="info", message="second"))

        self.assertEqual(len(app.root.callbacks), 1)
        self.assertEqual(len(app.route_proxy_settings.events), 2)

        app.root.callbacks[0][1]()

        self.assertEqual(render_count, 1)
        self.assertFalse(app._proxy_log_render_pending)

    def test_route_proxy_usage_updates_coalesce_state_flushes(self) -> None:
        app = _make_minimal_app()
        app.root = _DelayedRoot()
        app.route_proxy_settings = RouteProxySettings()
        app.stats_refresh_count = 0
        app.refresh_stats_tab = lambda: setattr(app, "stats_refresh_count", app.stats_refresh_count + 1)
        first = RouteProxySettings()
        second = RouteProxySettings()

        app._record_route_proxy_token_usage(first)
        app._record_route_proxy_token_usage(second)

        self.assertEqual(len(app.root.callbacks), 1)
        self.assertIs(app.route_proxy_settings, second)
        self.assertEqual(app.persist_count, 0)

        app.root.callbacks[0][1]()

        self.assertEqual(app.persist_count, 1)
        self.assertEqual(app.stats_refresh_count, 1)
        self.assertFalse(app._route_proxy_token_usage_update_pending)

    def test_account_pool_updates_coalesce_state_flushes(self) -> None:
        app = _make_minimal_app()
        app.root = _DelayedRoot()
        app.account_pool_settings = AccountPoolSettings()
        app.account_pool_refresh_count = 0
        app.proxy_refresh_count = 0
        app.refresh_account_pool_tab = lambda: setattr(app, "account_pool_refresh_count", app.account_pool_refresh_count + 1)
        app.refresh_proxy_tab = lambda: setattr(app, "proxy_refresh_count", app.proxy_refresh_count + 1)
        first = AccountPoolSettings()
        second = AccountPoolSettings()

        app._record_account_pool_update(first)
        app._record_account_pool_update(second)

        self.assertEqual(len(app.root.callbacks), 1)
        self.assertIs(app.account_pool_settings, second)
        self.assertEqual(app.persist_count, 0)

        app.root.callbacks[0][1]()

        self.assertEqual(app.persist_count, 1)
        self.assertEqual(app.account_pool_refresh_count, 1)
        self.assertEqual(app.proxy_refresh_count, 1)
        self.assertFalse(app._account_pool_update_pending)

    def test_project_skill_groups_sync_to_flat_project_skills(self) -> None:
        skill = SkillDefinition.create("python-helper", content="old")
        group = SkillGroup.create("代码组", skills=[skill])
        project = ProjectRecord.create(
            str(Path.cwd()),
            "profile-id",
            skill_group_ids=[group.id],
            skills=[],
            skill_names=[],
        )
        app = _make_minimal_app()
        app.skill_groups = [group]
        app.projects = [project]

        app._sync_projects_from_skill_groups()

        self.assertEqual([skill.name for skill in app.projects[0].skills], ["python-helper"])
        self.assertEqual(app.projects[0].skill_names, ["python-helper"])
        self.assertEqual(app.persist_count, 1)

        updated_skill = SkillDefinition.create("python-helper", content="new")
        extra_skill = SkillDefinition.create("review-helper", content="review")
        app.skill_groups = [replace(group, skills=[updated_skill, extra_skill])]

        app._sync_projects_from_skill_groups()

        self.assertEqual([skill.content for skill in app.projects[0].skills], ["new", "review"])
        self.assertEqual(app.projects[0].skill_names, ["python-helper", "review-helper"])

    def test_refresh_skills_tab_syncs_project_skill_groups(self) -> None:
        stale_skill = SkillDefinition.create("python-helper", content="old")
        fresh_skill = SkillDefinition.create("python-helper", content="new")
        extra_skill = SkillDefinition.create("review-helper", content="review")
        group = SkillGroup.create("代码组", skills=[fresh_skill, extra_skill])
        project = ProjectRecord.create(
            str(Path.cwd()),
            "profile-id",
            skill_group_ids=[group.id],
            skills=[stale_skill],
            skill_names=[stale_skill.name],
        )
        app = _make_minimal_app()
        app.skill_groups = [group]
        app.projects = [project]
        app.skills_hint_var = _ValueVar("")
        app._refresh_skill_repo_detail = lambda: None
        app._refresh_skill_group_detail = lambda: None
        app._refresh_skill_project_detail = lambda: None
        app.refresh_skills_tab = CodexSwitchApp.refresh_skills_tab.__get__(app, CodexSwitchApp)

        app.refresh_skills_tab()

        self.assertEqual([skill.content for skill in app.projects[0].skills], ["new", "review"])
        self.assertEqual(app.projects[0].skill_names, ["python-helper", "review-helper"])
        self.assertEqual(app.persist_count, 1)

    def test_hot_update_manual_decline_keeps_repo_and_project_pending(self) -> None:
        repo = SkillMarketRepo.create(
            "https://github.com/example/skills",
            last_sync_commit="old-repo",
            auto_update=False,
        )
        project = ProjectRecord.create(
            str(Path.cwd()),
            "profile-id",
            github_repo="https://github.com/example/project",
            github_last_sync_commit="old-project",
            github_auto_update=False,
        )
        app = _make_minimal_app()
        app.skill_market_repos = [repo]
        app.projects = [project]
        app._skill_repo_remote_update = lambda _repo: GitRemoteUpdate("new-repo", "old-repo")
        app._project_remote_update = lambda _project: GitRemoteUpdate("new-project", "old-project")

        with patch("codex_switch.ui.app.messagebox.askyesno", return_value=False) as askyesno:
            summary = app._check_and_apply_hot_updates(automatic=False)

        self.assertEqual(askyesno.call_count, 2)
        self.assertEqual(app.skill_market_repos[0].last_sync_commit, "old-repo")
        self.assertEqual(app.projects[0].github_last_sync_commit, "old-project")
        self.assertIn("待确认仓库 1、项目 1", summary)
        self.assertEqual([event.status for event in app.hot_update_events], ["pending", "pending", "summary"])
        self.assertEqual(app.hot_update_events[0].target, "https://github.com/example/skills")
        self.assertEqual(app.hot_update_events[1].target, project.name)
        self.assertFalse(app.hot_update_events[-1].automatic)

    def test_hot_update_auto_failure_keeps_project_pending(self) -> None:
        project = ProjectRecord.create(
            str(Path.cwd()),
            "profile-id",
            github_repo="https://github.com/example/project",
            github_last_sync_commit="old-project",
            github_auto_update=True,
        )
        app = _make_minimal_app()
        app.projects = [project]
        app._project_remote_update = lambda _project: GitRemoteUpdate("new-project", "old-project")
        app._apply_project_update = lambda _project, _commit, automatic: False

        summary = app._check_and_apply_hot_updates(automatic=True)

        self.assertEqual(app.projects[0].github_last_sync_commit, "old-project")
        self.assertIn("待确认仓库 0、项目 1", summary)
        self.assertEqual([event.status for event in app.hot_update_events], ["pending", "summary"])
        self.assertEqual(app.hot_update_events[0].scope, "project")
        self.assertTrue(app.hot_update_events[0].automatic)

    def test_project_remote_update_uses_configured_ref(self) -> None:
        class FakeCompleted:
            def __init__(self, *, returncode: int = 0, stdout: str = "", stderr: str = "") -> None:
                self.returncode = returncode
                self.stdout = stdout
                self.stderr = stderr

        project = ProjectRecord.create(
            str(Path.cwd()),
            "profile-id",
            github_repo="https://github.com/example/project",
            github_ref="release/v1",
            github_last_sync_commit="old-project",
        )
        app = _make_minimal_app()

        def fake_run(args, **_kwargs):
            if args[:3] == ["git", "ls-remote", "https://github.com/example/project"]:
                self.assertIn("refs/heads/release/v1", args)
                self.assertIn("refs/tags/release/v1^{}", args)
                return FakeCompleted(stdout="new-project refs/heads/release/v1\n")
            raise AssertionError(args)

        with patch("codex_switch.ui.app.subprocess.run", side_effect=fake_run):
            update = app._project_remote_update(project)

        self.assertEqual(update.latest_commit, "new-project")
        self.assertEqual(update.previous_commit, "old-project")

    def test_hot_update_auto_skill_repo_head_mismatch_keeps_pending(self) -> None:
        group = SkillGroup.create("代码组")
        repo = SkillMarketRepo.create(
            "https://github.com/example/skills",
            last_sync_commit="old-repo",
            auto_update=True,
            installed_group_id=group.id,
        )
        app = _make_minimal_app()
        app.skill_groups = [group]
        app.skill_market_repos = [repo]
        app._skill_repo_remote_update = lambda _repo: GitRemoteUpdate("new-repo", "old-repo")

        def reject_mismatch(_repo, expected_commit=None):
            self.assertEqual(expected_commit, "new-repo")
            raise RuntimeError("仓库同步后的 HEAD 与检测到的远端提交不一致")

        app._sync_skill_repo_cache = reject_mismatch

        summary = app._check_and_apply_hot_updates(automatic=True)

        self.assertEqual(app.skill_market_repos[0].last_sync_commit, "old-repo")
        self.assertIn("待确认仓库 1、项目 0", summary)
        self.assertEqual([event.status for event in app.hot_update_events], ["pending", "summary"])
        self.assertEqual(app.hot_update_events[0].commit, "new-repo")

    def test_skill_repo_cache_rejects_synced_head_mismatch(self) -> None:
        class FakeCompleted:
            def __init__(self, *, returncode: int = 0, stdout: str = "", stderr: str = "") -> None:
                self.returncode = returncode
                self.stdout = stdout
                self.stderr = stderr

        with workspace_tempdir() as temp_dir:
            repo = SkillMarketRepo.create("https://github.com/example/skills", last_sync_commit="old-repo")
            app = _make_minimal_app()
            app.store = type("FakeStore", (), {"root_dir": temp_dir})()
            app.skill_market_repos = [repo]

            def fake_run(args, **_kwargs):
                if args[1] == "init":
                    return FakeCompleted()
                if args[1:4] == ["-C", str(temp_dir / "skill-market" / repo.id), "remote"]:
                    return FakeCompleted()
                if args[1:4] == ["-C", str(temp_dir / "skill-market" / repo.id), "fetch"]:
                    return FakeCompleted()
                if args[1:4] == ["-C", str(temp_dir / "skill-market" / repo.id), "checkout"]:
                    return FakeCompleted()
                if args[-2:] == ["rev-parse", "HEAD"]:
                    return FakeCompleted(stdout="different-commit\n")
                raise AssertionError(args)

            with patch("codex_switch.ui.app.subprocess.run", side_effect=fake_run):
                with self.assertRaisesRegex(RuntimeError, "不一致"):
                    app._sync_skill_repo_cache(repo, "expected-commit")

            self.assertEqual(app.skill_market_repos[0].last_sync_commit, "old-repo")

    def test_skill_repo_update_reloads_skills_and_model_metadata(self) -> None:
        with workspace_tempdir() as temp_dir:
            cache_dir = temp_dir / "repo"
            skill_dir = cache_dir / "python-helper"
            skill_dir.mkdir(parents=True)
            skill_file = skill_dir / "SKILL.md"
            skill_file.write_text("Use Python.", encoding="utf-8")
            profile = Profile.create("image-api", "https://image.example.com", "sk-local")
            profile.health = HealthResult(status="unknown", detail="old", models=["old-model"])
            metadata_path = cache_dir / "codex-switch-model-metadata.json"
            metadata_path.write_text(
                json.dumps(
                    {
                        "model_vendor_keywords": {"Acme": ["acme-"]},
                        "profiles": [
                            {
                                "id": profile.id,
                                "category": PROFILE_CATEGORY_IMAGE_GENERATION,
                                "api_provided": False,
                                "codex_model": "image-fast",
                                "models": [
                                    {"name": "image-fast", "vendor": "Acme"},
                                    {"id": "image-pro"},
                                    "image-fast",
                                ],
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            manifest_dir = cache_dir / ".codex-switch"
            manifest_dir.mkdir()
            (manifest_dir / "checksums.json").write_text(
                json.dumps(
                    {
                        "sha256": {
                            skill_file.relative_to(cache_dir).as_posix(): _file_sha256(skill_file),
                            metadata_path.relative_to(cache_dir).as_posix(): _file_sha256(metadata_path),
                        }
                    }
                ),
                encoding="utf-8",
            )
            group = SkillGroup.create("代码组")
            repo = SkillMarketRepo.create(
                "https://github.com/example/skills",
                installed_group_id=group.id,
            )
            app = _make_minimal_app()
            app.profiles = [profile]
            app.skill_groups = [group]
            app.skill_market_repos = [repo]
            app._sync_skill_repo_cache = lambda _repo, _expected=None: cache_dir

            updated = app._apply_skill_repo_update(repo, automatic=False)

            self.assertTrue(updated)
            self.assertEqual([skill.name for skill in app.skill_groups[0].skills], ["python-helper"])
            self.assertEqual(app.model_vendor_keywords["Acme"], ["acme-"])
            self.assertEqual(app.profiles[0].category, PROFILE_CATEGORY_IMAGE_GENERATION)
            self.assertFalse(app.profiles[0].api_provided)
            self.assertEqual(app.profiles[0].api_keys, [])
            self.assertEqual(app.profiles[0].codex_model, "image-fast")
            self.assertEqual(app.profiles[0].health.models, ["image-fast", "image-pro"])
            self.assertIn("模型元数据已更新", app.status_var.get())

    def test_model_metadata_ignores_unknown_or_ambiguous_profile_targets(self) -> None:
        with workspace_tempdir() as temp_dir:
            repo_root = temp_dir / "repo"
            repo_root.mkdir()
            first = Profile.create("shared", "https://first.example.com", "sk-first")
            second = Profile.create("shared", "https://second.example.com", "sk-second")
            metadata_path = repo_root / "model-metadata.json"
            metadata_path.write_text(
                json.dumps(
                    {
                        "profiles": [
                            {
                                "id": "missing-profile",
                                "category": PROFILE_CATEGORY_IMAGE_GENERATION,
                                "models": ["missing-model"],
                            },
                            {
                                "name": "shared",
                                "category": PROFILE_CATEGORY_IMAGE_GENERATION,
                                "models": ["ambiguous-model"],
                            },
                        ]
                    }
                ),
                encoding="utf-8",
            )
            app = _make_minimal_app()
            app.profiles = [first, second]

            changed = app._load_model_metadata_from_repo(repo_root)

            self.assertFalse(changed)
            self.assertNotEqual(app.profiles[0].category, PROFILE_CATEGORY_IMAGE_GENERATION)
            self.assertNotEqual(app.profiles[1].category, PROFILE_CATEGORY_IMAGE_GENERATION)
            self.assertEqual(app.profiles[0].health.models, [])
            self.assertEqual(app.profiles[1].health.models, [])

    def test_model_metadata_profile_models_can_match_unique_profile_name(self) -> None:
        with workspace_tempdir() as temp_dir:
            repo_root = temp_dir / "repo"
            repo_root.mkdir()
            profile = Profile.create("image-api", "https://image.example.com", "sk-image")
            metadata_path = repo_root / ".codex-switch"
            metadata_path.mkdir()
            (metadata_path / "model-metadata.json").write_text(
                json.dumps({"profile_models": {"image-api": ["image-fast", "image-pro"]}}),
                encoding="utf-8",
            )
            app = _make_minimal_app()
            app.profiles = [profile]

            changed = app._load_model_metadata_from_repo(repo_root)

            self.assertTrue(changed)
            self.assertEqual(app.profiles[0].health.models, ["image-fast", "image-pro"])

    def test_skill_repo_update_rejects_missing_checksum_entry(self) -> None:
        with workspace_tempdir() as temp_dir:
            cache_dir = temp_dir / "repo"
            skill_dir = cache_dir / "python-helper"
            skill_dir.mkdir(parents=True)
            (skill_dir / "SKILL.md").write_text("Use Python.", encoding="utf-8")
            other_file = cache_dir / "README.md"
            other_file.write_text("checksummed", encoding="utf-8")
            manifest_dir = cache_dir / ".codex-switch"
            manifest_dir.mkdir()
            (manifest_dir / "checksums.json").write_text(
                json.dumps({"sha256": {other_file.relative_to(cache_dir).as_posix(): _file_sha256(other_file)}}),
                encoding="utf-8",
            )
            group = SkillGroup.create("代码组")
            repo = SkillMarketRepo.create(
                "https://github.com/example/skills",
                installed_group_id=group.id,
            )
            app = _make_minimal_app()
            app.skill_groups = [group]
            app.skill_market_repos = [repo]
            app._sync_skill_repo_cache = lambda _repo, _expected=None: cache_dir

            with patch("codex_switch.ui.app.messagebox.showerror") as showerror:
                updated = app._apply_skill_repo_update(repo, automatic=False)

            self.assertFalse(updated)
            self.assertEqual(app.skill_groups[0].skills, [])
            self.assertEqual(app.persist_count, 0)
            self.assertIn("missing python-helper/SKILL.md", showerror.call_args.args[1])

    def test_skill_repo_preview_rejects_checksum_mismatch(self) -> None:
        with workspace_tempdir() as temp_dir:
            repo_root = temp_dir / "preview"
            skill_dir = repo_root / "alpha-helper"
            skill_dir.mkdir(parents=True)
            skill_file = skill_dir / "SKILL.md"
            skill_file.write_text("alpha content", encoding="utf-8")
            manifest_dir = repo_root / ".codex-switch"
            manifest_dir.mkdir()
            (manifest_dir / "checksums.json").write_text(
                json.dumps({"sha256": {skill_file.relative_to(repo_root).as_posix(): "0" * 64}}),
                encoding="utf-8",
            )
            repo = SkillMarketRepo.create("https://github.com/example/skills")
            app = _make_minimal_app()
            app._sync_skill_repo_preview_cache = lambda _repo: repo_root

            with self.assertRaisesRegex(RuntimeError, "Checksum mismatch"):
                app._preview_skill_repo_sources(repo)

    def test_skill_repo_preview_discovers_repo_skills(self) -> None:
        with workspace_tempdir() as temp_dir:
            repo_root = temp_dir / "preview"
            for name in ("alpha-helper", "beta-helper"):
                skill_dir = repo_root / name
                skill_dir.mkdir(parents=True)
                (skill_dir / "SKILL.md").write_text(f"{name} content", encoding="utf-8")
            repo = SkillMarketRepo.create("https://github.com/example/skills")
            app = _make_minimal_app()
            app._sync_skill_repo_preview_cache = lambda _repo: repo_root

            sources = app._preview_skill_repo_sources(repo)

            self.assertEqual([source.name for source in sources], ["alpha-helper", "beta-helper"])

    def test_skill_repo_preview_filter_uses_cached_sources(self) -> None:
        class FakePreviewTree:
            def __init__(self) -> None:
                self.rows: dict[str, tuple[str, str]] = {}

            def get_children(self) -> list[str]:
                return list(self.rows)

            def delete(self, item_id: str) -> None:
                self.rows.pop(item_id, None)

            def insert(self, _parent: str, _index: str, *, iid: str, values: tuple[str, str]) -> None:
                self.rows[iid] = values

        with workspace_tempdir() as temp_dir:
            repo = SkillMarketRepo.create("https://github.com/example/skills")
            sources = [
                SkillSource("alpha-helper", "Alpha Helper", temp_dir / "alpha-helper"),
                SkillSource("beta-helper", "Beta Helper", temp_dir / "tooling" / "beta-helper"),
                SkillSource("gamma-helper", "Gamma Helper", temp_dir / "category" / "gamma-helper"),
            ]
            app = _make_minimal_app()
            app.skill_market_repos = [repo]
            app.skill_repo_preview_tree = FakePreviewTree()

            app._render_skill_repo_preview(repo, sources)

            self.assertEqual(set(app.skill_repo_preview_tree.rows), {str(source.source_path) for source in sources})

            app.skill_repo_preview_filter_var.set("beta")
            app.apply_skill_repo_preview_filter()

            self.assertEqual(list(app.skill_repo_preview_tree.rows.values())[0][0], "beta-helper")
            self.assertIn("1 / 3", app.skill_repo_preview_var.get())
            self.assertEqual([source.name for source in app.skill_repo_preview_sources], ["alpha-helper", "beta-helper", "gamma-helper"])

            app.skill_repo_preview_filter_var.set("category")
            app.apply_skill_repo_preview_filter()

            self.assertEqual(list(app.skill_repo_preview_tree.rows.values())[0][0], "gamma-helper")

            app.clear_skill_repo_preview_filter()
            app.apply_skill_repo_preview_filter()

            self.assertEqual(set(app.skill_repo_preview_tree.rows), {str(source.source_path) for source in sources})

    def test_skill_repo_filter_matches_repo_metadata(self) -> None:
        group = SkillGroup.create("代码组")
        repo_alpha = SkillMarketRepo.create(
            "https://github.com/example/alpha-skills",
            branch="main",
            last_sync_commit="commit-alpha",
            auto_update=False,
            installed_group_id=group.id,
        )
        repo_beta = SkillMarketRepo.create(
            "https://github.com/example/beta-skills",
            branch="release/v1",
            last_sync_commit="commit-beta",
            auto_update=True,
        )
        app = _make_minimal_app()
        app.skill_groups = [group]
        app.skill_market_repos = [repo_alpha, repo_beta]
        app.skill_repo_filter_var = _ValueVar("")

        self.assertEqual([repo.url for repo in app._filtered_skill_market_repos()], [repo_alpha.url, repo_beta.url])

        app.skill_repo_filter_var.set("release")
        self.assertEqual([repo.url for repo in app._filtered_skill_market_repos()], [repo_beta.url])

        app.skill_repo_filter_var.set("代码")
        self.assertEqual([repo.url for repo in app._filtered_skill_market_repos()], [repo_alpha.url])

        app.skill_repo_filter_var.set("自动")
        self.assertEqual([repo.url for repo in app._filtered_skill_market_repos()], [repo_beta.url])

        app.clear_skill_repo_filter()
        self.assertEqual([repo.url for repo in app._filtered_skill_market_repos()], [repo_alpha.url, repo_beta.url])

    def test_skill_repo_preview_sync_does_not_mark_repo_synced(self) -> None:
        class FakeCompleted:
            def __init__(self, *, returncode: int = 0, stdout: str = "", stderr: str = "") -> None:
                self.returncode = returncode
                self.stdout = stdout
                self.stderr = stderr

        with workspace_tempdir() as temp_dir:
            repo = SkillMarketRepo.create("https://github.com/example/skills", last_sync_commit="old-repo")
            app = _make_minimal_app()
            app.store = type("FakeStore", (), {"root_dir": temp_dir})()
            app.skill_market_repos = [repo]

            def fake_run(args, **_kwargs):
                if args[:2] == ["git", "ls-remote"]:
                    return FakeCompleted(stdout="new-repo refs/heads/main\n")
                if args[1] == "init":
                    return FakeCompleted()
                if args[1:4] == ["-C", str(temp_dir / "skill-market" / f"{repo.id}-preview"), "remote"]:
                    return FakeCompleted()
                if args[1:4] == ["-C", str(temp_dir / "skill-market" / f"{repo.id}-preview"), "fetch"]:
                    return FakeCompleted()
                if args[1:4] == ["-C", str(temp_dir / "skill-market" / f"{repo.id}-preview"), "checkout"]:
                    return FakeCompleted()
                if args[-2:] == ["rev-parse", "HEAD"]:
                    return FakeCompleted(stdout="new-repo\n")
                raise AssertionError(args)

            with patch("codex_switch.ui.app.subprocess.run", side_effect=fake_run):
                cache_dir = app._sync_skill_repo_preview_cache(repo)

            self.assertEqual(cache_dir.name, f"{repo.id}-preview")
            self.assertEqual(app.skill_market_repos[0].last_sync_commit, "old-repo")

    def test_skill_repo_cache_syncs_tag_and_commit_refs_with_real_git(self) -> None:
        git_available = subprocess.run(["git", "--version"], capture_output=True, text=True, check=False, timeout=10)
        if git_available.returncode != 0:
            self.skipTest("git is not available")

        def run_git(*args: str) -> str:
            completed = subprocess.run(
                ["git", *args],
                capture_output=True,
                text=True,
                check=False,
                timeout=30,
            )
            if completed.returncode != 0:
                raise AssertionError(completed.stderr.strip() or completed.stdout.strip())
            return completed.stdout.strip()

        with workspace_tempdir() as temp_dir:
            remote_repo = temp_dir / "remote"
            remote_repo.mkdir()
            skill_dir = remote_repo / "tag-helper"
            skill_dir.mkdir()
            (skill_dir / "SKILL.md").write_text("tag helper", encoding="utf-8")
            run_git("-C", str(remote_repo), "init")
            run_git("-C", str(remote_repo), "add", ".")
            run_git(
                "-C",
                str(remote_repo),
                "-c",
                "user.name=Codex Test",
                "-c",
                "user.email=codex@example.test",
                "commit",
                "-m",
                "initial skill",
            )
            commit_hash = run_git("-C", str(remote_repo), "rev-parse", "HEAD")
            run_git("-C", str(remote_repo), "tag", "v1.0.0")

            app = _make_minimal_app()
            app.store = type("FakeStore", (), {"root_dir": temp_dir / "state"})()
            tag_repo = SkillMarketRepo.create(str(remote_repo), branch="v1.0.0")
            app.skill_market_repos = [tag_repo]

            update = app._skill_repo_remote_update(tag_repo)
            tag_cache = app._sync_skill_repo_cache(tag_repo, update.latest_commit)

            self.assertEqual(update.latest_commit, commit_hash)
            self.assertEqual((tag_cache / "tag-helper" / "SKILL.md").read_text(encoding="utf-8"), "tag helper")
            self.assertEqual(app.skill_market_repos[0].last_sync_commit, commit_hash)

            pinned_repo = SkillMarketRepo.create(str(remote_repo), branch=commit_hash)
            app.skill_market_repos = [pinned_repo]

            pinned_update = app._skill_repo_remote_update(pinned_repo)
            pinned_cache = app._sync_skill_repo_cache(pinned_repo, pinned_update.latest_commit)

            self.assertEqual(pinned_update.latest_commit, commit_hash)
            self.assertEqual((pinned_cache / "tag-helper" / "SKILL.md").read_text(encoding="utf-8"), "tag helper")
            self.assertEqual(app.skill_market_repos[0].last_sync_commit, commit_hash)

    def test_install_selected_skill_repo_preview_imports_only_selected_skill(self) -> None:
        class FakeRepoTree:
            def __init__(self, selected_id: str) -> None:
                self.selected_id = selected_id

            def selection(self) -> list[str]:
                return [self.selected_id]

            def focus(self) -> str:
                return self.selected_id

        class FakePreviewTree:
            def __init__(self, rows: dict[str, tuple[str, str]], selected_ids: list[str]) -> None:
                self.rows = rows
                self.selected_ids = selected_ids

            def selection(self) -> list[str]:
                return list(self.selected_ids)

            def item(self, item_id: str, option: str | None = None):
                if option == "values":
                    return self.rows[item_id]
                return {"values": self.rows[item_id]}

        with workspace_tempdir() as temp_dir:
            preview_root = temp_dir / "repo-preview"
            selected_dir = preview_root / "alpha-helper"
            skipped_dir = preview_root / "beta-helper"
            selected_dir.mkdir(parents=True)
            skipped_dir.mkdir(parents=True)
            (selected_dir / "SKILL.md").write_text("alpha content", encoding="utf-8")
            (skipped_dir / "SKILL.md").write_text("beta content", encoding="utf-8")
            group = SkillGroup.create("本地组")
            repo = SkillMarketRepo.create("https://github.com/example/skills")
            app = _make_minimal_app()
            app.skill_groups = [group]
            app.skill_market_repos = [repo]
            app.skill_repo_tree = FakeRepoTree(repo.id)
            app.skill_repo_preview_tree = FakePreviewTree(
                {
                    str(selected_dir): ("alpha-helper", str(selected_dir)),
                    str(skipped_dir): ("beta-helper", str(skipped_dir)),
                },
                [str(selected_dir)],
            )
            app._choose_skill_group = lambda _title: group

            with (
                patch("codex_switch.ui.app.messagebox.showinfo") as showinfo,
            ):
                app.install_selected_skill_repo_preview_to_group()

            self.assertEqual([skill.name for skill in app.skill_groups[0].skills], ["alpha-helper"])
            self.assertEqual(app.skill_groups[0].skills[0].content, "alpha content")
            self.assertFalse(app.skill_market_repos[0].installed_group_id)
            self.assertEqual(app.persist_count, 1)
            self.assertIn("已安装 1 个选中 Skill", app.status_var.get())
            showinfo.assert_not_called()

    def test_local_skill_add_and_edit_preserve_type(self) -> None:
        class FakeGroupTree:
            def __init__(self, selected_id: str) -> None:
                self.selected_id = selected_id

            def selection(self) -> list[str]:
                return [self.selected_id]

            def focus(self) -> str:
                return self.selected_id

        group = SkillGroup.create("本地组")
        app = _make_minimal_app()
        app.skill_groups = [group]
        app.skill_group_tree = FakeGroupTree(group.id)

        with (
            patch(
                "codex_switch.ui.app.simpledialog.askstring",
                side_effect=["config-helper", "config", "2.0.0", "config content"],
            ),
            patch("codex_switch.ui.app.messagebox.showinfo") as showinfo,
        ):
            app.add_skill_to_group()

        self.assertEqual(app.skill_groups[0].skills[0].name, "config-helper")
        self.assertEqual(app.skill_groups[0].skills[0].type, SKILL_TYPE_CONFIG)
        self.assertEqual(app.skill_groups[0].skills[0].version, "2.0.0")
        showinfo.assert_not_called()

        with patch(
            "codex_switch.ui.app.simpledialog.askstring",
            side_effect=["config-helper", "script-helper", "脚本", "3.0.0", "script content"],
        ):
            app.edit_skill_in_group()

        self.assertEqual(app.skill_groups[0].skills[0].name, "script-helper")
        self.assertEqual(app.skill_groups[0].skills[0].type, SKILL_TYPE_SCRIPT)
        self.assertEqual(app.skill_groups[0].skills[0].content, "script content")
        self.assertEqual(app.persist_count, 2)

    def test_project_metadata_reloads_skill_group_ids_from_repo(self) -> None:
        with workspace_tempdir() as temp_dir:
            old_skill = SkillDefinition.create("old-helper", content="old")
            new_skill = SkillDefinition.create("new-helper", content="new")
            old_group = SkillGroup.create("old", skills=[old_skill])
            new_group = SkillGroup.create("new", skills=[new_skill])
            project = ProjectRecord.create(
                str(temp_dir),
                "profile-id",
                skill_group_ids=[old_group.id],
                skills=[old_skill],
                skill_names=[old_skill.name],
            )
            metadata_dir = temp_dir / ".codex-switch"
            metadata_dir.mkdir()
            (metadata_dir / "project.json").write_text(
                json.dumps({"skill_group_ids": [new_group.id]}),
                encoding="utf-8",
            )
            app = _make_minimal_app()
            app.skill_groups = [old_group, new_group]
            app.projects = [project]

            updated, changed = app._load_project_metadata_from_repo(project, temp_dir)

            self.assertTrue(changed)
            self.assertEqual(updated.skill_group_ids, [new_group.id])
            self.assertEqual([skill.name for skill in updated.skills], ["new-helper"])
            self.assertEqual(updated.skill_names, ["new-helper"])
            self.assertEqual(app.projects[0].skill_group_ids, [new_group.id])

    def test_project_metadata_reloads_profile_ids_from_repo(self) -> None:
        with workspace_tempdir() as temp_dir:
            old_codex = Profile.create("old-codex", "https://old-codex.example.com", "sk-old-codex", vendor=VENDOR_CODEX)
            old_claude = Profile.create("old-claude", "https://old-claude.example.com", "sk-old-claude", vendor=VENDOR_CLAUDE)
            new_codex = Profile.create("new-codex", "https://new-codex.example.com", "sk-new-codex", vendor=VENDOR_CODEX)
            new_claude = Profile.create("new-claude", "https://new-claude.example.com", "sk-new-claude", vendor=VENDOR_CLAUDE)
            project = ProjectRecord.create(
                str(temp_dir),
                old_codex.id,
                codex_profile_id=old_codex.id,
                claude_profile_id=old_claude.id,
            )
            metadata_dir = temp_dir / ".codex-switch"
            metadata_dir.mkdir()
            (metadata_dir / "project.json").write_text(
                json.dumps({"codex_profile_id": new_codex.id, "claude_profile_id": new_claude.id}),
                encoding="utf-8",
            )
            app = _make_minimal_app()
            app.profiles = [old_codex, old_claude, new_codex, new_claude]
            app.projects = [project]

            updated, changed = app._load_project_metadata_from_repo(project, temp_dir)

            self.assertTrue(changed)
            self.assertEqual(updated.profile_id, new_codex.id)
            self.assertEqual(project_codex_profile_id(updated), new_codex.id)
            self.assertEqual(project_claude_profile_id(updated), new_claude.id)
            self.assertEqual(project_codex_profile_id(app.projects[0]), new_codex.id)
            self.assertEqual(project_claude_profile_id(app.projects[0]), new_claude.id)

    def test_project_metadata_ignores_unknown_or_unsupported_profile_ids(self) -> None:
        with workspace_tempdir() as temp_dir:
            codex = Profile.create("codex", "https://codex.example.com", "sk-codex", vendor=VENDOR_CODEX)
            claude = Profile.create("claude", "https://claude.example.com", "sk-claude", vendor=VENDOR_CLAUDE)
            project = ProjectRecord.create(
                str(temp_dir),
                codex.id,
                codex_profile_id=codex.id,
                claude_profile_id=claude.id,
            )
            (temp_dir / "codex-switch-project.json").write_text(
                json.dumps({"codex_profile_id": claude.id, "claude_profile_id": "missing-profile"}),
                encoding="utf-8",
            )
            app = _make_minimal_app()
            app.profiles = [codex, claude]
            app.projects = [project]

            updated, changed = app._load_project_metadata_from_repo(project, temp_dir)

            self.assertFalse(changed)
            self.assertEqual(project_codex_profile_id(updated), codex.id)
            self.assertEqual(project_claude_profile_id(updated), claude.id)
            self.assertEqual(project_codex_profile_id(app.projects[0]), codex.id)
            self.assertEqual(project_claude_profile_id(app.projects[0]), claude.id)

    def test_project_metadata_ignores_unknown_skill_group_ids(self) -> None:
        with workspace_tempdir() as temp_dir:
            skill = SkillDefinition.create("old-helper", content="old")
            group = SkillGroup.create("old", skills=[skill])
            project = ProjectRecord.create(
                str(temp_dir),
                "profile-id",
                skill_group_ids=[group.id],
                skills=[skill],
                skill_names=[skill.name],
            )
            (temp_dir / "codex-switch-project.json").write_text(
                json.dumps({"skill_group_ids": ["missing-group"]}),
                encoding="utf-8",
            )
            app = _make_minimal_app()
            app.skill_groups = [group]
            app.projects = [project]

            updated, changed = app._load_project_metadata_from_repo(project, temp_dir)

            self.assertFalse(changed)
            self.assertEqual(updated.skill_group_ids, [group.id])
            self.assertEqual(app.projects[0].skill_group_ids, [group.id])

    def test_project_update_applies_project_metadata_after_git_pull(self) -> None:
        class FakeCompleted:
            def __init__(self, *, returncode: int = 0, stdout: str = "", stderr: str = "") -> None:
                self.returncode = returncode
                self.stdout = stdout
                self.stderr = stderr

        with workspace_tempdir() as temp_dir:
            (temp_dir / ".git").mkdir()
            old_skill = SkillDefinition.create("old-helper", content="old")
            new_skill = SkillDefinition.create("new-helper", content="new")
            old_group = SkillGroup.create("old", skills=[old_skill])
            new_group = SkillGroup.create("new", skills=[new_skill])
            project = ProjectRecord.create(
                str(temp_dir),
                "profile-id",
                skill_group_ids=[old_group.id],
                skills=[old_skill],
                skill_names=[old_skill.name],
                github_repo="https://github.com/example/project",
                github_last_sync_commit="oldcommit",
            )
            metadata_dir = temp_dir / ".codex-switch"
            metadata_dir.mkdir()
            (metadata_dir / "project.json").write_text(
                json.dumps({"skill_group_ids": [new_group.id]}),
                encoding="utf-8",
            )
            app = _make_minimal_app()
            app.skill_groups = [old_group, new_group]
            app.projects = [project]

            def fake_run(args, **_kwargs):
                if args[-2:] == ["pull", "--ff-only"]:
                    return FakeCompleted()
                if args[-2:] == ["rev-parse", "HEAD"]:
                    return FakeCompleted(stdout="newcommit\n")
                raise AssertionError(args)

            with patch("codex_switch.ui.app.subprocess.run", side_effect=fake_run):
                applied = app._apply_project_update(project, "newcommit", automatic=False)

            self.assertTrue(applied)
            self.assertEqual(app.projects[0].github_last_sync_commit, "newcommit")
            self.assertEqual(app.projects[0].skill_group_ids, [new_group.id])
            self.assertEqual([skill.name for skill in app.projects[0].skills], ["new-helper"])
            self.assertIn("项目元数据已同步", app.status_var.get())
            self.assertEqual(app.persist_count, 1)

    def test_project_update_syncs_api_binding_after_metadata_profile_change(self) -> None:
        class FakeCompleted:
            def __init__(self, *, returncode: int = 0, stdout: str = "", stderr: str = "") -> None:
                self.returncode = returncode
                self.stdout = stdout
                self.stderr = stderr

        with workspace_tempdir() as temp_dir:
            (temp_dir / ".git").mkdir()
            old_codex = Profile.create("old-codex", "https://old-codex.example.com", "sk-old-codex", vendor=VENDOR_CODEX)
            old_claude = Profile.create("old-claude", "https://old-claude.example.com", "sk-old-claude", vendor=VENDOR_CLAUDE)
            new_codex = Profile.create("new-codex", "https://new-codex.example.com", "sk-new-codex", vendor=VENDOR_CODEX)
            new_claude = Profile.create("new-claude", "https://new-claude.example.com", "sk-new-claude", vendor=VENDOR_CLAUDE)
            project = ProjectRecord.create(
                str(temp_dir),
                old_codex.id,
                codex_profile_id=old_codex.id,
                claude_profile_id=old_claude.id,
                github_repo="https://github.com/example/project",
                github_last_sync_commit="oldcommit",
            )
            metadata_dir = temp_dir / ".codex-switch"
            metadata_dir.mkdir()
            (metadata_dir / "project.json").write_text(
                json.dumps({"codex_profile_id": new_codex.id, "claude_profile_id": new_claude.id}),
                encoding="utf-8",
            )
            app = _make_minimal_app()
            app.profiles = [old_codex, old_claude, new_codex, new_claude]
            app.projects = [project]
            sync_calls = []

            def fake_sync_project_api_binding(project_arg, *, sync_codex=True, sync_claude=True):
                sync_calls.append((project_arg, sync_codex, sync_claude))
                return True

            app._sync_project_api_binding = fake_sync_project_api_binding

            def fake_run(args, **_kwargs):
                if args[-2:] == ["pull", "--ff-only"]:
                    return FakeCompleted()
                if args[-2:] == ["rev-parse", "HEAD"]:
                    return FakeCompleted(stdout="newcommit\n")
                raise AssertionError(args)

            with patch("codex_switch.ui.app.subprocess.run", side_effect=fake_run):
                applied = app._apply_project_update(project, "newcommit", automatic=False)

            self.assertTrue(applied)
            self.assertEqual(len(sync_calls), 1)
            synced_project, sync_codex, sync_claude = sync_calls[0]
            self.assertTrue(sync_codex)
            self.assertTrue(sync_claude)
            self.assertEqual(project_codex_profile_id(synced_project), new_codex.id)
            self.assertEqual(project_claude_profile_id(synced_project), new_claude.id)
            self.assertEqual(app.projects[0].github_last_sync_commit, "newcommit")
            self.assertEqual(app.persist_count, 1)

    def test_project_update_rolls_back_metadata_profile_change_when_api_sync_fails(self) -> None:
        class FakeCompleted:
            def __init__(self, *, returncode: int = 0, stdout: str = "", stderr: str = "") -> None:
                self.returncode = returncode
                self.stdout = stdout
                self.stderr = stderr

        with workspace_tempdir() as temp_dir:
            (temp_dir / ".git").mkdir()
            old_codex = Profile.create("old-codex", "https://old-codex.example.com", "sk-old-codex", vendor=VENDOR_CODEX)
            old_claude = Profile.create("old-claude", "https://old-claude.example.com", "sk-old-claude", vendor=VENDOR_CLAUDE)
            new_codex = Profile.create("new-codex", "https://new-codex.example.com", "sk-new-codex", vendor=VENDOR_CODEX)
            project = ProjectRecord.create(
                str(temp_dir),
                old_codex.id,
                codex_profile_id=old_codex.id,
                claude_profile_id=old_claude.id,
                github_repo="https://github.com/example/project",
                github_last_sync_commit="oldcommit",
            )
            metadata_dir = temp_dir / ".codex-switch"
            metadata_dir.mkdir()
            (metadata_dir / "project.json").write_text(
                json.dumps({"codex_profile_id": new_codex.id}),
                encoding="utf-8",
            )
            app = _make_minimal_app()
            app.profiles = [old_codex, old_claude, new_codex]
            app.projects = [project]
            app._sync_project_api_binding = lambda *_args, **_kwargs: False

            def fake_run(args, **_kwargs):
                if args[-2:] == ["pull", "--ff-only"]:
                    return FakeCompleted()
                if args[-2:] == ["rev-parse", "HEAD"]:
                    return FakeCompleted(stdout="newcommit\n")
                raise AssertionError(args)

            with patch("codex_switch.ui.app.subprocess.run", side_effect=fake_run):
                applied = app._apply_project_update(project, "newcommit", automatic=False)

            self.assertFalse(applied)
            self.assertEqual(project_codex_profile_id(app.projects[0]), old_codex.id)
            self.assertEqual(project_claude_profile_id(app.projects[0]), old_claude.id)
            self.assertEqual(app.projects[0].github_last_sync_commit, "oldcommit")
            self.assertEqual(app.persist_count, 0)

    def test_project_update_rejects_head_mismatch_after_git_pull(self) -> None:
        class FakeCompleted:
            def __init__(self, *, returncode: int = 0, stdout: str = "", stderr: str = "") -> None:
                self.returncode = returncode
                self.stdout = stdout
                self.stderr = stderr

        with workspace_tempdir() as temp_dir:
            (temp_dir / ".git").mkdir()
            project = ProjectRecord.create(
                str(temp_dir),
                "profile-id",
                github_repo="https://github.com/example/project",
                github_last_sync_commit="oldcommit",
            )
            app = _make_minimal_app()
            app.projects = [project]

            def fake_run(args, **_kwargs):
                if args[-2:] == ["pull", "--ff-only"]:
                    return FakeCompleted()
                if args[-2:] == ["rev-parse", "HEAD"]:
                    return FakeCompleted(stdout="different-commit\n")
                raise AssertionError(args)

            with patch("codex_switch.ui.app.subprocess.run", side_effect=fake_run):
                with patch("codex_switch.ui.app.messagebox.showerror") as showerror:
                    applied = app._apply_project_update(project, "expected-commit", automatic=False)

            self.assertFalse(applied)
            self.assertEqual(app.projects[0].github_last_sync_commit, "oldcommit")
            self.assertEqual(app.persist_count, 0)
            self.assertIn("不一致", showerror.call_args.args[1])

    def test_project_update_rejects_metadata_checksum_mismatch(self) -> None:
        class FakeCompleted:
            def __init__(self, *, returncode: int = 0, stdout: str = "", stderr: str = "") -> None:
                self.returncode = returncode
                self.stdout = stdout
                self.stderr = stderr

        with workspace_tempdir() as temp_dir:
            (temp_dir / ".git").mkdir()
            old_skill = SkillDefinition.create("old-helper", content="old")
            new_skill = SkillDefinition.create("new-helper", content="new")
            old_group = SkillGroup.create("old", skills=[old_skill])
            new_group = SkillGroup.create("new", skills=[new_skill])
            project = ProjectRecord.create(
                str(temp_dir),
                "profile-id",
                skill_group_ids=[old_group.id],
                skills=[old_skill],
                skill_names=[old_skill.name],
                github_repo="https://github.com/example/project",
                github_last_sync_commit="oldcommit",
            )
            metadata_dir = temp_dir / ".codex-switch"
            metadata_dir.mkdir()
            metadata_path = metadata_dir / "project.json"
            metadata_path.write_text(
                json.dumps({"skill_group_ids": [new_group.id]}),
                encoding="utf-8",
            )
            (metadata_dir / "checksums.json").write_text(
                json.dumps({"sha256": {metadata_path.relative_to(temp_dir).as_posix(): "0" * 64}}),
                encoding="utf-8",
            )
            app = _make_minimal_app()
            app.skill_groups = [old_group, new_group]
            app.projects = [project]

            def fake_run(args, **_kwargs):
                if args[-2:] == ["pull", "--ff-only"]:
                    return FakeCompleted()
                if args[-2:] == ["rev-parse", "HEAD"]:
                    return FakeCompleted(stdout="newcommit\n")
                raise AssertionError(args)

            with patch("codex_switch.ui.app.subprocess.run", side_effect=fake_run):
                with patch("codex_switch.ui.app.messagebox.showerror") as showerror:
                    applied = app._apply_project_update(project, "newcommit", automatic=False)

            self.assertFalse(applied)
            self.assertEqual(app.projects[0].github_last_sync_commit, "oldcommit")
            self.assertEqual(app.projects[0].skill_group_ids, [old_group.id])
            self.assertEqual([skill.name for skill in app.projects[0].skills], ["old-helper"])
            self.assertEqual(app.persist_count, 0)
            self.assertIn("Checksum mismatch", showerror.call_args.args[1])

    def test_project_hot_update_uses_real_git_to_sync_project_metadata(self) -> None:
        git_available = subprocess.run(["git", "--version"], capture_output=True, text=True, check=False, timeout=10)
        if git_available.returncode != 0:
            self.skipTest("git is not available")

        def run_git(*args: str) -> str:
            completed = subprocess.run(
                ["git", *args],
                capture_output=True,
                text=True,
                check=False,
                timeout=30,
            )
            if completed.returncode != 0:
                raise AssertionError(completed.stderr.strip() or completed.stdout.strip())
            return completed.stdout.strip()

        with workspace_tempdir() as temp_dir:
            remote_repo = temp_dir / "remote"
            local_repo = temp_dir / "local"
            remote_repo.mkdir()
            run_git("-C", str(remote_repo), "init")

            old_skill = SkillDefinition.create("old-helper", content="old")
            new_skill = SkillDefinition.create("new-helper", content="new")
            old_group = SkillGroup.create("old", skills=[old_skill])
            new_group = SkillGroup.create("new", skills=[new_skill])

            metadata_dir = remote_repo / ".codex-switch"
            metadata_dir.mkdir()
            metadata_path = metadata_dir / "project.json"
            metadata_path.write_text(
                json.dumps({"skill_group_ids": [old_group.id]}),
                encoding="utf-8",
            )
            run_git("-C", str(remote_repo), "add", ".")
            run_git(
                "-C",
                str(remote_repo),
                "-c",
                "user.name=Codex Test",
                "-c",
                "user.email=codex@example.test",
                "commit",
                "-m",
                "initial",
            )
            old_commit = run_git("-C", str(remote_repo), "rev-parse", "HEAD")

            run_git("clone", str(remote_repo), str(local_repo))

            metadata_path.write_text(
                json.dumps({"skill_group_ids": [new_group.id]}),
                encoding="utf-8",
            )
            run_git("-C", str(remote_repo), "add", ".")
            run_git(
                "-C",
                str(remote_repo),
                "-c",
                "user.name=Codex Test",
                "-c",
                "user.email=codex@example.test",
                "commit",
                "-m",
                "update project skills",
            )

            project = ProjectRecord.create(
                str(local_repo),
                "profile-id",
                skill_group_ids=[old_group.id],
                skills=[old_skill],
                skill_names=[old_skill.name],
                github_repo=str(remote_repo),
                github_last_sync_commit=old_commit,
                github_auto_update=True,
            )
            app = _make_minimal_app()
            app.skill_groups = [old_group, new_group]
            app.projects = [project]

            update = app._project_remote_update(project)
            applied = app._apply_project_update(project, update.latest_commit, automatic=True)

            self.assertTrue(update.has_update)
            self.assertTrue(applied)
            self.assertEqual(app.projects[0].github_last_sync_commit, update.latest_commit)
            self.assertEqual(app.projects[0].skill_group_ids, [new_group.id])
            self.assertEqual([skill.name for skill in app.projects[0].skills], ["new-helper"])

    def test_real_git_hot_update_syncs_skills_profile_project_metadata_and_checksums(self) -> None:
        git_available = subprocess.run(["git", "--version"], capture_output=True, text=True, check=False, timeout=10)
        if git_available.returncode != 0:
            self.skipTest("git is not available")

        def run_git(*args: str) -> str:
            completed = subprocess.run(
                ["git", *args],
                capture_output=True,
                text=True,
                check=False,
                timeout=30,
            )
            if completed.returncode != 0:
                raise AssertionError(completed.stderr.strip() or completed.stdout.strip())
            return completed.stdout.strip()

        def write_checksums(repo_root: Path, paths: list[Path]) -> None:
            manifest_dir = repo_root / ".codex-switch"
            manifest_dir.mkdir(exist_ok=True)
            manifest = {
                "sha256": {
                    path.relative_to(repo_root).as_posix(): _file_sha256(path)
                    for path in paths
                }
            }
            (manifest_dir / "checksums.json").write_text(
                json.dumps(manifest, sort_keys=True),
                encoding="utf-8",
            )

        with workspace_tempdir() as temp_dir:
            profile = Profile.create("vision-api", "https://image.example.com", "sk-local")
            group = SkillGroup.create("repo group")
            app = _make_minimal_app()
            app.store = type("FakeStore", (), {"root_dir": temp_dir / "state"})()
            app.profiles = [profile]
            app.skill_groups = [group]

            skills_remote = temp_dir / "skills-remote"
            skills_remote.mkdir()
            skill_dir = skills_remote / "combo-helper"
            skill_dir.mkdir()
            skill_file = skill_dir / "SKILL.md"
            skill_file.write_text("combo helper", encoding="utf-8")
            model_metadata_dir = skills_remote / ".codex-switch"
            model_metadata_dir.mkdir()
            model_metadata_path = model_metadata_dir / "model-metadata.json"
            model_metadata_path.write_text(
                json.dumps(
                    {
                        "profiles": [
                            {
                                "id": profile.id,
                                "category": PROFILE_CATEGORY_IMAGE_GENERATION,
                                "api_provided": False,
                                "provider_name": "VisionVendor",
                                "models": ["image-fast", "image-pro"],
                            }
                        ]
                    },
                    sort_keys=True,
                ),
                encoding="utf-8",
            )
            write_checksums(skills_remote, [skill_file, model_metadata_path])
            run_git("-C", str(skills_remote), "init")
            run_git("-C", str(skills_remote), "add", ".")
            run_git(
                "-C",
                str(skills_remote),
                "-c",
                "user.name=Codex Test",
                "-c",
                "user.email=codex@example.test",
                "commit",
                "-m",
                "skills metadata",
            )
            run_git("-C", str(skills_remote), "branch", "-M", "main")

            skill_repo = SkillMarketRepo.create(
                str(skills_remote),
                installed_group_id=group.id,
                auto_update=True,
            )
            app.skill_market_repos = [skill_repo]

            skill_update = app._skill_repo_remote_update(skill_repo)
            skill_applied = app._apply_skill_repo_update(
                skill_repo,
                automatic=True,
                expected_commit=skill_update.latest_commit,
            )

            self.assertTrue(skill_update.has_update)
            self.assertTrue(skill_applied)
            self.assertEqual(app.skill_market_repos[0].last_sync_commit, skill_update.latest_commit)
            self.assertEqual([skill.name for skill in app.skill_groups[0].skills], ["combo-helper"])
            self.assertEqual(app.profiles[0].category, PROFILE_CATEGORY_IMAGE_GENERATION)
            self.assertFalse(app.profiles[0].api_provided)
            self.assertEqual(app.profiles[0].api_keys, [])
            self.assertEqual(app.profiles[0].provider_name, "VisionVendor")
            self.assertEqual(app.profiles[0].health.models, ["image-fast", "image-pro"])

            project_remote = temp_dir / "project-remote"
            local_project = temp_dir / "project-local"
            project_remote.mkdir()
            run_git("-C", str(project_remote), "init")
            project_metadata_dir = project_remote / ".codex-switch"
            project_metadata_dir.mkdir()
            project_metadata_path = project_metadata_dir / "project.json"
            project_metadata_path.write_text(
                json.dumps({"skill_group_ids": []}, sort_keys=True),
                encoding="utf-8",
            )
            write_checksums(project_remote, [project_metadata_path])
            run_git("-C", str(project_remote), "add", ".")
            run_git(
                "-C",
                str(project_remote),
                "-c",
                "user.name=Codex Test",
                "-c",
                "user.email=codex@example.test",
                "commit",
                "-m",
                "initial project metadata",
            )
            old_project_commit = run_git("-C", str(project_remote), "rev-parse", "HEAD")
            run_git("clone", str(project_remote), str(local_project))

            project_metadata_path.write_text(
                json.dumps({"skill_group_ids": [group.id]}, sort_keys=True),
                encoding="utf-8",
            )
            write_checksums(project_remote, [project_metadata_path])
            run_git("-C", str(project_remote), "add", ".")
            run_git(
                "-C",
                str(project_remote),
                "-c",
                "user.name=Codex Test",
                "-c",
                "user.email=codex@example.test",
                "commit",
                "-m",
                "bind project skills",
            )

            project = ProjectRecord.create(
                str(local_project),
                profile.id,
                skill_group_ids=[],
                skills=[],
                skill_names=[],
                github_repo=str(project_remote),
                github_last_sync_commit=old_project_commit,
                github_auto_update=True,
            )
            app.projects = [project]

            project_update = app._project_remote_update(project)
            project_applied = app._apply_project_update(
                project,
                project_update.latest_commit,
                automatic=True,
            )

            self.assertTrue(project_update.has_update)
            self.assertTrue(project_applied)
            self.assertEqual(app.projects[0].github_last_sync_commit, project_update.latest_commit)
            self.assertEqual(app.projects[0].skill_group_ids, [group.id])
            self.assertEqual([skill.name for skill in app.projects[0].skills], ["combo-helper"])
            self.assertGreaterEqual(app.persist_count, 2)

    def test_project_hot_update_can_read_public_github_repo(self) -> None:
        if os.environ.get("CODEX_SWITCH_RUN_GITHUB_NETWORK") != "1":
            self.skipTest("set CODEX_SWITCH_RUN_GITHUB_NETWORK=1 to run public GitHub integration")
        git_available = subprocess.run(["git", "--version"], capture_output=True, text=True, check=False, timeout=10)
        if git_available.returncode != 0:
            self.skipTest("git is not available")

        repo_url = os.environ.get("CODEX_SWITCH_GITHUB_TEST_REPO", "https://github.com/octocat/Hello-World")

        def run_git(*args: str, timeout: int = 120) -> str:
            completed = subprocess.run(
                ["git", *args],
                capture_output=True,
                text=True,
                check=False,
                timeout=timeout,
            )
            if completed.returncode != 0:
                raise AssertionError(completed.stderr.strip() or completed.stdout.strip())
            return completed.stdout.strip()

        with workspace_tempdir() as temp_dir:
            local_repo = temp_dir / "public-github"
            run_git("clone", "--depth", "1", repo_url, str(local_repo))
            local_commit = run_git("-C", str(local_repo), "rev-parse", "HEAD", timeout=20)
            project = ProjectRecord.create(
                str(local_repo),
                "profile-id",
                github_repo=repo_url,
                github_last_sync_commit=local_commit,
                github_auto_update=True,
            )
            app = _make_minimal_app()
            app.projects = [project]

            update = app._project_remote_update(project)
            applied = app._apply_project_update(project, update.latest_commit, automatic=True)

            self.assertTrue(applied)
            self.assertTrue(update.latest_commit)
            self.assertEqual(app.projects[0].github_last_sync_commit, update.latest_commit)
            self.assertGreaterEqual(app.persist_count, 1)

    def test_add_account_pool_channel_saves_only_after_models_check_success(self) -> None:
        class FakeRoot:
            def wait_window(self, _dialog) -> None:
                return

        class FakeDialog:
            result = {
                "name": "pool-ok",
                "base_url": "https://pool.example.com",
                "api_key": "sk-pool",
                "wire_api": "responses",
                "default_model": "gpt-pool",
            }

            def __init__(self, _root) -> None:
                return

        class FakeChecker:
            def check(self, _profile: Profile) -> HealthResult:
                return HealthResult(status="healthy", detail="ok", checked_at="2026-06-06T10:00:00")

        app = CodexSwitchApp.__new__(CodexSwitchApp)
        app.root = FakeRoot()
        app.health_checker = FakeChecker()
        app.account_pool_settings = AccountPoolSettings()
        app.status_var = _ValueVar("")
        app.persist_state = lambda: None
        app.refresh_account_pool_tab = lambda: None

        with patch("codex_switch.ui.app.AccountPoolChannelDialog", FakeDialog):
            app.add_account_pool_channel()

        self.assertEqual(len(app.account_pool_settings.channels), 1)
        self.assertEqual(app.account_pool_settings.channels[0].name, "pool-ok")
        self.assertEqual(app.account_pool_settings.channels[0].last_success_at, "2026-06-06T10:00:00")

    def test_add_account_pool_channel_does_not_save_failed_models_check(self) -> None:
        class FakeRoot:
            def wait_window(self, _dialog) -> None:
                return

        class FakeDialog:
            result = {
                "name": "pool-bad",
                "base_url": "https://pool.example.com",
                "api_key": "sk-pool",
                "wire_api": "responses",
                "default_model": "gpt-pool",
            }

            def __init__(self, _root) -> None:
                return

        class FakeChecker:
            def check(self, _profile: Profile) -> HealthResult:
                return HealthResult(status="error", detail="鉴权失败", checked_at="2026-06-06T10:00:00")

        app = CodexSwitchApp.__new__(CodexSwitchApp)
        app.root = FakeRoot()
        app.health_checker = FakeChecker()
        app.account_pool_settings = AccountPoolSettings()
        app.status_var = _ValueVar("")
        app.persist_state = lambda: None
        app.refresh_account_pool_tab = lambda: None

        with (
            patch("codex_switch.ui.app.AccountPoolChannelDialog", FakeDialog),
            patch("codex_switch.ui.app.messagebox.showerror") as showerror,
        ):
            app.add_account_pool_channel()

        self.assertEqual(app.account_pool_settings.channels, [])
        showerror.assert_called_once()
        self.assertIn("鉴权失败", showerror.call_args.args[1])

    def test_prepare_account_pool_channel_submission_marks_success_and_preserves_existing_id(self) -> None:
        class FakeChecker:
            def check(self, _profile: Profile) -> HealthResult:
                return HealthResult(status="healthy", detail="ok", checked_at="2026-06-06T10:00:00")

        settings = AccountPoolSettings()
        default_group = settings.ensure_default_group()
        existing = AccountPoolChannel.create(
            name="existing",
            base_url="https://existing.example.com",
            api_key="sk-existing",
            group_id=default_group.id,
        )

        submission = prepare_account_pool_channel_submission(
            {
                "name": "pool-ok",
                "base_url": "https://pool.example.com",
                "api_key": "sk-pool",
                "wire_api": "responses",
                "default_model": "gpt-pool",
            },
            selected_group_id=default_group.id,
            settings=settings,
            existing=existing,
            validator=FakeChecker(),
        )

        self.assertEqual(submission.health_result.status, "healthy")
        self.assertEqual(submission.channel.id, existing.id)
        self.assertEqual(submission.channel.last_checked_at, "2026-06-06T10:00:00")
        self.assertEqual(submission.channel.last_success_at, "2026-06-06T10:00:00")

    def test_resolve_account_pool_group_settings_update_applies_defaults(self) -> None:
        update = resolve_account_pool_group_settings_update(
            enabled=True,
            group_type_label="Claude",
            default_model_value="",
            claude_model_value="",
            claude_fallback_model_value="",
        )

        self.assertTrue(update.enabled)
        self.assertEqual(update.pool_type, ACCOUNT_POOL_GROUP_TYPE_CLAUDE)
        self.assertTrue(update.default_model)
        self.assertTrue(update.claude_model)
        self.assertTrue(update.claude_fallback_model)

    def test_account_pool_group_delete_error_checks_last_group_and_channels(self) -> None:
        settings = AccountPoolSettings()
        default_group = settings.ensure_default_group()

        self.assertEqual(account_pool_group_delete_error(settings, default_group.id), "至少保留一个号池组。")

        extra_group = settings.add_group("extra")
        self.assertIsNone(account_pool_group_delete_error(settings, extra_group.id))

        channel = AccountPoolChannel.create(
            name="busy",
            base_url="https://busy.example.com",
            api_key="sk-busy",
            group_id=extra_group.id,
        )
        settings.channels.append(channel)
        self.assertEqual(
            account_pool_group_delete_error(settings, extra_group.id),
            "当前号池组还有渠道，请先删除或移动渠道。",
        )

    def test_account_pool_group_choices_and_summary_display_build_expected_text(self) -> None:
        settings = AccountPoolSettings()
        default_group = settings.ensure_default_group()
        default_group.default_model = "gpt-pool"
        extra_group = settings.add_group("claude-pool", pool_type=ACCOUNT_POOL_GROUP_TYPE_CLAUDE)
        settings.selected_group_id = extra_group.id

        display = account_pool_group_choices_display(settings)
        summary = account_pool_summary_text(settings, group_id=extra_group.id, project_count=2)

        self.assertIn(default_group.id, display.choices.values())
        self.assertIn(extra_group.id, display.choices.values())
        self.assertTrue(display.selected_label)
        self.assertIsNotNone(display.form)
        self.assertEqual(display.form.group_type_label, "Claude")
        self.assertIn("连接号池项目 2 个", summary)

    def test_account_pool_channel_rows_and_detail_display_format_fields(self) -> None:
        channel = AccountPoolChannel.create(
            name="pool-a",
            base_url="https://pool.example.com",
            api_key="sk-pool",
            wire_api="responses",
            default_model="gpt-pool",
        )
        channel.status = "error"
        channel.failure_reason = "timeout"
        channel.last_checked_at = "2026-06-06T10:00:00"

        rows = account_pool_channel_rows([channel])
        detail = account_pool_detail_display(channel)

        self.assertEqual(rows[0].channel_id, channel.id)
        self.assertEqual(rows[0].values[0], "pool-a")
        self.assertEqual(rows[0].values[5], "异常")
        self.assertIn("API：https://pool.example.com", detail.detail_text)
        self.assertEqual(detail.selected_name, "pool-a")


class McpEditorPrefillTests(unittest.TestCase):
    def test_resolve_mcp_editor_text_prefers_saved_then_fallbacks(self) -> None:
        default_toml = "[mcp_servers.default]\ncommand = \"default\"\n"

        self.assertEqual(resolve_mcp_editor_text("saved", "global", default_toml), "saved")
        self.assertEqual(resolve_mcp_editor_text("", "global", default_toml), "global")
        self.assertEqual(resolve_mcp_editor_text("  ", "", default_toml), default_toml)


class HealthCheckerTests(unittest.TestCase):
    def test_build_candidate_urls(self) -> None:
        self.assertEqual(
            build_candidate_urls("https://api.example.com"),
            ["https://api.example.com/v1/models", "https://api.example.com/models"],
        )
        self.assertEqual(
            build_candidate_urls("https://api.example.com/v1"),
            ["https://api.example.com/v1/models"],
        )

    def test_success_payload_keeps_all_returned_models(self) -> None:
        payload = {"data": [{"id": f"model-{index}"} for index in range(35)]}
        detail, models = HealthChecker()._build_success_payload(json.dumps(payload))

        self.assertIn("35", detail)
        self.assertEqual(len(models), 35)
        self.assertEqual(models[0], "model-0")
        self.assertEqual(models[-1], "model-34")

    def test_health_check_success(self) -> None:
        captured: dict[str, str | None] = {}

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802
                if self.path != "/v1/models":
                    self.send_response(404)
                    self.end_headers()
                    return
                captured["authorization"] = self.headers.get("Authorization")
                captured["beta"] = self.headers.get("OpenAI-Beta")
                captured["user_agent"] = self.headers.get("User-Agent")
                if self.headers.get("Authorization") != "Bearer sk-ok":
                    self.send_response(401)
                    self.end_headers()
                    return
                body = json.dumps({"data": [{"id": "gpt-5.4"}]}).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, format: str, *args) -> None:  # noqa: A003
                return

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(thread.join, 1)
        self.addCleanup(server.shutdown)

        profile = Profile.create(
            "本地",
            f"http://127.0.0.1:{server.server_port}",
            "sk-bad",
            api_keys=["sk-bad", "sk-ok"],
            active_api_key_index=1,
            custom_headers={"OpenAI-Beta": "codex=v1", "User-Agent": "codex-cli-test"},
        )
        checker = HealthChecker(timeout=5)

        result = checker.check(profile)

        self.assertEqual(result.status, "healthy")
        self.assertEqual(result.http_status, 200)
        self.assertIn("已返回", result.detail)
        self.assertEqual(result.models, ["gpt-5.4"])
        self.assertEqual(captured["authorization"], "Bearer sk-ok")
        self.assertEqual(captured["beta"], "codex=v1")
        self.assertEqual(captured["user_agent"], "codex-cli-test")

    def test_health_check_invalid_key(self) -> None:
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802
                self.send_response(401)
                self.end_headers()

            def log_message(self, format: str, *args) -> None:  # noqa: A003
                return

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(thread.join, 1)
        self.addCleanup(server.shutdown)

        profile = Profile.create("本地", f"http://127.0.0.1:{server.server_port}", "sk-bad")
        checker = HealthChecker(timeout=5)

        result = checker.check(profile)

        self.assertEqual(result.status, "error")
        self.assertEqual(result.http_status, 401)
        self.assertIn("鉴权失败", result.detail)


class MainStartupTests(unittest.TestCase):
    def test_normalize_tk_environment_replaces_stale_mei_paths(self) -> None:
        with workspace_tempdir() as temp_dir:
            tcl_dir = temp_dir / "tcl" / "tcl8.6"
            tk_dir = temp_dir / "tcl" / "tk8.6"
            tcl_dir.mkdir(parents=True, exist_ok=True)
            tk_dir.mkdir(parents=True, exist_ok=True)
            (tcl_dir / "init.tcl").write_text("# test", encoding="utf-8")
            (tk_dir / "tk.tcl").write_text("# test", encoding="utf-8")

            with (
                patch.object(main.sys, "base_prefix", str(temp_dir)),
                patch.dict(
                    main.os.environ,
                    {
                        "TCL_LIBRARY": r"C:\Users\fan\AppData\Local\Temp\_MEI168922\_tcl_data",
                        "TK_LIBRARY": r"C:\Users\fan\AppData\Local\Temp\_MEI168922\_tk_data",
                    },
                    clear=False,
                ),
            ):
                main._normalize_tk_environment()

                self.assertEqual(main.os.environ["TCL_LIBRARY"], str(tcl_dir))
                self.assertEqual(main.os.environ["TK_LIBRARY"], str(tk_dir))
