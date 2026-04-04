from __future__ import annotations

from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import json
import shutil
import threading
import tomllib
import unittest
import uuid
from unittest.mock import patch

from app_chat import ChatTester
from app_codex_config import CodexConfigManager
from app_health import HealthChecker, build_candidate_urls
from app_models import HealthResult, Profile
from app_storage import ProfileStore


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

            profiles, selected_profile_id = store.load()

            self.assertEqual(selected_profile_id, profile.id)
            self.assertEqual(len(profiles), 1)
            self.assertEqual(profiles[0].name, "主线路")
            self.assertEqual(profiles[0].health.status, "healthy")
            self.assertEqual(profiles[0].manual_health_status, "error")
            self.assertEqual(profiles[0].effective_health_status, "error")


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

    def test_send_message_timeout_returns_error_result(self) -> None:
        tester = ChatTester(timeout=1)
        profile = Profile.create(
            "chat-timeout",
            "https://example.com",
            "sk-chat",
            model="gpt-5.4",
            wire_api="responses",
        )

        with patch("app_chat.request.urlopen", side_effect=TimeoutError):
            result = tester.send_message(profile, "ping")

        self.assertFalse(result.ok)
        self.assertIn("超时", result.text)


if __name__ == "__main__":
    unittest.main()
