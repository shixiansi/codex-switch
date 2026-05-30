from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any
from urllib import error, parse, request

from codex_switch.models import Profile, parse_model_names


SUPPORTED_WIRE_APIS = ("responses", "chat_completions")


@dataclass
class ChatResult:
    ok: bool
    text: str
    endpoint: str | None = None
    model: str | None = None
    detail: str | None = None


def _normalize_base_url(base_url: str) -> str:
    return base_url.strip().rstrip("/")


def _normalize_wire_api(wire_api: str | None) -> str:
    normalized = (wire_api or "responses").strip() or "responses"
    if normalized not in SUPPORTED_WIRE_APIS:
        raise ValueError(f"不支持的接口标准：{normalized}")
    return normalized


def _build_endpoint(base_url: str, wire_api: str) -> str:
    base = _normalize_base_url(base_url)
    parsed = parse.urlparse(base)
    if not parsed.scheme or not parsed.netloc:
        raise ValueError("API 地址格式不正确，请输入形如 https://example.com 的地址。")

    if _normalize_wire_api(wire_api) == "responses":
        return f"{base}/responses" if base.endswith("/v1") else f"{base}/v1/responses"
    return f"{base}/chat/completions" if base.endswith("/v1") else f"{base}/v1/chat/completions"


def _pick_model(profile: Profile, override_model: str | None = None) -> str:
    if override_model and override_model.strip():
        return override_model.strip()
    default_model = profile.codex_display_model
    models = parse_model_names(default_model)
    if models:
        return models[0]
    if default_model.strip():
        return default_model.strip()
    raise ValueError("当前配置没有可用的默认模型。")


class ChatTester:
    def __init__(self, timeout: int = 30) -> None:
        self.timeout = timeout

    def send_message(
        self,
        profile: Profile,
        prompt: str,
        model_override: str | None = None,
        wire_api_override: str | None = None,
        payload_override_text: str | None = None,
    ) -> ChatResult:
        prompt = prompt.strip()
        if not prompt:
            return ChatResult(ok=False, text="请输入测试消息。")
        if not profile.api_key.strip():
            return ChatResult(ok=False, text="当前配置缺少 API Key。")

        try:
            wire_api = _normalize_wire_api(wire_api_override or profile.wire_api)
            endpoint = _build_endpoint(profile.base_url, wire_api)
            model = _pick_model(profile, model_override)
            payload = self._build_payload(wire_api, model, prompt, payload_override_text)
        except ValueError as exc:
            return ChatResult(ok=False, text=str(exc))

        body = json.dumps(payload).encode("utf-8")
        req = request.Request(
            url=endpoint,
            data=body,
            headers={
                "Authorization": f"Bearer {profile.api_key}",
                "Content-Type": "application/json",
                "Accept": "application/json",
                "User-Agent": "CodexSwitch/1.0",
            },
            method="POST",
        )

        try:
            with request.urlopen(req, timeout=self.timeout) as response:
                text = response.read().decode("utf-8", errors="replace")
                parsed = json.loads(text)
                if not isinstance(parsed, dict):
                    return ChatResult(
                        ok=False,
                        text="接口返回了 JSON，但根节点不是对象。",
                        endpoint=endpoint,
                        model=model,
                    )
                return ChatResult(
                    ok=True,
                    text=self._extract_text(wire_api, parsed),
                    endpoint=endpoint,
                    model=model,
                )
        except error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            return ChatResult(
                ok=False,
                text=f"请求失败：HTTP {exc.code}",
                endpoint=endpoint,
                model=model,
                detail=detail[:400] if detail else None,
            )
        except error.URLError as exc:
            return ChatResult(
                ok=False,
                text=f"网络连接失败：{exc.reason}",
                endpoint=endpoint,
                model=model,
            )
        except TimeoutError:
            return ChatResult(
                ok=False,
                text="请求超时，接口长时间没有返回结果。",
                endpoint=endpoint,
                model=model,
            )
        except json.JSONDecodeError:
            return ChatResult(
                ok=False,
                text="接口返回了无法解析的 JSON。",
                endpoint=endpoint,
                model=model,
            )
        except Exception as exc:
            return ChatResult(
                ok=False,
                text=f"请求异常：{exc}",
                endpoint=endpoint,
                model=model,
            )

    def build_payload_template(self, wire_api: str) -> dict[str, Any]:
        if _normalize_wire_api(wire_api) == "responses":
            return {
                "model": "{{model}}",
                "input": "{{prompt}}",
                "max_output_tokens": 512,
            }
        return {
            "model": "{{model}}",
            "messages": [{"role": "user", "content": "{{prompt}}"}],
            "max_tokens": 512,
        }

    def _build_payload(
        self,
        wire_api: str,
        model: str,
        prompt: str,
        payload_override_text: str | None = None,
    ) -> dict[str, Any]:
        if payload_override_text and payload_override_text.strip():
            try:
                payload_template = json.loads(payload_override_text)
            except json.JSONDecodeError as exc:
                raise ValueError(
                    f"请求体 JSON 无效：第 {exc.lineno} 行第 {exc.colno} 列附近存在语法错误。"
                ) from exc
            if not isinstance(payload_template, dict):
                raise ValueError("请求体必须是 JSON 对象。")
        else:
            payload_template = self.build_payload_template(wire_api)
        return self._apply_payload_placeholders(payload_template, model, prompt)

    def _apply_payload_placeholders(self, payload: Any, model: str, prompt: str) -> Any:
        if isinstance(payload, dict):
            return {
                key: self._apply_payload_placeholders(value, model, prompt)
                for key, value in payload.items()
            }
        if isinstance(payload, list):
            return [self._apply_payload_placeholders(item, model, prompt) for item in payload]
        if isinstance(payload, str):
            return payload.replace("{{model}}", model).replace("{{prompt}}", prompt)
        return payload

    def _format_unextracted_response(self, payload: dict[str, Any]) -> str:
        return "接口已返回响应，但没有提取到文本内容。完整返回结果：\n" + json.dumps(
            payload,
            ensure_ascii=False,
            indent=2,
        )

    def _extract_text(self, wire_api: str, payload: dict[str, Any]) -> str:
        if _normalize_wire_api(wire_api) == "responses":
            output_text = payload.get("output_text")
            if isinstance(output_text, str) and output_text.strip():
                return output_text.strip()

            fragments: list[str] = []
            for item in payload.get("output", []):
                if not isinstance(item, dict):
                    continue
                for content in item.get("content", []):
                    if not isinstance(content, dict):
                        continue
                    text_value = content.get("text")
                    if isinstance(text_value, str) and text_value.strip():
                        fragments.append(text_value.strip())
            if fragments:
                return "\n".join(fragments)
            return self._format_unextracted_response(payload)

        choices = payload.get("choices")
        if isinstance(choices, list) and choices:
            message = choices[0].get("message", {})
            content = message.get("content")
            if isinstance(content, str) and content.strip():
                return content.strip()
        return self._format_unextracted_response(payload)
