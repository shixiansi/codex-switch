from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any
import os
import uuid


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def today_iso() -> str:
    return datetime.now().date().isoformat()


def normalize_project_dir(value: str) -> str:
    raw = value.strip()
    if not raw:
        return ''
    try:
        normalized = Path(raw).expanduser().resolve(strict=False)
    except OSError:
        normalized = Path(raw).expanduser()
    return os.path.normpath(str(normalized))


def project_dir_key(value: str) -> str:
    return os.path.normcase(normalize_project_dir(value))


def mask_secret(value: str) -> str:
    if not value:
        return ""
    if len(value) <= 10:
        return "*" * len(value)
    return f"{value[:6]}...{value[-4:]}"


def parse_model_names(value: str | None) -> list[str]:
    if not value:
        return []

    normalized = value
    for token in ("\r", "\n", "，", ";", "；", "|"):
        normalized = normalized.replace(token, ",")

    models: list[str] = []
    for item in normalized.split(","):
        model = item.strip()
        if model and model not in models:
            models.append(model)
    return models


@dataclass
class HealthResult:
    status: str = "unknown"
    detail: str = "未检测"
    checked_at: str | None = None
    latency_ms: int | None = None
    http_status: int | None = None
    endpoint: str | None = None
    models: list[str] = field(default_factory=list)

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
            models=list(data.get("models", [])),
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
    requires_sign_in: bool = False
    sign_in_url: str = ""
    last_signed_date: str | None = None
    notes: str = ""
    health: HealthResult = field(default_factory=HealthResult)
    manual_health_status: str | None = None

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
        requires_sign_in: bool = False,
        sign_in_url: str = "",
        last_signed_date: str | None = None,
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
            requires_sign_in=requires_sign_in,
            sign_in_url=sign_in_url.strip(),
            last_signed_date=last_signed_date,
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
            requires_sign_in=data.get("requires_sign_in", False),
            sign_in_url=data.get("sign_in_url", ""),
            last_signed_date=data.get("last_signed_date"),
            notes=data.get("notes", ""),
            health=HealthResult.from_dict(data.get("health")),
            manual_health_status=data.get("manual_health_status"),
        )

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["health"] = self.health.to_dict()
        return payload

    @property
    def effective_health_status(self) -> str:
        return self.manual_health_status or self.health.status

    @property
    def has_manual_health_override(self) -> bool:
        return bool(self.manual_health_status)

    @property
    def sign_in_status(self) -> str:
        if not self.requires_sign_in:
            return "无需签到"
        if self.last_signed_date == today_iso():
            return "已签到"
        return "未签到"


@dataclass
class ProjectRecord:
    id: str
    name: str
    project_dir: str
    profile_id: str
    created_at: str
    updated_at: str
    mcp_toml: str = ""
    run_command: str = ""

    @classmethod
    def create(
        cls,
        project_dir: str,
        profile_id: str,
        name: str | None = None,
        run_command: str = "",
    ) -> "ProjectRecord":
        normalized_dir = normalize_project_dir(project_dir)
        default_name = name.strip() if name else ""
        if not default_name:
            default_name = normalized_dir.rstrip("\\/").split("\\")[-1].split("/")[-1] or "未命名项目"
        timestamp = now_iso()
        return cls(
            id=str(uuid.uuid4()),
            name=default_name,
            project_dir=normalized_dir,
            profile_id=profile_id.strip(),
            created_at=timestamp,
            updated_at=timestamp,
            mcp_toml="",
            run_command=run_command.strip(),
        )

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ProjectRecord":
        timestamp = data.get("updated_at") or data.get("created_at") or now_iso()
        return cls(
            id=data["id"],
            name=data.get("name") or "未命名项目",
            project_dir=normalize_project_dir(data["project_dir"]),
            profile_id=data["profile_id"],
            created_at=data.get("created_at", timestamp),
            updated_at=data.get("updated_at", timestamp),
            mcp_toml=data.get("mcp_toml", ""),
            run_command=str(data.get("run_command", "") or "").strip(),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


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
    mcp_server_names: list[str]

    @property
    def api_key_masked(self) -> str:
        return mask_secret(self.api_key or "")

    @property
    def api_key_loaded(self) -> bool:
        return bool(self.api_key)
