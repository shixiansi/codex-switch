from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any
import os
import uuid


VENDOR_CODEX = "codex"
VENDOR_CLAUDE = "claude"
VENDOR_GENERIC = "通用"
PROFILE_VENDOR_CHOICES = (VENDOR_CODEX, VENDOR_CLAUDE, VENDOR_GENERIC)
DEFAULT_CODEX_MODEL = "gpt-5.4"
DEFAULT_CLAUDE_MODEL = "sonnet"
DEFAULT_CLAUDE_FALLBACK_MODEL = "haiku"


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


def normalize_api_keys(values: list[str] | tuple[str, ...] | None, fallback: str = "") -> list[str]:
    api_keys: list[str] = []
    source = values if isinstance(values, (list, tuple)) else []
    for value in source:
        if value is None:
            continue
        key = str(value).strip()
        if key:
            api_keys.append(key)
    fallback_key = fallback.strip()
    if not api_keys and fallback_key:
        api_keys.append(fallback_key)
    return api_keys


def normalize_api_key_index(api_keys: list[str], value: int | str | None) -> int:
    try:
        index = int(value or 0)
    except (TypeError, ValueError):
        index = 0
    if not api_keys:
        return 0
    return max(0, min(index, len(api_keys) - 1))


def normalize_profile_vendor(value: str | None) -> str:
    vendor = str(value or "").strip().lower()
    if vendor in (VENDOR_CODEX, VENDOR_CLAUDE):
        return vendor
    if vendor in ("generic", "common", "general", VENDOR_GENERIC.lower()):
        return VENDOR_GENERIC
    return VENDOR_GENERIC


def profile_supports_codex(profile: "Profile") -> bool:
    return profile.vendor in (VENDOR_CODEX, VENDOR_GENERIC)


def profile_supports_claude(profile: "Profile") -> bool:
    return profile.vendor in (VENDOR_CLAUDE, VENDOR_GENERIC)


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
    api_keys: list[str] = field(default_factory=list)
    active_api_key_index: int = 0
    model: str = DEFAULT_CODEX_MODEL
    vendor: str = VENDOR_GENERIC
    codex_model: str = DEFAULT_CODEX_MODEL
    claude_model: str = DEFAULT_CLAUDE_MODEL
    claude_fallback_model: str = DEFAULT_CLAUDE_FALLBACK_MODEL
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
        model: str = DEFAULT_CODEX_MODEL,
        vendor: str = VENDOR_GENERIC,
        codex_model: str | None = None,
        claude_model: str | None = None,
        claude_fallback_model: str | None = None,
        provider_name: str = "OpenAI",
        wire_api: str = "responses",
        requires_openai_auth: bool = True,
        requires_sign_in: bool = False,
        sign_in_url: str = "",
        last_signed_date: str | None = None,
        notes: str = "",
        api_keys: list[str] | None = None,
        active_api_key_index: int = 0,
    ) -> "Profile":
        normalized_keys = normalize_api_keys(api_keys, api_key)
        normalized_vendor = normalize_profile_vendor(vendor)
        legacy_model = model.strip() or DEFAULT_CODEX_MODEL
        if normalized_vendor == VENDOR_CLAUDE:
            effective_codex_model = (codex_model or DEFAULT_CODEX_MODEL).strip() or DEFAULT_CODEX_MODEL
            effective_claude_model = (claude_model or legacy_model or DEFAULT_CLAUDE_MODEL).strip() or DEFAULT_CLAUDE_MODEL
        else:
            effective_codex_model = (codex_model or legacy_model or DEFAULT_CODEX_MODEL).strip() or DEFAULT_CODEX_MODEL
            effective_claude_model = (claude_model or DEFAULT_CLAUDE_MODEL).strip() or DEFAULT_CLAUDE_MODEL
        effective_claude_fallback_model = (
            claude_fallback_model or DEFAULT_CLAUDE_FALLBACK_MODEL
        ).strip() or DEFAULT_CLAUDE_FALLBACK_MODEL
        return cls(
            id=str(uuid.uuid4()),
            name=name.strip(),
            base_url=base_url.strip(),
            api_keys=normalized_keys,
            active_api_key_index=normalize_api_key_index(normalized_keys, active_api_key_index),
            model=effective_codex_model,
            vendor=normalized_vendor,
            codex_model=effective_codex_model,
            claude_model=effective_claude_model,
            claude_fallback_model=effective_claude_fallback_model,
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
        api_keys = normalize_api_keys(data.get("api_keys"), str(data.get("api_key", "") or ""))
        vendor = normalize_profile_vendor(data.get("vendor"))
        legacy_model = str(data.get("model", "") or "").strip()
        codex_model = str(data.get("codex_model", "") or "").strip() or legacy_model or DEFAULT_CODEX_MODEL
        claude_model = str(data.get("claude_model", "") or "").strip() or (
            legacy_model if vendor == VENDOR_CLAUDE else ""
        ) or DEFAULT_CLAUDE_MODEL
        claude_fallback_model = (
            str(data.get("claude_fallback_model", "") or "").strip()
            or DEFAULT_CLAUDE_FALLBACK_MODEL
        )
        return cls(
            id=data["id"],
            name=data["name"],
            base_url=data["base_url"],
            api_keys=api_keys,
            active_api_key_index=normalize_api_key_index(api_keys, data.get("active_api_key_index")),
            model=codex_model,
            vendor=vendor,
            codex_model=codex_model,
            claude_model=claude_model,
            claude_fallback_model=claude_fallback_model,
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
        payload["api_keys"] = list(self.api_keys)
        payload["active_api_key_index"] = self.effective_active_api_key_index
        payload["api_key"] = self.api_key
        payload["vendor"] = self.vendor
        payload["codex_model"] = self.codex_model
        payload["claude_model"] = self.claude_model
        payload["claude_fallback_model"] = self.claude_fallback_model
        payload["model"] = self.codex_model
        return payload

    @property
    def effective_active_api_key_index(self) -> int:
        return normalize_api_key_index(self.api_keys, self.active_api_key_index)

    @property
    def api_key(self) -> str:
        if not self.api_keys:
            return ""
        return self.api_keys[self.effective_active_api_key_index]

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

    @property
    def codex_display_model(self) -> str:
        return self.codex_model or self.model or DEFAULT_CODEX_MODEL

    @property
    def claude_display_model(self) -> str:
        return self.claude_model or DEFAULT_CLAUDE_MODEL

    @property
    def claude_display_fallback_model(self) -> str:
        return self.claude_fallback_model or DEFAULT_CLAUDE_FALLBACK_MODEL

    @property
    def vendor_label(self) -> str:
        if self.vendor == VENDOR_CODEX:
            return "Codex"
        if self.vendor == VENDOR_CLAUDE:
            return "Claude"
        return VENDOR_GENERIC


@dataclass
class ProjectRecord:
    id: str
    name: str
    project_dir: str
    profile_id: str
    created_at: str
    updated_at: str
    codex_profile_id: str = ""
    claude_profile_id: str = ""
    mcp_toml: str = ""
    run_command: str = ""
    mcp_server_names: list[str] | None = None

    @classmethod
    def create(
        cls,
        project_dir: str,
        profile_id: str,
        name: str | None = None,
        run_command: str = "",
        mcp_server_names: list[str] | None = None,
        codex_profile_id: str | None = None,
        claude_profile_id: str | None = None,
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
            codex_profile_id=(codex_profile_id or profile_id).strip(),
            claude_profile_id=(claude_profile_id or profile_id).strip(),
            mcp_toml="",
            run_command=run_command.strip(),
            mcp_server_names=list(mcp_server_names) if mcp_server_names is not None else None,
        )

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ProjectRecord":
        timestamp = data.get("updated_at") or data.get("created_at") or now_iso()
        legacy_profile_id = str(data.get("profile_id", "") or "").strip()
        codex_profile_id = str(data.get("codex_profile_id", "") or "").strip() or legacy_profile_id
        claude_profile_id = str(data.get("claude_profile_id", "") or "").strip() or legacy_profile_id
        profile_id = legacy_profile_id or codex_profile_id or claude_profile_id
        raw_mcp_server_names = data.get("mcp_server_names")
        mcp_server_names = None
        if isinstance(raw_mcp_server_names, list):
            mcp_server_names = [
                str(item).strip()
                for item in raw_mcp_server_names
                if str(item).strip()
            ]
        return cls(
            id=data["id"],
            name=data.get("name") or "未命名项目",
            project_dir=normalize_project_dir(data["project_dir"]),
            profile_id=profile_id,
            created_at=data.get("created_at", timestamp),
            updated_at=data.get("updated_at", timestamp),
            codex_profile_id=codex_profile_id,
            claude_profile_id=claude_profile_id,
            mcp_toml=data.get("mcp_toml", ""),
            run_command=str(data.get("run_command", "") or "").strip(),
            mcp_server_names=mcp_server_names,
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
