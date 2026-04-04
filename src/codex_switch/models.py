from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any
import uuid


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def mask_secret(value: str) -> str:
    if not value:
        return ""
    if len(value) <= 10:
        return "*" * len(value)
    return f"{value[:6]}...{value[-4:]}"


@dataclass
class HealthResult:
    status: str = "unknown"
    detail: str = "未检测"
    checked_at: str | None = None
    latency_ms: int | None = None
    http_status: int | None = None
    endpoint: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "HealthResult":
        if not data:
            return cls()
        return cls(
            status=data.get("status", "unknown"),
            detail=data.get("detail", "未检测"),
            checked_at=data.get("checked_at"),
            latency_ms=data.get("latency_ms"),
            http_status=data.get("http_status"),
            endpoint=data.get("endpoint"),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Profile:
    id: str
    name: str
    base_url: str
    api_key: str
    model: str = "gpt-5.4"
    provider_name: str = "OpenAI"
    wire_api: str = "responses"
    requires_openai_auth: bool = True
    notes: str = ""
    health: HealthResult = field(default_factory=HealthResult)

    @classmethod
    def create(
        cls,
        name: str,
        base_url: str,
        api_key: str,
        model: str = "gpt-5.4",
        provider_name: str = "OpenAI",
        wire_api: str = "responses",
        requires_openai_auth: bool = True,
        notes: str = "",
    ) -> "Profile":
        return cls(
            id=str(uuid.uuid4()),
            name=name.strip(),
            base_url=base_url.strip(),
            api_key=api_key.strip(),
            model=model.strip() or "gpt-5.4",
            provider_name=provider_name.strip() or "OpenAI",
            wire_api=wire_api.strip() or "responses",
            requires_openai_auth=requires_openai_auth,
            notes=notes.strip(),
        )

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Profile":
        return cls(
            id=data["id"],
            name=data["name"],
            base_url=data["base_url"],
            api_key=data["api_key"],
            model=data.get("model", "gpt-5.4"),
            provider_name=data.get("provider_name", "OpenAI"),
            wire_api=data.get("wire_api", "responses"),
            requires_openai_auth=data.get("requires_openai_auth", True),
            notes=data.get("notes", ""),
            health=HealthResult.from_dict(data.get("health")),
        )

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["health"] = self.health.to_dict()
        return payload


@dataclass
class CurrentCodexConfig:
    model_provider: str | None
    model: str | None
    review_model: str | None
    base_url: str | None
    wire_api: str | None
    requires_openai_auth: bool | None
    auth_mode: str | None
    api_key: str | None
    config_path: str
    auth_path: str

    @property
    def api_key_masked(self) -> str:
        return mask_secret(self.api_key or "")

    @property
    def api_key_loaded(self) -> bool:
        return bool(self.api_key)

