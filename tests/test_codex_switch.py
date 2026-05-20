from __future__ import annotations

from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
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
from codex_switch.codex_config import CodexConfigManager, scope_mcp_servers_to_project
from codex_switch.health import HealthChecker, build_candidate_urls
from codex_switch.models import HealthResult, Profile
from codex_switch.project_template import (
    CODEX_SCRIPT_DIRNAME,
    GITIGNORE_MANAGED_BEGIN,
    GITIGNORE_MANAGED_END,
    ProjectTemplateService,
)
from codex_switch.storage import ProfileStore
from codex_switch.ui.app import (
    ModelBatchCache,
    ModelBatchResult,
    model_batch_targets,
    ordered_model_batch_models,
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
            ) = store.load()

            self.assertEqual(selected_profile_id, profile.id)
            self.assertEqual(len(profiles), 1)
            self.assertEqual(profiles[0].name, "主线路")
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

    def test_store_persists_agents_doc_text(self) -> None:
        with workspace_tempdir() as temp_dir:
            store = ProfileStore(temp_dir)
            store.save([], None, agents_doc_text="Custom AGENTS text")

            loaded = store.load()
            self.assertEqual(loaded[8], "Custom AGENTS text")

            payload = json.loads(store.storage_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["version"], 4)
            self.assertEqual(payload["settings"]["agents_doc_text"], "Custom AGENTS text")


class UiFilterTests(unittest.TestCase):
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
        results: list[tuple[str, str, str]] = []

        run_model_batch_requests(
            tester,
            profile,
            models,
            "responses",
            None,
            started.append,
            lambda model, status, detail: results.append((model, status, detail)),
        )

        self.assertEqual(set(started), set(models))
        self.assertEqual({model for model, _, _ in results}, set(models))
        self.assertTrue(all(status == "success" for _, status, _ in results))
        self.assertEqual(tester.max_active, 3)


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
            self.assertEqual(auth_data["OPENAI_API_KEY"], "sk-123456")

            current = manager.read_current_config()
            self.assertEqual(current.base_url, "https://gateway.example.com")
            self.assertEqual(current.api_key, "sk-123456")

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
            profile = Profile.create("项目模板", "https://gateway.example.com", "sk-template")

            result = service.generate(temp_dir, profile)

            script_dir = temp_dir / CODEX_SCRIPT_DIRNAME
            self.assertEqual(result.start_script_path, script_dir / "start-codex.ps1")
            self.assertTrue((script_dir / "start-codex.ps1").exists())
            self.assertTrue((script_dir / "start-codex.cmd").exists())
            self.assertTrue((script_dir / "codex-profile.cmd").exists())
            self.assertTrue((temp_dir / ".codex" / "home" / "AGENTS.md").exists())

            gitignore_text = (temp_dir / ".gitignore").read_text(encoding="utf-8")
            self.assertIn("node_modules/", gitignore_text)
            self.assertIn(GITIGNORE_MANAGED_BEGIN, gitignore_text)
            self.assertIn(f"{CODEX_SCRIPT_DIRNAME}/", gitignore_text)
            self.assertIn(GITIGNORE_MANAGED_END, gitignore_text)

            backup_gitignore = result.backup_dir / ".gitignore"
            self.assertTrue(backup_gitignore.exists())
            self.assertEqual(backup_gitignore.read_text(encoding="utf-8"), "node_modules/\n")

            status = service.inspect(temp_dir)
            self.assertEqual(status.start_script_path, script_dir / "start-codex.ps1")
            self.assertIn(temp_dir / ".gitignore", status.generated_paths)
            self.assertIn(temp_dir / ".codex" / "home" / "AGENTS.md", status.generated_paths)

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

        profile = Profile.create("本地", f"http://127.0.0.1:{server.server_port}", "sk-ok")
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
            "sk-chat",
            model="gpt-5.4",
            wire_api="responses",
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
