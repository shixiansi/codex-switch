from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import replace
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
    AccountPoolChannel,
    AccountPoolSettings,
    DEFAULT_CODEX_MODEL,
    Profile,
    ProjectRecord,
    RouteProxyEvent,
    RouteProxyRule,
    RouteProxySettings,
    ROUTE_PROXY_CLIENT_CLAUDE,
    ROUTE_PROXY_CLIENT_CODEX,
    ROUTE_PROXY_PROTOCOL_ANTHROPIC,
    ROUTE_PROXY_PROTOCOL_OPENAI,
    ROUTE_PROXY_PROTOCOL_OPENAI_RESPONSES_TO_CHAT,
    ROUTE_PROXY_UPSTREAM_SOURCE_ACCOUNT_POOL,
    ROUTE_PROXY_UPSTREAM_SOURCE_PROFILE,
)
from codex_switch.health import HealthChecker
from codex_switch.proxy.protocol_matrix import translation_for_protocol
from codex_switch.proxy.sanitize import sanitize_text
from codex_switch.proxy.translator import TranslationError


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
OPENAI_PATH_ALIASES = {
    "/responses": "/v1/responses",
    "/responses/compact": "/v1/responses/compact",
    "/chat/completions": "/v1/chat/completions",
    "/models": "/v1/models",
}
OPENAI_PROXY_PATHS = set(OPENAI_PATH_ALIASES) | set(OPENAI_PATH_ALIASES.values())
OPENAI_COMPACT_PATHS = {"/responses/compact", "/v1/responses/compact"}
ACCOUNT_POOL_RECOVERY_INTERVAL_SECONDS = 600
ACCOUNT_POOL_UNAVAILABLE_STATUSES = {401, 403, 407, 429, 500, 502, 503, 504}


class RouteProxyServer:
    def __init__(
        self,
        settings_provider: Callable[[], RouteProxySettings],
        profiles_provider: Callable[[], list[Profile]],
        event_callback: Callable[[RouteProxyEvent], None] | None = None,
        account_pool_provider: Callable[[], AccountPoolSettings] | None = None,
        account_pool_update_callback: Callable[[AccountPoolSettings], None] | None = None,
        project_provider: Callable[[], list[ProjectRecord]] | None = None,
        recovery_checker: HealthChecker | None = None,
    ) -> None:
        self.settings_provider = settings_provider
        self.profiles_provider = profiles_provider
        self.event_callback = event_callback
        self.account_pool_provider = account_pool_provider
        self.account_pool_update_callback = account_pool_update_callback
        self.project_provider = project_provider
        self.recovery_checker = recovery_checker or HealthChecker()
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
    ) -> tuple[int, dict[str, str], bytes | None, Iterable[bytes] | None]:
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
        if self._uses_account_pool(route):
            return self._handle_account_pool_route(
                method=method,
                upstream_path=upstream_path,
                headers=headers,
                body=body,
                request_payload=request_payload,
                route=route,
                model=model,
                project_id=project_id,
                client_type=client_type,
            )

        last_error = ""
        for profile in self._route_profiles(route):
            log_context = self._route_log_context(
                project_id=project_id,
                upstream_source=ROUTE_PROXY_UPSTREAM_SOURCE_PROFILE,
                channel_name=profile.name,
            )
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
                    project_id=project_id,
                )
                self._record(
                    "info",
                    f"{log_context} {client_type} {upstream_path} -> ok",
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
                    f"{log_context} {client_type} {upstream_path} failed: {last_error}",
                    project_id=project_id,
                    client_type=client_type,
                    profile_id=profile.id,
                    path=upstream_path,
                )
        return self._json_response(HTTPStatus.BAD_GATEWAY, {"error": last_error or "All route proxy upstreams failed."})

    def _handle_account_pool_route(
        self,
        *,
        method: str,
        upstream_path: str,
        headers: dict[str, str],
        body: bytes,
        request_payload: dict[str, Any],
        route: RouteProxyRule,
        model: str,
        project_id: str,
        client_type: str,
    ) -> tuple[int, dict[str, str], bytes | None, Iterable[bytes] | None]:
        pool = self.account_pool_provider() if self.account_pool_provider is not None else AccountPoolSettings()
        if not pool.enabled:
            return self._json_response(HTTPStatus.BAD_GATEWAY, {"error": "Account pool is disabled."})
        self._maybe_recover_account_pool(pool)
        if pool.normal_count == 0:
            return self._json_response(HTTPStatus.BAD_GATEWAY, {"error": "No normal account pool channels are available."})

        attempted_channel_ids: set[str] = set()
        last_error = ""
        while len(attempted_channel_ids) < len(pool.channels):
            channel = pool.take_next_normal_channel(attempted_channel_ids)
            if channel is None:
                break
            attempted_channel_ids.add(channel.id)
            log_context = self._route_log_context(
                project_id=project_id,
                upstream_source=ROUTE_PROXY_UPSTREAM_SOURCE_ACCOUNT_POOL,
                channel_name=channel.name,
            )
            profile = self._profile_from_account_pool_channel(channel)
            effective_route = self._account_pool_route(route, channel)
            try:
                response = self._forward(
                    method=method,
                    upstream_path=upstream_path,
                    headers=headers,
                    body=body,
                    request_payload=request_payload,
                    route=effective_route,
                    profile=profile,
                    model=model,
                    project_id=project_id,
                )
            except TranslationError as exc:
                return self._json_response(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
            except Exception as exc:
                last_error = sanitize_text(str(exc))
                pool.mark_failed(channel.id, last_error)
                self._notify_account_pool_updated(pool)
                self._record(
                    "error",
                    f"{log_context} {client_type} {upstream_path} failed: {last_error}",
                    project_id=project_id,
                    client_type=client_type,
                    profile_id=channel.id,
                    path=upstream_path,
                )
                continue

            status, _response_headers, response_body, response_chunks = response
            if self._is_account_pool_unavailable_status(status):
                if response_chunks is not None and hasattr(response_chunks, "close"):
                    response_chunks.close()
                last_error = self._account_pool_status_error(status, response_body)
                pool.mark_failed(channel.id, last_error)
                self._notify_account_pool_updated(pool)
                self._record(
                    "error",
                    f"{log_context} {client_type} {upstream_path} unavailable: {last_error}",
                    project_id=project_id,
                    client_type=client_type,
                    profile_id=channel.id,
                    path=upstream_path,
                )
                continue

            pool.mark_success(channel.id)
            self._notify_account_pool_updated(pool)
            self._record(
                "info",
                f"{log_context} {client_type} {upstream_path} -> ok",
                project_id=project_id,
                client_type=client_type,
                profile_id=channel.id,
                path=upstream_path,
            )
            return response

        return self._json_response(HTTPStatus.BAD_GATEWAY, {"error": last_error or "All account pool channels failed."})

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
        project_id: str,
    ) -> tuple[int, dict[str, str], bytes | None, Iterable[bytes] | None]:
        protocol = route.upstream_protocol
        rendered_body = body
        rendered_path = self._canonical_openai_path(upstream_path) if route.client_type == ROUTE_PROXY_CLIENT_CODEX else upstream_path
        response_transform = None
        stream_transform = None
        upstream_model = route.upstream_model or profile.codex_display_model or model
        translation = translation_for_protocol(protocol, rendered_path)
        if translation is not None:
            rendered_path = self._replace_path_endpoint(upstream_path, translation.upstream_endpoint)
            converted = translation.request(request_payload, upstream_model)
            rendered_body = json.dumps(converted, ensure_ascii=False).encode("utf-8")
            response_transform = lambda payload: translation.response(payload, model or upstream_model)
            stream_transform = lambda chunks: translation.stream(chunks, model or upstream_model)
        elif route.client_type == ROUTE_PROXY_CLIENT_CODEX and self._is_openai_compact_path(rendered_path):
            compact_model = route.compact_model.strip()
            if compact_model and request_payload:
                converted = dict(request_payload)
                converted["model"] = compact_model
                rendered_body = json.dumps(converted, ensure_ascii=False).encode("utf-8")

        parsed_base = parse.urlparse(profile.base_url.rstrip("/"))
        if parsed_base.scheme not in {"http", "https"} or not parsed_base.netloc:
            raise ValueError("Invalid upstream base_url.")
        parsed_rendered_path = parse.urlparse(rendered_path)
        upstream_target = self._join_upstream_path(parsed_base.path, parsed_rendered_path.path)
        if parsed_rendered_path.query:
            upstream_target = f"{upstream_target}?{parsed_rendered_path.query}"
        rendered_headers = self._render_headers(headers, profile, protocol, project_id=project_id)
        upstream_url = self._format_upstream_url(parsed_base, upstream_target)

        connection_cls = http.client.HTTPSConnection if parsed_base.scheme == "https" else http.client.HTTPConnection
        connection = connection_cls(parsed_base.netloc, timeout=90)
        close_connection = True
        try:
            connection.request(method, upstream_target or "/", body=rendered_body if method != "GET" else None, headers=rendered_headers)
            upstream_response = connection.getresponse()
            response_headers = self._response_headers(upstream_response)
            is_stream = "text/event-stream" in response_headers.get("content-type", "")
            if is_stream:
                response_headers["content-type"] = "text/event-stream"
                response_headers.pop("content-length", None)
                close_connection = False
                response_chunks = stream_transform(upstream_response) if stream_transform is not None else upstream_response
                return upstream_response.status, response_headers, None, self._closing_stream(
                    connection,
                    response_chunks,
                )
            response_body = upstream_response.read()
            response_body = self._decode_response_body(response_body, response_headers)
            if response_transform is not None and response_body:
                payload = json.loads(response_body.decode("utf-8"))
                response_body = json.dumps(response_transform(payload), ensure_ascii=False).encode("utf-8")
                response_headers["content-type"] = "application/json"
                response_headers["content-length"] = str(len(response_body))
            return upstream_response.status, response_headers, response_body, None
        except OSError as exc:
            raise OSError(f"{exc} (upstream: {upstream_url})") from exc
        finally:
            if close_connection:
                connection.close()

    def _closing_stream(
        self,
        connection: http.client.HTTPConnection,
        chunks: Iterable[bytes],
    ) -> Iterable[bytes]:
        try:
            yield from chunks
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
        if parsed_path in OPENAI_PROXY_PATHS:
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

    def _render_headers(self, headers: dict[str, str], profile: Profile, protocol: str, *, project_id: str) -> dict[str, str]:
        rendered: dict[str, str] = {}
        for name, value in headers.items():
            lowered = name.casefold()
            if lowered in HOP_BY_HOP_HEADERS or lowered in AUTH_HEADERS:
                continue
            rendered[name] = self._safe_header_value(value)
        rendered["Content-Type"] = "application/json"
        rendered["Accept-Encoding"] = "identity"
        if protocol == ROUTE_PROXY_PROTOCOL_ANTHROPIC:
            rendered["x-api-key"] = profile.api_key
            rendered.setdefault("anthropic-version", headers.get("anthropic-version", "2023-06-01"))
        else:
            rendered["Authorization"] = f"Bearer {profile.api_key}"
        rendered["X-Codex-Switch-Project-Id"] = project_id
        project_name = self._project_name(project_id)
        if project_name:
            rendered["X-Codex-Switch-Project-Name"] = self._safe_header_value(project_name)
        return rendered

    def _safe_header_value(self, value: str) -> str:
        rendered = str(value)
        try:
            rendered.encode("latin-1")
        except UnicodeEncodeError:
            return parse.quote(rendered, safe="")
        return rendered

    def _uses_account_pool(self, route: RouteProxyRule) -> bool:
        return (
            route.client_type == ROUTE_PROXY_CLIENT_CODEX
            and route.upstream_source == ROUTE_PROXY_UPSTREAM_SOURCE_ACCOUNT_POOL
        )

    def _profile_from_account_pool_channel(self, channel: AccountPoolChannel) -> Profile:
        profile = Profile.create(
            channel.name,
            channel.base_url,
            channel.api_key,
            model=channel.default_model or DEFAULT_CODEX_MODEL,
            codex_model=channel.default_model or DEFAULT_CODEX_MODEL,
            wire_api=channel.wire_api,
        )
        profile.id = channel.id
        return profile

    def _account_pool_route(self, route: RouteProxyRule, channel: AccountPoolChannel) -> RouteProxyRule:
        if channel.wire_api == "chat_completions":
            return replace(
                route,
                primary_profile_id=channel.id,
                upstream_protocol=ROUTE_PROXY_PROTOCOL_OPENAI_RESPONSES_TO_CHAT,
                upstream_model=channel.default_model or DEFAULT_CODEX_MODEL,
            )
        return replace(
            route,
            primary_profile_id=channel.id,
            upstream_protocol=ROUTE_PROXY_PROTOCOL_OPENAI,
            upstream_model="",
        )

    def _project_name(self, project_id: str) -> str:
        if self.project_provider is None:
            return ""
        return next((project.name for project in self.project_provider() if project.id == project_id), "")

    def _route_log_context(self, *, project_id: str, upstream_source: str, channel_name: str) -> str:
        project_name = self._project_name(project_id) or project_id or "-"
        mode = (
            "account_pool_proxy"
            if upstream_source == ROUTE_PROXY_UPSTREAM_SOURCE_ACCOUNT_POOL
            else "profile_proxy"
        )
        return (
            f"[project={project_name} "
            f"project_id={project_id or '-'} "
            f"mode={mode} "
            f"channel={channel_name or '-'}]"
        )

    def _is_account_pool_unavailable_status(self, status: int) -> bool:
        return status in ACCOUNT_POOL_UNAVAILABLE_STATUSES

    def _account_pool_status_error(self, status: int, response_body: bytes | None) -> str:
        if response_body:
            detail = response_body.decode("utf-8", errors="replace").strip()
            if detail:
                return sanitize_text(f"HTTP {status}: {detail[:200]}")
        return f"HTTP {status}"

    def _maybe_recover_account_pool(self, pool: AccountPoolSettings) -> None:
        if not pool.recovery_due(interval_seconds=ACCOUNT_POOL_RECOVERY_INTERVAL_SECONDS):
            return
        pool.mark_recovery_checked()
        for channel in list(pool.failed_channels):
            result = self.recovery_checker.check(self._profile_from_account_pool_channel(channel))
            if result.status == "healthy":
                pool.mark_recovered(channel.id)
                self._record(
                    "info",
                    f"[mode=account_pool_proxy channel={channel.name}] recovered",
                    profile_id=channel.id,
                )
            else:
                pool.mark_failed(channel.id, result.detail)
        self._notify_account_pool_updated(pool)

    def _notify_account_pool_updated(self, pool: AccountPoolSettings) -> None:
        if self.account_pool_update_callback is not None:
            self.account_pool_update_callback(pool)

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

    def _canonical_openai_path(self, path: str) -> str:
        parsed = parse.urlparse(path)
        rendered = OPENAI_PATH_ALIASES.get(parsed.path, parsed.path)
        if parsed.query:
            rendered = f"{rendered}?{parsed.query}"
        return rendered

    def _is_openai_compact_path(self, path: str) -> bool:
        return parse.urlparse(path).path in OPENAI_COMPACT_PATHS

    def _join_upstream_path(self, base_path: str, request_path: str) -> str:
        normalized_base = (base_path or "").rstrip("/")
        if normalized_base == "/":
            normalized_base = ""
        normalized_request = request_path if request_path.startswith("/") else f"/{request_path}"
        if normalized_base.endswith("/v1") and normalized_request.startswith("/v1/"):
            normalized_request = normalized_request[len("/v1") :]
        if not normalized_base:
            return normalized_request or "/"
        return f"{normalized_base}{normalized_request}"

    def _format_upstream_url(self, parsed_base: parse.ParseResult, upstream_target: str) -> str:
        parsed_target = parse.urlparse(upstream_target or "/")
        return parse.urlunparse(
            (
                parsed_base.scheme,
                parsed_base.netloc,
                parsed_target.path or "/",
                "",
                parsed_target.query,
                "",
            )
        )

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
