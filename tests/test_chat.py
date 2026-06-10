from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import threading
import time
import unittest
from unittest.mock import patch

from helpers import start_test_server

from codex_switch.chat import WIRE_API_ANTHROPIC_MESSAGES, AccountPoolSessionValidator, ChatResult, ChatTester
from codex_switch.models import Profile, VENDOR_CLAUDE


class ChatTesterTests(unittest.TestCase):
    def test_account_pool_session_validator_requires_returned_marker(self) -> None:
        captured: dict[str, str] = {}

        class FakeChatTester:
            def send_message(self, profile, prompt, model_override=None, wire_api_override=None):  # noqa: ANN001
                marker = prompt.rsplit(":", 1)[-1].strip()
                captured["marker"] = marker
                return ChatResult(ok=True, text=f"ok {marker}", endpoint="https://api.example.com/v1/responses", model=model_override)

        profile = Profile.create("pool", "https://api.example.com", "sk-pool", codex_model="gpt-pool")
        result = AccountPoolSessionValidator(FakeChatTester()).check(profile)

        self.assertEqual(result.status, "healthy")
        self.assertEqual(result.models, ["gpt-pool"])
        self.assertIn("codex-switch-", captured["marker"])

    def test_account_pool_session_validator_rejects_missing_marker(self) -> None:
        class FakeChatTester:
            def send_message(self, profile, prompt, model_override=None, wire_api_override=None):  # noqa: ANN001
                return ChatResult(ok=True, text="ok but no marker", endpoint="https://api.example.com/v1/responses", model=model_override)

        profile = Profile.create("pool", "https://api.example.com", "sk-pool")
        result = AccountPoolSessionValidator(FakeChatTester()).check(profile)

        self.assertEqual(result.status, "error")
        self.assertIn("未包含要求返回", result.detail)

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

    def test_send_message_applies_custom_headers_without_overriding_auth(self) -> None:
        captured: dict[str, str | None] = {}

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:  # noqa: N802
                captured["authorization"] = self.headers.get("Authorization")
                captured["beta"] = self.headers.get("OpenAI-Beta")
                captured["user_agent"] = self.headers.get("User-Agent")
                self.rfile.read(int(self.headers.get("Content-Length", "0")))
                body = json.dumps({"output_text": "custom headers ok"}).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, format: str, *args) -> None:  # noqa: A003
                return

        server = start_test_server(Handler)
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)

        profile = Profile.create(
            "headers",
            f"http://127.0.0.1:{server.server_port}",
            "sk-chat",
            custom_headers={
                "OpenAI-Beta": "codex=v1",
                "User-Agent": "codex-cli-test",
                "Authorization": "Bearer leaked",
            },
        )

        result = ChatTester(timeout=5).send_message(profile, "ping")

        self.assertTrue(result.ok)
        self.assertEqual(captured["authorization"], "Bearer sk-chat")
        self.assertEqual(captured["beta"], "codex=v1")
        self.assertEqual(captured["user_agent"], "codex-cli-test")

    def test_send_message_with_chat_completions(self) -> None:
        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:  # noqa: N802
                if self.path != "/v1/chat/completions":
                    self.send_response(404)
                    self.end_headers()
                    return
                self.rfile.read(int(self.headers.get("Content-Length", "0")))
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

    def test_send_message_with_anthropic_messages_api(self) -> None:
        captured: dict[str, object] = {}

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:  # noqa: N802
                captured["path"] = self.path
                captured["x_api_key"] = self.headers.get("x-api-key")
                captured["authorization"] = self.headers.get("Authorization")
                captured["anthropic_version"] = self.headers.get("anthropic-version")
                captured["payload"] = json.loads(self.rfile.read(int(self.headers.get("Content-Length", "0"))))
                body = json.dumps({"content": [{"type": "text", "text": "claude ok"}]}).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, format: str, *args) -> None:  # noqa: A003
                return

        server = start_test_server(Handler)
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)

        tester = ChatTester(timeout=5)
        profile = Profile.create(
            "claude-chat",
            f"http://127.0.0.1:{server.server_port}",
            "sk-claude",
            vendor=VENDOR_CLAUDE,
            claude_model="claude-sonnet",
        )

        result = tester.send_message(profile, "ping")

        self.assertTrue(result.ok)
        self.assertEqual(result.model, "claude-sonnet")
        self.assertEqual(result.text, "claude ok")
        self.assertEqual(result.endpoint, f"http://127.0.0.1:{server.server_port}/v1/messages")
        self.assertEqual(captured["path"], "/v1/messages")
        self.assertEqual(captured["x_api_key"], "sk-claude")
        self.assertIsNone(captured["authorization"])
        self.assertEqual(captured["anthropic_version"], "2023-06-01")
        self.assertEqual(
            captured["payload"],
            {
                "model": "claude-sonnet",
                "messages": [{"role": "user", "content": "ping"}],
                "max_tokens": 512,
            },
        )
        self.assertEqual(
            tester.build_payload_template(WIRE_API_ANTHROPIC_MESSAGES),
            {
                "model": "{{model}}",
                "messages": [{"role": "user", "content": "{{prompt}}"}],
                "max_tokens": 512,
            },
        )

    def test_send_message_returns_full_response_when_responses_text_is_missing(self) -> None:
        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:  # noqa: N802
                self.rfile.read(int(self.headers.get("Content-Length", "0")))
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
                self.rfile.read(int(self.headers.get("Content-Length", "0")))
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
