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
from unittest.mock import patch

from helpers import start_test_server, workspace_tempdir

from codex_switch import main
from codex_switch.chat import ChatResult
from codex_switch.health import HealthChecker, build_candidate_urls
from codex_switch.models import (
    AccountPoolSettings,
    HealthResult,
    Profile,
    ProjectRecord,
    RouteProxyRule,
    RouteProxySettings,
    ROUTE_PROXY_CLIENT_CLAUDE,
    ROUTE_PROXY_CLIENT_CODEX,
    ROUTE_PROXY_PROTOCOL_ANTHROPIC,
    ROUTE_PROXY_PROTOCOL_ANTHROPIC_TO_OPENAI,
    ROUTE_PROXY_PROTOCOL_OPENAI,
    ROUTE_PROXY_PROTOCOL_OPENAI_CHAT_TO_RESPONSES,
    ROUTE_PROXY_PROTOCOL_OPENAI_RESPONSES_TO_CHAT,
    ROUTE_PROXY_UPSTREAM_SOURCE_ACCOUNT_POOL,
    ROUTE_PROXY_UPSTREAM_SOURCE_PROFILE,
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
)
from codex_switch.storage import DEFAULT_MODEL_BATCH_CONCURRENCY
from codex_switch.skills import SkillSource
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
from codex_switch.ui.project_logic import (
    claude_project_template_options,
    codex_project_template_options,
    preferred_project_script_path,
    project_bound_profile_ids,
    project_claude_binding_changed,
    project_claude_cmd_command,
    project_claude_profile_id,
    project_codex_cmd_command,
    project_codex_binding_changed,
    project_codex_profile_id,
    project_codex_script_paths,
    project_codex_vscode_command,
    project_custom_run_command,
    project_root_path,
    project_text_file_path,
    project_vscode_open_command,
)
from codex_switch.ui.route_proxy_logic import (
    refresh_route_proxy_rules_for_project,
    route_proxy_base_url_for_project,
    route_proxy_codex_protocol_for_profile,
    route_proxy_rules_for_project,
    route_proxy_rules_for_project_profiles,
)
from codex_switch.ui.utils import is_github_repo_url, resolve_mcp_editor_text


class _ValueVar:
    def __init__(self, value: str) -> None:
        self.value = value

    def get(self) -> str:
        return self.value

    def set(self, value: str) -> None:
        self.value = value


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
    app.skill_repo_preview_var = _ValueVar("")
    app.skill_repo_preview_filter_var = _ValueVar("")
    app.skill_repo_preview_sources = []
    app.skill_repo_preview_repo_id = ""
    app.persist_count = 0
    app.persist_state = lambda: setattr(app, "persist_count", app.persist_count + 1)
    app.refresh_project_tab = lambda: None
    app.refresh_skills_tab = lambda: None
    app.refresh_library_tab = lambda: None
    return app


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
        settings = RouteProxySettings(rules=[codex_rule, claude_rule, other_rule])
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
        app.proxy_claude_protocol_var = _ValueVar(ROUTE_PROXY_PROTOCOL_ANTHROPIC_TO_OPENAI)
        app.proxy_codex_compact_model_var = _ValueVar("gpt-4.1-compact")
        app.account_pool_settings = AccountPoolSettings()
        group = app.account_pool_settings.ensure_default_group()
        app.proxy_account_pool_group_var = _ValueVar("default")
        app.proxy_account_pool_group_choices = {"default": group.id}

        app._save_selected_route_proxy_project_rules()

        codex_rule = next(rule for rule in app.route_proxy_settings.rules_for_project(project.id) if rule.client_type == ROUTE_PROXY_CLIENT_CODEX)
        claude_rule = next(rule for rule in app.route_proxy_settings.rules_for_project(project.id) if rule.client_type == ROUTE_PROXY_CLIENT_CLAUDE)
        self.assertEqual(codex_rule.upstream_source, ROUTE_PROXY_UPSTREAM_SOURCE_ACCOUNT_POOL)
        self.assertEqual(codex_rule.account_pool_group_id, group.id)
        self.assertEqual(codex_rule.upstream_protocol, ROUTE_PROXY_PROTOCOL_OPENAI_RESPONSES_TO_CHAT)
        self.assertEqual(codex_rule.upstream_model, "gpt-real")
        self.assertEqual(codex_rule.compact_model, "gpt-4.1-compact")
        self.assertTrue(codex_rule.manual_upstream_protocol)
        self.assertEqual(claude_rule.upstream_source, ROUTE_PROXY_UPSTREAM_SOURCE_PROFILE)
        self.assertEqual(claude_rule.upstream_protocol, ROUTE_PROXY_PROTOCOL_ANTHROPIC_TO_OPENAI)
        self.assertEqual(claude_rule.upstream_model, "sonnet-real")
        self.assertTrue(claude_rule.manual_upstream_protocol)

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

            with (
                patch("codex_switch.ui.app.simpledialog.askstring", return_value=group.name),
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
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802
                if self.path != "/v1/models":
                    self.send_response(404)
                    self.end_headers()
                    return
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
        )
        checker = HealthChecker(timeout=5)

        result = checker.check(profile)

        self.assertEqual(result.status, "healthy")
        self.assertEqual(result.http_status, 200)
        self.assertIn("已返回", result.detail)
        self.assertEqual(result.models, ["gpt-5.4"])

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
