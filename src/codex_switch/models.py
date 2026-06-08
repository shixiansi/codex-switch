from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any
import fnmatch
import os
import uuid


VENDOR_CODEX = "codex"
VENDOR_CLAUDE = "claude"
VENDOR_GENERIC = "通用"
VENDOR_OTHER = "其他"
PROFILE_VENDOR_CHOICES = (VENDOR_CODEX, VENDOR_CLAUDE, VENDOR_GENERIC, VENDOR_OTHER)
PROFILE_CATEGORY_TEXT = "text"
PROFILE_CATEGORY_IMAGE_GENERATION = "image_generation"
PROFILE_CATEGORY_CHOICES = (PROFILE_CATEGORY_TEXT, PROFILE_CATEGORY_IMAGE_GENERATION)
PROFILE_CATEGORY_LABELS = {
    PROFILE_CATEGORY_TEXT: "文本",
    PROFILE_CATEGORY_IMAGE_GENERATION: "生图",
}
MODEL_VENDOR_OTHER = "其他"
MAINSTREAM_MODEL_VENDORS = (
    "OpenAI",
    "Anthropic",
    "Google",
    "Meta",
    "Mistral",
    "Qwen",
    "DeepSeek",
    "xAI",
    "Moonshot",
)
MODEL_VENDOR_KEYWORDS = {
    "OpenAI": ("openai", "gpt-", "o1", "o3", "o4"),
    "Anthropic": ("anthropic", "claude", "sonnet", "haiku", "opus"),
    "Google": ("google", "gemini", "palm"),
    "Meta": ("meta", "llama"),
    "Mistral": ("mistral", "mixtral", "codestral"),
    "Qwen": ("qwen", "qwq", "通义"),
    "DeepSeek": ("deepseek", "deep-seek"),
    "xAI": ("xai", "grok"),
    "Moonshot": ("moonshot", "kimi"),
}
DEFAULT_CODEX_MODEL = "gpt-5.4"
DEFAULT_CLAUDE_MODEL = "sonnet"
DEFAULT_CLAUDE_FALLBACK_MODEL = "haiku"
ROUTE_PROXY_DEFAULT_HOST = "127.0.0.1"
ROUTE_PROXY_DEFAULT_PORT = 15721
ROUTE_PROXY_PLACEHOLDER_KEY = "codex-switch-proxy"
ROUTE_PROXY_CLIENT_CODEX = "codex"
ROUTE_PROXY_CLIENT_CLAUDE = "claude"
ROUTE_PROXY_PROTOCOL_OPENAI = "openai_passthrough"
ROUTE_PROXY_PROTOCOL_OPENAI_CHAT_TO_RESPONSES = "openai_chat_to_responses"
ROUTE_PROXY_PROTOCOL_OPENAI_RESPONSES_TO_CHAT = "openai_responses_to_chat"
ROUTE_PROXY_PROTOCOL_ANTHROPIC = "anthropic_passthrough"
ROUTE_PROXY_PROTOCOL_ANTHROPIC_TO_OPENAI = "anthropic_to_openai"
ROUTE_PROXY_UPSTREAM_SOURCE_PROFILE = "profile"
ROUTE_PROXY_UPSTREAM_SOURCE_ACCOUNT_POOL = "account_pool"
ROUTE_PROXY_UPSTREAM_SOURCE_CHOICES = (
    ROUTE_PROXY_UPSTREAM_SOURCE_PROFILE,
    ROUTE_PROXY_UPSTREAM_SOURCE_ACCOUNT_POOL,
)
ROUTE_PROXY_CLIENT_CHOICES = (ROUTE_PROXY_CLIENT_CODEX, ROUTE_PROXY_CLIENT_CLAUDE)
ROUTE_PROXY_PROTOCOL_CHOICES = (
    ROUTE_PROXY_PROTOCOL_OPENAI,
    ROUTE_PROXY_PROTOCOL_OPENAI_CHAT_TO_RESPONSES,
    ROUTE_PROXY_PROTOCOL_OPENAI_RESPONSES_TO_CHAT,
    ROUTE_PROXY_PROTOCOL_ANTHROPIC,
    ROUTE_PROXY_PROTOCOL_ANTHROPIC_TO_OPENAI,
)
ACCOUNT_POOL_CHANNEL_STATUS_NORMAL = "normal"
ACCOUNT_POOL_CHANNEL_STATUS_ERROR = "error"
ACCOUNT_POOL_CHANNEL_STATUS_CHOICES = (
    ACCOUNT_POOL_CHANNEL_STATUS_NORMAL,
    ACCOUNT_POOL_CHANNEL_STATUS_ERROR,
)
ACCOUNT_POOL_CHANNEL_SOURCE_TEMPORARY = "temporary"
ACCOUNT_POOL_CHANNEL_SOURCE_PROFILE = "profile"
ACCOUNT_POOL_CHANNEL_SOURCE_CHOICES = (
    ACCOUNT_POOL_CHANNEL_SOURCE_TEMPORARY,
    ACCOUNT_POOL_CHANNEL_SOURCE_PROFILE,
)
DEFAULT_ACCOUNT_POOL_GROUP_NAME = "默认号池"
DEFAULT_ACCOUNT_POOL_RECOVERY_INTERVAL_MINUTES = 5
ACCOUNT_POOL_RECOVERY_INTERVAL_MINUTES_MIN = 1
ACCOUNT_POOL_RECOVERY_INTERVAL_MINUTES_MAX = 1440


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


def detect_model_vendor(model_name: str) -> str:
    normalized = str(model_name or "").strip().lower()
    if not normalized:
        return MODEL_VENDOR_OTHER
    for vendor, keywords in MODEL_VENDOR_KEYWORDS.items():
        if any(keyword.lower() in normalized for keyword in keywords):
            return vendor
    return MODEL_VENDOR_OTHER


def model_vendor_stats(models: list[str]) -> dict[str, int]:
    stats = {vendor: 0 for vendor in MAINSTREAM_MODEL_VENDORS}
    stats[MODEL_VENDOR_OTHER] = 0
    for model in models:
        model_name = str(model or "").strip()
        if not model_name:
            continue
        vendor = detect_model_vendor(model_name)
        stats[vendor] = stats.get(vendor, 0) + 1
    return {vendor: count for vendor, count in stats.items() if count > 0}


def models_by_vendor(models: list[str]) -> dict[str, list[str]]:
    grouped = {vendor: [] for vendor in MAINSTREAM_MODEL_VENDORS}
    grouped[MODEL_VENDOR_OTHER] = []
    for model in models:
        model_name = str(model or "").strip()
        if not model_name:
            continue
        vendor = detect_model_vendor(model_name)
        grouped.setdefault(vendor, []).append(model_name)
    return {vendor: names for vendor, names in grouped.items() if names}


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
    if vendor in ("other", "others", VENDOR_OTHER.lower()):
        return VENDOR_OTHER
    return VENDOR_GENERIC


def normalize_profile_category(value: object) -> str:
    category = str(value or "").strip()
    if category == PROFILE_CATEGORY_IMAGE_GENERATION:
        return PROFILE_CATEGORY_IMAGE_GENERATION
    return PROFILE_CATEGORY_TEXT


def normalize_route_proxy_client(value: str | None) -> str:
    client = str(value or "").strip().lower()
    if client in ROUTE_PROXY_CLIENT_CHOICES:
        return client
    return ROUTE_PROXY_CLIENT_CODEX


def normalize_route_proxy_protocol(value: str | None, client: str | None = None) -> str:
    protocol = str(value or "").strip().lower()
    if protocol in ROUTE_PROXY_PROTOCOL_CHOICES:
        return protocol
    if normalize_route_proxy_client(client) == ROUTE_PROXY_CLIENT_CLAUDE:
        return ROUTE_PROXY_PROTOCOL_ANTHROPIC
    return ROUTE_PROXY_PROTOCOL_OPENAI


def normalize_route_proxy_upstream_source(value: str | None) -> str:
    source = str(value or "").strip().lower()
    if source in ROUTE_PROXY_UPSTREAM_SOURCE_CHOICES:
        return source
    return ROUTE_PROXY_UPSTREAM_SOURCE_PROFILE


def normalize_route_proxy_port(value: int | str | None) -> int:
    try:
        port = int(value or ROUTE_PROXY_DEFAULT_PORT)
    except (TypeError, ValueError):
        port = ROUTE_PROXY_DEFAULT_PORT
    return max(1, min(65535, port))


def profile_supports_codex(profile: "Profile") -> bool:
    return profile.api_provided and profile.vendor in (VENDOR_CODEX, VENDOR_GENERIC)


def profile_supports_claude(profile: "Profile") -> bool:
    return profile.api_provided and profile.vendor in (VENDOR_CLAUDE, VENDOR_GENERIC)


def normalize_account_pool_wire_api(value: str | None) -> str:
    wire_api = str(value or "").strip().lower()
    if wire_api == "chat_completions":
        return "chat_completions"
    return "responses"


def normalize_account_pool_status(value: str | None) -> str:
    status = str(value or "").strip().lower()
    if status in ACCOUNT_POOL_CHANNEL_STATUS_CHOICES:
        return status
    return ACCOUNT_POOL_CHANNEL_STATUS_NORMAL


def normalize_account_pool_source_type(value: str | None) -> str:
    source_type = str(value or "").strip().lower()
    if source_type in ACCOUNT_POOL_CHANNEL_SOURCE_CHOICES:
        return source_type
    return ACCOUNT_POOL_CHANNEL_SOURCE_TEMPORARY


def normalize_account_pool_recovery_interval_minutes(value: int | str | None) -> int:
    try:
        minutes = int(value or DEFAULT_ACCOUNT_POOL_RECOVERY_INTERVAL_MINUTES)
    except (TypeError, ValueError):
        minutes = DEFAULT_ACCOUNT_POOL_RECOVERY_INTERVAL_MINUTES
    return max(
        ACCOUNT_POOL_RECOVERY_INTERVAL_MINUTES_MIN,
        min(ACCOUNT_POOL_RECOVERY_INTERVAL_MINUTES_MAX, minutes),
    )


def normalize_non_negative_int(value: int | str | None) -> int:
    try:
        parsed = int(value or 0)
    except (TypeError, ValueError):
        parsed = 0
    return max(0, parsed)


@dataclass
class AccountPoolGroup:
    id: str
    name: str
    enabled: bool = True
    next_index: int = 0

    @classmethod
    def create(cls, name: str = DEFAULT_ACCOUNT_POOL_GROUP_NAME) -> "AccountPoolGroup":
        return cls(id=str(uuid.uuid4()), name=name.strip() or DEFAULT_ACCOUNT_POOL_GROUP_NAME)

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "AccountPoolGroup":
        data = data or {}
        try:
            next_index = int(data.get("next_index", 0) or 0)
        except (TypeError, ValueError):
            next_index = 0
        return cls(
            id=str(data.get("id") or uuid.uuid4()),
            name=str(data.get("name") or DEFAULT_ACCOUNT_POOL_GROUP_NAME).strip() or DEFAULT_ACCOUNT_POOL_GROUP_NAME,
            enabled=bool(data.get("enabled", True)),
            next_index=max(0, next_index),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class AccountPoolChannel:
    id: str
    name: str
    base_url: str
    api_key: str
    group_id: str = ""
    source_type: str = ACCOUNT_POOL_CHANNEL_SOURCE_TEMPORARY
    source_profile_id: str = ""
    source_profile_name: str = ""
    source_api_key_index: int = 0
    wire_api: str = "responses"
    default_model: str = DEFAULT_CODEX_MODEL
    status: str = ACCOUNT_POOL_CHANNEL_STATUS_NORMAL
    failure_reason: str = ""
    failed_at: str | None = None
    last_success_at: str | None = None
    last_checked_at: str | None = None

    @classmethod
    def create(
        cls,
        *,
        name: str,
        base_url: str,
        api_key: str,
        group_id: str = "",
        source_type: str = ACCOUNT_POOL_CHANNEL_SOURCE_TEMPORARY,
        source_profile_id: str = "",
        source_profile_name: str = "",
        source_api_key_index: int = 0,
        wire_api: str = "responses",
        default_model: str = DEFAULT_CODEX_MODEL,
    ) -> "AccountPoolChannel":
        return cls(
            id=str(uuid.uuid4()),
            name=name.strip(),
            base_url=base_url.strip().rstrip("/"),
            api_key=api_key.strip(),
            group_id=group_id.strip(),
            source_type=normalize_account_pool_source_type(source_type),
            source_profile_id=source_profile_id.strip(),
            source_profile_name=source_profile_name.strip(),
            source_api_key_index=normalize_non_negative_int(source_api_key_index),
            wire_api=normalize_account_pool_wire_api(wire_api),
            default_model=default_model.strip() or DEFAULT_CODEX_MODEL,
        )

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "AccountPoolChannel":
        data = data or {}
        return cls(
            id=str(data.get("id") or uuid.uuid4()),
            name=str(data.get("name") or "").strip(),
            base_url=str(data.get("base_url") or "").strip().rstrip("/"),
            api_key=str(data.get("api_key") or "").strip(),
            group_id=str(data.get("group_id") or "").strip(),
            source_type=normalize_account_pool_source_type(data.get("source_type")),
            source_profile_id=str(data.get("source_profile_id") or "").strip(),
            source_profile_name=str(data.get("source_profile_name") or "").strip(),
            source_api_key_index=normalize_non_negative_int(data.get("source_api_key_index", 0)),
            wire_api=normalize_account_pool_wire_api(data.get("wire_api")),
            default_model=str(data.get("default_model") or DEFAULT_CODEX_MODEL).strip() or DEFAULT_CODEX_MODEL,
            status=normalize_account_pool_status(data.get("status")),
            failure_reason=str(data.get("failure_reason") or "").strip(),
            failed_at=data.get("failed_at"),
            last_success_at=data.get("last_success_at"),
            last_checked_at=data.get("last_checked_at"),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @property
    def is_normal(self) -> bool:
        return self.status == ACCOUNT_POOL_CHANNEL_STATUS_NORMAL

    @property
    def api_key_masked(self) -> str:
        return mask_secret(self.api_key)


@dataclass
class AccountPoolSettings:
    enabled: bool = False
    groups: list[AccountPoolGroup] = field(default_factory=list)
    selected_group_id: str = ""
    channels: list[AccountPoolChannel] = field(default_factory=list)
    next_index: int = 0
    last_recovery_checked_at: str | None = None
    recovery_interval_minutes: int = DEFAULT_ACCOUNT_POOL_RECOVERY_INTERVAL_MINUTES

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "AccountPoolSettings":
        if not isinstance(data, dict):
            settings = cls()
            settings.ensure_default_group()
            return settings
        raw_channels = data.get("channels", [])
        channels = [AccountPoolChannel.from_dict(item) for item in raw_channels] if isinstance(raw_channels, list) else []
        raw_groups = data.get("groups", [])
        groups = [AccountPoolGroup.from_dict(item) for item in raw_groups] if isinstance(raw_groups, list) else []
        try:
            next_index = int(data.get("next_index", 0) or 0)
        except (TypeError, ValueError):
            next_index = 0
        settings = cls(
            enabled=bool(data.get("enabled", False)),
            groups=groups,
            selected_group_id=str(data.get("selected_group_id") or "").strip(),
            channels=channels,
            next_index=max(0, next_index),
            last_recovery_checked_at=data.get("last_recovery_checked_at"),
            recovery_interval_minutes=normalize_account_pool_recovery_interval_minutes(
                data.get("recovery_interval_minutes")
            ),
        )
        settings.ensure_default_group()
        return settings

    def to_dict(self) -> dict[str, Any]:
        self.ensure_default_group()
        return {
            "enabled": self.enabled,
            "groups": [group.to_dict() for group in self.groups],
            "selected_group_id": self.selected_group_id,
            "channels": [channel.to_dict() for channel in self.channels],
            "next_index": self.next_index,
            "last_recovery_checked_at": self.last_recovery_checked_at,
            "recovery_interval_minutes": self.recovery_interval_minutes,
        }

    def ensure_default_group(self) -> AccountPoolGroup:
        if not self.groups:
            group = AccountPoolGroup.create()
            group.next_index = self.next_index
            self.groups.append(group)
        valid_group_ids = {group.id for group in self.groups}
        default_group = self.groups[0]
        for channel in self.channels:
            if channel.group_id not in valid_group_ids:
                channel.group_id = default_group.id
        if self.selected_group_id not in valid_group_ids:
            self.selected_group_id = default_group.id
        return default_group

    def group_by_id(self, group_id: str | None) -> AccountPoolGroup | None:
        self.ensure_default_group()
        if group_id:
            group = next((item for item in self.groups if item.id == group_id), None)
            if group is not None:
                return group
        return self.groups[0] if self.groups else None

    def add_group(self, name: str) -> AccountPoolGroup:
        group = AccountPoolGroup.create(name)
        self.groups.append(group)
        self.selected_group_id = group.id
        return group

    def remove_group(self, group_id: str) -> bool:
        self.ensure_default_group()
        if len(self.groups) <= 1:
            return False
        if any(channel.group_id == group_id for channel in self.channels):
            return False
        original_count = len(self.groups)
        self.groups = [group for group in self.groups if group.id != group_id]
        if len(self.groups) == original_count:
            return False
        if self.selected_group_id == group_id:
            self.selected_group_id = self.groups[0].id if self.groups else ""
        return True

    def channels_for_group(self, group_id: str | None) -> list[AccountPoolChannel]:
        group = self.group_by_id(group_id)
        if group is None:
            return []
        return [channel for channel in self.channels if channel.group_id == group.id]

    def normal_channels_for_group(self, group_id: str | None) -> list[AccountPoolChannel]:
        return [channel for channel in self.channels_for_group(group_id) if channel.is_normal]

    def failed_channels_for_group(self, group_id: str | None) -> list[AccountPoolChannel]:
        return [channel for channel in self.channels_for_group(group_id) if not channel.is_normal]

    @property
    def normal_channels(self) -> list[AccountPoolChannel]:
        return [channel for channel in self.channels if channel.is_normal]

    @property
    def failed_channels(self) -> list[AccountPoolChannel]:
        return [channel for channel in self.channels if not channel.is_normal]

    @property
    def normal_count(self) -> int:
        return len(self.normal_channels)

    @property
    def failed_count(self) -> int:
        return len(self.failed_channels)

    def take_next_normal_channel(
        self,
        exclude_ids: set[str] | None = None,
        *,
        group_id: str | None = None,
    ) -> AccountPoolChannel | None:
        excluded = exclude_ids or set()
        if group_id:
            group = self.group_by_id(group_id)
            if group is None:
                return None
            channels = self.channels_for_group(group.id)
            if not channels:
                group.next_index = 0
                return None
            channel_count = len(channels)
            start_index = group.next_index % channel_count
            for offset in range(channel_count):
                index = (start_index + offset) % channel_count
                channel = channels[index]
                if channel.is_normal and channel.id not in excluded:
                    group.next_index = (index + 1) % channel_count
                    return channel
            group.next_index = start_index
            return None

        if not self.channels:
            self.next_index = 0
            return None
        channel_count = len(self.channels)
        start_index = self.next_index % channel_count
        for offset in range(channel_count):
            index = (start_index + offset) % channel_count
            channel = self.channels[index]
            if channel.is_normal and channel.id not in excluded:
                self.next_index = (index + 1) % channel_count
                return channel
        self.next_index = start_index
        return None

    def mark_failed(self, channel_id: str, reason: str) -> None:
        timestamp = now_iso()
        for channel in self.channels:
            if channel.id == channel_id:
                channel.status = ACCOUNT_POOL_CHANNEL_STATUS_ERROR
                channel.failure_reason = reason.strip() or "上游不可用"
                channel.failed_at = timestamp
                channel.last_checked_at = timestamp
                return

    def mark_success(self, channel_id: str) -> None:
        timestamp = now_iso()
        for channel in self.channels:
            if channel.id == channel_id:
                channel.status = ACCOUNT_POOL_CHANNEL_STATUS_NORMAL
                channel.failure_reason = ""
                channel.failed_at = None
                channel.last_success_at = timestamp
                channel.last_checked_at = timestamp
                return

    def mark_recovered(self, channel_id: str) -> None:
        self.mark_success(channel_id)

    def replace_channel(self, updated: AccountPoolChannel) -> None:
        self.channels = [updated if channel.id == updated.id else channel for channel in self.channels]
        if self.channels:
            self.next_index = self.next_index % len(self.channels)
        else:
            self.next_index = 0

    def remove_channel(self, channel_id: str) -> None:
        self.channels = [channel for channel in self.channels if channel.id != channel_id]
        if self.channels:
            self.next_index = self.next_index % len(self.channels)
        else:
            self.next_index = 0

    def recovery_due(self, *, interval_seconds: int, now: datetime | None = None) -> bool:
        if not self.failed_channels:
            return False
        if not self.last_recovery_checked_at:
            return True
        try:
            last_checked = datetime.fromisoformat(self.last_recovery_checked_at)
        except (TypeError, ValueError):
            return True
        return ((now or datetime.now()) - last_checked).total_seconds() >= interval_seconds

    def mark_recovery_checked(self) -> None:
        self.last_recovery_checked_at = now_iso()


@dataclass
class RouteProxyRule:
    id: str
    project_id: str
    client_type: str
    model_pattern: str = "*"
    primary_profile_id: str = ""
    fallback_profile_ids: list[str] = field(default_factory=list)
    upstream_source: str = ROUTE_PROXY_UPSTREAM_SOURCE_PROFILE
    account_pool_group_id: str = ""
    upstream_protocol: str = ROUTE_PROXY_PROTOCOL_OPENAI
    upstream_model: str = ""
    compact_model: str = ""
    manual_upstream_protocol: bool = False
    enabled: bool = True

    @classmethod
    def create(
        cls,
        *,
        project_id: str,
        client_type: str,
        primary_profile_id: str,
        model_pattern: str = "*",
        fallback_profile_ids: list[str] | None = None,
        upstream_protocol: str | None = None,
        upstream_source: str | None = None,
        account_pool_group_id: str = "",
        upstream_model: str = "",
        compact_model: str = "",
        manual_upstream_protocol: bool = False,
        enabled: bool = True,
    ) -> "RouteProxyRule":
        normalized_client = normalize_route_proxy_client(client_type)
        return cls(
            id=str(uuid.uuid4()),
            project_id=project_id.strip(),
            client_type=normalized_client,
            model_pattern=model_pattern.strip() or "*",
            primary_profile_id=primary_profile_id.strip(),
            fallback_profile_ids=[item.strip() for item in (fallback_profile_ids or []) if item.strip()],
            upstream_source=normalize_route_proxy_upstream_source(upstream_source),
            account_pool_group_id=account_pool_group_id.strip(),
            upstream_protocol=normalize_route_proxy_protocol(upstream_protocol, normalized_client),
            upstream_model=upstream_model.strip(),
            compact_model=compact_model.strip(),
            manual_upstream_protocol=manual_upstream_protocol,
            enabled=enabled,
        )

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "RouteProxyRule":
        data = data or {}
        client_type = normalize_route_proxy_client(data.get("client_type"))
        raw_fallbacks = data.get("fallback_profile_ids", [])
        fallback_profile_ids = raw_fallbacks if isinstance(raw_fallbacks, list) else []
        return cls(
            id=str(data.get("id") or uuid.uuid4()),
            project_id=str(data.get("project_id") or "").strip(),
            client_type=client_type,
            model_pattern=str(data.get("model_pattern") or "*").strip() or "*",
            primary_profile_id=str(data.get("primary_profile_id") or "").strip(),
            fallback_profile_ids=[str(item).strip() for item in fallback_profile_ids if str(item).strip()],
            upstream_source=normalize_route_proxy_upstream_source(data.get("upstream_source")),
            account_pool_group_id=str(data.get("account_pool_group_id") or "").strip(),
            upstream_protocol=normalize_route_proxy_protocol(data.get("upstream_protocol"), client_type),
            upstream_model=str(data.get("upstream_model") or "").strip(),
            compact_model=str(data.get("compact_model") or "").strip(),
            manual_upstream_protocol=bool(data.get("manual_upstream_protocol", False)),
            enabled=bool(data.get("enabled", True)),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def matches(self, *, project_id: str, client_type: str, model: str | None = None) -> bool:
        if not self.enabled:
            return False
        if self.project_id != project_id:
            return False
        if self.client_type != normalize_route_proxy_client(client_type):
            return False
        candidate = (model or "").strip()
        pattern = self.model_pattern.strip() or "*"
        return pattern == "*" or fnmatch.fnmatchcase(candidate, pattern)

    @property
    def profile_ids(self) -> list[str]:
        ids = [self.primary_profile_id, *self.fallback_profile_ids]
        return [item for index, item in enumerate(ids) if item and item not in ids[:index]]


@dataclass
class RouteProxyEvent:
    timestamp: str
    level: str
    message: str
    project_id: str = ""
    client_type: str = ""
    profile_id: str = ""
    path: str = ""

    @classmethod
    def create(
        cls,
        *,
        level: str,
        message: str,
        project_id: str = "",
        client_type: str = "",
        profile_id: str = "",
        path: str = "",
    ) -> "RouteProxyEvent":
        return cls(
            timestamp=now_iso(),
            level=level,
            message=message,
            project_id=project_id,
            client_type=client_type,
            profile_id=profile_id,
            path=path,
        )

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "RouteProxyEvent":
        data = data or {}
        return cls(
            timestamp=str(data.get("timestamp") or now_iso()),
            level=str(data.get("level") or "info"),
            message=str(data.get("message") or ""),
            project_id=str(data.get("project_id") or ""),
            client_type=str(data.get("client_type") or ""),
            profile_id=str(data.get("profile_id") or ""),
            path=str(data.get("path") or ""),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class RouteProxySettings:
    enabled: bool = False
    host: str = ROUTE_PROXY_DEFAULT_HOST
    port: int = ROUTE_PROXY_DEFAULT_PORT
    rules: list[RouteProxyRule] = field(default_factory=list)
    events: list[RouteProxyEvent] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "RouteProxySettings":
        if not isinstance(data, dict):
            return cls()
        raw_rules = data.get("rules", [])
        raw_events = data.get("events", [])
        rules = [RouteProxyRule.from_dict(item) for item in raw_rules] if isinstance(raw_rules, list) else []
        events = [RouteProxyEvent.from_dict(item) for item in raw_events] if isinstance(raw_events, list) else []
        return cls(
            enabled=bool(data.get("enabled", False)),
            host=str(data.get("host") or ROUTE_PROXY_DEFAULT_HOST).strip() or ROUTE_PROXY_DEFAULT_HOST,
            port=normalize_route_proxy_port(data.get("port")),
            rules=rules,
            events=events[-50:],
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "host": self.host,
            "port": self.port,
            "rules": [rule.to_dict() for rule in self.rules],
            "events": [event.to_dict() for event in self.events[-50:]],
        }

    @property
    def base_url(self) -> str:
        return f"http://{self.host}:{self.port}"

    def project_base_url(self, project_id: str) -> str:
        return f"{self.base_url}/project/{project_id}"

    def project_enabled(self, project_id: str) -> bool:
        return any(rule.enabled and rule.project_id == project_id for rule in self.rules)

    def rules_for_project(self, project_id: str) -> list[RouteProxyRule]:
        return [rule for rule in self.rules if rule.project_id == project_id]

    def without_project_rules(self, project_id: str) -> "RouteProxySettings":
        return RouteProxySettings(
            enabled=self.enabled,
            host=self.host,
            port=self.port,
            rules=[rule for rule in self.rules if rule.project_id != project_id],
            events=list(self.events),
        )

    def append_event(self, event: RouteProxyEvent) -> None:
        self.events = [*self.events, event][-50:]


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
    category: str = PROFILE_CATEGORY_TEXT
    api_provided: bool = True
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
        category: str = PROFILE_CATEGORY_TEXT,
        api_provided: bool = True,
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
        normalized_category = normalize_profile_category(category)
        provides_api = bool(api_provided) if normalized_category == PROFILE_CATEGORY_IMAGE_GENERATION else True
        if not provides_api:
            normalized_keys = []
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
            category=normalized_category,
            api_provided=provides_api,
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
        category = normalize_profile_category(data.get("category"))
        api_provided = bool(data.get("api_provided", True)) if category == PROFILE_CATEGORY_IMAGE_GENERATION else True
        if not api_provided:
            api_keys = []
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
            category=category,
            api_provided=api_provided,
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
        payload["category"] = normalize_profile_category(self.category)
        payload["api_provided"] = bool(self.api_provided) if payload["category"] == PROFILE_CATEGORY_IMAGE_GENERATION else True
        if not payload["api_provided"]:
            payload["api_keys"] = []
            payload["active_api_key_index"] = 0
            payload["api_key"] = ""
        return payload

    @property
    def effective_active_api_key_index(self) -> int:
        return normalize_api_key_index(self.api_keys, self.active_api_key_index)

    @property
    def api_key(self) -> str:
        if not self.api_provided:
            return ""
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
        if self.vendor == VENDOR_OTHER:
            return VENDOR_OTHER
        return VENDOR_GENERIC

    @property
    def category_label(self) -> str:
        return PROFILE_CATEGORY_LABELS.get(normalize_profile_category(self.category), "文本")


@dataclass
class SkillDefinition:
    id: str
    name: str
    type: str = "script"
    content: str = ""
    version: str = "1.0.0"
    source_path: str = ""

    @classmethod
    def create(
        cls,
        name: str,
        *,
        type: str = "script",
        content: str = "",
        version: str = "1.0.0",
        source_path: str = "",
    ) -> "SkillDefinition":
        return cls(
            id=str(uuid.uuid4()),
            name=name.strip(),
            type=type.strip() or "script",
            content=content.strip(),
            version=version.strip() or "1.0.0",
            source_path=str(source_path or "").strip(),
        )

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SkillDefinition":
        return cls(
            id=str(data.get("id") or uuid.uuid4()),
            name=str(data.get("name") or "").strip(),
            type=str(data.get("type") or "script").strip() or "script",
            content=str(data.get("content") or ""),
            version=str(data.get("version") or "1.0.0").strip() or "1.0.0",
            source_path=str(data.get("source_path") or "").strip(),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class SkillGroup:
    id: str
    name: str
    description: str = ""
    skills: list[SkillDefinition] = field(default_factory=list)

    @classmethod
    def create(
        cls,
        name: str,
        *,
        description: str = "",
        skills: list[SkillDefinition] | None = None,
    ) -> "SkillGroup":
        return cls(
            id=str(uuid.uuid4()),
            name=name.strip(),
            description=description.strip(),
            skills=list(skills or []),
        )

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SkillGroup":
        raw_skills = data.get("skills", [])
        skills = [
            SkillDefinition.from_dict(item)
            for item in raw_skills
            if isinstance(item, dict)
        ] if isinstance(raw_skills, list) else []
        return cls(
            id=str(data.get("id") or uuid.uuid4()),
            name=str(data.get("name") or "未命名组").strip() or "未命名组",
            description=str(data.get("description") or "").strip(),
            skills=skills,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "skills": [skill.to_dict() for skill in self.skills],
        }


@dataclass
class SkillMarketRepo:
    id: str
    url: str
    branch: str = "main"
    last_sync_commit: str = ""
    auto_update: bool = False

    @classmethod
    def create(
        cls,
        url: str,
        *,
        branch: str = "main",
        last_sync_commit: str = "",
        auto_update: bool = False,
    ) -> "SkillMarketRepo":
        return cls(
            id=str(uuid.uuid4()),
            url=url.strip(),
            branch=branch.strip() or "main",
            last_sync_commit=last_sync_commit.strip(),
            auto_update=bool(auto_update),
        )

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SkillMarketRepo":
        return cls(
            id=str(data.get("id") or uuid.uuid4()),
            url=str(data.get("url") or "").strip(),
            branch=str(data.get("branch") or "main").strip() or "main",
            last_sync_commit=str(data.get("last_sync_commit") or "").strip(),
            auto_update=bool(data.get("auto_update", False)),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


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
    skill_names: list[str] | None = None
    skill_group_ids: list[str] | None = None
    skills: list[SkillDefinition] = field(default_factory=list)
    github_repo: str = ""

    @classmethod
    def create(
        cls,
        project_dir: str,
        profile_id: str,
        name: str | None = None,
        run_command: str = "",
        mcp_server_names: list[str] | None = None,
        skill_names: list[str] | None = None,
        skill_group_ids: list[str] | None = None,
        skills: list[SkillDefinition] | None = None,
        github_repo: str = "",
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
            skill_names=list(skill_names) if skill_names is not None else None,
            skill_group_ids=list(skill_group_ids) if skill_group_ids is not None else None,
            skills=list(skills or []),
            github_repo=github_repo.strip(),
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
        raw_skill_names = data.get("skill_names")
        skill_names = None
        if isinstance(raw_skill_names, list):
            skill_names = [
                str(item).strip()
                for item in raw_skill_names
                if str(item).strip()
            ]
        raw_skill_group_ids = data.get("skill_group_ids")
        skill_group_ids = None
        if isinstance(raw_skill_group_ids, list):
            skill_group_ids = [
                str(item).strip()
                for item in raw_skill_group_ids
                if str(item).strip()
            ]
        raw_skills = data.get("skills")
        skills = [
            SkillDefinition.from_dict(item)
            for item in raw_skills
            if isinstance(item, dict)
        ] if isinstance(raw_skills, list) else []
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
            skill_names=skill_names,
            skill_group_ids=skill_group_ids,
            skills=skills,
            github_repo=str(data.get("github_repo", "") or "").strip(),
        )

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["skills"] = [skill.to_dict() for skill in self.skills]
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
    mcp_server_names: list[str]

    @property
    def api_key_masked(self) -> str:
        return mask_secret(self.api_key or "")

    @property
    def api_key_loaded(self) -> bool:
        return bool(self.api_key)
