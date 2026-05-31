from __future__ import annotations

import json
from pathlib import Path
import unittest

from helpers import workspace_tempdir

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
    ROUTE_PROXY_PROTOCOL_ANTHROPIC,
    ROUTE_PROXY_PROTOCOL_ANTHROPIC_TO_OPENAI,
    ROUTE_PROXY_PROTOCOL_OPENAI_RESPONSES_TO_CHAT,
    VENDOR_GENERIC,
    normalize_profile_vendor,
    today_iso,
)
from codex_switch.storage import DEFAULT_MODEL_BATCH_CONCURRENCY, ProfileStore, clamp_model_batch_concurrency


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
                global_mcp_server_names,
                selected_codex_global_profile_id,
                selected_claude_global_profile_id,
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
            self.assertIsNone(global_mcp_server_names)
            self.assertIsNone(selected_codex_global_profile_id)
            self.assertIsNone(selected_claude_global_profile_id)

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

    def test_store_persists_global_profile_and_mcp_selection(self) -> None:
        with workspace_tempdir() as temp_dir:
            store = ProfileStore(temp_dir)

            store.save(
                [],
                None,
                global_mcp_server_names=["filesystem", "serena"],
                selected_codex_global_profile_id="codex-profile",
                selected_claude_global_profile_id="claude-profile",
            )
            loaded = store.load()
            payload = json.loads(store.storage_path.read_text(encoding="utf-8"))

            self.assertEqual(loaded[12], ["filesystem", "serena"])
            self.assertEqual(loaded[13], "codex-profile")
            self.assertEqual(loaded[14], "claude-profile")
            self.assertEqual(payload["settings"]["global_mcp_server_names"], ["filesystem", "serena"])
            self.assertEqual(payload["settings"]["selected_codex_global_profile_id"], "codex-profile")
            self.assertEqual(payload["settings"]["selected_claude_global_profile_id"], "claude-profile")

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
