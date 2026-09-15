"""Form schemas and payload conversion for drawer editors.

A form is a list of QML-friendly field descriptors; a submitted payload is a
flat dict that gets converted here into the exact argument shape the existing
business helpers (``profile_from_dialog_result`` etc.) expect.
"""

from __future__ import annotations

from typing import Any

from ..models import (
    ACCOUNT_POOL_GROUP_TYPE_CHOICES,
    ACCOUNT_POOL_GROUP_TYPE_LABELS,
    PROFILE_CATEGORY_CHOICES,
    PROFILE_CATEGORY_LABELS,
    PROFILE_VENDOR_CHOICES,
    SKILL_TYPE_CHOICES,
    SKILL_TYPE_LABELS,
    VENDOR_GENERIC,
    AccountPoolChannel,
    AccountPoolGroup,
    Profile,
    ProjectRecord,
    SkillDefinition,
    SkillGroup,
    SkillMarketRepo,
    custom_headers_to_text,
    normalize_api_key_index,
    normalize_api_keys,
    parse_custom_headers_text,
)
from ..chat import SUPPORTED_WIRE_APIS
from .errors import FormError

VENDOR_LABELS = {"codex": "Codex", "claude": "Claude", VENDOR_GENERIC: "通用", "其他": "其他"}


def _choice(options: list[tuple[str, str]], value: str) -> dict[str, Any]:
    return {
        "options": [{"value": key, "label": label} for key, label in options],
        "value": value,
    }


def _text(key: str, label: str, value: Any = "", **extra: Any) -> dict[str, Any]:
    return {"key": key, "label": label, "type": "text", "value": str(value or ""), **extra}


def _payload_str(payload: dict[str, Any], key: str, default: str = "") -> str:
    return str(payload.get(key, default) or "").strip()


def _payload_bool(payload: dict[str, Any], key: str, default: bool = False) -> bool:
    value = payload.get(key, default)
    if isinstance(value, str):
        return value.strip().casefold() in {"1", "true", "yes", "on", "是"}
    return bool(value)


def _payload_list(payload: dict[str, Any], key: str) -> list[str]:
    value = payload.get(key)
    if value is None:
        return []
    if isinstance(value, str):
        return [item.strip() for item in value.splitlines() if item.strip()]
    if isinstance(value, (list, tuple)):
        return [str(item).strip() for item in value if str(item).strip()]
    return []


# -- profile -------------------------------------------------------------
def profile_form(profile: Profile | None = None) -> list[dict[str, Any]]:
    return [
        _text("name", "名称", getattr(profile, "name", "")),
        {
            "key": "vendor",
            "label": "供应商",
            "type": "choice",
            **_choice(
                [(item, VENDOR_LABELS.get(item, item)) for item in PROFILE_VENDOR_CHOICES],
                getattr(profile, "vendor", VENDOR_GENERIC),
            ),
        },
        {
            "key": "category",
            "label": "类别",
            "type": "choice",
            **_choice(
                [(item, PROFILE_CATEGORY_LABELS.get(item, item)) for item in PROFILE_CATEGORY_CHOICES],
                getattr(profile, "category", "text"),
            ),
        },
        _text("providerName", "Provider", getattr(profile, "provider_name", "OpenAI")),
        _text("baseUrl", "API 地址", getattr(profile, "base_url", ""), placeholder="https://api.example.com"),
        {
            "key": "apiKeysText",
            "label": "API Keys（每行一个）",
            "type": "textarea",
            "value": "\n".join(getattr(profile, "api_keys", None) or []),
        },
        {
            "key": "activeKeyIndex",
            "label": "活动 Key 序号（从 0 开始）",
            "type": "number",
            "value": getattr(profile, "active_api_key_index", 0),
        },
        {
            "key": "wireApi",
            "label": "接口标准",
            "type": "choice",
            **_choice([(item, item) for item in SUPPORTED_WIRE_APIS], getattr(profile, "wire_api", "responses")),
        },
        _text("codexModel", "Codex 模型", getattr(profile, "codex_model", "")),
        _text("claudeModel", "Claude 模型", getattr(profile, "claude_model", "")),
        _text("claudeFallbackModel", "Claude 兜底模型", getattr(profile, "claude_fallback_model", "")),
        {
            "key": "customHeadersText",
            "label": "自定义请求头（每行 Name: Value）",
            "type": "textarea",
            "value": custom_headers_to_text(getattr(profile, "custom_headers", None) or {}),
        },
        {"key": "requiresOpenaiAuth", "label": "需要 OpenAI Auth", "type": "switch",
         "value": bool(getattr(profile, "requires_openai_auth", True))},
        {"key": "apiProvided", "label": "提供 API", "type": "switch",
         "value": bool(getattr(profile, "api_provided", True))},
        {"key": "requiresSignIn", "label": "需要签到", "type": "switch",
         "value": bool(getattr(profile, "requires_sign_in", False))},
        _text("signInUrl", "签到地址", getattr(profile, "sign_in_url", "")),
        {"key": "notes", "label": "备注", "type": "textarea", "value": getattr(profile, "notes", "")},
    ]


def profile_payload(payload: dict[str, Any], existing: Profile | None = None) -> dict[str, Any]:
    """Convert a form payload into the dict shape ``Profile.create`` expects.

    ``existing`` lets an edit preserve fields the form does not expose (the
    sign-in date), matching the legacy dialog contract that
    ``updated_profile_from_dialog`` relies on.
    """
    name = _payload_str(payload, "name")
    if not name:
        raise FormError("请填写配置名称。")

    api_provided = _payload_bool(payload, "apiProvided", True)
    base_url = _payload_str(payload, "baseUrl")
    if api_provided:
        if not base_url:
            raise FormError("请填写 API 地址。")
        if not base_url.startswith(("http://", "https://")):
            raise FormError("API 地址必须以 http:// 或 https:// 开头。")

    api_keys = normalize_api_keys(_payload_list(payload, "apiKeysText"))
    if api_provided and not api_keys:
        raise FormError("请输入至少一个 API Key。")

    raw_headers = str(payload.get("customHeadersText", "") or "")
    custom_headers, header_errors = parse_custom_headers_text(raw_headers)
    if api_provided and header_errors:
        raise FormError("自定义请求头无效：" + "；".join(header_errors))

    requires_sign_in = _payload_bool(payload, "requiresSignIn", False)
    sign_in_url = _payload_str(payload, "signInUrl")
    if requires_sign_in and sign_in_url and not sign_in_url.startswith(("http://", "https://")):
        raise FormError("签到地址必须以 http:// 或 https:// 开头。")

    codex_model = _payload_str(payload, "codexModel")
    claude_model = _payload_str(payload, "claudeModel")
    claude_fallback_model = _payload_str(payload, "claudeFallbackModel")
    vendor = _payload_str(payload, "vendor", VENDOR_GENERIC)

    if vendor == "codex" and not codex_model:
        raise FormError("请填写 Codex 默认模型。")
    if vendor == "claude" and (not claude_model or not claude_fallback_model):
        raise FormError("请填写 Claude 默认模型和兜底模型。")
    if vendor == VENDOR_GENERIC and (not codex_model or not claude_model or not claude_fallback_model):
        raise FormError("通用配置需要填写三项模型。")

    try:
        active_index = int(payload.get("activeKeyIndex", 0) or 0)
    except (TypeError, ValueError):
        active_index = 0
    active_index = normalize_api_key_index(api_keys, active_index) if api_provided else 0

    return {
        "name": name,
        "base_url": base_url.rstrip("/") if api_provided else "",
        "api_key": api_keys[active_index] if api_provided and api_keys else "",
        "api_keys": api_keys if api_provided else [],
        "active_api_key_index": active_index,
        "model": codex_model,
        "vendor": vendor,
        "codex_model": codex_model,
        "claude_model": claude_model,
        "claude_fallback_model": claude_fallback_model,
        "provider_name": _payload_str(payload, "providerName") or "OpenAI",
        "category": _payload_str(payload, "category", "text") or "text",
        "api_provided": api_provided,
        "wire_api": _payload_str(payload, "wireApi", "responses") or "responses",
        "custom_headers": custom_headers if api_provided else {},
        "requires_openai_auth": _payload_bool(payload, "requiresOpenaiAuth", True),
        "requires_sign_in": requires_sign_in,
        "sign_in_url": sign_in_url if requires_sign_in else "",
        # Preserved from the existing record: the drawer has no date input.
        "last_signed_date": getattr(existing, "last_signed_date", None) if requires_sign_in else None,
        "notes": str(payload.get("notes", "") or "").strip(),
    }


# -- project -------------------------------------------------------------
def project_form(
    project: ProjectRecord | None,
    *,
    profiles: list[Profile],
    skill_groups: list[SkillGroup],
    mcp_names: list[str],
) -> list[dict[str, Any]]:
    profile_choices = [("", "未选择")] + [(item.id, item.name) for item in profiles]
    group_choices = [(item.id, item.name) for item in skill_groups]
    return [
        _text("name", "项目名称", getattr(project, "name", "")),
        {
            "key": "projectDir",
            "label": "项目目录",
            "type": "path",
            "value": getattr(project, "project_dir", ""),
            "directory": True,
        },
        {
            "key": "codexProfileId",
            "label": "Codex 配置",
            "type": "choice",
            **_choice(profile_choices, getattr(project, "codex_profile_id", "") or getattr(project, "profile_id", "")),
        },
        {
            "key": "claudeProfileId",
            "label": "Claude 配置",
            "type": "choice",
            **_choice(profile_choices, getattr(project, "claude_profile_id", "")),
        },
        _text("runCommand", "运行命令", getattr(project, "run_command", "")),
        {
            "key": "mcpServerNames",
            "label": "项目 MCP",
            "type": "multichoice",
            "options": [{"value": name, "label": name} for name in mcp_names],
            "values": list(getattr(project, "mcp_server_names", None) or []),
        },
        {
            "key": "skillGroupIds",
            "label": "Skills 组",
            "type": "multichoice",
            "options": [{"value": key, "label": label} for key, label in group_choices],
            "values": list(getattr(project, "skill_group_ids", None) or []),
        },
        _text("githubRepo", "GitHub 仓库", getattr(project, "github_repo", "")),
        _text("githubRef", "Git 引用", getattr(project, "github_ref", "HEAD")),
        {"key": "githubAutoUpdate", "label": "自动更新", "type": "switch",
         "value": bool(getattr(project, "github_auto_update", False))},
    ]


def project_payload(payload: dict[str, Any]) -> dict[str, Any]:
    project_dir = _payload_str(payload, "projectDir")
    if not project_dir:
        raise FormError("请选择项目目录。")

    codex_profile_id = _payload_str(payload, "codexProfileId")
    claude_profile_id = _payload_str(payload, "claudeProfileId")
    if not codex_profile_id and not claude_profile_id:
        raise FormError("请至少为项目选择一套 Codex 或 Claude 配置。")

    github_repo = _payload_str(payload, "githubRepo")
    github_ref = _payload_str(payload, "githubRef", "HEAD") or "HEAD"
    if github_repo and not github_repo.startswith("https://github.com/"):
        raise FormError("GitHub 地址必须是 https://github.com/owner/repo 形式。")

    return {
        "name": _payload_str(payload, "name"),
        "project_dir": project_dir,
        "profile_id": codex_profile_id or claude_profile_id,
        "codex_profile_id": codex_profile_id,
        "claude_profile_id": claude_profile_id,
        "run_command": _payload_str(payload, "runCommand"),
        "github_repo": github_repo,
        "github_ref": github_ref if github_repo else "HEAD",
        "github_auto_update": _payload_bool(payload, "githubAutoUpdate") if github_repo else False,
        "mcp_server_names": _payload_list(payload, "mcpServerNames"),
        "skill_names": None,
        "skill_group_ids": _payload_list(payload, "skillGroupIds"),
        "skills": [],
    }


# -- MCP -----------------------------------------------------------------
def mcp_form(name: str = "", config: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    config = config or {}
    args = config.get("args", [])
    env = config.get("env", {})
    return [
        _text("name", "名称", name),
        _text("type", "类型", str(config.get("type", "stdio") or "stdio")),
        _text("command", "命令", str(config.get("command", "") or "")),
        {
            "key": "argsText",
            "label": "参数（每行一个）",
            "type": "textarea",
            "value": "\n".join(str(item) for item in args) if isinstance(args, list) else "",
        },
        _text("cwd", "工作目录", str(config.get("cwd", "") or "")),
        {
            "key": "envText",
            "label": "环境变量（每行 KEY=VALUE）",
            "type": "textarea",
            "value": "\n".join(f"{key}={value}" for key, value in env.items()) if isinstance(env, dict) else "",
        },
    ]


def mcp_payload(payload: dict[str, Any], *, default_type: str = "stdio", default_args: list[str] | None = None,
                default_env: dict[str, str] | None = None) -> tuple[str, dict[str, Any]]:
    name = _payload_str(payload, "name")
    if not name:
        raise FormError("请填写 MCP 名称。")

    command = _payload_str(payload, "command")
    if not command:
        raise FormError("请填写 MCP 启动命令。")

    config: dict[str, Any] = {
        "type": _payload_str(payload, "type") or default_type or "stdio",
        "command": command,
    }

    args = _payload_list(payload, "argsText")
    if not args and default_args:
        args = list(default_args)
    config["args"] = args

    cwd = _payload_str(payload, "cwd")
    if cwd:
        config["cwd"] = cwd

    env: dict[str, str] = {}
    for line in str(payload.get("envText", "") or "").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if key:
            env[key] = value.strip()
    if not env and default_env:
        env = dict(default_env)
    if env:
        config["env"] = env

    return name, config


# -- skills --------------------------------------------------------------
def skill_group_form(group: SkillGroup | None = None) -> list[dict[str, Any]]:
    return [
        _text("name", "组名", getattr(group, "name", "")),
        {"key": "description", "label": "描述", "type": "textarea", "value": getattr(group, "description", "")},
    ]


def skill_group_payload(payload: dict[str, Any]) -> dict[str, str]:
    name = _payload_str(payload, "name")
    if not name:
        raise FormError("请填写 Skills 组名。")
    return {"name": name, "description": str(payload.get("description", "") or "").strip()}


def skill_form(skill: SkillDefinition | None = None) -> list[dict[str, Any]]:
    return [
        _text("name", "Skill 名称", getattr(skill, "name", "")),
        {
            "key": "type",
            "label": "类型",
            "type": "choice",
            **_choice(
                [(item, SKILL_TYPE_LABELS.get(item, item)) for item in SKILL_TYPE_CHOICES],
                getattr(skill, "type", "script"),
            ),
        },
        _text("version", "版本", getattr(skill, "version", "1.0.0")),
        {"key": "content", "label": "内容", "type": "textarea", "value": getattr(skill, "content", "")},
    ]


def skill_payload(payload: dict[str, Any]) -> dict[str, str]:
    name = _payload_str(payload, "name")
    if not name:
        raise FormError("请填写 Skill 名称。")
    return {
        "name": name,
        "type": _payload_str(payload, "type", "script") or "script",
        "version": _payload_str(payload, "version", "1.0.0") or "1.0.0",
        "content": str(payload.get("content", "") or ""),
    }


def skill_repo_form(repo: SkillMarketRepo | None = None) -> list[dict[str, Any]]:
    return [
        _text("url", "仓库地址", getattr(repo, "url", "")),
        _text("branch", "分支", getattr(repo, "branch", "main")),
        {"key": "autoUpdate", "label": "自动更新", "type": "switch", "value": bool(getattr(repo, "auto_update", False))},
    ]


def skill_repo_payload(payload: dict[str, Any]) -> dict[str, Any]:
    url = _payload_str(payload, "url")
    if not url:
        raise FormError("请填写仓库地址。")
    if not url.startswith("https://github.com/"):
        raise FormError("仓库地址必须是 https://github.com/owner/repo 形式。")
    return {
        "url": url,
        "branch": _payload_str(payload, "branch", "main") or "main",
        "auto_update": _payload_bool(payload, "autoUpdate"),
    }


# -- account pool --------------------------------------------------------
def pool_group_form(group: AccountPoolGroup | None = None) -> list[dict[str, Any]]:
    return [
        _text("name", "组名", getattr(group, "name", "")),
        {"key": "enabled", "label": "启用", "type": "switch", "value": bool(getattr(group, "enabled", True))},
        {
            "key": "poolType",
            "label": "类型",
            "type": "choice",
            **_choice(
                [(item, ACCOUNT_POOL_GROUP_TYPE_LABELS.get(item, item)) for item in ACCOUNT_POOL_GROUP_TYPE_CHOICES],
                getattr(group, "pool_type", "codex"),
            ),
        },
        _text("defaultModel", "默认 Codex 模型", getattr(group, "default_model", "")),
        _text("claudeModel", "Claude 模型", getattr(group, "claude_model", "")),
        _text("claudeFallbackModel", "Claude 兜底模型", getattr(group, "claude_fallback_model", "")),
    ]


def pool_group_payload(payload: dict[str, Any]) -> dict[str, Any]:
    name = _payload_str(payload, "name")
    if not name:
        raise FormError("请填写号池组名。")
    return {
        "name": name,
        "enabled": _payload_bool(payload, "enabled", True),
        "pool_type": _payload_str(payload, "poolType", "codex") or "codex",
        "default_model": _payload_str(payload, "defaultModel"),
        "claude_model": _payload_str(payload, "claudeModel"),
        "claude_fallback_model": _payload_str(payload, "claudeFallbackModel"),
    }


def pool_channel_form(channel: AccountPoolChannel | None = None) -> list[dict[str, Any]]:
    return [
        _text("name", "渠道名称", getattr(channel, "name", "")),
        _text("baseUrl", "API 地址", getattr(channel, "base_url", "")),
        {"key": "apiKey", "label": "API Key", "type": "password", "value": getattr(channel, "api_key", "")},
        {
            "key": "wireApi",
            "label": "接口标准",
            "type": "choice",
            **_choice([(item, item) for item in SUPPORTED_WIRE_APIS], getattr(channel, "wire_api", "responses")),
        },
        _text("defaultModel", "默认模型", getattr(channel, "default_model", "")),
    ]


def pool_channel_payload(payload: dict[str, Any]) -> dict[str, Any]:
    name = _payload_str(payload, "name")
    base_url = _payload_str(payload, "baseUrl")
    api_key = _payload_str(payload, "apiKey")
    if not name:
        raise FormError("请填写渠道名称。")
    if not base_url:
        raise FormError("请填写渠道 API 地址。")
    if not base_url.startswith(("http://", "https://")):
        raise FormError("API 地址必须以 http:// 或 https:// 开头。")
    if not api_key:
        raise FormError("请填写渠道 API Key。")
    return {
        "name": name,
        "base_url": base_url.rstrip("/"),
        "api_key": api_key,
        "wire_api": _payload_str(payload, "wireApi", "responses") or "responses",
        "default_model": _payload_str(payload, "defaultModel"),
    }


__all__ = [
    "FormError",
    "VENDOR_LABELS",
    "mcp_form",
    "mcp_payload",
    "pool_channel_form",
    "pool_channel_payload",
    "pool_group_form",
    "pool_group_payload",
    "profile_form",
    "profile_payload",
    "project_form",
    "project_payload",
    "skill_form",
    "skill_group_form",
    "skill_group_payload",
    "skill_payload",
    "skill_repo_form",
    "skill_repo_payload",
]
