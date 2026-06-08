from __future__ import annotations

import json
from pathlib import Path
import unittest

from helpers import workspace_tempdir

from codex_switch.models import (
    AccountPoolChannel,
    AccountPoolGroup,
    AccountPoolSettings,
    ACCOUNT_POOL_CHANNEL_SOURCE_PROFILE,
    DEFAULT_CLAUDE_FALLBACK_MODEL,
    DEFAULT_CLAUDE_MODEL,
    DEFAULT_HOT_UPDATE_INTERVAL_MINUTES,
    HOT_UPDATE_INTERVAL_MINUTES_MAX,
    HOT_UPDATE_INTERVAL_MINUTES_MIN,
    HealthResult,
    PROFILE_CATEGORY_IMAGE_GENERATION,
    PROFILE_CATEGORY_TEXT,
    Profile,
    ProjectRecord,
    RouteProxyRule,
    RouteProxySettings,
    ROUTE_PROXY_CLIENT_CLAUDE,
    ROUTE_PROXY_CLIENT_CODEX,
    ROUTE_PROXY_PROTOCOL_ANTHROPIC,
    ROUTE_PROXY_PROTOCOL_ANTHROPIC_TO_OPENAI,
    ROUTE_PROXY_PROTOCOL_OPENAI_RESPONSES_TO_CHAT,
    ROUTE_PROXY_UPSTREAM_SOURCE_ACCOUNT_POOL,
    ROUTE_PROXY_UPSTREAM_SOURCE_PROFILE,
    SkillDefinition,
    SkillGroup,
    SkillMarketRepo,
    VENDOR_GENERIC,
    model_vendor_stats,
    models_by_vendor,
    normalize_hot_update_interval_minutes,
    normalize_profile_vendor,
    profile_supports_codex,
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
                account_pool_settings,
                skill_groups,
                skill_market_repos,
                hot_update_enabled,
                hot_update_interval_minutes,
            ) = store.load()

            self.assertEqual(selected_profile_id, profile.id)
            self.assertEqual(len(profiles), 1)
            self.assertEqual(profiles[0].name, "主线路")
            self.assertEqual(profiles[0].api_keys, ["sk-demo"])
            self.assertEqual(profiles[0].api_key, "sk-demo")
            self.assertEqual(profiles[0].category, PROFILE_CATEGORY_TEXT)
            self.assertTrue(profiles[0].api_provided)
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
            self.assertFalse(account_pool_settings.enabled)
            self.assertEqual(account_pool_settings.channels, [])
            self.assertEqual(skill_groups, [])
            self.assertEqual(skill_market_repos, [])
            self.assertFalse(hot_update_enabled)
            self.assertEqual(hot_update_interval_minutes, DEFAULT_HOT_UPDATE_INTERVAL_MINUTES)

    def test_store_persists_agents_doc_text(self) -> None:
        with workspace_tempdir() as temp_dir:
            store = ProfileStore(temp_dir)
            store.save([], None, agents_doc_text="Custom AGENTS text")

            loaded = store.load()
            self.assertEqual(loaded[8], "Custom AGENTS text")

            payload = json.loads(store.storage_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["version"], 14)
            self.assertEqual(payload["settings"]["agents_doc_text"], "Custom AGENTS text")

    def test_store_persists_image_generation_profile_without_api(self) -> None:
        with workspace_tempdir() as temp_dir:
            store = ProfileStore(temp_dir)
            profile = Profile.create(
                "image",
                "https://image.example.com",
                "sk-image",
                category=PROFILE_CATEGORY_IMAGE_GENERATION,
                api_provided=False,
            )

            store.save([profile], profile.id)
            loaded_profiles = store.load()[0]
            payload = json.loads(store.storage_path.read_text(encoding="utf-8"))

            self.assertEqual(loaded_profiles[0].category, PROFILE_CATEGORY_IMAGE_GENERATION)
            self.assertFalse(loaded_profiles[0].api_provided)
            self.assertEqual(loaded_profiles[0].api_keys, [])
            self.assertEqual(loaded_profiles[0].api_key, "")
            self.assertFalse(profile_supports_codex(loaded_profiles[0]))
            self.assertEqual(payload["profiles"][0]["category"], PROFILE_CATEGORY_IMAGE_GENERATION)
            self.assertFalse(payload["profiles"][0]["api_provided"])
            self.assertEqual(payload["profiles"][0]["api_key"], "")

    def test_store_persists_account_pool_settings(self) -> None:
        with workspace_tempdir() as temp_dir:
            store = ProfileStore(temp_dir)
            channel = AccountPoolChannel.create(
                name="pool-a",
                base_url="https://pool.example.com/v1",
                api_key="sk-pool",
                wire_api="chat_completions",
                default_model="gpt-pool",
            )
            channel.status = "error"
            channel.failure_reason = "HTTP 503"
            account_pool = AccountPoolSettings(
                enabled=True,
                channels=[channel],
                next_index=1,
                last_recovery_checked_at="2026-06-06T10:00:00",
            )

            store.save([], None, account_pool_settings=account_pool)
            loaded = store.load()[15]
            payload = json.loads(store.storage_path.read_text(encoding="utf-8"))

            self.assertTrue(loaded.enabled)
            self.assertEqual(loaded.next_index, 1)
            self.assertEqual(loaded.last_recovery_checked_at, "2026-06-06T10:00:00")
            self.assertEqual(loaded.channels[0].name, "pool-a")
            self.assertEqual(loaded.channels[0].wire_api, "chat_completions")
            self.assertEqual(loaded.channels[0].default_model, "gpt-pool")
            self.assertEqual(loaded.channels[0].failure_reason, "HTTP 503")
            self.assertEqual(payload["version"], 14)
            self.assertEqual(loaded.recovery_interval_minutes, 5)
            self.assertEqual(len(loaded.groups), 1)
            self.assertEqual(loaded.channels[0].group_id, loaded.groups[0].id)
            self.assertEqual(payload["settings"]["account_pool"]["channels"][0]["api_key"], "sk-pool")

    def test_store_persists_account_pool_groups_and_profile_source(self) -> None:
        with workspace_tempdir() as temp_dir:
            store = ProfileStore(temp_dir)
            group = AccountPoolGroup.create("项目组")
            channel = AccountPoolChannel.create(
                name="配置库渠道",
                base_url="https://pool.example.com",
                api_key="sk-second",
                group_id=group.id,
                source_type=ACCOUNT_POOL_CHANNEL_SOURCE_PROFILE,
                source_profile_id="profile-1",
                source_profile_name="配置库 API",
                source_api_key_index=1,
                wire_api="responses",
                default_model="gpt-profile",
            )
            account_pool = AccountPoolSettings(
                enabled=True,
                groups=[group],
                selected_group_id=group.id,
                channels=[channel],
                recovery_interval_minutes=8,
            )

            store.save([], None, account_pool_settings=account_pool)
            loaded = store.load()[15]

            self.assertEqual(loaded.selected_group_id, group.id)
            self.assertEqual(loaded.recovery_interval_minutes, 8)
            self.assertEqual(loaded.groups[0].name, "项目组")
            self.assertEqual(loaded.channels[0].source_type, ACCOUNT_POOL_CHANNEL_SOURCE_PROFILE)
            self.assertEqual(loaded.channels[0].source_profile_id, "profile-1")
            self.assertEqual(loaded.channels[0].source_api_key_index, 1)

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

    def test_store_persists_project_mcp_and_skill_selection(self) -> None:
        with workspace_tempdir() as temp_dir:
            store = ProfileStore(temp_dir)
            skill = SkillDefinition.create(
                "frontend-dev",
                content="frontend skill",
                source_path=str(temp_dir / "frontend-dev"),
            )
            project = ProjectRecord.create(
                str(temp_dir),
                "codex-profile",
                name="project",
                mcp_server_names=["filesystem", "serena"],
                skill_names=["frontend-dev", "fullstack-dev"],
                skill_group_ids=["group-1"],
                skills=[skill],
                github_repo="https://github.com/example/project",
                github_last_sync_commit="def456",
                github_auto_update=True,
                codex_profile_id="codex-profile",
                claude_profile_id="claude-profile",
            )

            store.save([], None, projects=[project], selected_project_id=project.id)
            loaded_projects = store.load()[2]
            payload = json.loads(store.storage_path.read_text(encoding="utf-8"))

            self.assertEqual(loaded_projects[0].mcp_server_names, ["filesystem", "serena"])
            self.assertEqual(loaded_projects[0].skill_names, ["frontend-dev", "fullstack-dev"])
            self.assertEqual(loaded_projects[0].skill_group_ids, ["group-1"])
            self.assertEqual(loaded_projects[0].skills[0].name, "frontend-dev")
            self.assertEqual(loaded_projects[0].github_repo, "https://github.com/example/project")
            self.assertEqual(loaded_projects[0].github_last_sync_commit, "def456")
            self.assertTrue(loaded_projects[0].github_auto_update)
            self.assertEqual(loaded_projects[0].profile_id, "codex-profile")
            self.assertEqual(loaded_projects[0].codex_profile_id, "codex-profile")
            self.assertEqual(loaded_projects[0].claude_profile_id, "claude-profile")
            self.assertEqual(payload["projects"][0]["mcp_server_names"], ["filesystem", "serena"])
            self.assertEqual(payload["projects"][0]["skill_names"], ["frontend-dev", "fullstack-dev"])
            self.assertEqual(payload["projects"][0]["skill_group_ids"], ["group-1"])
            self.assertEqual(payload["projects"][0]["skills"][0]["name"], "frontend-dev")
            self.assertEqual(payload["projects"][0]["github_repo"], "https://github.com/example/project")
            self.assertEqual(payload["projects"][0]["github_last_sync_commit"], "def456")
            self.assertTrue(payload["projects"][0]["github_auto_update"])
            self.assertEqual(payload["projects"][0]["codex_profile_id"], "codex-profile")
            self.assertEqual(payload["projects"][0]["claude_profile_id"], "claude-profile")

    def test_store_persists_skill_groups_and_market_repos(self) -> None:
        with workspace_tempdir() as temp_dir:
            store = ProfileStore(temp_dir)
            skill = SkillDefinition.create("python-helper", content="Use Python carefully.")
            group = SkillGroup.create("代码组", description="常用编码技能", skills=[skill])
            repo = SkillMarketRepo.create(
                "https://github.com/example/skills",
                branch="main",
                last_sync_commit="abc123",
                auto_update=True,
                installed_group_id=group.id,
            )

            store.save(
                [],
                None,
                skill_groups=[group],
                skill_market_repos=[repo],
                hot_update_enabled=True,
                hot_update_interval_minutes=15,
            )
            loaded = store.load()
            payload = json.loads(store.storage_path.read_text(encoding="utf-8"))

            self.assertEqual(loaded[16][0].name, "代码组")
            self.assertEqual(loaded[16][0].skills[0].content, "Use Python carefully.")
            self.assertEqual(loaded[17][0].url, "https://github.com/example/skills")
            self.assertTrue(loaded[17][0].auto_update)
            self.assertEqual(loaded[17][0].installed_group_id, group.id)
            self.assertTrue(loaded[18])
            self.assertEqual(loaded[19], 15)
            self.assertEqual(payload["settings"]["skill_groups"][0]["skills"][0]["name"], "python-helper")
            self.assertEqual(payload["settings"]["skill_market_repos"][0]["last_sync_commit"], "abc123")
            self.assertEqual(payload["settings"]["skill_market_repos"][0]["installed_group_id"], group.id)
            self.assertTrue(payload["settings"]["hot_update_enabled"])
            self.assertEqual(payload["settings"]["hot_update_interval_minutes"], 15)

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
            self.assertIsNone(loaded_project.skill_names)
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
        self.assertEqual(profile.category, PROFILE_CATEGORY_TEXT)
        self.assertTrue(profile.api_provided)
        self.assertEqual(profile.codex_model, "legacy-model")
        self.assertEqual(profile.claude_model, DEFAULT_CLAUDE_MODEL)
        self.assertEqual(profile.claude_fallback_model, DEFAULT_CLAUDE_FALLBACK_MODEL)

    def test_model_vendor_stats_groups_known_vendors_and_other(self) -> None:
        models = ["gpt-5.4", "claude-sonnet-4", "gemini-2.5-pro", "custom-local"]

        self.assertEqual(
            model_vendor_stats(models),
            {
                "OpenAI": 1,
                "Anthropic": 1,
                "Google": 1,
                "其他": 1,
            },
        )
        self.assertEqual(models_by_vendor(models)["其他"], ["custom-local"])

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
            self.assertFalse(loaded[15].enabled)
            self.assertEqual(loaded[15].channels, [])

    def test_route_proxy_rule_defaults_upstream_source_to_profile(self) -> None:
        rule = RouteProxyRule.from_dict(
            {
                "project_id": "project-1",
                "client_type": ROUTE_PROXY_CLIENT_CODEX,
                "primary_profile_id": "profile-1",
            }
        )

        self.assertEqual(rule.upstream_source, ROUTE_PROXY_UPSTREAM_SOURCE_PROFILE)

    def test_route_proxy_rule_persists_account_pool_source(self) -> None:
        rule = RouteProxyRule.create(
            project_id="project-1",
            client_type=ROUTE_PROXY_CLIENT_CODEX,
            primary_profile_id="profile-1",
            upstream_source=ROUTE_PROXY_UPSTREAM_SOURCE_ACCOUNT_POOL,
        )

        loaded = RouteProxyRule.from_dict(rule.to_dict())

        self.assertEqual(loaded.upstream_source, ROUTE_PROXY_UPSTREAM_SOURCE_ACCOUNT_POOL)

    def test_model_batch_concurrency_is_clamped(self) -> None:
        self.assertEqual(clamp_model_batch_concurrency(0), 1)
        self.assertEqual(clamp_model_batch_concurrency(9), 5)
        self.assertEqual(clamp_model_batch_concurrency("bad"), DEFAULT_MODEL_BATCH_CONCURRENCY)

    def test_hot_update_interval_is_normalized(self) -> None:
        self.assertEqual(normalize_hot_update_interval_minutes(0), HOT_UPDATE_INTERVAL_MINUTES_MIN)
        self.assertEqual(normalize_hot_update_interval_minutes(2000), HOT_UPDATE_INTERVAL_MINUTES_MAX)
        self.assertEqual(normalize_hot_update_interval_minutes("bad"), DEFAULT_HOT_UPDATE_INTERVAL_MINUTES)
