from __future__ import annotations

from dataclasses import dataclass
from urllib import error, parse, request
import json

from app_models import Profile, parse_model_names


@dataclass
class ChatResult:
    ok: bool
    text: str
    endpoint: str | None = None
    model: str | None = None
    detail: str | None = None


def _normalize_base_url(base_url: str) -> str:
    return base_url.strip().rstrip("/")


def _build_endpoint(base_url: str, wire_api: str) -> str:
    base = _normalize_base_url(base_url)
    parsed = parse.urlparse(base)
    if not parsed.scheme or not parsed.netloc:
        raise ValueError("API 地址格式不正确，请输入形如 https://example.com 的地址。")

    if wire_api == "responses":
        return f"{base}/responses" if base.endswith("/v1") else f"{base}/v1/responses"
    return f"{base}/chat/completions" if base.endswith("/v1") else f"{base}/v1/chat/completions"


def _pick_model(profile: Profile, override_model: str | None = None) -> str:
    if override_model and override_model.strip():
        return override_model.strip()
    models = parse_model_names(profile.model)
    if models:
        return models[0]
    if profile.model.strip():
        return profile.model.strip()
    raise ValueError("当前配置没有可用的默认模型。")


class ChatTester:
    def __init__(self, timeout: int = 30) -> None:
        self.timeout = timeout

    def send_message(self, profile: Profile, prompt: str, model_override: str | None = None) -> ChatResult:
        prompt = prompt.strip()
        if not prompt:
            return ChatResult(ok=False, text="请输入测试消息。")
        if not profile.api_key.strip():
            return ChatResult(ok=False, text="当前配置缺少 API Key。")

        try:
            endpoint = _build_endpoint(profile.base_url, profile.wire_api)
            model = _pick_model(profile, model_override)
        except ValueError as exc:
            return ChatResult(ok=False, text=str(exc))

        payload = self._build_payload(profile, model, prompt)
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
                return ChatResult(
                    ok=True,
                    text=self._extract_text(profile, parsed),
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

    def _build_payload(self, profile: Profile, model: str, prompt: str) -> dict:
        if profile.wire_api == "responses":
            return {
                "model": model,
                "input": prompt,
                "max_output_tokens": 512,
            }
        return {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": 512,
        }

    def _extract_text(self, profile: Profile, payload: dict) -> str:
        if profile.wire_api == "responses":
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
            return "接口已返回响应，但没有提取到文本内容。"

        choices = payload.get("choices")
        if isinstance(choices, list) and choices:
            message = choices[0].get("message", {})
            content = message.get("content")
            if isinstance(content, str) and content.strip():
                return content.strip()
        return "接口已返回响应，但没有提取到文本内容。"
