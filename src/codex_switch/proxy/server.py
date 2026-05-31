from __future__ import annotations

from collections.abc import Callable
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib import parse
import gzip
import http.client
import json
import threading
import zlib

from codex_switch.models import (
    Profile,
    RouteProxyEvent,
    RouteProxyRule,
    RouteProxySettings,
    ROUTE_PROXY_CLIENT_CLAUDE,
    ROUTE_PROXY_CLIENT_CODEX,
    ROUTE_PROXY_PROTOCOL_ANTHROPIC,
    ROUTE_PROXY_PROTOCOL_ANTHROPIC_TO_OPENAI,
    ROUTE_PROXY_PROTOCOL_OPENAI,
    ROUTE_PROXY_PROTOCOL_OPENAI_CHAT_TO_RESPONSES,
)
from codex_switch.proxy.sanitize import sanitize_text
from codex_switch.proxy.translator import (
    TranslationError,
    anthropic_to_openai_request,
    iter_openai_sse_to_anthropic,
    iter_responses_sse_to_openai_chat,
    openai_chat_to_responses_request,
    openai_to_anthropic_response,
    responses_to_openai_chat_response,
)


HOP_BY_HOP_HEADERS = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailer",
    "transfer-encoding",
    "upgrade",
    "host",
    "content-length",
}
AUTH_HEADERS = {
    "authorization",
    "x-api-key",
    "api-key",
    "anthropic-api-key",
}


class RouteProxyServer:
    def __init__(
        self,
        settings_provider: Callable[[], RouteProxySettings],
        profiles_provider: Callable[[], list[Profile]],
        event_callback: Callable[[RouteProxyEvent], None] | None = None,
    ) -> None:
        self.settings_provider = settings_provider
        self.profiles_provider = profiles_provider
        self.event_callback = event_callback
        self._httpd: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        if self.is_running:
            return
        settings = self.settings_provider()
        server = _ProxyHTTPServer((settings.host, settings.port), _RouteProxyHandler)
        server.route_proxy = self
        self._httpd = server
        self._thread = threading.Thread(target=server.serve_forever, daemon=True)
        self._thread.start()
        self._record("info", f"Proxy listening at {settings.base_url}")

    def stop(self) -> None:
        if self._httpd is None:
            return
        self._httpd.shutdown()
        self._httpd.server_close()
        self._httpd = None
        self._thread = None
        self._record("info", "Proxy stopped")

    def handle(
        self,
        *,
        method: str,
        raw_path: str,
        headers: dict[str, str],
        body: bytes,
    ) -> tuple[int, dict[str, str], bytes | None, list[bytes] | None]:
        project_id, upstream_path = self._split_project_path(raw_path)
        if not project_id:
            return self._json_response(HTTPStatus.NOT_FOUND, {"error": "Missing /project/<id> proxy prefix."})
        client_type = self._detect_client_type(upstream_path)
        if client_type is None:
            return self._json_response(HTTPStatus.NOT_FOUND, {"error": f"Unsupported proxy path: {upstream_path}"})
        try:
            request_payload = json.loads(body.decode("utf-8")) if body else {}
        except json.JSONDecodeError:
            request_payload = {}
        model = str(request_payload.get("model") or "")
        route = self._select_rule(project_id, client_type, model)
        if route is None:
            return self._json_response(HTTPStatus.NOT_FOUND, {"error": "No route proxy rule matched this request."})

        last_error = ""
        for profile in self._route_profiles(route):
            try:
                response = self._forward(
                    method=method,
                    upstream_path=upstream_path,
                    headers=headers,
                    body=body,
                    request_payload=request_payload,
                    route=route,
                    profile=profile,
                    model=model,
                )
                self._record(
                    "info",
                    f"{client_type} {upstream_path} -> {profile.name}",
                    project_id=project_id,
                    client_type=client_type,
                    profile_id=profile.id,
                    path=upstream_path,
                )
                return response
            except TranslationError as exc:
                return self._json_response(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
            except Exception as exc:
                last_error = sanitize_text(str(exc))
                self._record(
                    "error",
                    f"{client_type} {upstream_path} failed via {profile.name}: {last_error}",
                    project_id=project_id,
                    client_type=client_type,
                    profile_id=profile.id,
                    path=upstream_path,
                )
        return self._json_response(HTTPStatus.BAD_GATEWAY, {"error": last_error or "All route proxy upstreams failed."})

    def _forward(
        self,
        *,
        method: str,
        upstream_path: str,
        headers: dict[str, str],
        body: bytes,
        request_payload: dict[str, Any],
        route: RouteProxyRule,
        profile: Profile,
        model: str,
    ) -> tuple[int, dict[str, str], bytes | None, list[bytes] | None]:
        protocol = route.upstream_protocol
        rendered_body = body
        rendered_path = upstream_path
        response_transform = None
        stream_transform = None
        upstream_model = route.upstream_model or profile.codex_display_model or model
        if protocol == ROUTE_PROXY_PROTOCOL_ANTHROPIC_TO_OPENAI:
            rendered_path = self._replace_path_endpoint(upstream_path, "/v1/chat/completions")
            converted = anthropic_to_openai_request(request_payload, upstream_model)
            rendered_body = json.dumps(converted, ensure_ascii=False).encode("utf-8")
            response_transform = lambda payload: openai_to_anthropic_response(payload, model or upstream_model)
            stream_transform = lambda chunks: list(iter_openai_sse_to_anthropic(chunks, model or upstream_model))
        elif (
            protocol == ROUTE_PROXY_PROTOCOL_OPENAI_CHAT_TO_RESPONSES
            and parse.urlparse(upstream_path).path.endswith("/v1/chat/completions")
        ):
            rendered_path = self._replace_path_endpoint(upstream_path, "/v1/responses")
            converted = openai_chat_to_responses_request(request_payload, upstream_model)
            rendered_body = json.dumps(converted, ensure_ascii=False).encode("utf-8")
            response_transform = lambda payload: responses_to_openai_chat_response(payload, model or upstream_model)
            stream_transform = lambda chunks: list(iter_responses_sse_to_openai_chat(chunks, model or upstream_model))

        parsed_base = parse.urlparse(profile.base_url.rstrip("/"))
        if parsed_base.scheme not in {"http", "https"} or not parsed_base.netloc:
            raise ValueError("Invalid upstream base_url.")
        parsed_rendered_path = parse.urlparse(rendered_path)
        upstream_target = f"{parsed_base.path.rstrip('/')}{parsed_rendered_path.path}"
        if parsed_rendered_path.query:
            upstream_target = f"{upstream_target}?{parsed_rendered_path.query}"
        rendered_headers = self._render_headers(headers, profile, protocol)

        connection_cls = http.client.HTTPSConnection if parsed_base.scheme == "https" else http.client.HTTPConnection
        connection = connection_cls(parsed_base.netloc, timeout=90)
        try:
            connection.request(method, upstream_target or "/", body=rendered_body if method != "GET" else None, headers=rendered_headers)
            upstream_response = connection.getresponse()
            response_headers = self._response_headers(upstream_response)
            is_stream = "text/event-stream" in response_headers.get("content-type", "")
            if is_stream and stream_transform is not None:
                response_headers["content-type"] = "text/event-stream"
                response_headers.pop("content-length", None)
                return upstream_response.status, response_headers, None, stream_transform(upstream_response)
            response_body = upstream_response.read()
            response_body = self._decode_response_body(response_body, response_headers)
            if response_transform is not None and response_body:
                payload = json.loads(response_body.decode("utf-8"))
                response_body = json.dumps(response_transform(payload), ensure_ascii=False).encode("utf-8")
                response_headers["content-type"] = "application/json"
                response_headers["content-length"] = str(len(response_body))
            return upstream_response.status, response_headers, response_body, None
        finally:
            connection.close()

    def _split_project_path(self, raw_path: str) -> tuple[str | None, str]:
        parsed = parse.urlparse(raw_path)
        parts = parsed.path.split("/")
        if len(parts) >= 4 and parts[1] == "project":
            project_id = parts[2]
            rest = "/" + "/".join(parts[3:])
            if parsed.query:
                rest = f"{rest}?{parsed.query}"
            return project_id, rest
        return None, parsed.path

    def _detect_client_type(self, path: str) -> str | None:
        parsed_path = parse.urlparse(path).path
        if parsed_path.endswith("/v1/messages"):
            return ROUTE_PROXY_CLIENT_CLAUDE
        if parsed_path.endswith(("/v1/responses", "/v1/chat/completions", "/v1/models")):
            return ROUTE_PROXY_CLIENT_CODEX
        return None

    def _select_rule(self, project_id: str, client_type: str, model: str) -> RouteProxyRule | None:
        settings = self.settings_provider()
        for rule in settings.rules:
            if rule.matches(project_id=project_id, client_type=client_type, model=model):
                return rule
        return None

    def _route_profiles(self, route: RouteProxyRule) -> list[Profile]:
        profiles = {profile.id: profile for profile in self.profiles_provider()}
        return [profiles[profile_id] for profile_id in route.profile_ids if profile_id in profiles]

    def _render_headers(self, headers: dict[str, str], profile: Profile, protocol: str) -> dict[str, str]:
        rendered: dict[str, str] = {}
        for name, value in headers.items():
            lowered = name.casefold()
            if lowered in HOP_BY_HOP_HEADERS or lowered in AUTH_HEADERS:
                continue
            rendered[name] = value
        rendered["Content-Type"] = "application/json"
        rendered["Accept-Encoding"] = "identity"
        if protocol == ROUTE_PROXY_PROTOCOL_ANTHROPIC:
            rendered["x-api-key"] = profile.api_key
            rendered.setdefault("anthropic-version", headers.get("anthropic-version", "2023-06-01"))
        else:
            rendered["Authorization"] = f"Bearer {profile.api_key}"
        return rendered

    def _response_headers(self, upstream_response: http.client.HTTPResponse) -> dict[str, str]:
        headers: dict[str, str] = {}
        for name, value in upstream_response.getheaders():
            lowered = name.casefold()
            if lowered in HOP_BY_HOP_HEADERS:
                continue
            headers[lowered] = value
        return headers

    def _decode_response_body(self, body: bytes, headers: dict[str, str]) -> bytes:
        encoding = headers.get("content-encoding", "").casefold().strip()
        if not body or not encoding or encoding == "identity":
            return body
        if encoding == "gzip":
            decoded = gzip.decompress(body)
        elif encoding == "deflate":
            decoded = zlib.decompress(body)
        else:
            return body
        headers.pop("content-encoding", None)
        headers["content-length"] = str(len(decoded))
        return decoded

    def _replace_path_endpoint(self, path: str, endpoint: str) -> str:
        parsed = parse.urlparse(path)
        rendered = endpoint
        if parsed.query:
            rendered = f"{rendered}?{parsed.query}"
        return rendered

    def _json_response(self, status: HTTPStatus, payload: dict[str, Any]) -> tuple[int, dict[str, str], bytes, None]:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        return int(status), {"content-type": "application/json", "content-length": str(len(body))}, body, None

    def _record(
        self,
        level: str,
        message: str,
        *,
        project_id: str = "",
        client_type: str = "",
        profile_id: str = "",
        path: str = "",
    ) -> None:
        if self.event_callback is None:
            return
        self.event_callback(
            RouteProxyEvent.create(
                level=level,
                message=sanitize_text(message),
                project_id=project_id,
                client_type=client_type,
                profile_id=profile_id,
                path=path,
            )
        )


class _ProxyHTTPServer(ThreadingHTTPServer):
    route_proxy: RouteProxyServer


class _RouteProxyHandler(BaseHTTPRequestHandler):
    server: _ProxyHTTPServer

    def do_GET(self) -> None:
        self._handle()

    def do_POST(self) -> None:
        self._handle()

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "*")
        self.send_header("Access-Control-Allow-Methods", "GET,POST,OPTIONS")
        self.end_headers()

    def log_message(self, _format: str, *args: Any) -> None:
        return

    def _handle(self) -> None:
        content_length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(content_length) if content_length else b""
        headers = {name: value for name, value in self.headers.items()}
        status, response_headers, response_body, response_chunks = self.server.route_proxy.handle(
            method=self.command,
            raw_path=self.path,
            headers=headers,
            body=body,
        )
        self.send_response(status)
        for name, value in response_headers.items():
            self.send_header(name, value)
        if response_chunks is not None:
            self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        if response_chunks is not None:
            for chunk in response_chunks:
                self.wfile.write(chunk)
                self.wfile.flush()
        elif response_body is not None:
            self.wfile.write(response_body)
