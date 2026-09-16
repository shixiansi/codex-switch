"""Pure functions turning business objects into QML-friendly dictionaries.

Snapshots are plain, immutable-ish dicts with camelCase keys. QML never sees a
``Profile``/``ProjectRecord`` instance, so it cannot mutate business state.
"""

from __future__ import annotations

from typing import Any, Iterable

from ..models import (
    ACCOUNT_POOL_CHANNEL_STATUS_NORMAL,
    AccountPoolChannel,
    AccountPoolGroup,
    AccountPoolSettings,
    DEFAULT_CLAUDE_FALLBACK_MODEL,
    DEFAULT_CLAUDE_MODEL,
    DEFAULT_CODEX_MODEL,
    HotUpdateEvent,
    Profile,
    ProjectRecord,
    RouteProxyEvent,
    RouteProxySettings,
    SCRIPT_KIND_LABELS,
    SCRIPT_RUN_MODE_LABELS,
    SkillDefinition,
    SkillGroup,
    SkillMarketRepo,
    custom_headers_to_text,
    mask_secret,
    model_vendor_stats,
    today_iso,
)
from ..ui.account_pool_logic import account_pool_group_label
from ..ui.library_logic import health_status_text
from ..ui.model_batch_logic import ModelBatchCache, successful_model_batch_models
from ..ui.route_proxy_logic import ROUTE_PROXY_ACCOUNT_POOL_STRATEGY_LABELS
from ..ui.utils import compact_text

HEALTH_LABELS = {
    "healthy": "健康",
    "degraded": "受限",
    "restricted": "受限",
    "error": "异常",
    "unknown": "未检测",
}

# Tone names understood by Theme.qml.
HEALTH_TONES = {
    "healthy": "success",
    "degraded": "warning",
    "restricted": "warning",
    "error": "danger",
    "unknown": "unknown",
}


def health_label(status: str, *, manual: bool = False) -> str:
    label = HEALTH_LABELS.get(str(status or "unknown"), "未检测")
    return f"{label}（手动）" if manual else label


def health_tone(status: str) -> str:
    return HEALTH_TONES.get(str(status or "unknown"), "unknown")


def _as_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


# -- profiles ------------------------------------------------------------
def profile_row(profile: Profile) -> dict[str, Any]:
    status = str(getattr(profile, "effective_health_status", "unknown") or "unknown")
    models = list(getattr(profile.health, "models", []) or [])
    return {
        "id": profile.id,
        "name": profile.name,
        "vendor": profile.vendor,
        "vendorLabel": profile.vendor_label,
        "category": profile.category,
        "categoryLabel": profile.category_label,
        "model": profile.codex_display_model or profile.claude_display_model or profile.model,
        "codexModel": profile.codex_display_model,
        "claudeModel": profile.claude_display_model,
        "claudeFallbackModel": profile.claude_display_fallback_model,
        "baseUrl": profile.base_url,
        "providerName": profile.provider_name,
        "wireApi": profile.wire_api,
        "apiProvided": bool(profile.api_provided),
        "apiKeyCount": len(profile.api_keys or []),
        "apiKeyMasked": mask_secret(profile.api_key),
        "activeKeyIndex": profile.effective_active_api_key_index,
        "health": status,
        "healthLabel": health_status_text(profile, HEALTH_LABELS),
        "healthTone": health_tone(status),
        "healthDetail": str(getattr(profile.health, "detail", "") or ""),
        "healthCheckedAt": str(getattr(profile.health, "checked_at", "") or ""),
        "latencyMs": getattr(profile.health, "latency_ms", None),
        "models": models,
        "modelCount": len(models),
        "notes": profile.notes,
        "requiresSignIn": bool(profile.requires_sign_in),
        "signInUrl": profile.sign_in_url,
        "signInStatus": str(profile.sign_in_status),
        "signedToday": bool(
            profile.requires_sign_in and profile.last_signed_date == today_iso()
        ),
        "lastSignedDate": profile.last_signed_date or "",
    }


def profile_detail(profile: Profile) -> dict[str, Any]:
    """Editable representation: includes full secret text for the drawer."""
    snapshot = profile_row(profile)
    snapshot.update(
        {
            "apiKeysText": "\n".join(profile.api_keys or []),
            "customHeadersText": custom_headers_to_text(profile.custom_headers or {}),
            "requiresOpenaiAuth": bool(profile.requires_openai_auth),
            "lastSignedDate": profile.last_signed_date or "",
            "manualHealthStatus": profile.manual_health_status or "",
            "vendorChoices": ["codex", "claude", "通用", "其他"],
            "categoryChoices": ["text", "image_generation"],
            "wireApiChoices": ["responses", "chat_completions", "anthropic_messages"],
        }
    )
    return snapshot


def profile_choice_rows(profiles: Iterable[Profile], selected_id: str | None) -> list[dict[str, Any]]:
    return [
        {"id": item.id, "name": item.name, "vendorLabel": item.vendor_label, "selected": item.id == selected_id}
        for item in profiles
    ]


def vendor_stats(models: Iterable[str]) -> list[dict[str, Any]]:
    counts = model_vendor_stats([str(item) for item in models])
    total = sum(counts.values()) or 1
    rows = []
    for vendor, count in sorted(counts.items(), key=lambda item: (-item[1], item[0])):
        rows.append({"vendor": vendor, "count": count, "ratio": count / total})
    return rows


# -- projects ------------------------------------------------------------
def project_row(project: ProjectRecord) -> dict[str, Any]:
    return {
        "id": project.id,
        "name": project.name,
        "projectDir": project.project_dir,
        "profileId": project.profile_id,
        "codexProfileId": project.codex_profile_id,
        "claudeProfileId": project.claude_profile_id,
        "runCommand": project.run_command,
        "githubRepo": project.github_repo,
        "githubRef": project.github_ref,
        "githubAutoUpdate": bool(project.github_auto_update),
        "mcpServerNames": list(project.mcp_server_names or []),
        "skillGroupIds": list(project.skill_group_ids or []),
        "skillCount": len(project.skills or []),
        "hasGithub": bool(project.github_repo),
    }


def project_detail(project: ProjectRecord, *, codex_profile: Profile | None, claude_profile: Profile | None) -> dict[str, Any]:
    snapshot = project_row(project)
    snapshot.update(
        {
            "codexProfileName": codex_profile.name if codex_profile else "未绑定",
            "claudeProfileName": claude_profile.name if claude_profile else "未绑定",
            "codexModel": codex_profile.codex_display_model if codex_profile else "-",
            "claudeModel": claude_profile.claude_display_model if claude_profile else "-",
            "codexKey": mask_secret(codex_profile.api_key) if codex_profile else "-",
            "claudeKey": mask_secret(claude_profile.api_key) if claude_profile else "-",
            "mcpText": ", ".join(project.mcp_server_names or []) or "未选择",
            "skillsText": ", ".join(item.name for item in (project.skills or [])) or "未选择",
            "githubText": _github_label(project),
        }
    )
    return snapshot


def _github_label(project: ProjectRecord) -> str:
    if not project.github_repo:
        return "未配置"
    ref = (project.github_ref or "HEAD").strip() or "HEAD"
    return f"{project.github_repo} @ {ref}"


# -- proxy ---------------------------------------------------------------
def proxy_status(settings: RouteProxySettings, *, running: bool) -> dict[str, Any]:
    usage = settings.token_usage
    today = usage.by_day.get(today_iso())
    return {
        "enabled": bool(settings.enabled),
        "running": bool(running),
        "host": settings.host,
        "port": settings.port,
        "baseUrl": settings.base_url,
        "strategy": settings.account_pool_strategy,
        "strategyLabel": ROUTE_PROXY_ACCOUNT_POOL_STRATEGY_LABELS.get(
            settings.account_pool_strategy, settings.account_pool_strategy
        ),
        "upstreamTimeoutSeconds": settings.upstream_timeout_seconds,
        "totalTokens": _as_int(usage.total.total_tokens),
        "todayTokens": _as_int(getattr(today, "total_tokens", 0)),
        "projectCount": len(usage.by_project),
        "apiCount": len(usage.by_api),
        "ruleCount": len(settings.rules),
        "eventCount": len(settings.events),
    }


def usage_rows(buckets: Any) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for bucket in (buckets or {}).values() if isinstance(buckets, dict) else (buckets or []):
        rows.append(
            {
                "key": str(getattr(bucket, "key", "") or ""),
                "label": str(getattr(bucket, "label", "") or ""),
                "totalTokens": _as_int(getattr(bucket, "total_tokens", 0)),
                "inputTokens": _as_int(getattr(bucket, "input_tokens", 0)),
                "outputTokens": _as_int(getattr(bucket, "output_tokens", 0)),
                "requests": _as_int(getattr(bucket, "requests", 0)),
            }
        )
    rows.sort(key=lambda item: item["totalTokens"], reverse=True)
    return rows


def event_row(event: RouteProxyEvent | HotUpdateEvent | Any, *, source: str) -> dict[str, Any]:
    if hasattr(event, "to_dict"):
        payload = dict(event.to_dict())
    else:
        payload = {
            "timestamp": getattr(event, "timestamp", ""),
            "level": getattr(event, "level", "info"),
            "message": getattr(event, "message", str(event)),
        }
    level = str(payload.get("level") or payload.get("status") or "info")
    tone = {"error": "danger", "warning": "warning", "warn": "warning"}.get(level.casefold(), "info")
    message = payload.get("message") or payload.get("target") or ""
    return {
        "timestamp": str(payload.get("timestamp") or payload.get("created_at") or ""),
        "level": level,
        "tone": tone,
        "message": str(message),
        "detail": str(payload.get("detail") or payload.get("path") or ""),
        "target": str(payload.get("target") or payload.get("project_id") or ""),
        "source": source,
    }


# -- account pool --------------------------------------------------------
def account_pool_group_row(group: AccountPoolGroup, settings: AccountPoolSettings) -> dict[str, Any]:
    channels = settings.channels_for_group(group.id)
    normal = sum(1 for item in channels if item.status == ACCOUNT_POOL_CHANNEL_STATUS_NORMAL)
    return {
        "id": group.id,
        "name": group.name,
        "label": account_pool_group_label(group, settings),
        "enabled": bool(group.enabled),
        "poolType": group.pool_type,
        "defaultModel": group.default_model,
        "claudeModel": group.claude_model,
        "claudeFallbackModel": group.claude_fallback_model,
        "channelCount": len(channels),
        "normalCount": normal,
        "failedCount": len(channels) - normal,
    }


def account_pool_channel_row(channel: AccountPoolChannel) -> dict[str, Any]:
    normal = channel.status == ACCOUNT_POOL_CHANNEL_STATUS_NORMAL
    return {
        "id": channel.id,
        "name": channel.name,
        "baseUrl": channel.base_url,
        "apiKeyMasked": mask_secret(channel.api_key),
        "groupId": channel.group_id,
        "sourceType": channel.source_type,
        "wireApi": channel.wire_api,
        "defaultModel": channel.default_model,
        "status": channel.status,
        "statusLabel": "正常" if normal else "异常",
        "tone": "success" if normal else "danger",
        "failureReason": channel.failure_reason,
        "lastCheckedAt": channel.last_checked_at or "",
    }


def account_pool_summary(settings: AccountPoolSettings, *, project_count: int) -> dict[str, Any]:
    return {
        "enabled": bool(settings.enabled),
        "groupCount": len(settings.groups),
        "totalChannels": len(settings.channels),
        "normalChannels": settings.normal_count,
        "failedChannels": settings.failed_count,
        "projectCount": project_count,
        "recoveryIntervalMinutes": settings.recovery_interval_minutes,
        "selectedGroupId": settings.selected_group_id,
    }


# -- model batch ---------------------------------------------------------
def batch_cache_snapshot(cache: ModelBatchCache | None) -> dict[str, Any]:
    if cache is None:
        return {
            "exists": False,
            "completed": False,
            "testedAt": "",
            "models": [],
            "successModels": [],
            "results": [],
            "successCount": 0,
            "errorCount": 0,
            "totalCount": 0,
        }
    results = []
    success = 0
    error = 0
    for model in cache.models:
        item = cache.results.get(model)
        status = str(getattr(item, "status", "pending") or "pending")
        if status == "success":
            success += 1
        elif status == "error":
            error += 1
        results.append(
            {
                "model": model,
                "status": status,
                "tone": {"success": "success", "error": "danger"}.get(status, "unknown"),
                "detail": str(getattr(item, "detail", "") or ""),
                "durationMs": getattr(item, "duration_ms", None),
            }
        )
    return {
        "exists": True,
        "completed": bool(cache.completed),
        "testedAt": cache.tested_at or "",
        "models": list(cache.models),
        "successModels": successful_model_batch_models(cache),
        "results": results,
        "successCount": success,
        "errorCount": error,
        "totalCount": len(cache.models),
    }


# -- skills --------------------------------------------------------------
def skill_row(skill: SkillDefinition) -> dict[str, Any]:
    return {
        "id": skill.id,
        "name": skill.name,
        "type": skill.type,
        "version": skill.version,
        "sourcePath": skill.source_path,
        "contentPreview": compact_text(skill.content or "", 160),
        "content": skill.content,
    }


def skill_group_row(group: SkillGroup) -> dict[str, Any]:
    return {
        "id": group.id,
        "name": group.name,
        "description": group.description,
        "skillCount": len(group.skills or []),
        "skills": [skill_row(item) for item in (group.skills or [])],
    }


def skill_repo_row(repo: SkillMarketRepo) -> dict[str, Any]:
    return {
        "id": repo.id,
        "url": repo.url,
        "branch": repo.branch,
        "lastSyncCommit": (repo.last_sync_commit or "")[:12],
        "autoUpdate": bool(repo.auto_update),
        "installedGroupId": repo.installed_group_id,
        "installed": bool(repo.installed_group_id),
    }


# -- scripts -------------------------------------------------------------
# Single source of truth for run-state labels/tones, so the list badge and the
# detail panel can never drift apart.
SCRIPT_STATUS_LABELS = {
    "idle": "未运行",
    "running": "运行中",
    "success": "已完成",
    "failed": "失败",
    "stopped": "已停止",
}
SCRIPT_STATUS_TONES = {
    "idle": "unknown",
    "running": "info",
    "success": "success",
    "failed": "danger",
    "stopped": "warning",
}


def script_status_label(status: str) -> str:
    return SCRIPT_STATUS_LABELS.get(str(status or "idle"), SCRIPT_STATUS_LABELS["idle"])


def script_status_tone(status: str) -> str:
    return SCRIPT_STATUS_TONES.get(str(status or "idle"), SCRIPT_STATUS_TONES["idle"])


def script_row(script, run_state: dict[str, Any] | None = None) -> dict[str, Any]:
    state = dict(run_state or {})
    status = str(state.get("status") or "idle")
    return {
        "id": script.id,
        "name": script.name,
        "kind": script.kind,
        "kindLabel": SCRIPT_KIND_LABELS.get(script.kind, script.kind),
        "description": script.description,
        "workingDir": script.working_dir,
        "updatedAt": script.updated_at,
        "runMode": script.run_mode,
        "runModeLabel": SCRIPT_RUN_MODE_LABELS.get(script.run_mode, script.run_mode),
        "closeOnFinish": bool(script.close_on_finish),
        "status": status,
        "statusLabel": script_status_label(status),
        "statusTone": script_status_tone(status),
        "running": status == "running",
        "exitCode": state.get("exitCode"),
        "startedAt": str(state.get("startedAt") or ""),
        "finishedAt": str(state.get("finishedAt") or ""),
        "logPath": str(state.get("logPath") or ""),
        "output": str(state.get("output") or ""),
    }


# -- mcp -----------------------------------------------------------------
def mcp_server_row(name: str, config: dict[str, Any]) -> dict[str, Any]:
    args = config.get("args") if isinstance(config, dict) else None
    env = config.get("env") if isinstance(config, dict) else None
    return {
        "name": name,
        "type": str((config or {}).get("type", "") or "-"),
        "command": str((config or {}).get("command", "") or "-"),
        "argsText": "\n".join(str(item) for item in args) if isinstance(args, list) else "",
        "argsCount": len(args) if isinstance(args, list) else 0,
        "cwd": str((config or {}).get("cwd", "") or ""),
        "envText": "\n".join(f"{key}={value}" for key, value in env.items()) if isinstance(env, dict) else "",
        "envCount": len(env) if isinstance(env, dict) else 0,
        "raw": dict(config or {}),
    }


# -- settings ------------------------------------------------------------
def settings_summary(
    *,
    dark_mode: bool,
    hot_update_enabled: bool,
    hot_update_interval_minutes: int,
    model_batch_concurrency: int,
    storage_path: str,
    profile_count: int,
    project_count: int,
    event_count: int,
    proxy_running: bool,
) -> dict[str, Any]:
    return {
        "darkMode": bool(dark_mode),
        "themeLabel": "深色" if dark_mode else "浅色",
        "hotUpdateEnabled": bool(hot_update_enabled),
        "hotUpdateIntervalMinutes": _as_int(hot_update_interval_minutes, 30),
        "modelBatchConcurrency": _as_int(model_batch_concurrency, 3),
        "storagePath": str(storage_path or ""),
        "profileCount": profile_count,
        "projectCount": project_count,
        "eventCount": event_count,
        "proxyRunning": bool(proxy_running),
    }


def model_defaults() -> dict[str, str]:
    return {
        "codex": DEFAULT_CODEX_MODEL,
        "claude": DEFAULT_CLAUDE_MODEL,
        "claudeFallback": DEFAULT_CLAUDE_FALLBACK_MODEL,
    }


__all__ = [
    "HEALTH_LABELS",
    "HEALTH_TONES",
    "SCRIPT_STATUS_LABELS",
    "SCRIPT_STATUS_TONES",
    "account_pool_channel_row",
    "account_pool_group_row",
    "account_pool_summary",
    "batch_cache_snapshot",
    "event_row",
    "health_label",
    "health_tone",
    "mcp_server_row",
    "model_defaults",
    "profile_choice_rows",
    "profile_detail",
    "profile_row",
    "project_detail",
    "project_row",
    "proxy_status",
    "script_row",
    "script_status_label",
    "script_status_tone",
    "settings_summary",
    "skill_group_row",
    "skill_repo_row",
    "skill_row",
    "usage_rows",
    "vendor_stats",
]
