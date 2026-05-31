from __future__ import annotations

from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import gzip
import json
import shutil
import threading
import time
import tomllib
import unittest
import uuid
from unittest.mock import patch

import sys

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
for path in (SRC, ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from codex_switch import main
from codex_switch.chat import ChatResult, ChatTester
from codex_switch.codex_config import CodexConfigManager, PROJECT_ENV_KEY, PROJECT_PROVIDER_ID, scope_mcp_servers_to_project
from codex_switch.health import HealthChecker, build_candidate_urls
from codex_switch.models import (
    DEFAULT_CLAUDE_FALLBACK_MODEL,
    DEFAULT_CLAUDE_MODEL,
    HealthResult,
    Profile,
    ProjectRecord,
    RouteProxyRule,
    RouteProxySettings,
    ROUTE_PROXY_CLIENT_CLAUDE,
    ROUTE_PROXY_CLIENT_CODEX,
    ROUTE_PROXY_PLACEHOLDER_KEY,
    ROUTE_PROXY_PROTOCOL_ANTHROPIC,
    ROUTE_PROXY_PROTOCOL_ANTHROPIC_TO_OPENAI,
    VENDOR_CLAUDE,
    VENDOR_CODEX,
    VENDOR_GENERIC,
    VENDOR_OTHER,
    normalize_profile_vendor,
    profile_supports_claude,
    profile_supports_codex,
    today_iso,
)
from codex_switch.proxy import RouteProxyServer, anthropic_to_openai_request, openai_to_anthropic_response
from codex_switch.proxy.translator import iter_openai_sse_to_anthropic
from codex_switch.project_template import (
    CLAUDE_API_KEY_ENV_KEY,
    CLAUDE_AUTH_TOKEN_ENV_KEY,
    CLAUDE_BASE_URL_ENV_KEY,
    CLAUDE_FALLBACK_MODEL_ENV_KEY,
    CLAUDE_MODEL_ENV_KEY,
    CODEX_SCRIPT_DIRNAME,
    GITIGNORE_MANAGED_BEGIN,
    GITIGNORE_MANAGED_END,
    ProjectTemplateService,
    apply_claude_profile_env,
    claude_env_from_profile,
)
from codex_switch.storage import DEFAULT_MODEL_BATCH_CONCURRENCY, ProfileStore, clamp_model_batch_concurrency
from codex_switch.ui.app import (
    LIBRARY_VIEW_ALL,
    ModelBatchCache,
    ModelBatchResult,
    model_batch_caches_from_payload,
    model_batch_caches_to_payload,
    model_batch_targets,
    ordered_model_batch_models,
    profile_library_sort_key,
    profiles_for_library_view,
    route_proxy_rules_for_project,
    run_model_batch_requests,
    successful_model_batch_models,
    visible_profiles_for_filter,
)
from codex_switch.ui.utils import resolve_mcp_editor_text


TEST_ROOT = Path.cwd() / ".test-temp"


@contextmanager
def workspace_tempdir():
    TEST_ROOT.mkdir(exist_ok=True)
    path = TEST_ROOT / uuid.uuid4().hex
    path.mkdir(parents=True, exist_ok=True)
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)


class ProfileStoreTests(unittest.TestCase):
    def test_store_roundtrip(self) -> None:
        with workspace_tempdir() as temp_dir:
            store = ProfileStore(temp_dir)
            profile = Profile.create("主线路", "https://example.com", "sk-demo")
            profile.health = HealthResult(status="healthy", detail="ok")
            profile.manual_health_status = "error"
            store.save([profile], profile.id)

            (
                profiles,
                selected_profile_id,
                projects,
                selected_project_id,
                hide_error_profiles,
                global_mcp_toml,
                applied_global_mcp_server_names,
                global_mcp_opt_out,
                agents_doc_text,
                model_batch_concurrency,
                model_batch_cache_by_profile,
                route_proxy_settings,
            ) = store.load()

            self.assertEqual(selected_profile_id, profile.id)
            self.assertEqual(len(profiles), 1)
            self.assertEqual(profiles[0].name, "主线路")
            self.assertEqual(profiles[0].api_keys, ["sk-demo"])
            self.assertEqual(profiles[0].api_key, "sk-demo")
            self.assertEqual(profiles[0].active_api_key_index, 0)
            self.assertEqual(profiles[0].health.status, "healthy")
            self.assertEqual(profiles[0].manual_health_status, "error")
            self.assertEqual(profiles[0].effective_health_status, "error")
            self.assertEqual(projects, [])
            self.assertIsNone(selected_project_id)
            self.assertFalse(hide_error_profiles)
            self.assertIsInstance(global_mcp_toml, str)
            self.assertEqual(applied_global_mcp_server_names, [])
            self.assertFalse(global_mcp_opt_out)
            self.assertIsInstance(agents_doc_text, str)
            self.assertTrue(agents_doc_text.strip())
            self.assertEqual(model_batch_concurrency, DEFAULT_MODEL_BATCH_CONCURRENCY)
            self.assertEqual(model_batch_cache_by_profile, {})
            self.assertFalse(route_proxy_settings.enabled)

    def test_store_persists_agents_doc_text(self) -> None:
        with workspace_tempdir() as temp_dir:
            store = ProfileStore(temp_dir)
            store.save([], None, agents_doc_text="Custom AGENTS text")

            loaded = store.load()
            self.assertEqual(loaded[8], "Custom AGENTS text")

            payload = json.loads(store.storage_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["version"], 8)
            self.assertEqual(payload["settings"]["agents_doc_text"], "Custom AGENTS text")

    def test_store_persists_route_proxy_settings(self) -> None:
        with workspace_tempdir() as temp_dir:
            store = ProfileStore(temp_dir)
            settings = RouteProxySettings(
                enabled=True,
                port=17890,
                rules=[
                    RouteProxyRule.create(
                        project_id="project-1",
                        client_type=ROUTE_PROXY_CLIENT_CLAUDE,
                        primary_profile_id="profile-1",
                        upstream_protocol=ROUTE_PROXY_PROTOCOL_ANTHROPIC_TO_OPENAI,
                    )
                ],
            )

            store.save([], None, route_proxy_settings=settings)
            loaded = store.load()[11]
            payload = json.loads(store.storage_path.read_text(encoding="utf-8"))

            self.assertTrue(loaded.enabled)
            self.assertEqual(loaded.port, 17890)
            self.assertEqual(loaded.rules[0].project_id, "project-1")
            self.assertEqual(loaded.rules[0].upstream_protocol, ROUTE_PROXY_PROTOCOL_ANTHROPIC_TO_OPENAI)
            self.assertEqual(payload["settings"]["route_proxy"]["rules"][0]["primary_profile_id"], "profile-1")

    def test_store_persists_project_mcp_selection(self) -> None:
        with workspace_tempdir() as temp_dir:
            store = ProfileStore(temp_dir)
            project = ProjectRecord.create(
                str(temp_dir),
                "codex-profile",
                name="project",
                mcp_server_names=["filesystem", "serena"],
                codex_profile_id="codex-profile",
                claude_profile_id="claude-profile",
            )

            store.save([], None, projects=[project], selected_project_id=project.id)
            loaded_projects = store.load()[2]
            payload = json.loads(store.storage_path.read_text(encoding="utf-8"))

            self.assertEqual(loaded_projects[0].mcp_server_names, ["filesystem", "serena"])
            self.assertEqual(loaded_projects[0].profile_id, "codex-profile")
            self.assertEqual(loaded_projects[0].codex_profile_id, "codex-profile")
            self.assertEqual(loaded_projects[0].claude_profile_id, "claude-profile")
            self.assertEqual(payload["projects"][0]["mcp_server_names"], ["filesystem", "serena"])
            self.assertEqual(payload["projects"][0]["codex_profile_id"], "codex-profile")
            self.assertEqual(payload["projects"][0]["claude_profile_id"], "claude-profile")

    def test_store_loads_legacy_project_without_mcp_selection(self) -> None:
        with workspace_tempdir() as temp_dir:
            store = ProfileStore(temp_dir)
            store.storage_path.write_text(
                json.dumps(
                    {
                        "version": 6,
                        "profiles": [],
                        "projects": [
                            {
                                "id": "project-1",
                                "name": "legacy-project",
                                "project_dir": str(temp_dir),
                                "profile_id": "profile-1",
                                "created_at": "2026-05-30T10:00:00",
                                "updated_at": "2026-05-30T10:00:00",
                                "mcp_toml": "[mcp_servers.legacy]\ncommand = \"legacy\"\n",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            loaded_project = store.load()[2][0]

            self.assertIsNone(loaded_project.mcp_server_names)
            self.assertEqual(loaded_project.profile_id, "profile-1")
            self.assertEqual(loaded_project.codex_profile_id, "profile-1")
            self.assertEqual(loaded_project.claude_profile_id, "profile-1")
            self.assertIn("mcp_servers.legacy", loaded_project.mcp_toml)

    def test_store_persists_model_batch_settings(self) -> None:
        with workspace_tempdir() as temp_dir:
            store = ProfileStore(temp_dir)
            cache_payload = {
                "profile-1": {
                    "models": ["m1"],
                    "results": {"m1": {"status": "success", "detail": "ok"}},
                    "completed": True,
                    "tested_at": "2026-05-20T12:00:00",
                }
            }

            store.save([], None, model_batch_concurrency=5, model_batch_cache_by_profile=cache_payload)
            loaded = store.load()

            self.assertEqual(loaded[9], 5)
            self.assertEqual(loaded[10], cache_payload)
            payload = json.loads(store.storage_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["settings"]["model_batch_concurrency"], 5)
            self.assertEqual(payload["settings"]["model_batch_cache_by_profile"], cache_payload)

    def test_store_loads_legacy_single_api_key_profile(self) -> None:
        with workspace_tempdir() as temp_dir:
            store = ProfileStore(temp_dir)
            store.storage_path.write_text(
                json.dumps(
                    {
                        "version": 5,
                        "profiles": [
                            {
                                "id": "profile-1",
                                "name": "legacy",
                                "base_url": "https://example.com",
                                "api_key": "sk-legacy",
                                "model": "legacy-model",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            profiles = store.load()[0]

            self.assertEqual(len(profiles), 1)
            self.assertEqual(profiles[0].api_keys, ["sk-legacy"])
            self.assertEqual(profiles[0].api_key, "sk-legacy")
            self.assertEqual(profiles[0].active_api_key_index, 0)
            self.assertEqual(profiles[0].vendor, VENDOR_GENERIC)
            self.assertEqual(profiles[0].model, "legacy-model")
            self.assertEqual(profiles[0].codex_model, "legacy-model")
            self.assertEqual(profiles[0].claude_model, DEFAULT_CLAUDE_MODEL)
            self.assertEqual(profiles[0].claude_fallback_model, DEFAULT_CLAUDE_FALLBACK_MODEL)

    def test_profile_from_dict_defaults_legacy_model_to_generic_vendor(self) -> None:
        profile = Profile.from_dict(
            {
                "id": "profile-1",
                "name": "legacy",
                "base_url": "https://example.com",
                "api_key": "sk-legacy",
                "model": "legacy-model",
            }
        )

        self.assertEqual(profile.vendor, VENDOR_GENERIC)
        self.assertEqual(profile.model, "legacy-model")
        self.assertEqual(profile.codex_model, "legacy-model")
        self.assertEqual(profile.claude_model, DEFAULT_CLAUDE_MODEL)
        self.assertEqual(profile.claude_fallback_model, DEFAULT_CLAUDE_FALLBACK_MODEL)

    def test_project_record_from_dict_migrates_legacy_profile_id_to_dual_bindings(self) -> None:
        project = ProjectRecord.from_dict(
            {
                "id": "project-1",
                "name": "legacy-project",
                "project_dir": str(Path.cwd()),
                "profile_id": "profile-1",
            }
        )

        self.assertEqual(project.profile_id, "profile-1")
        self.assertEqual(project.codex_profile_id, "profile-1")
        self.assertEqual(project.claude_profile_id, "profile-1")

    def test_store_roundtrip_keeps_active_api_key(self) -> None:
        with workspace_tempdir() as temp_dir:
            store = ProfileStore(temp_dir)
            profile = Profile.create(
                "multi-key",
                "https://example.com",
                "sk-first",
                api_keys=["sk-first", "sk-active"],
                active_api_key_index=1,
            )

            store.save([profile], profile.id)
            profiles = store.load()[0]
            payload = json.loads(store.storage_path.read_text(encoding="utf-8"))

            self.assertEqual(profiles[0].api_keys, ["sk-first", "sk-active"])
            self.assertEqual(profiles[0].api_key, "sk-active")
            self.assertEqual(profiles[0].active_api_key_index, 1)
            self.assertEqual(payload["profiles"][0]["api_key"], "sk-active")
            self.assertEqual(payload["profiles"][0]["api_keys"], ["sk-first", "sk-active"])
            self.assertEqual(payload["profiles"][0]["active_api_key_index"], 1)

    def test_store_loads_legacy_payload_with_model_batch_defaults(self) -> None:
        with workspace_tempdir() as temp_dir:
            store = ProfileStore(temp_dir)
            store.storage_path.write_text(
                json.dumps({"version": 4, "profiles": [], "settings": {}}),
                encoding="utf-8",
            )

            loaded = store.load()

            self.assertEqual(loaded[9], DEFAULT_MODEL_BATCH_CONCURRENCY)
            self.assertEqual(loaded[10], {})

    def test_model_batch_concurrency_is_clamped(self) -> None:
        self.assertEqual(clamp_model_batch_concurrency(0), 1)
        self.assertEqual(clamp_model_batch_concurrency(9), 5)
        self.assertEqual(clamp_model_batch_concurrency("bad"), DEFAULT_MODEL_BATCH_CONCURRENCY)


class UiFilterTests(unittest.TestCase):
    def test_other_vendor_is_not_a_codex_or_claude_binding(self) -> None:
        profile = Profile.create("other", "https://other.example.com", "sk-other", vendor=VENDOR_OTHER)

        self.assertEqual(normalize_profile_vendor("other"), VENDOR_OTHER)
        self.assertEqual(profile.vendor, VENDOR_OTHER)
        self.assertEqual(profile.vendor_label, "其他")
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
            ROUTE_PROXY_PROTOCOL_ANTHROPIC_TO_OPENAI,
        )

        self.assertEqual(rules[0].primary_profile_id, "codex-profile")
        self.assertEqual(rules[1].primary_profile_id, "claude-profile")
        self.assertEqual(rules[1].upstream_protocol, ROUTE_PROXY_PROTOCOL_ANTHROPIC_TO_OPENAI)
        self.assertEqual(rules[1].upstream_model, "mimo-v2.5-pro")


class CodexConfigManagerTests(unittest.TestCase):
    def test_apply_profile_updates_codex_files(self) -> None:
        with workspace_tempdir() as temp_dir:
            codex_dir = temp_dir / ".codex"
            manager = CodexConfigManager(codex_dir=codex_dir, backup_root=codex_dir / "backups")
            profile = Profile.create(
                name="代理 A",
                base_url="https://gateway.example.com",
                api_key="sk-123456",
                model="gpt-5.4",
                api_keys=["sk-123456", "sk-active"],
                active_api_key_index=1,
            )

            backup_dir = manager.apply_profile(profile)

            self.assertTrue(backup_dir.exists())

            config_data = tomllib.loads(manager.config_path.read_text(encoding="utf-8"))
            self.assertEqual(config_data["model_provider"], "OpenAI")
            self.assertEqual(config_data["model"], "gpt-5.4")
            self.assertEqual(
                config_data["model_providers"]["OpenAI"]["base_url"],
                "https://gateway.example.com",
            )

            auth_data = json.loads(manager.auth_path.read_text(encoding="utf-8"))
            self.assertEqual(auth_data["auth_mode"], "apikey")
            self.assertEqual(auth_data["OPENAI_API_KEY"], "sk-active")

            current = manager.read_current_config()
            self.assertEqual(current.base_url, "https://gateway.example.com")
            self.assertEqual(current.api_key, "sk-active")

    def test_scope_mcp_servers_to_project_updates_serena_and_filesystem(self) -> None:
        with workspace_tempdir() as temp_dir:
            mcp_servers = {
                "serena": {
                    "command": "serena",
                    "args": [
                        "start-mcp-server",
                        "--context",
                        "ide-assistant",
                        "--project",
                        ".",
                    ],
                    "env": {},
                },
                "filesystem": {
                    "command": "npx",
                    "args": [
                        "-y",
                        "@modelcontextprotocol/server-filesystem@latest",
                        "/Users/username/projects",
                    ],
                    "env": {},
                },
            }

            scoped = scope_mcp_servers_to_project(mcp_servers, temp_dir)
            expected_project_dir = str(temp_dir.resolve())

            self.assertEqual(mcp_servers["serena"]["args"][-1], ".")
            self.assertEqual(mcp_servers["filesystem"]["args"][-1], "/Users/username/projects")
            self.assertEqual(scoped["serena"]["args"][-1], expected_project_dir)
            self.assertEqual(scoped["filesystem"]["args"][-1], expected_project_dir)

    def test_scope_mcp_servers_to_project_replaces_project_root_placeholder(self) -> None:
        with workspace_tempdir() as temp_dir:
            mcp_servers = {
                "custom": {
                    "command": "{project_root}/bin/tool",
                    "args": ["--root", "{project_root}", "--config", "{project_root}/config.json"],
                    "cwd": "{project_root}",
                    "env": {
                        "PROJECT_HOME": "{project_root}",
                        "CONFIG_PATH": "{project_root}/config.json",
                    },
                    "nested": {
                        "path": "{project_root}/nested",
                    },
                },
                "filesystem": {
                    "command": "npx",
                    "args": ["-y", "server", "{project_root}/allowed"],
                },
            }

            scoped = scope_mcp_servers_to_project(mcp_servers, temp_dir)
            expected_project_dir = str(temp_dir.resolve())

            self.assertEqual(mcp_servers["custom"]["command"], "{project_root}/bin/tool")
            self.assertEqual(scoped["custom"]["command"], f"{expected_project_dir}/bin/tool")
            self.assertEqual(scoped["custom"]["args"][1], expected_project_dir)
            self.assertEqual(scoped["custom"]["cwd"], expected_project_dir)
            self.assertEqual(scoped["custom"]["env"]["PROJECT_HOME"], expected_project_dir)
            self.assertEqual(scoped["custom"]["nested"]["path"], f"{expected_project_dir}/nested")
            self.assertEqual(scoped["filesystem"]["args"][-1], f"{expected_project_dir}/allowed")


class ProjectTemplateServiceTests(unittest.TestCase):
    def test_generate_writes_scripts_agents_and_gitignore(self) -> None:
        with workspace_tempdir() as temp_dir:
            (temp_dir / ".gitignore").write_text("node_modules/\n", encoding="utf-8")
            service = ProjectTemplateService()
            profile = Profile.create(
                "项目模板",
                "https://gateway.example.com",
                "sk-template",
                api_keys=["sk-template", "sk-template-active"],
                active_api_key_index=1,
            )

            result = service.generate(temp_dir, profile)

            script_dir = temp_dir / CODEX_SCRIPT_DIRNAME
            self.assertEqual(result.start_script_path, script_dir / "start-codex.ps1")
            self.assertTrue((script_dir / "start-codex.ps1").exists())
            self.assertTrue((script_dir / "start-codex.cmd").exists())
            self.assertTrue((script_dir / "codex-profile.cmd").exists())
            self.assertTrue((temp_dir / ".codex" / "home" / "AGENTS.md").exists())
            self.assertTrue((temp_dir / "CLAUDE.md").exists())
            self.assertTrue((temp_dir / ".mcp.json").exists())

            gitignore_text = (temp_dir / ".gitignore").read_text(encoding="utf-8")
            self.assertIn("node_modules/", gitignore_text)
            self.assertIn(GITIGNORE_MANAGED_BEGIN, gitignore_text)
            self.assertIn(f"{CODEX_SCRIPT_DIRNAME}/", gitignore_text)
            self.assertIn(GITIGNORE_MANAGED_END, gitignore_text)

            repo_config_data = tomllib.loads((temp_dir / ".codex" / "config.toml").read_text(encoding="utf-8"))
            runtime_config_data = tomllib.loads((temp_dir / ".codex" / "home" / "config.toml").read_text(encoding="utf-8"))
            self.assertEqual(repo_config_data["model"], profile.model)
            self.assertEqual(repo_config_data["review_model"], profile.model)
            self.assertEqual(runtime_config_data["model"], profile.model)
            self.assertEqual(runtime_config_data["review_model"], profile.model)
            self.assertEqual(
                (temp_dir / ".codex" / "local.env").read_text(encoding="utf-8"),
                f"{PROJECT_ENV_KEY}=sk-template-active\n",
            )

            backup_gitignore = result.backup_dir / ".gitignore"
            self.assertTrue(backup_gitignore.exists())
            self.assertEqual(backup_gitignore.read_text(encoding="utf-8"), "node_modules/\n")

            status = service.inspect(temp_dir)
            self.assertEqual(status.start_script_path, script_dir / "start-codex.ps1")
            self.assertIn(temp_dir / ".gitignore", status.generated_paths)
            self.assertIn(temp_dir / ".codex" / "home" / "AGENTS.md", status.generated_paths)
            self.assertIn(temp_dir / "CLAUDE.md", status.generated_paths)
            self.assertIn(temp_dir / ".mcp.json", status.generated_paths)

    def test_generate_updates_gitignore_idempotently(self) -> None:
        with workspace_tempdir() as temp_dir:
            (temp_dir / ".gitignore").write_text("dist/\n", encoding="utf-8")
            service = ProjectTemplateService()
            profile = Profile.create("项目模板", "https://gateway.example.com", "sk-template")

            service.generate(temp_dir, profile)
            service.generate(temp_dir, profile)

            gitignore_text = (temp_dir / ".gitignore").read_text(encoding="utf-8")
            self.assertIn("dist/", gitignore_text)
            self.assertEqual(gitignore_text.count(GITIGNORE_MANAGED_BEGIN), 1)
            self.assertEqual(gitignore_text.count(GITIGNORE_MANAGED_END), 1)
            self.assertEqual(gitignore_text.count(f"{CODEX_SCRIPT_DIRNAME}/"), 1)

    def test_generate_uses_custom_agents_doc_text(self) -> None:
        with workspace_tempdir() as temp_dir:
            service = ProjectTemplateService()
            profile = Profile.create("project-template", "https://gateway.example.com", "sk-template")

            service.generate(temp_dir, profile, agents_doc_text="# Custom Agents\n")

            self.assertEqual((temp_dir / "AGENTS.md").read_text(encoding="utf-8"), "# Custom Agents\n")
            self.assertEqual((temp_dir / ".codex" / "home" / "AGENTS.md").read_text(encoding="utf-8"), "# Custom Agents\n")
            self.assertEqual((temp_dir / "CLAUDE.md").read_text(encoding="utf-8"), "# Custom Agents\n")

    def test_generate_writes_project_mcp_for_codex_and_claude(self) -> None:
        with workspace_tempdir() as temp_dir:
            service = ProjectTemplateService()
            profile = Profile.create("project-template", "https://gateway.example.com", "sk-template")
            mcp_toml = """
[mcp_servers.custom]
command = "{project_root}/bin/tool"
args = ["--root", "{project_root}"]

[mcp_servers.filesystem]
command = "npx"
args = ["-y", "server", "/tmp"]
""".strip()

            service.generate(temp_dir, profile, global_mcp_toml=mcp_toml, project_mcp_toml=mcp_toml)

            project_dir = str(temp_dir.resolve())
            repo_config_data = tomllib.loads((temp_dir / ".codex" / "config.toml").read_text(encoding="utf-8"))
            runtime_config_data = tomllib.loads((temp_dir / ".codex" / "home" / "config.toml").read_text(encoding="utf-8"))
            claude_config_data = json.loads((temp_dir / ".mcp.json").read_text(encoding="utf-8"))
            repo_servers = repo_config_data["mcp_servers"]
            runtime_servers = runtime_config_data["mcp_servers"]
            claude_servers = claude_config_data["mcpServers"]

            self.assertEqual(repo_servers, runtime_servers)
            self.assertEqual(repo_servers, claude_servers)
            self.assertEqual(repo_servers["custom"]["command"], f"{project_dir}/bin/tool")
            self.assertEqual(repo_servers["custom"]["args"], ["--root", project_dir])
            self.assertEqual(repo_servers["filesystem"]["args"][-1], project_dir)

    def test_generate_uses_codex_profile_and_writes_claude_settings_from_claude_profile(self) -> None:
        with workspace_tempdir() as temp_dir:
            service = ProjectTemplateService()
            codex_profile = Profile.create(
                "codex-project",
                "https://codex.example.com",
                "sk-codex",
                vendor=VENDOR_CODEX,
                codex_model="codex-special",
            )
            claude_profile = Profile.create(
                "claude-project",
                "https://claude.example.com",
                "sk-claude",
                vendor=VENDOR_CLAUDE,
                claude_model="sonnet-special",
                claude_fallback_model="haiku-special",
            )

            service.generate(temp_dir, codex_profile, claude_profile=claude_profile)

            repo_config_data = tomllib.loads((temp_dir / ".codex" / "config.toml").read_text(encoding="utf-8"))
            runtime_config_data = tomllib.loads((temp_dir / ".codex" / "home" / "config.toml").read_text(encoding="utf-8"))
            claude_settings = json.loads((temp_dir / ".claude" / "settings.local.json").read_text(encoding="utf-8"))

            self.assertEqual(repo_config_data["model"], "codex-special")
            self.assertEqual(runtime_config_data["model"], "codex-special")
            self.assertEqual(claude_settings["env"][CLAUDE_BASE_URL_ENV_KEY], "https://claude.example.com")
            self.assertEqual(claude_settings["env"][CLAUDE_API_KEY_ENV_KEY], "sk-claude")
            self.assertEqual(claude_settings["env"][CLAUDE_MODEL_ENV_KEY], "sonnet-special")
            self.assertEqual(claude_settings["env"][CLAUDE_FALLBACK_MODEL_ENV_KEY], "haiku-special")

    def test_generate_with_route_proxy_writes_proxy_endpoint_and_placeholder_key(self) -> None:
        with workspace_tempdir() as temp_dir:
            service = ProjectTemplateService()
            codex_profile = Profile.create("codex", "https://codex.example.com", "sk-codex", codex_model="codex-model")
            claude_profile = Profile.create(
                "claude",
                "https://claude.example.com",
                "sk-claude",
                vendor=VENDOR_CLAUDE,
                claude_model="sonnet-proxy",
            )

            service.generate(
                temp_dir,
                codex_profile,
                claude_profile=claude_profile,
                route_proxy_base_url="http://127.0.0.1:15721/project/p1",
            )

            runtime_config_data = tomllib.loads((temp_dir / ".codex" / "home" / "config.toml").read_text(encoding="utf-8"))
            provider = runtime_config_data["model_providers"][PROJECT_PROVIDER_ID]
            claude_settings = json.loads((temp_dir / ".claude" / "settings.local.json").read_text(encoding="utf-8"))

            self.assertEqual(provider["base_url"], "http://127.0.0.1:15721/project/p1")
            self.assertEqual((temp_dir / ".codex" / "local.env").read_text(encoding="utf-8"), f"{PROJECT_ENV_KEY}={ROUTE_PROXY_PLACEHOLDER_KEY}\n")
            self.assertEqual(claude_settings["env"][CLAUDE_BASE_URL_ENV_KEY], "http://127.0.0.1:15721/project/p1")
            self.assertEqual(claude_settings["env"][CLAUDE_API_KEY_ENV_KEY], ROUTE_PROXY_PLACEHOLDER_KEY)

    def test_generate_claude_template_does_not_write_codex_config(self) -> None:
        with workspace_tempdir() as temp_dir:
            service = ProjectTemplateService()
            profile = Profile.create(
                "claude-project",
                "https://claude.example.com",
                "sk-claude",
                vendor=VENDOR_CLAUDE,
                claude_model="sonnet-template",
                claude_fallback_model="haiku-template",
            )
            mcp_toml = """
[mcp_servers.custom]
command = "tool"
""".strip()

            result = service.generate_claude_template(temp_dir, profile, project_mcp_toml=mcp_toml, agents_doc_text="# Claude\n")

            self.assertEqual(
                {path.relative_to(temp_dir).as_posix() for path in result.generated_paths},
                {"CLAUDE.md", ".mcp.json", ".claude/settings.local.json"},
            )
            self.assertFalse((temp_dir / ".codex" / "config.toml").exists())
            self.assertEqual((temp_dir / "CLAUDE.md").read_text(encoding="utf-8"), "# Claude\n")
            self.assertEqual(json.loads((temp_dir / ".mcp.json").read_text(encoding="utf-8"))["mcpServers"]["custom"]["command"], "tool")
            claude_settings = json.loads((temp_dir / ".claude" / "settings.local.json").read_text(encoding="utf-8"))
            self.assertEqual(claude_settings["env"][CLAUDE_BASE_URL_ENV_KEY], "https://claude.example.com")
            self.assertEqual(claude_settings["env"][CLAUDE_API_KEY_ENV_KEY], "sk-claude")
            self.assertEqual(claude_settings["env"][CLAUDE_MODEL_ENV_KEY], "sonnet-template")
            self.assertEqual(claude_settings["env"][CLAUDE_FALLBACK_MODEL_ENV_KEY], "haiku-template")

    def test_sync_api_binding_updates_repo_runtime_models_api_and_key(self) -> None:
        with workspace_tempdir() as temp_dir:
            service = ProjectTemplateService()
            initial_profile = Profile.create(
                "api-a",
                "https://old.example.com",
                "sk-old",
                model="old-model",
                wire_api="responses",
            )
            service.generate(temp_dir, initial_profile)
            env_path = temp_dir / ".codex" / "local.env"
            env_path.write_text(f"{PROJECT_ENV_KEY}=sk-old\nEXTRA=value\n", encoding="utf-8")

            updated_profile = Profile.create(
                "api-b",
                "https://new.example.com/v1/",
                "sk-new",
                model="new-model",
                wire_api="chat_completions",
                api_keys=["sk-new", "sk-new-active"],
                active_api_key_index=1,
            )

            updated_paths = service.sync_api_binding(temp_dir, updated_profile)

            self.assertEqual(
                {path.relative_to(temp_dir).as_posix() for path in updated_paths},
                {".codex/config.toml", ".codex/home/config.toml", ".codex/local.env"},
            )
            repo_config_data = tomllib.loads((temp_dir / ".codex" / "config.toml").read_text(encoding="utf-8"))
            runtime_config_data = tomllib.loads((temp_dir / ".codex" / "home" / "config.toml").read_text(encoding="utf-8"))
            provider = runtime_config_data["model_providers"][PROJECT_PROVIDER_ID]
            self.assertEqual(repo_config_data["model"], "new-model")
            self.assertEqual(repo_config_data["review_model"], "new-model")
            self.assertEqual(runtime_config_data["model"], "new-model")
            self.assertEqual(runtime_config_data["review_model"], "new-model")
            self.assertEqual(provider["base_url"], "https://new.example.com/v1")
            self.assertEqual(provider["wire_api"], "chat_completions")
            self.assertEqual(provider["env_key"], PROJECT_ENV_KEY)
            self.assertNotIn("requires_openai_auth", provider)
            self.assertEqual(env_path.read_text(encoding="utf-8"), f"{PROJECT_ENV_KEY}=sk-new-active\nEXTRA=value\n")

    def test_sync_bindings_with_route_proxy_writes_placeholder_values(self) -> None:
        with workspace_tempdir() as temp_dir:
            service = ProjectTemplateService()
            codex_profile = Profile.create("codex", "https://codex.example.com", "sk-codex", codex_model="gpt-real")
            claude_profile = Profile.create(
                "claude",
                "https://claude.example.com",
                "sk-claude",
                vendor=VENDOR_CLAUDE,
                claude_model="sonnet-real",
            )
            service.generate(temp_dir, codex_profile, claude_profile=claude_profile)
            route_proxy_base_url = "http://127.0.0.1:15721/project/project-1"

            service.sync_api_binding(temp_dir, codex_profile, route_proxy_base_url=route_proxy_base_url)
            service.sync_claude_binding(temp_dir, claude_profile, route_proxy_base_url=route_proxy_base_url)

            runtime_config_data = tomllib.loads((temp_dir / ".codex" / "home" / "config.toml").read_text(encoding="utf-8"))
            provider = runtime_config_data["model_providers"][PROJECT_PROVIDER_ID]
            claude_settings = json.loads((temp_dir / ".claude" / "settings.local.json").read_text(encoding="utf-8"))

            self.assertEqual(provider["base_url"], route_proxy_base_url)
            self.assertEqual((temp_dir / ".codex" / "local.env").read_text(encoding="utf-8"), f"{PROJECT_ENV_KEY}={ROUTE_PROXY_PLACEHOLDER_KEY}\n")
            self.assertEqual(claude_settings["env"][CLAUDE_BASE_URL_ENV_KEY], route_proxy_base_url)
            self.assertEqual(claude_settings["env"][CLAUDE_API_KEY_ENV_KEY], ROUTE_PROXY_PLACEHOLDER_KEY)

    def test_sync_claude_binding_updates_settings_env_and_preserves_existing_fields(self) -> None:
        with workspace_tempdir() as temp_dir:
            service = ProjectTemplateService()
            settings_path = temp_dir / ".claude" / "settings.local.json"
            settings_path.parent.mkdir(parents=True, exist_ok=True)
            settings_path.write_text(
                json.dumps(
                    {
                        "permissions": {"allow": ["Bash(ls)"]},
                        "env": {
                            "EXTRA": "value",
                            CLAUDE_AUTH_TOKEN_ENV_KEY: "token-old",
                            "Anthropic_Auth_Token": "token-mixed",
                            CLAUDE_BASE_URL_ENV_KEY: "https://old.example.com",
                            CLAUDE_API_KEY_ENV_KEY: "sk-old",
                        },
                    }
                ),
                encoding="utf-8",
            )
            updated_profile = Profile.create(
                "claude-new",
                "https://new-claude.example.com/v1/",
                "sk-new",
                vendor=VENDOR_CLAUDE,
                claude_model="sonnet-new",
                claude_fallback_model="haiku-new",
                api_keys=["sk-new", "sk-active"],
                active_api_key_index=1,
            )

            updated_paths = service.sync_claude_binding(temp_dir, updated_profile)

            self.assertEqual({path.relative_to(temp_dir).as_posix() for path in updated_paths}, {".claude/settings.local.json"})
            settings = json.loads(settings_path.read_text(encoding="utf-8"))
            self.assertEqual(settings["permissions"], {"allow": ["Bash(ls)"]})
            self.assertEqual(settings["env"]["EXTRA"], "value")
            self.assertFalse(
                any(key.casefold() == CLAUDE_AUTH_TOKEN_ENV_KEY.casefold() for key in settings["env"])
            )
            self.assertEqual(settings["env"][CLAUDE_BASE_URL_ENV_KEY], "https://new-claude.example.com/v1")
            self.assertEqual(settings["env"][CLAUDE_API_KEY_ENV_KEY], "sk-active")
            self.assertEqual(settings["env"][CLAUDE_MODEL_ENV_KEY], "sonnet-new")
            self.assertEqual(settings["env"][CLAUDE_FALLBACK_MODEL_ENV_KEY], "haiku-new")

    def test_claude_env_from_profile_uses_active_project_binding_values(self) -> None:
        profile = Profile.create(
            "claude-env",
            "https://claude.example.com/v1/",
            "sk-old",
            vendor=VENDOR_CLAUDE,
            claude_model="sonnet-env",
            claude_fallback_model="haiku-env",
            api_keys=["sk-old", "sk-active"],
            active_api_key_index=1,
        )

        self.assertEqual(
            claude_env_from_profile(profile),
            {
                CLAUDE_BASE_URL_ENV_KEY: "https://claude.example.com/v1",
                CLAUDE_API_KEY_ENV_KEY: "sk-active",
                CLAUDE_MODEL_ENV_KEY: "sonnet-env",
                CLAUDE_FALLBACK_MODEL_ENV_KEY: "haiku-env",
            },
        )
        applied_env = apply_claude_profile_env(
            {
                "EXTRA": "value",
                "Anthropic_Auth_Token": "token-old",
            },
            profile,
        )

        self.assertEqual(applied_env["EXTRA"], "value")
        self.assertFalse(any(key.casefold() == CLAUDE_AUTH_TOKEN_ENV_KEY.casefold() for key in applied_env))
        self.assertEqual(applied_env[CLAUDE_API_KEY_ENV_KEY], "sk-active")


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


class RouteProxyTests(unittest.TestCase):
    def _serve(self, handler_cls: type[BaseHTTPRequestHandler]) -> ThreadingHTTPServer:
        server = ThreadingHTTPServer(("127.0.0.1", 0), handler_cls)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(thread.join, 1)
        self.addCleanup(server.shutdown)
        return server

    def test_openai_passthrough_rewrites_auth_and_preserves_query_once(self) -> None:
        captured: dict[str, str | None] = {}

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802
                captured["path"] = self.path
                captured["authorization"] = self.headers.get("Authorization")
                captured["x_api_key"] = self.headers.get("x-api-key")
                body = json.dumps({"data": [{"id": "gpt-proxy"}]}).encode("utf-8")
                self.send_response(200 if self.path == "/root/v1/models?after=abc" else 418)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, format: str, *args) -> None:  # noqa: A003
                return

        upstream = self._serve(Handler)
        profile = Profile.create("upstream", f"http://127.0.0.1:{upstream.server_port}/root", "sk-upstream")
        settings = RouteProxySettings(
            rules=[
                RouteProxyRule.create(
                    project_id="project-1",
                    client_type=ROUTE_PROXY_CLIENT_CODEX,
                    primary_profile_id=profile.id,
                )
            ]
        )
        events = []
        proxy = RouteProxyServer(lambda: settings, lambda: [profile], events.append)

        status, _headers, body, chunks = proxy.handle(
            method="GET",
            raw_path="/project/project-1/v1/models?after=abc",
            headers={"Authorization": "Bearer placeholder", "x-api-key": "placeholder"},
            body=b"",
        )

        self.assertEqual(status, 200)
        self.assertIsNone(chunks)
        self.assertIn("gpt-proxy", body.decode("utf-8") if body else "")
        self.assertEqual(captured["path"], "/root/v1/models?after=abc")
        self.assertEqual(captured["authorization"], "Bearer sk-upstream")
        self.assertIsNone(captured["x_api_key"])
        self.assertEqual(events[-1].client_type, ROUTE_PROXY_CLIENT_CODEX)

    def test_anthropic_passthrough_uses_x_api_key(self) -> None:
        captured: dict[str, object] = {}

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:  # noqa: N802
                captured["path"] = self.path
                captured["x_api_key"] = self.headers.get("x-api-key")
                captured["authorization"] = self.headers.get("Authorization")
                captured["anthropic_version"] = self.headers.get("anthropic-version")
                captured["payload"] = json.loads(self.rfile.read(int(self.headers.get("Content-Length", "0"))))
                body = json.dumps(
                    {
                        "id": "msg_1",
                        "type": "message",
                        "role": "assistant",
                        "content": [{"type": "text", "text": "ok"}],
                    }
                ).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, format: str, *args) -> None:  # noqa: A003
                return

        upstream = self._serve(Handler)
        profile = Profile.create("claude", f"http://127.0.0.1:{upstream.server_port}", "sk-claude", vendor=VENDOR_CLAUDE)
        settings = RouteProxySettings(
            rules=[
                RouteProxyRule.create(
                    project_id="project-1",
                    client_type=ROUTE_PROXY_CLIENT_CLAUDE,
                    primary_profile_id=profile.id,
                    upstream_protocol=ROUTE_PROXY_PROTOCOL_ANTHROPIC,
                )
            ]
        )
        proxy = RouteProxyServer(lambda: settings, lambda: [profile])
        request_body = json.dumps({"model": "sonnet", "messages": [{"role": "user", "content": "hi"}]}).encode("utf-8")

        status, _headers, body, chunks = proxy.handle(
            method="POST",
            raw_path="/project/project-1/v1/messages",
            headers={"Authorization": "Bearer placeholder"},
            body=request_body,
        )

        self.assertEqual(status, 200)
        self.assertIsNone(chunks)
        self.assertIn("msg_1", body.decode("utf-8") if body else "")
        self.assertEqual(captured["path"], "/v1/messages")
        self.assertEqual(captured["x_api_key"], "sk-claude")
        self.assertIsNone(captured["authorization"])
        self.assertEqual(captured["anthropic_version"], "2023-06-01")
        self.assertEqual(captured["payload"], {"model": "sonnet", "messages": [{"role": "user", "content": "hi"}]})

    def test_anthropic_to_openai_converts_tools_and_tool_results(self) -> None:
        converted = anthropic_to_openai_request(
            {
                "model": "claude-sonnet",
                "system": [{"type": "text", "text": "be precise"}],
                "messages": [
                    {"role": "user", "content": "inspect file"},
                    {
                        "role": "assistant",
                        "content": [
                            {"type": "text", "text": "I will inspect it."},
                            {"type": "tool_use", "id": "toolu_1", "name": "read_file", "input": {"path": "README.md"}},
                        ],
                    },
                    {
                        "role": "user",
                        "content": [
                            {"type": "tool_result", "tool_use_id": "toolu_1", "content": [{"type": "text", "text": "done"}]},
                        ],
                    },
                ],
                "tools": [
                    {
                        "name": "read_file",
                        "description": "Read a file",
                        "input_schema": {"type": "object", "properties": {"path": {"type": "string"}}},
                    }
                ],
                "tool_choice": {"type": "tool", "name": "read_file"},
            },
            "gpt-5",
        )

        self.assertEqual(converted["model"], "gpt-5")
        self.assertEqual(converted["messages"][0], {"role": "system", "content": "be precise"})
        self.assertEqual(converted["messages"][2]["tool_calls"][0]["function"]["name"], "read_file")
        self.assertEqual(json.loads(converted["messages"][2]["tool_calls"][0]["function"]["arguments"]), {"path": "README.md"})
        self.assertEqual(converted["messages"][3], {"role": "tool", "tool_call_id": "toolu_1", "content": "done"})
        self.assertEqual(converted["tools"][0]["function"]["parameters"]["properties"]["path"]["type"], "string")
        self.assertEqual(converted["tool_choice"], {"type": "function", "function": {"name": "read_file"}})

        anthropic = openai_to_anthropic_response(
            {
                "id": "chatcmpl_1",
                "choices": [
                    {
                        "finish_reason": "tool_calls",
                        "message": {
                            "tool_calls": [
                                {
                                    "id": "call_1",
                                    "type": "function",
                                    "function": {"name": "read_file", "arguments": "{\"path\": \"README.md\"}"},
                                }
                            ]
                        },
                    }
                ],
                "usage": {"prompt_tokens": 11, "completion_tokens": 7},
            },
            "claude-sonnet",
        )

        self.assertEqual(anthropic["stop_reason"], "tool_use")
        self.assertEqual(anthropic["usage"], {"input_tokens": 11, "output_tokens": 7})
        self.assertEqual(anthropic["content"][0]["type"], "tool_use")
        self.assertEqual(anthropic["content"][0]["input"], {"path": "README.md"})

    def test_anthropic_to_openai_route_converts_request_and_response(self) -> None:
        captured: dict[str, object] = {}

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:  # noqa: N802
                captured["path"] = self.path
                captured["authorization"] = self.headers.get("Authorization")
                captured["payload"] = json.loads(self.rfile.read(int(self.headers.get("Content-Length", "0"))))
                body = json.dumps(
                    {
                        "id": "chatcmpl_1",
                        "choices": [{"finish_reason": "stop", "message": {"content": "converted ok"}}],
                        "usage": {"prompt_tokens": 3, "completion_tokens": 2},
                    }
                ).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, format: str, *args) -> None:  # noqa: A003
                return

        upstream = self._serve(Handler)
        profile = Profile.create("openai", f"http://127.0.0.1:{upstream.server_port}", "sk-openai", codex_model="gpt-5")
        settings = RouteProxySettings(
            rules=[
                RouteProxyRule.create(
                    project_id="project-1",
                    client_type=ROUTE_PROXY_CLIENT_CLAUDE,
                    primary_profile_id=profile.id,
                    upstream_protocol=ROUTE_PROXY_PROTOCOL_ANTHROPIC_TO_OPENAI,
                )
            ]
        )
        proxy = RouteProxyServer(lambda: settings, lambda: [profile])
        request_body = json.dumps(
            {
                "model": "claude-sonnet",
                "messages": [{"role": "user", "content": "hi"}],
                "max_tokens": 64,
            }
        ).encode("utf-8")

        status, headers, body, chunks = proxy.handle(
            method="POST",
            raw_path="/project/project-1/v1/messages",
            headers={"x-api-key": "placeholder"},
            body=request_body,
        )

        response_payload = json.loads(body.decode("utf-8") if body else "{}")
        self.assertEqual(status, 200)
        self.assertIsNone(chunks)
        self.assertEqual(headers["content-type"], "application/json")
        self.assertEqual(captured["path"], "/v1/chat/completions")
        self.assertEqual(captured["authorization"], "Bearer sk-openai")
        self.assertEqual(captured["payload"]["model"], "gpt-5")
        self.assertEqual(captured["payload"]["messages"], [{"role": "user", "content": "hi"}])
        self.assertEqual(response_payload["type"], "message")
        self.assertEqual(response_payload["content"], [{"type": "text", "text": "converted ok"}])
        self.assertEqual(response_payload["usage"], {"input_tokens": 3, "output_tokens": 2})

    def test_anthropic_to_openai_route_decodes_gzip_response(self) -> None:
        captured: dict[str, object] = {}

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:  # noqa: N802
                captured["accept_encoding"] = self.headers.get("Accept-Encoding")
                self.rfile.read(int(self.headers.get("Content-Length", "0")))
                raw_body = json.dumps(
                    {
                        "id": "chatcmpl_gzip",
                        "choices": [{"finish_reason": "stop", "message": {"content": "gzip ok"}}],
                    }
                ).encode("utf-8")
                body = gzip.compress(raw_body)
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Encoding", "gzip")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, format: str, *args) -> None:  # noqa: A003
                return

        upstream = self._serve(Handler)
        profile = Profile.create("openai", f"http://127.0.0.1:{upstream.server_port}", "sk-openai", codex_model="gpt-5")
        settings = RouteProxySettings(
            rules=[
                RouteProxyRule.create(
                    project_id="project-1",
                    client_type=ROUTE_PROXY_CLIENT_CLAUDE,
                    primary_profile_id=profile.id,
                    upstream_protocol=ROUTE_PROXY_PROTOCOL_ANTHROPIC_TO_OPENAI,
                )
            ]
        )
        proxy = RouteProxyServer(lambda: settings, lambda: [profile])
        request_body = json.dumps({"model": "claude-sonnet", "messages": [{"role": "user", "content": "hi"}]}).encode("utf-8")

        status, headers, body, chunks = proxy.handle(
            method="POST",
            raw_path="/project/project-1/v1/messages",
            headers={"Accept-Encoding": "gzip, deflate"},
            body=request_body,
        )

        response_payload = json.loads(body.decode("utf-8") if body else "{}")
        self.assertEqual(status, 200)
        self.assertIsNone(chunks)
        self.assertEqual(captured["accept_encoding"], "identity")
        self.assertIsNone(headers.get("content-encoding"))
        self.assertEqual(response_payload["content"], [{"type": "text", "text": "gzip ok"}])

    def test_anthropic_to_openai_route_converts_streaming_response(self) -> None:
        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:  # noqa: N802
                self.rfile.read(int(self.headers.get("Content-Length", "0")))
                body = b"".join(
                    [
                        b'data: {"choices":[{"delta":{"content":"stream "}}]}\n\n',
                        b'data: {"choices":[{"delta":{"content":"ok"}}]}\n\n',
                        b"data: [DONE]\n\n",
                    ]
                )
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, format: str, *args) -> None:  # noqa: A003
                return

        upstream = self._serve(Handler)
        profile = Profile.create("openai", f"http://127.0.0.1:{upstream.server_port}", "sk-openai", codex_model="gpt-5")
        settings = RouteProxySettings(
            rules=[
                RouteProxyRule.create(
                    project_id="project-1",
                    client_type=ROUTE_PROXY_CLIENT_CLAUDE,
                    primary_profile_id=profile.id,
                    upstream_protocol=ROUTE_PROXY_PROTOCOL_ANTHROPIC_TO_OPENAI,
                )
            ]
        )
        proxy = RouteProxyServer(lambda: settings, lambda: [profile])
        request_body = json.dumps(
            {
                "model": "claude-sonnet",
                "stream": True,
                "messages": [{"role": "user", "content": "hi"}],
            }
        ).encode("utf-8")

        status, headers, body, chunks = proxy.handle(
            method="POST",
            raw_path="/project/project-1/v1/messages",
            headers={},
            body=request_body,
        )

        rendered = b"".join(chunks or []).decode("utf-8")
        self.assertEqual(status, 200)
        self.assertIsNone(body)
        self.assertEqual(headers["content-type"], "text/event-stream")
        self.assertIn("event: message_start", rendered)
        self.assertIn("\"text\": \"stream \"", rendered)
        self.assertIn("\"text\": \"ok\"", rendered)
        self.assertIn("event: message_stop", rendered)

    def test_anthropic_to_openai_rejects_unsupported_multimodal_blocks(self) -> None:
        profile = Profile.create("openai", "http://127.0.0.1:1", "sk-openai")
        settings = RouteProxySettings(
            rules=[
                RouteProxyRule.create(
                    project_id="project-1",
                    client_type=ROUTE_PROXY_CLIENT_CLAUDE,
                    primary_profile_id=profile.id,
                    upstream_protocol=ROUTE_PROXY_PROTOCOL_ANTHROPIC_TO_OPENAI,
                )
            ]
        )
        proxy = RouteProxyServer(lambda: settings, lambda: [profile])
        request_body = json.dumps(
            {
                "model": "claude-sonnet",
                "messages": [
                    {
                        "role": "user",
                        "content": [{"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": "AA=="}}],
                    }
                ],
            }
        ).encode("utf-8")

        status, _headers, body, chunks = proxy.handle(
            method="POST",
            raw_path="/project/project-1/v1/messages",
            headers={},
            body=request_body,
        )

        self.assertEqual(status, 400)
        self.assertIsNone(chunks)
        self.assertIn("Unsupported content block", body.decode("utf-8") if body else "")

    def test_openai_sse_chunks_convert_to_anthropic_events(self) -> None:
        rendered = b"".join(
            iter_openai_sse_to_anthropic(
                [
                    b'data: {"choices":[{"delta":{"content":"hel"}}]}\n\n',
                    b'data: {"choices":[{"delta":{"content":"lo"}}]}\n\n',
                    b"data: [DONE]\n\n",
                ],
                "claude-sonnet",
            )
        ).decode("utf-8")

        self.assertIn("event: message_start", rendered)
        self.assertIn("\"type\": \"text_delta\", \"text\": \"hel\"", rendered)
        self.assertIn("\"type\": \"text_delta\", \"text\": \"lo\"", rendered)
        self.assertIn("event: content_block_stop", rendered)
        self.assertIn("event: message_stop", rendered)


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


class ChatTesterTests(unittest.TestCase):
    def test_send_message_with_responses_api(self) -> None:
        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:  # noqa: N802
                if self.path != "/v1/responses":
                    self.send_response(404)
                    self.end_headers()
                    return
                payload = json.loads(self.rfile.read(int(self.headers.get("Content-Length", "0"))))
                if self.headers.get("Authorization") != "Bearer sk-chat":
                    self.send_response(401)
                    self.end_headers()
                    return
                if payload.get("model") != "gpt-4o-mini":
                    self.send_response(400)
                    self.end_headers()
                    return
                body = json.dumps({"output_text": "hello from api"}).encode("utf-8")
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

        tester = ChatTester(timeout=5)
        profile = Profile.create(
            "chat",
            f"http://127.0.0.1:{server.server_port}",
            "sk-wrong",
            model="gpt-5.4",
            wire_api="responses",
            api_keys=["sk-wrong", "sk-chat"],
            active_api_key_index=1,
        )

        result = tester.send_message(profile, "ping", model_override="gpt-4o-mini")

        self.assertTrue(result.ok)
        self.assertEqual(result.model, "gpt-4o-mini")
        self.assertEqual(result.text, "hello from api")
        self.assertEqual(result.endpoint, f"http://127.0.0.1:{server.server_port}/v1/responses")

    def test_send_message_with_chat_completions(self) -> None:
        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:  # noqa: N802
                if self.path != "/v1/chat/completions":
                    self.send_response(404)
                    self.end_headers()
                    return
                body = json.dumps({"choices": [{"message": {"content": "chat completion ok"}}]}).encode("utf-8")
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

        tester = ChatTester(timeout=5)
        profile = Profile.create(
            "chat2",
            f"http://127.0.0.1:{server.server_port}",
            "sk-chat",
            model="gpt-4.1",
            wire_api="chat_completions",
        )

        result = tester.send_message(profile, "ping")

        self.assertTrue(result.ok)
        self.assertEqual(result.text, "chat completion ok")
        self.assertEqual(result.endpoint, f"http://127.0.0.1:{server.server_port}/v1/chat/completions")

    def test_send_message_returns_full_response_when_responses_text_is_missing(self) -> None:
        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:  # noqa: N802
                body = json.dumps(
                    {
                        "id": "resp_123",
                        "status": "completed",
                        "output": [{"type": "message", "content": [{"type": "json", "value": {"ok": True}}]}],
                    }
                ).encode("utf-8")
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

        tester = ChatTester(timeout=5)
        profile = Profile.create("chat-full-response", f"http://127.0.0.1:{server.server_port}", "sk-chat")

        result = tester.send_message(profile, "ping")

        self.assertTrue(result.ok)
        self.assertIn("完整返回结果", result.text)
        self.assertIn('"id": "resp_123"', result.text)
        self.assertIn('"ok": true', result.text)

    def test_send_message_returns_full_response_when_chat_content_is_missing(self) -> None:
        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:  # noqa: N802
                body = json.dumps({"choices": [{"message": {"tool_calls": [{"id": "call_1"}]}}]}).encode("utf-8")
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

        tester = ChatTester(timeout=5)
        profile = Profile.create(
            "chat-full-chat-response",
            f"http://127.0.0.1:{server.server_port}",
            "sk-chat",
            wire_api="chat_completions",
        )

        result = tester.send_message(profile, "ping")

        self.assertTrue(result.ok)
        self.assertIn("完整返回结果", result.text)
        self.assertIn('"tool_calls"', result.text)
        self.assertIn('"id": "call_1"', result.text)

    def test_send_message_supports_wire_api_override_and_custom_payload(self) -> None:
        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:  # noqa: N802
                if self.path != "/v1/chat/completions":
                    self.send_response(404)
                    self.end_headers()
                    return
                payload = json.loads(self.rfile.read(int(self.headers.get("Content-Length", "0"))))
                expected = {
                    "model": "gpt-4o-mini",
                    "messages": [
                        {"role": "system", "content": "be precise"},
                        {"role": "user", "content": "ping"},
                    ],
                    "temperature": 0,
                }
                if payload != expected:
                    self.send_response(400)
                    self.end_headers()
                    return
                body = json.dumps({"choices": [{"message": {"content": "custom payload ok"}}]}).encode("utf-8")
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

        tester = ChatTester(timeout=5)
        profile = Profile.create(
            "chat-override",
            f"http://127.0.0.1:{server.server_port}",
            "sk-chat",
            model="gpt-5.4",
            wire_api="responses",
        )
        payload_override_text = json.dumps(
            {
                "model": "{{model}}",
                "messages": [
                    {"role": "system", "content": "be precise"},
                    {"role": "user", "content": "{{prompt}}"},
                ],
                "temperature": 0,
            }
        )

        result = tester.send_message(
            profile,
            "ping",
            model_override="gpt-4o-mini",
            wire_api_override="chat_completions",
            payload_override_text=payload_override_text,
        )

        self.assertTrue(result.ok)
        self.assertEqual(result.text, "custom payload ok")
        self.assertEqual(result.endpoint, f"http://127.0.0.1:{server.server_port}/v1/chat/completions")

    def test_send_message_returns_error_for_invalid_payload_json(self) -> None:
        tester = ChatTester(timeout=1)
        profile = Profile.create(
            "chat-invalid-payload",
            "https://example.com",
            "sk-chat",
            model="gpt-5.4",
            wire_api="responses",
        )

        result = tester.send_message(profile, "ping", payload_override_text="{")

        self.assertFalse(result.ok)
        self.assertIn("请求体 JSON 无效", result.text)

    def test_send_message_timeout_returns_error_result(self) -> None:
        tester = ChatTester(timeout=1)
        profile = Profile.create(
            "chat-timeout",
            "https://example.com",
            "sk-chat",
            model="gpt-5.4",
            wire_api="responses",
        )

        with patch("codex_switch.chat.request.urlopen", side_effect=TimeoutError):
            result = tester.send_message(profile, "ping")

        self.assertFalse(result.ok)
        self.assertIn("超时", result.text)


if __name__ == "__main__":
    unittest.main()
