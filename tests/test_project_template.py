from __future__ import annotations

import json
from pathlib import Path
import tomllib
import unittest

from helpers import workspace_tempdir

from codex_switch.claude_config import ClaudeConfigManager
from codex_switch.codex_config import CodexConfigManager, PROJECT_ENV_KEY, PROJECT_PROVIDER_ID, scope_mcp_servers_to_project
from codex_switch.models import (
    DEFAULT_CLAUDE_FALLBACK_MODEL,
    DEFAULT_CLAUDE_MODEL,
    Profile,
    ProjectRecord,
    ROUTE_PROXY_PLACEHOLDER_KEY,
    ROUTE_PROXY_PROTOCOL_OPENAI_RESPONSES_TO_CHAT,
    VENDOR_CLAUDE,
    VENDOR_CODEX,
)
from codex_switch.project_template import (
    CLAUDE_API_KEY_ENV_KEY,
    CLAUDE_AUTH_TOKEN_ENV_KEY,
    CLAUDE_BASE_URL_ENV_KEY,
    CLAUDE_FALLBACK_MODEL_ENV_KEY,
    CLAUDE_LEGACY_API_KEY_ENV_KEY,
    CLAUDE_MODEL_ENV_KEY,
    CODEX_SCRIPT_DIRNAME,
    GITIGNORE_MANAGED_BEGIN,
    GITIGNORE_MANAGED_END,
    ProjectTemplateService,
    apply_claude_profile_env,
    claude_env_from_profile,
)
from codex_switch.skills import PROJECT_SKILLS_RELATIVE_DIR, SKILL_MANAGED_MARKER, SkillSource


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
            self.assertNotIn("wire_api", config_data["model_providers"]["OpenAI"])

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


class ClaudeConfigManagerTests(unittest.TestCase):
    def test_apply_profile_updates_global_claude_settings(self) -> None:
        with workspace_tempdir() as temp_dir:
            claude_dir = temp_dir / ".claude"
            claude_dir.mkdir()
            settings_path = claude_dir / "settings.json"
            settings_path.write_text(
                json.dumps(
                    {
                        "permissions": {"allow": ["Bash(git status)"]},
                        "env": {
                            CLAUDE_API_KEY_ENV_KEY: "token-old",
                            CLAUDE_LEGACY_API_KEY_ENV_KEY: "sk-old",
                            "KEEP_ME": "1",
                        },
                    }
                ),
                encoding="utf-8",
            )
            manager = ClaudeConfigManager(claude_dir=claude_dir, backup_root=claude_dir / "backups")
            profile = Profile.create(
                "claude-global",
                "https://claude.example.com/v1",
                "sk-claude",
                vendor=VENDOR_CLAUDE,
                claude_model="sonnet-global",
                claude_fallback_model="haiku-global",
            )

            backup_dir = manager.apply_profile(profile)

            settings = json.loads(settings_path.read_text(encoding="utf-8"))
            env = settings["env"]
            self.assertTrue((backup_dir / "settings.json").exists())
            self.assertEqual(settings["permissions"]["allow"], ["Bash(git status)"])
            self.assertEqual(env["KEEP_ME"], "1")
            self.assertEqual(env[CLAUDE_BASE_URL_ENV_KEY], "https://claude.example.com/v1")
            self.assertEqual(env[CLAUDE_API_KEY_ENV_KEY], "sk-claude")
            self.assertEqual(env[CLAUDE_MODEL_ENV_KEY], "sonnet-global")
            self.assertEqual(env[CLAUDE_FALLBACK_MODEL_ENV_KEY], "haiku-global")
            self.assertFalse(any(key.casefold() == CLAUDE_LEGACY_API_KEY_ENV_KEY.casefold() for key in env))


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

    def test_generate_copies_selected_project_skills(self) -> None:
        with workspace_tempdir() as temp_dir:
            source = temp_dir / "skill-source" / "frontend-dev"
            source.mkdir(parents=True)
            (source / "SKILL.md").write_text("frontend skill", encoding="utf-8")
            (source / "references").mkdir()
            (source / "references" / "guide.md").write_text("guide", encoding="utf-8")
            service = ProjectTemplateService()
            profile = Profile.create("project", "https://example.com", "sk-template")

            result = service.generate(
                temp_dir / "project",
                profile,
                skill_sources=[SkillSource("frontend-dev", "frontend-dev", source)],
            )

            target = temp_dir / "project" / PROJECT_SKILLS_RELATIVE_DIR / "frontend-dev"
            self.assertTrue(target in result.generated_paths)
            self.assertEqual((target / "SKILL.md").read_text(encoding="utf-8"), "frontend skill")
            self.assertEqual((target / "references" / "guide.md").read_text(encoding="utf-8"), "guide")
            self.assertTrue((target / SKILL_MANAGED_MARKER).exists())

    def test_generate_removes_unselected_managed_project_skills(self) -> None:
        with workspace_tempdir() as temp_dir:
            project_root = temp_dir / "project"
            skills_root = project_root / PROJECT_SKILLS_RELATIVE_DIR
            old = skills_root / "old"
            old.mkdir(parents=True)
            (old / "SKILL.md").write_text("old", encoding="utf-8")
            (old / SKILL_MANAGED_MARKER).write_text("managed by codex-switch\n", encoding="utf-8")
            manual = skills_root / "manual"
            manual.mkdir()
            (manual / "SKILL.md").write_text("manual", encoding="utf-8")
            service = ProjectTemplateService()
            profile = Profile.create("project", "https://example.com", "sk-template")

            result = service.generate(project_root, profile, skill_sources=[])

            self.assertFalse(old.exists())
            self.assertTrue(manual.exists())
            self.assertEqual(
                (result.backup_dir / PROJECT_SKILLS_RELATIVE_DIR / "old" / "SKILL.md").read_text(encoding="utf-8"),
                "old",
            )

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
            self.assertNotIn("wire_api", provider)
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
            self.assertNotIn("wire_api", provider)
            self.assertEqual(provider["env_key"], PROJECT_ENV_KEY)
            self.assertNotIn("requires_openai_auth", provider)
            self.assertEqual(env_path.read_text(encoding="utf-8"), f"{PROJECT_ENV_KEY}=sk-new-active\nEXTRA=value\n")

    def test_sync_bindings_with_route_proxy_writes_placeholder_values(self) -> None:
        with workspace_tempdir() as temp_dir:
            service = ProjectTemplateService()
            codex_profile = Profile.create("codex", "https://codex.example.com", "sk-codex", codex_model="gpt-real", wire_api="chat_completions")
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
            self.assertNotIn("wire_api", provider)
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
                            CLAUDE_LEGACY_API_KEY_ENV_KEY: "sk-old",
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
                any(key.casefold() == CLAUDE_LEGACY_API_KEY_ENV_KEY.casefold() for key in settings["env"])
            )
            self.assertEqual(settings["env"][CLAUDE_BASE_URL_ENV_KEY], "https://new-claude.example.com/v1")
            self.assertEqual(settings["env"][CLAUDE_API_KEY_ENV_KEY], "sk-active")
            self.assertEqual(settings["env"][CLAUDE_MODEL_ENV_KEY], "sonnet-new")
            self.assertEqual(settings["env"][CLAUDE_FALLBACK_MODEL_ENV_KEY], "haiku-new")

    def test_claude_env_from_profile_uses_active_project_binding_values(self) -> None:
        self.assertEqual(CLAUDE_API_KEY_ENV_KEY, "ANTHROPIC_AUTH_TOKEN")
        self.assertEqual(CLAUDE_AUTH_TOKEN_ENV_KEY, "ANTHROPIC_AUTH_TOKEN")
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
        self.assertFalse(any(key.casefold() == CLAUDE_LEGACY_API_KEY_ENV_KEY.casefold() for key in applied_env))
        self.assertEqual(applied_env[CLAUDE_API_KEY_ENV_KEY], "sk-active")
