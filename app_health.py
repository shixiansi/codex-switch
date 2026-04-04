from __future__ import annotations

from time import perf_counter
from urllib import error, parse, request
import json
import socket
import ssl

from app_models import HealthResult, Profile, now_iso


def normalize_base_url(base_url: str) -> str:
    return base_url.strip().rstrip("/")


def build_candidate_urls(base_url: str) -> list[str]:
    normalized = normalize_base_url(base_url)
    parsed = parse.urlparse(normalized)
    if not parsed.scheme or not parsed.netloc:
        raise ValueError("API 地址格式不正确，请输入形如 https://example.com 的地址。")

    if normalized.endswith("/v1"):
        return [f"{normalized}/models"]
    return [f"{normalized}/v1/models", f"{normalized}/models"]


class HealthChecker:
    def __init__(self, timeout: int = 15) -> None:
        self.timeout = timeout

    def check(self, profile: Profile) -> HealthResult:
        if not profile.base_url.strip():
            return HealthResult(status="error", detail="API 地址不能为空", checked_at=now_iso())
        if not profile.api_key.strip():
            return HealthResult(status="error", detail="API Key 不能为空", checked_at=now_iso())

        try:
            urls = build_candidate_urls(profile.base_url)
        except ValueError as exc:
            return HealthResult(status="error", detail=str(exc), checked_at=now_iso())

        last_not_found: error.HTTPError | None = None

        for url in urls:
            started = perf_counter()
            try:
                response = self._send_request(url, profile.api_key)
                body = response.read().decode("utf-8", errors="replace")
                latency_ms = int((perf_counter() - started) * 1000)
                detail, models = self._build_success_payload(body)
                return HealthResult(
                    status="healthy",
                    detail=detail,
                    checked_at=now_iso(),
                    latency_ms=latency_ms,
                    http_status=response.status,
                    endpoint=url,
                    models=models,
                )
            except error.HTTPError as exc:
                latency_ms = int((perf_counter() - started) * 1000)
                if exc.code == 404:
                    last_not_found = exc
                    continue
                return self._map_http_error(exc, url, latency_ms)
            except error.URLError as exc:
                latency_ms = int((perf_counter() - started) * 1000)
                reason = exc.reason
                if isinstance(reason, socket.timeout):
                    detail = "连接超时，API 无响应"
                elif isinstance(reason, ssl.SSLError):
                    detail = f"SSL 连接失败: {reason}"
                else:
                    detail = f"网络连接失败: {reason}"
                return HealthResult(
                    status="error",
                    detail=detail,
                    checked_at=now_iso(),
                    latency_ms=latency_ms,
                    endpoint=url,
                )
            except TimeoutError:
                latency_ms = int((perf_counter() - started) * 1000)
                return HealthResult(
                    status="error",
                    detail="连接超时，API 无响应",
                    checked_at=now_iso(),
                    latency_ms=latency_ms,
                    endpoint=url,
                )

        detail = "接口返回 404，未找到兼容的 models 探测端点"
        if last_not_found is not None:
            detail = f"接口返回 {last_not_found.code}，未找到兼容的 models 探测端点"
        return HealthResult(status="error", detail=detail, checked_at=now_iso())

    def _send_request(self, url: str, api_key: str):
        req = request.Request(
            url=url,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Accept": "application/json",
                "User-Agent": "CodexSwitch/1.0",
            },
            method="GET",
        )
        return request.urlopen(req, timeout=self.timeout)

    def _build_success_payload(self, body: str) -> tuple[str, list[str]]:
        try:
            payload = json.loads(body)
        except json.JSONDecodeError:
            return "接口可连接，但返回内容不是 JSON", []

        data = payload.get("data")
        if not isinstance(data, list):
            return "接口可用，鉴权通过", []

        models: list[str] = []
        for item in data:
            if not isinstance(item, dict):
                continue
            model_id = str(item.get("id", "")).strip()
            if model_id and model_id not in models:
                models.append(model_id)
            if len(models) >= 24:
                break

        if models:
            return f"接口可用，已返回 {len(models)} 个模型", models
        return "接口可用，已获取模型列表", []

    def _map_http_error(self, exc: error.HTTPError, endpoint: str, latency_ms: int) -> HealthResult:
        detail_map = {
            400: "请求被接口拒绝，请检查兼容性",
            401: "鉴权失败，请检查 API Key 是否正确",
            403: "接口拒绝访问，请检查 Key 权限或白名单",
            407: "代理认证失败",
            408: "接口响应超时",
            429: "接口可达，但请求过于频繁或额度不足",
            500: "服务端内部错误",
            502: "网关错误，服务可能暂时不可用",
            503: "服务不可用",
            504: "网关超时",
        }
        status = "degraded" if exc.code == 429 else "error"
        detail = detail_map.get(exc.code, f"接口返回 HTTP {exc.code}")
        return HealthResult(
            status=status,
            detail=detail,
            checked_at=now_iso(),
            latency_ms=latency_ms,
            http_status=exc.code,
            endpoint=endpoint,
        )
