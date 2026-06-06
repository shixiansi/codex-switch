from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import gzip
import json
import unittest

from helpers import start_test_server

from codex_switch.models import (
    AccountPoolChannel,
    AccountPoolSettings,
    Profile,
    ProjectRecord,
    RouteProxyRule,
    RouteProxySettings,
    ROUTE_PROXY_CLIENT_CLAUDE,
    ROUTE_PROXY_CLIENT_CODEX,
    ROUTE_PROXY_PLACEHOLDER_KEY,
    ROUTE_PROXY_PROTOCOL_ANTHROPIC,
    ROUTE_PROXY_PROTOCOL_ANTHROPIC_TO_OPENAI,
    ROUTE_PROXY_PROTOCOL_OPENAI,
    ROUTE_PROXY_PROTOCOL_OPENAI_CHAT_TO_RESPONSES,
    ROUTE_PROXY_PROTOCOL_OPENAI_RESPONSES_TO_CHAT,
    ROUTE_PROXY_UPSTREAM_SOURCE_ACCOUNT_POOL,
    VENDOR_CLAUDE,
)
from codex_switch.proxy import (
    RouteProxyServer,
    anthropic_to_openai_request,
    openai_chat_to_responses_response,
    openai_chat_to_responses_request,
    openai_responses_to_chat_request,
    openai_to_anthropic_response,
    responses_to_openai_chat_response,
)
from codex_switch.proxy.protocol_matrix import PROTOCOL_TRANSLATIONS, translation_for_protocol
from codex_switch.proxy.translator import iter_openai_chat_sse_to_responses, iter_openai_sse_to_anthropic
from codex_switch.ui.route_proxy_logic import route_proxy_rules_for_project_profiles


class RouteProxyTests(unittest.TestCase):
    def _serve(self, handler_cls: type[BaseHTTPRequestHandler]) -> ThreadingHTTPServer:
        server = start_test_server(handler_cls)
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        return server

    def test_protocol_matrix_selects_conversion_by_protocol_and_endpoint(self) -> None:
        self.assertEqual(
            [item.protocol for item in PROTOCOL_TRANSLATIONS],
            [
                ROUTE_PROXY_PROTOCOL_ANTHROPIC_TO_OPENAI,
                ROUTE_PROXY_PROTOCOL_OPENAI_CHAT_TO_RESPONSES,
                ROUTE_PROXY_PROTOCOL_OPENAI_RESPONSES_TO_CHAT,
            ],
        )
        anthropic = translation_for_protocol(ROUTE_PROXY_PROTOCOL_ANTHROPIC_TO_OPENAI, "/v1/messages?stream=true")
        chat_to_responses = translation_for_protocol(ROUTE_PROXY_PROTOCOL_OPENAI_CHAT_TO_RESPONSES, "/v1/chat/completions")
        responses_to_chat = translation_for_protocol(ROUTE_PROXY_PROTOCOL_OPENAI_RESPONSES_TO_CHAT, "/v1/responses")

        self.assertIsNotNone(anthropic)
        self.assertIsNotNone(chat_to_responses)
        self.assertIsNotNone(responses_to_chat)
        self.assertEqual(anthropic.upstream_endpoint, "/v1/chat/completions")
        self.assertEqual(chat_to_responses.upstream_endpoint, "/v1/responses")
        self.assertEqual(responses_to_chat.upstream_endpoint, "/v1/chat/completions")
        self.assertIsNone(translation_for_protocol(ROUTE_PROXY_PROTOCOL_OPENAI, "/v1/responses"))
        self.assertIsNone(translation_for_protocol(ROUTE_PROXY_PROTOCOL_OPENAI_CHAT_TO_RESPONSES, "/v1/responses"))

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

    def test_openai_passthrough_accepts_responses_without_v1_and_dedupes_base_v1(self) -> None:
        captured: dict[str, str | None] = {}

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:  # noqa: N802
                captured["path"] = self.path
                captured["authorization"] = self.headers.get("Authorization")
                self.rfile.read(int(self.headers.get("Content-Length", "0")))
                body = json.dumps({"id": "resp_1", "output_text": "ok"}).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, format: str, *args) -> None:  # noqa: A003
                return

        upstream = self._serve(Handler)
        profile = Profile.create("upstream", f"http://127.0.0.1:{upstream.server_port}/v1", "sk-upstream")
        settings = RouteProxySettings(
            rules=[
                RouteProxyRule.create(
                    project_id="project-1",
                    client_type=ROUTE_PROXY_CLIENT_CODEX,
                    primary_profile_id=profile.id,
                )
            ]
        )
        proxy = RouteProxyServer(lambda: settings, lambda: [profile])
        request_body = json.dumps({"model": "gpt-5"}).encode("utf-8")

        status, _headers, body, chunks = proxy.handle(
            method="POST",
            raw_path="/project/project-1/responses",
            headers={"Authorization": "Bearer placeholder"},
            body=request_body,
        )

        self.assertEqual(status, 200)
        self.assertIsNone(chunks)
        self.assertIn("resp_1", body.decode("utf-8") if body else "")
        self.assertEqual(captured["path"], "/v1/responses")
        self.assertEqual(captured["authorization"], "Bearer sk-upstream")

    def test_openai_passthrough_accepts_compact_path_and_overrides_compact_model(self) -> None:
        captured: dict[str, object] = {}

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:  # noqa: N802
                captured["path"] = self.path
                captured["authorization"] = self.headers.get("Authorization")
                captured["payload"] = json.loads(self.rfile.read(int(self.headers.get("Content-Length", "0"))))
                body = json.dumps({"id": "compact_1", "model": captured["payload"]["model"]}).encode("utf-8")
                self.send_response(200 if self.path == "/v1/responses/compact" else 404)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, format: str, *args) -> None:  # noqa: A003
                return

        upstream = self._serve(Handler)
        profile = Profile.create("upstream", f"http://127.0.0.1:{upstream.server_port}/v1", "sk-upstream")
        settings = RouteProxySettings(
            rules=[
                RouteProxyRule.create(
                    project_id="project-1",
                    client_type=ROUTE_PROXY_CLIENT_CODEX,
                    primary_profile_id=profile.id,
                    compact_model="gpt-4.1-compact",
                )
            ]
        )
        proxy = RouteProxyServer(lambda: settings, lambda: [profile])
        request_body = json.dumps({"model": "gpt-5.5-openai-compact", "input": "history"}).encode("utf-8")

        status, _headers, body, chunks = proxy.handle(
            method="POST",
            raw_path="/project/project-1/v1/responses/compact",
            headers={"Authorization": "Bearer placeholder"},
            body=request_body,
        )

        response_payload = json.loads(body.decode("utf-8") if body else "{}")
        self.assertEqual(status, 200)
        self.assertIsNone(chunks)
        self.assertEqual(captured["path"], "/v1/responses/compact")
        self.assertEqual(captured["authorization"], "Bearer sk-upstream")
        self.assertEqual(captured["payload"]["model"], "gpt-4.1-compact")
        self.assertEqual(response_payload["model"], "gpt-4.1-compact")

    def test_openai_passthrough_compact_model_does_not_affect_regular_responses(self) -> None:
        captured: dict[str, object] = {}

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:  # noqa: N802
                captured["path"] = self.path
                captured["payload"] = json.loads(self.rfile.read(int(self.headers.get("Content-Length", "0"))))
                body = json.dumps({"id": "resp_1", "model": captured["payload"]["model"]}).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, format: str, *args) -> None:  # noqa: A003
                return

        upstream = self._serve(Handler)
        profile = Profile.create("upstream", f"http://127.0.0.1:{upstream.server_port}/v1", "sk-upstream")
        settings = RouteProxySettings(
            rules=[
                RouteProxyRule.create(
                    project_id="project-1",
                    client_type=ROUTE_PROXY_CLIENT_CODEX,
                    primary_profile_id=profile.id,
                    compact_model="gpt-4.1-compact",
                )
            ]
        )
        proxy = RouteProxyServer(lambda: settings, lambda: [profile])
        request_body = json.dumps({"model": "gpt-5", "input": "hello"}).encode("utf-8")

        status, _headers, body, chunks = proxy.handle(
            method="POST",
            raw_path="/project/project-1/responses",
            headers={"Authorization": "Bearer placeholder"},
            body=request_body,
        )

        response_payload = json.loads(body.decode("utf-8") if body else "{}")
        self.assertEqual(status, 200)
        self.assertIsNone(chunks)
        self.assertEqual(captured["path"], "/v1/responses")
        self.assertEqual(captured["payload"]["model"], "gpt-5")
        self.assertEqual(response_payload["model"], "gpt-5")

    def test_openai_proxy_error_includes_rendered_upstream_url(self) -> None:
        profile = Profile.create("closed", "http://127.0.0.1:1/root", "sk-closed")
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
        request_body = json.dumps({"model": "gpt-5", "input": "hi"}).encode("utf-8")

        status, _headers, body, chunks = proxy.handle(
            method="POST",
            raw_path="/project/project-1/responses?stream=true",
            headers={},
            body=request_body,
        )

        error_text = json.loads(body.decode("utf-8") if body else "{}")["error"]
        expected_url = "upstream: http://127.0.0.1:1/root/v1/responses?stream=true"
        self.assertEqual(status, 502)
        self.assertIsNone(chunks)
        self.assertIn(expected_url, error_text)
        self.assertIn(expected_url, events[-1].message)

    def test_account_pool_round_robin_is_shared_across_projects_and_skips_failed_channels(self) -> None:
        def handler_for(label: str):
            class Handler(BaseHTTPRequestHandler):
                def do_POST(self) -> None:  # noqa: N802
                    self.rfile.read(int(self.headers.get("Content-Length", "0")))
                    body = json.dumps({"label": label}).encode("utf-8")
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)

                def log_message(self, format: str, *args) -> None:  # noqa: A003
                    return

            return Handler

        upstream_a = self._serve(handler_for("a"))
        upstream_b = self._serve(handler_for("b"))
        channel_a = AccountPoolChannel.create(name="pool-a", base_url=f"http://127.0.0.1:{upstream_a.server_port}", api_key="sk-a")
        channel_b = AccountPoolChannel.create(name="pool-b", base_url=f"http://127.0.0.1:{upstream_b.server_port}", api_key="sk-b")
        pool = AccountPoolSettings(enabled=True, channels=[channel_a, channel_b])
        settings = RouteProxySettings(
            rules=[
                RouteProxyRule.create(
                    project_id="project-1",
                    client_type=ROUTE_PROXY_CLIENT_CODEX,
                    primary_profile_id="profile-1",
                    upstream_source=ROUTE_PROXY_UPSTREAM_SOURCE_ACCOUNT_POOL,
                ),
                RouteProxyRule.create(
                    project_id="project-2",
                    client_type=ROUTE_PROXY_CLIENT_CODEX,
                    primary_profile_id="profile-2",
                    upstream_source=ROUTE_PROXY_UPSTREAM_SOURCE_ACCOUNT_POOL,
                ),
            ]
        )
        proxy = RouteProxyServer(lambda: settings, lambda: [], account_pool_provider=lambda: pool)
        request_body = json.dumps({"model": "gpt-5", "input": "hi"}).encode("utf-8")

        first = proxy.handle(method="POST", raw_path="/project/project-1/responses", headers={}, body=request_body)
        second = proxy.handle(method="POST", raw_path="/project/project-2/responses", headers={}, body=request_body)
        pool.mark_failed(channel_a.id, "manual")
        third = proxy.handle(method="POST", raw_path="/project/project-1/responses", headers={}, body=request_body)

        self.assertEqual(json.loads(first[2].decode("utf-8"))["label"], "a")
        self.assertEqual(json.loads(second[2].decode("utf-8"))["label"], "b")
        self.assertEqual(json.loads(third[2].decode("utf-8"))["label"], "b")

    def test_account_pool_marks_unavailable_channel_and_skips_it_later(self) -> None:
        counts = {"bad": 0, "good": 0}

        class BadHandler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:  # noqa: N802
                counts["bad"] += 1
                self.rfile.read(int(self.headers.get("Content-Length", "0")))
                body = b'{"error":"down"}'
                self.send_response(503)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, format: str, *args) -> None:  # noqa: A003
                return

        class GoodHandler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:  # noqa: N802
                counts["good"] += 1
                self.rfile.read(int(self.headers.get("Content-Length", "0")))
                body = json.dumps({"ok": counts["good"]}).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, format: str, *args) -> None:  # noqa: A003
                return

        bad = self._serve(BadHandler)
        good = self._serve(GoodHandler)
        bad_channel = AccountPoolChannel.create(name="bad", base_url=f"http://127.0.0.1:{bad.server_port}", api_key="sk-bad")
        good_channel = AccountPoolChannel.create(name="good", base_url=f"http://127.0.0.1:{good.server_port}", api_key="sk-good")
        pool = AccountPoolSettings(
            enabled=True,
            channels=[bad_channel, good_channel],
            last_recovery_checked_at="2999-01-01T00:00:00",
        )
        settings = RouteProxySettings(
            rules=[
                RouteProxyRule.create(
                    project_id="project-1",
                    client_type=ROUTE_PROXY_CLIENT_CODEX,
                    primary_profile_id="profile-1",
                    upstream_source=ROUTE_PROXY_UPSTREAM_SOURCE_ACCOUNT_POOL,
                )
            ]
        )
        proxy = RouteProxyServer(lambda: settings, lambda: [], account_pool_provider=lambda: pool)
        request_body = json.dumps({"model": "gpt-5", "input": "hi"}).encode("utf-8")

        first = proxy.handle(method="POST", raw_path="/project/project-1/responses", headers={}, body=request_body)
        second = proxy.handle(method="POST", raw_path="/project/project-1/responses", headers={}, body=request_body)

        self.assertEqual(first[0], 200)
        self.assertEqual(second[0], 200)
        self.assertEqual(counts, {"bad": 1, "good": 2})
        self.assertFalse(bad_channel.is_normal)
        self.assertIn("HTTP 503", bad_channel.failure_reason)

    def test_account_pool_recovery_checks_failed_channels_after_interval(self) -> None:
        class RecoveredHandler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802
                body = json.dumps({"data": [{"id": "gpt-recovered"}]}).encode("utf-8")
                self.send_response(200 if self.path == "/v1/models" else 404)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_POST(self) -> None:  # noqa: N802
                self.rfile.read(int(self.headers.get("Content-Length", "0")))
                body = json.dumps({"ok": True}).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, format: str, *args) -> None:  # noqa: A003
                return

        class StillFailedHandler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802
                self.send_response(401)
                self.end_headers()

            def log_message(self, format: str, *args) -> None:  # noqa: A003
                return

        recovered = self._serve(RecoveredHandler)
        failed = self._serve(StillFailedHandler)
        recovered_channel = AccountPoolChannel.create(name="recovered", base_url=f"http://127.0.0.1:{recovered.server_port}", api_key="sk-ok")
        failed_channel = AccountPoolChannel.create(name="failed", base_url=f"http://127.0.0.1:{failed.server_port}", api_key="sk-bad")
        pool = AccountPoolSettings(
            enabled=True,
            channels=[recovered_channel, failed_channel],
            last_recovery_checked_at="2000-01-01T00:00:00",
        )
        pool.mark_failed(recovered_channel.id, "old")
        pool.mark_failed(failed_channel.id, "old")
        pool.last_recovery_checked_at = "2000-01-01T00:00:00"
        settings = RouteProxySettings(
            rules=[
                RouteProxyRule.create(
                    project_id="project-1",
                    client_type=ROUTE_PROXY_CLIENT_CODEX,
                    primary_profile_id="profile-1",
                    upstream_source=ROUTE_PROXY_UPSTREAM_SOURCE_ACCOUNT_POOL,
                )
            ]
        )
        proxy = RouteProxyServer(lambda: settings, lambda: [], account_pool_provider=lambda: pool)
        request_body = json.dumps({"model": "gpt-5", "input": "hi"}).encode("utf-8")

        status, _headers, _body, _chunks = proxy.handle(
            method="POST",
            raw_path="/project/project-1/responses",
            headers={},
            body=request_body,
        )

        self.assertEqual(status, 200)
        self.assertTrue(recovered_channel.is_normal)
        self.assertFalse(failed_channel.is_normal)
        self.assertIn("鉴权失败", failed_channel.failure_reason)
        self.assertNotEqual(pool.last_recovery_checked_at, "2000-01-01T00:00:00")

    def test_route_proxy_injects_project_headers(self) -> None:
        captured: dict[str, str | None] = {}

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:  # noqa: N802
                captured["project_id"] = self.headers.get("X-Codex-Switch-Project-Id")
                captured["project_name"] = self.headers.get("X-Codex-Switch-Project-Name")
                self.rfile.read(int(self.headers.get("Content-Length", "0")))
                body = b'{"id":"resp_1"}'
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, format: str, *args) -> None:  # noqa: A003
                return

        upstream = self._serve(Handler)
        project = ProjectRecord.create("project-root", "profile-id", name="Header Project")
        project.id = "project-1"
        profile = Profile.create("upstream", f"http://127.0.0.1:{upstream.server_port}", "sk-upstream")
        settings = RouteProxySettings(
            rules=[
                RouteProxyRule.create(
                    project_id=project.id,
                    client_type=ROUTE_PROXY_CLIENT_CODEX,
                    primary_profile_id=profile.id,
                )
            ]
        )
        proxy = RouteProxyServer(lambda: settings, lambda: [profile], project_provider=lambda: [project])
        request_body = json.dumps({"model": "gpt-5"}).encode("utf-8")

        proxy.handle(method="POST", raw_path="/project/project-1/responses", headers={}, body=request_body)

        self.assertEqual(captured["project_id"], "project-1")
        self.assertEqual(captured["project_name"], "Header Project")

    def test_route_proxy_percent_encodes_non_latin_project_header(self) -> None:
        captured: dict[str, str | None] = {}

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:  # noqa: N802
                captured["project_name"] = self.headers.get("X-Codex-Switch-Project-Name")
                self.rfile.read(int(self.headers.get("Content-Length", "0")))
                body = b'{"id":"resp_1"}'
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, format: str, *args) -> None:  # noqa: A003
                return

        upstream = self._serve(Handler)
        project = ProjectRecord.create("project-root", "profile-id", name="冰")
        project.id = "project-cn"
        profile = Profile.create("upstream", f"http://127.0.0.1:{upstream.server_port}", "sk-upstream")
        settings = RouteProxySettings(
            rules=[
                RouteProxyRule.create(
                    project_id=project.id,
                    client_type=ROUTE_PROXY_CLIENT_CODEX,
                    primary_profile_id=profile.id,
                )
            ]
        )
        proxy = RouteProxyServer(lambda: settings, lambda: [profile], project_provider=lambda: [project])
        request_body = json.dumps({"model": "gpt-5"}).encode("utf-8")

        status, _headers, _body, chunks = proxy.handle(
            method="POST",
            raw_path="/project/project-cn/responses",
            headers={},
            body=request_body,
        )

        self.assertEqual(status, 200)
        self.assertIsNone(chunks)
        self.assertEqual(captured["project_name"], "%E5%86%B0")

    def test_openai_chat_to_responses_converts_request_and_response(self) -> None:
        converted = openai_chat_to_responses_request(
            {
                "model": "chat-model",
                "messages": [
                    {"role": "system", "content": "be helpful"},
                    {"role": "user", "content": "hello"},
                ],
                "max_tokens": 32,
                "tool_choice": {"type": "function", "function": {"name": "lookup"}},
                "tools": [
                    {
                        "type": "function",
                        "function": {
                            "name": "lookup",
                            "description": "Lookup data",
                            "parameters": {"type": "object"},
                        },
                    }
                ],
            },
            "responses-model",
        )

        self.assertEqual(converted["model"], "responses-model")
        self.assertEqual(converted["instructions"], "be helpful")
        self.assertEqual(converted["input"], [{"role": "user", "content": "hello"}])
        self.assertEqual(converted["max_output_tokens"], 32)
        self.assertEqual(converted["tools"][0]["name"], "lookup")
        self.assertEqual(converted["tool_choice"], {"type": "function", "name": "lookup"})

        chat = responses_to_openai_chat_response(
            {
                "id": "resp_1",
                "model": "responses-model",
                "output": [
                    {
                        "type": "message",
                        "content": [{"type": "output_text", "text": "hello back"}],
                    }
                ],
                "usage": {"input_tokens": 4, "output_tokens": 5},
            },
            "chat-model",
        )

        self.assertEqual(chat["object"], "chat.completion")
        self.assertEqual(chat["model"], "chat-model")
        self.assertEqual(chat["choices"][0]["message"]["content"], "hello back")
        self.assertEqual(chat["usage"]["prompt_tokens"], 4)
        self.assertEqual(chat["usage"]["completion_tokens"], 5)

    def test_openai_chat_to_responses_route_converts_request_and_response(self) -> None:
        captured: dict[str, object] = {}

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:  # noqa: N802
                captured["path"] = self.path
                captured["authorization"] = self.headers.get("Authorization")
                captured["payload"] = json.loads(self.rfile.read(int(self.headers.get("Content-Length", "0"))))
                body = json.dumps(
                    {
                        "id": "resp_1",
                        "model": "responses-model",
                        "output_text": "responses ok",
                        "usage": {"input_tokens": 2, "output_tokens": 3},
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
        profile = Profile.create("responses", f"http://127.0.0.1:{upstream.server_port}", "sk-responses", codex_model="responses-model")
        settings = RouteProxySettings(
            rules=[
                RouteProxyRule.create(
                    project_id="project-1",
                    client_type=ROUTE_PROXY_CLIENT_CODEX,
                    primary_profile_id=profile.id,
                    upstream_protocol=ROUTE_PROXY_PROTOCOL_OPENAI_CHAT_TO_RESPONSES,
                    upstream_model="responses-model",
                )
            ]
        )
        proxy = RouteProxyServer(lambda: settings, lambda: [profile])
        request_body = json.dumps(
            {
                "model": "chat-model",
                "messages": [{"role": "user", "content": "hello"}],
                "max_tokens": 64,
            }
        ).encode("utf-8")

        status, headers, body, chunks = proxy.handle(
            method="POST",
            raw_path="/project/project-1/v1/chat/completions",
            headers={"Authorization": "Bearer placeholder"},
            body=request_body,
        )

        response_payload = json.loads(body.decode("utf-8") if body else "{}")
        self.assertEqual(status, 200)
        self.assertIsNone(chunks)
        self.assertEqual(headers["content-type"], "application/json")
        self.assertEqual(captured["path"], "/v1/responses")
        self.assertEqual(captured["authorization"], "Bearer sk-responses")
        self.assertEqual(captured["payload"]["model"], "responses-model")
        self.assertEqual(captured["payload"]["input"], [{"role": "user", "content": "hello"}])
        self.assertEqual(captured["payload"]["max_output_tokens"], 64)
        self.assertEqual(response_payload["choices"][0]["message"]["content"], "responses ok")
        self.assertEqual(response_payload["usage"]["completion_tokens"], 3)

    def test_openai_chat_to_responses_route_accepts_chat_path_without_v1(self) -> None:
        captured: dict[str, object] = {}

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:  # noqa: N802
                captured["path"] = self.path
                captured["payload"] = json.loads(self.rfile.read(int(self.headers.get("Content-Length", "0"))))
                body = json.dumps({"id": "resp_1", "output_text": "alias ok"}).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, format: str, *args) -> None:  # noqa: A003
                return

        upstream = self._serve(Handler)
        profile = Profile.create("responses", f"http://127.0.0.1:{upstream.server_port}", "sk-responses", codex_model="responses-model")
        settings = RouteProxySettings(
            rules=[
                RouteProxyRule.create(
                    project_id="project-1",
                    client_type=ROUTE_PROXY_CLIENT_CODEX,
                    primary_profile_id=profile.id,
                    upstream_protocol=ROUTE_PROXY_PROTOCOL_OPENAI_CHAT_TO_RESPONSES,
                    upstream_model="responses-model",
                )
            ]
        )
        proxy = RouteProxyServer(lambda: settings, lambda: [profile])
        request_body = json.dumps({"model": "chat-model", "messages": [{"role": "user", "content": "hello"}]}).encode("utf-8")

        status, _headers, body, chunks = proxy.handle(
            method="POST",
            raw_path="/project/project-1/chat/completions",
            headers={"Authorization": "Bearer placeholder"},
            body=request_body,
        )

        response_payload = json.loads(body.decode("utf-8") if body else "{}")
        self.assertEqual(status, 200)
        self.assertIsNone(chunks)
        self.assertEqual(captured["path"], "/v1/responses")
        self.assertEqual(captured["payload"]["model"], "responses-model")
        self.assertEqual(response_payload["choices"][0]["message"]["content"], "alias ok")

    def test_openai_responses_to_chat_converts_request_and_response(self) -> None:
        converted = openai_responses_to_chat_request(
            {
                "model": "responses-model",
                "instructions": "be helpful",
                "input": [{"role": "user", "content": [{"type": "input_text", "text": "hello"}]}],
                "max_output_tokens": 32,
                "tool_choice": {"type": "function", "name": "lookup"},
                "tools": [
                    {
                        "type": "function",
                        "name": "lookup",
                        "description": "Lookup data",
                        "parameters": {"type": "object"},
                    }
                ],
            },
            "chat-model",
        )

        self.assertEqual(converted["model"], "chat-model")
        self.assertEqual(converted["messages"][0], {"role": "system", "content": "be helpful"})
        self.assertEqual(converted["messages"][1], {"role": "user", "content": "hello"})
        self.assertEqual(converted["max_tokens"], 32)
        self.assertEqual(converted["tools"][0]["function"]["name"], "lookup")
        self.assertEqual(converted["tool_choice"], {"type": "function", "function": {"name": "lookup"}})

        responses = openai_chat_to_responses_response(
            {
                "id": "chatcmpl_1",
                "model": "chat-model",
                "choices": [{"finish_reason": "stop", "message": {"content": "hello back"}}],
                "usage": {"prompt_tokens": 4, "completion_tokens": 5},
            },
            "responses-model",
        )

        self.assertEqual(responses["object"], "response")
        self.assertEqual(responses["model"], "responses-model")
        self.assertEqual(responses["output_text"], "hello back")
        self.assertEqual(responses["output"][0]["content"][0]["text"], "hello back")
        self.assertEqual(responses["usage"]["input_tokens"], 4)
        self.assertEqual(responses["usage"]["output_tokens"], 5)

    def test_openai_responses_to_chat_route_converts_request_and_response(self) -> None:
        captured: dict[str, object] = {}

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:  # noqa: N802
                captured["path"] = self.path
                captured["authorization"] = self.headers.get("Authorization")
                captured["payload"] = json.loads(self.rfile.read(int(self.headers.get("Content-Length", "0"))))
                body = json.dumps(
                    {
                        "id": "chatcmpl_1",
                        "model": "chat-model",
                        "choices": [{"finish_reason": "stop", "message": {"content": "chat ok"}}],
                        "usage": {"prompt_tokens": 2, "completion_tokens": 3},
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
        profile = Profile.create("chat", f"http://127.0.0.1:{upstream.server_port}", "sk-chat", codex_model="chat-model")
        settings = RouteProxySettings(
            rules=[
                RouteProxyRule.create(
                    project_id="project-1",
                    client_type=ROUTE_PROXY_CLIENT_CODEX,
                    primary_profile_id=profile.id,
                    upstream_protocol=ROUTE_PROXY_PROTOCOL_OPENAI_RESPONSES_TO_CHAT,
                    upstream_model="chat-model",
                )
            ]
        )
        proxy = RouteProxyServer(lambda: settings, lambda: [profile])
        request_body = json.dumps({"model": "responses-model", "input": "hello", "max_output_tokens": 64}).encode("utf-8")

        status, headers, body, chunks = proxy.handle(
            method="POST",
            raw_path="/project/project-1/responses",
            headers={"Authorization": "Bearer placeholder"},
            body=request_body,
        )

        response_payload = json.loads(body.decode("utf-8") if body else "{}")
        self.assertEqual(status, 200)
        self.assertIsNone(chunks)
        self.assertEqual(headers["content-type"], "application/json")
        self.assertEqual(captured["path"], "/v1/chat/completions")
        self.assertEqual(captured["authorization"], "Bearer sk-chat")
        self.assertEqual(captured["payload"]["model"], "chat-model")
        self.assertEqual(captured["payload"]["messages"], [{"role": "user", "content": "hello"}])
        self.assertEqual(captured["payload"]["max_tokens"], 64)
        self.assertEqual(response_payload["output_text"], "chat ok")
        self.assertEqual(response_payload["usage"]["output_tokens"], 3)

    def test_chat_only_upstream_with_v1_base_accepts_responses_client_route(self) -> None:
        captured: dict[str, object] = {}

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:  # noqa: N802
                captured["path"] = self.path
                captured["payload"] = json.loads(self.rfile.read(int(self.headers.get("Content-Length", "0"))))
                body = json.dumps(
                    {
                        "id": "chatcmpl_1",
                        "model": "chat-model",
                        "choices": [{"finish_reason": "stop", "message": {"content": "chat ok"}}],
                    }
                ).encode("utf-8")
                self.send_response(200 if self.path == "/v1/chat/completions" else 404)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, format: str, *args) -> None:  # noqa: A003
                return

        upstream = self._serve(Handler)
        project = ProjectRecord.create("project-root", "profile-id")
        profile = Profile.create(
            "zero-bug",
            f"http://127.0.0.1:{upstream.server_port}/v1",
            "sk-zero",
            codex_model="chat-model",
            wire_api="chat_completions",
        )
        profile.id = "profile-id"
        claude_profile = Profile.create("claude", "https://claude.example.com", "sk-claude", vendor=VENDOR_CLAUDE)
        settings = RouteProxySettings(rules=route_proxy_rules_for_project_profiles(project, profile, claude_profile))
        proxy = RouteProxyServer(lambda: settings, lambda: [profile, claude_profile])
        request_body = json.dumps({"model": "responses-model", "input": "hello"}).encode("utf-8")

        status, headers, body, chunks = proxy.handle(
            method="POST",
            raw_path=f"/project/{project.id}/responses",
            headers={"Authorization": "Bearer placeholder"},
            body=request_body,
        )

        response_payload = json.loads(body.decode("utf-8") if body else "{}")
        self.assertEqual(status, 200)
        self.assertIsNone(chunks)
        self.assertEqual(headers["content-type"], "application/json")
        self.assertEqual(captured["path"], "/v1/chat/completions")
        self.assertEqual(captured["payload"]["model"], "chat-model")
        self.assertEqual(captured["payload"]["messages"], [{"role": "user", "content": "hello"}])
        self.assertEqual(response_payload["output_text"], "chat ok")

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

        self.assertEqual(status, 200)
        self.assertIsNone(body)
        self.assertEqual(headers["content-type"], "text/event-stream")
        self.assertIsNotNone(chunks)
        self.assertNotIsInstance(chunks, list)
        rendered = b"".join(chunks or []).decode("utf-8")
        self.assertIn("event: message_start", rendered)
        self.assertIn("\"text\": \"stream \"", rendered)
        self.assertIn("\"text\": \"ok\"", rendered)
        self.assertIn("event: message_stop", rendered)

    def test_openai_passthrough_streaming_response_is_returned_lazy(self) -> None:
        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:  # noqa: N802
                self.rfile.read(int(self.headers.get("Content-Length", "0")))
                body = b"data: {\"type\":\"response.output_text.delta\",\"delta\":\"ok\"}\n\ndata: [DONE]\n\n"
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, format: str, *args) -> None:  # noqa: A003
                return

        upstream = self._serve(Handler)
        profile = Profile.create("openai", f"http://127.0.0.1:{upstream.server_port}", "sk-openai")
        settings = RouteProxySettings(
            rules=[
                RouteProxyRule.create(
                    project_id="project-1",
                    client_type=ROUTE_PROXY_CLIENT_CODEX,
                    primary_profile_id=profile.id,
                    upstream_protocol=ROUTE_PROXY_PROTOCOL_OPENAI,
                )
            ]
        )
        proxy = RouteProxyServer(lambda: settings, lambda: [profile])
        request_body = json.dumps({"model": "gpt-5", "input": "hi", "stream": True}).encode("utf-8")

        status, headers, body, chunks = proxy.handle(
            method="POST",
            raw_path="/project/project-1/responses",
            headers={},
            body=request_body,
        )

        self.assertEqual(status, 200)
        self.assertIsNone(body)
        self.assertEqual(headers["content-type"], "text/event-stream")
        self.assertIsNotNone(chunks)
        self.assertNotIsInstance(chunks, list)
        rendered = b"".join(chunks or []).decode("utf-8")
        self.assertIn("\"delta\":\"ok\"", rendered)
        self.assertIn("data: [DONE]", rendered)

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

    def test_openai_chat_sse_chunks_convert_to_responses_events(self) -> None:
        rendered = b"".join(
            iter_openai_chat_sse_to_responses(
                [
                    b'data: {"choices":[{"delta":{"content":"hel"}}]}\n\n',
                    b'data: {"choices":[{"delta":{"content":"lo"}}]}\n\n',
                    b"data: [DONE]\n\n",
                ],
                "responses-model",
            )
        ).decode("utf-8")

        self.assertIn("event: response.created", rendered)
        self.assertIn("event: response.output_text.delta", rendered)
        self.assertIn('"delta": "hel"', rendered)
        self.assertIn('"delta": "lo"', rendered)
        self.assertIn("event: response.completed", rendered)

    def test_openai_chat_sse_tool_calls_convert_to_responses_events(self) -> None:
        rendered = b"".join(
            iter_openai_chat_sse_to_responses(
                [
                    (
                        b'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"id":"call_1",'
                        b'"type":"function","function":{"name":"read_file","arguments":"{\\"path\\": "}}]}}]}\n\n'
                    ),
                    b'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"function":{"arguments":"\\"README.md\\"}"}}]}}]}\n\n',
                    b"data: [DONE]\n\n",
                ],
                "responses-model",
            )
        ).decode("utf-8")
        payloads = []
        for block in rendered.strip().split("\n\n"):
            for line in block.splitlines():
                if line.startswith("data: "):
                    payloads.append(json.loads(line[6:]))

        completed = next(payload for payload in payloads if payload.get("type") == "response.completed")
        output = completed["response"]["output"]

        self.assertIn("event: response.function_call_arguments.delta", rendered)
        self.assertIn("event: response.function_call_arguments.done", rendered)
        self.assertEqual(len(output), 1)
        self.assertEqual(output[0]["type"], "function_call")
        self.assertEqual(output[0]["call_id"], "call_1")
        self.assertEqual(output[0]["name"], "read_file")
        self.assertEqual(output[0]["arguments"], '{"path": "README.md"}')
