from __future__ import annotations

from dataclasses import replace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
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
    SkillDefinition,
    SkillGroup,
    SkillMarketRepo,
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
from codex_switch.ui.utils import resolve_mcp_editor_text


class _ValueVar:
    def __init__(self, value: str) -> None:
        self.value = value

    def get(self) -> str:
        return self.value

    def set(self, value: str) -> None:
        self.value = value


def _make_minimal_app() -> CodexSwitchApp:
    app = CodexSwitchApp.__new__(CodexSwitchApp)
    app.root = None
    app.profiles = []
    app.projects = []
    app.skill_groups = []
    app.skill_market_repos = []
    app.model_vendor_keywords = {}
    app.status_var = _ValueVar("")
    app.persist_count = 0
    app.persist_state = lambda: setattr(app, "persist_count", app.persist_count + 1)
    app.refresh_project_tab = lambda: None
    app.refresh_skills_tab = lambda: None
    app.refresh_library_tab = lambda: None
    return app


class UiFilterTests(unittest.TestCase):
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
        project = ProjectRecord.create(str(Path.cwd()), "profile-id", skill_names=["frontend-dev"])
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

    def test_skill_repo_update_reloads_skills_and_model_metadata(self) -> None:
        with workspace_tempdir() as temp_dir:
            cache_dir = temp_dir / "repo"
            skill_dir = cache_dir / "python-helper"
            skill_dir.mkdir(parents=True)
            (skill_dir / "SKILL.md").write_text("Use Python.", encoding="utf-8")
            (cache_dir / "codex-switch-model-metadata.json").write_text(
                json.dumps({"model_vendor_keywords": {"Acme": ["acme-"]}}),
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
            app._sync_skill_repo_cache = lambda _repo: cache_dir

            updated = app._apply_skill_repo_update(repo, automatic=False)

            self.assertTrue(updated)
            self.assertEqual([skill.name for skill in app.skill_groups[0].skills], ["python-helper"])
            self.assertEqual(app.model_vendor_keywords["Acme"], ["acme-"])
            self.assertIn("模型元数据已更新", app.status_var.get())

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
