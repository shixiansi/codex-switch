"""Headless business orchestration for the QML UI.

``Workspace`` owns the session and every service the UI drives, and performs all
mutations. It contains no Qt code, so it is unit-testable on its own and the
controller stays limited to signals, threading and drawer state.

Every method returns a small result object; user-facing failures are raised as
``WorkspaceError`` with an already-localised Chinese message.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from pathlib import Path
import os
import subprocess
from typing import Any, Callable, Iterable

from .. import __version__
from ..chat import (
    SUPPORTED_WIRE_APIS,
    AccountPoolSessionValidator,
    ChatResult,
    ChatTester,
    default_wire_api_for_profile,
)
from ..claude_config import ClaudeConfigManager
from ..codex_config import (
    CodexConfigManager,
    load_default_global_mcp_toml,
    mcp_server_names_from_toml,
    parse_mcp_servers_toml,
    render_mcp_servers_toml,
)
from ..health import HealthChecker
from ..models import (
    ACCOUNT_POOL_CHANNEL_SOURCE_PROFILE,
    ACCOUNT_POOL_CHANNEL_SOURCE_TEMPORARY,
    AccountPoolChannel,
    AccountPoolSettings,
    HealthResult,
    HotUpdateEvent,
    Profile,
    ProjectRecord,
    RouteProxyEvent,
    RouteProxySettings,
    SkillDefinition,
    SkillGroup,
    SkillMarketRepo,
    VENDOR_CODEX,
    mask_secret,
    normalize_hot_update_interval_minutes,
    profile_supports_claude,
    profile_supports_codex,
    today_iso,
)
from ..project_template import (
    ProjectTemplateService,
    claude_runtime_env_from_profile,
    load_default_agents_doc_text,
)
from ..proxy.server import RouteProxyServer
from ..skills import SkillSource, default_skill_roots, discover_skill_sources
from ..software_update import SoftwareUpdateChecker, SoftwareUpdateInfo, is_newer_version
from ..storage import ProfileStore, clamp_model_batch_concurrency
from ..ui.account_pool_logic import (
    account_pool_channel_by_id,
    check_account_pool_channel,
    prepare_account_pool_channel_submission,
)
from ..ui.global_logic import GlobalApplyResult, global_apply_detail, global_apply_targets, global_profile_apply_error
from ..ui.hot_update_logic import append_hot_update_event
from ..ui.library_logic import current_status_counts, health_status_text, visible_profiles_for_filter, profile_library_sort_key
from ..ui.model_batch_logic import ModelBatchCache, ModelBatchResult, model_batch_targets, run_model_batch_requests
from ..ui.profile_logic import (
    profile_collection_after_add,
    profile_collection_after_replace,
    profile_delete_error,
    profile_from_dialog_result,
    updated_profile_from_dialog,
)
from ..ui.project_logic import (
    build_codex_template_execution_plan,
    build_claude_template_execution_plan,
    build_codex_template_run_spec,
    build_claude_template_run_spec,
    build_project_add_execution_plan,
    build_project_binding_sync_plan,
    build_project_claude_cmd_launch_preparation,
    build_project_delete_execution_plan,
    build_project_edit_execution_plan,
    build_project_launch_feedback,
    build_project_repo_update_status_text,
    execute_project_binding_sync,
    execute_project_folder_open,
    execute_project_launch_plan,
    execute_project_repo_update,
    project_claude_settings_edit_plan,
    project_codex_config_edit_plan,
    project_custom_run_launch_plan,
    project_codex_cmd_launch_plan,
    project_codex_profile_id,
    project_claude_profile_id,
    project_bound_profile_ids,
    project_duplicate_dir_error,
    project_vscode_launch_plan,
    resolve_selected_project_id,
)
from ..ui.repo_sync_logic import (
    git_remote_commit,
    project_remote_update,
    skill_repo_remote_update,
    sync_project_checkout,
    sync_repo_cache,
)
from ..ui.route_proxy_logic import (
    build_route_proxy_project_disable_plan,
    build_route_proxy_project_enable_plan,
    refresh_route_proxy_rules_for_project,
    route_proxy_base_url_for_project,
)
from ..ui.skills_logic import (
    MODEL_METADATA_RELATIVE_PATHS,
    apply_profile_metadata,
    existing_repo_files,
    expanded_skills_for_group_ids,
    import_skill_sources_to_group,
    projects_after_skill_group_delete,
    remove_skill_group,
    replace_skill_group,
    skill_group_name_error,
    skill_group_with_added_skill,
    skill_group_with_deleted_skill,
    skill_group_with_metadata,
    skill_group_with_replaced_skill,
    skill_repo_checksum_required_paths,
    sync_projects_from_skill_groups,
)
from ..ui.update_logic import (
    DEFAULT_PROJECT_GITHUB_REF,
    DEFAULT_SKILL_REPO_REF,
    normalize_git_ref,
    verify_hot_update_checksums,
)
from ..ui import mcp_logic
from . import forms
from .errors import FormError, WorkspaceError
from .session import AppSession
from . import snapshots


_CREATE_NEW_CONSOLE = getattr(subprocess, "CREATE_NEW_CONSOLE", 0)
MODEL_BATCH_TASK_PREFIX = "model-batch"
HEALTH_TASK_PREFIX = "health"

# Manual health overrides, mirroring the legacy UI's choices.
MANUAL_HEALTH_LABELS = {
    "healthy": "健康",
    "degraded": "受限",
    "error": "异常",
    "unknown": "未检测",
}
MANUAL_HEALTH_CHOICES = tuple(MANUAL_HEALTH_LABELS)

# Batch sign-in pacing: open this many pages, then pause before the next batch
# so the browser is not flooded and the machine stays responsive.
SIGN_IN_BATCH_SIZE = 5
SIGN_IN_BATCH_PAUSE_MS = 1000


@dataclass
class ActionResult:
    """Outcome of a mutating operation."""

    message: str = ""
    level: str = "success"
    detail: str = ""
    changed: bool = True


@dataclass
class HealthOutcome:
    results: dict[str, HealthResult] = field(default_factory=dict)
    failures: list[str] = field(default_factory=list)

    @property
    def summary(self) -> str:
        healthy = sum(1 for item in self.results.values() if item.status == "healthy")
        failed = len(self.results) - healthy
        if not self.results:
            return "没有可检测的配置。"
        if failed:
            return f"健康检测完成：{healthy} 个健康，{failed} 个异常。"
        return f"健康检测完成：{healthy} 个配置全部健康。"


class Workspace:
    """Owns session state and performs every business operation the UI needs."""

    def __init__(
        self,
        store: ProfileStore | None = None,
        *,
        project_root: Path | None = None,
        codex_manager: CodexConfigManager | None = None,
        claude_manager: ClaudeConfigManager | None = None,
        template_service: ProjectTemplateService | None = None,
        health_checker: HealthChecker | None = None,
        chat_tester: ChatTester | None = None,
        update_checker: SoftwareUpdateChecker | None = None,
    ) -> None:
        self.store = store or ProfileStore()
        self.project_root = Path(project_root or Path.cwd())
        self.session = AppSession.from_store(self.store)
        self.codex_manager = codex_manager or CodexConfigManager()
        self.claude_manager = claude_manager or ClaudeConfigManager()
        self.template_service = template_service or ProjectTemplateService()
        self.health_checker = health_checker or HealthChecker()
        self.chat_tester = chat_tester or ChatTester()
        self.update_checker = update_checker or SoftwareUpdateChecker()
        self.account_pool_validator = AccountPoolSessionValidator(self.chat_tester)
        self.software_update_info: SoftwareUpdateInfo | None = None

        self._proxy_events: list[RouteProxyEvent] = []
        self._proxy_dirty = False
        self.route_proxy_server = RouteProxyServer(
            lambda: self.session.route_proxy,
            lambda: self.session.profiles,
            self._record_proxy_event,
            account_pool_provider=lambda: self.session.account_pool,
            account_pool_update_callback=self._record_account_pool_update,
            project_provider=lambda: self.session.projects,
            recovery_checker=self.account_pool_validator,
            token_usage_callback=self._record_proxy_token_usage,
        )

    # -- persistence ------------------------------------------------------
    def persist(self) -> None:
        self.session.persist(self.store)

    def reload(self) -> ActionResult:
        self.session = AppSession.from_store(self.store)
        return ActionResult(message="状态已刷新。", level="info")

    # -- proxy callbacks (invoked from the proxy worker thread) -----------
    def _record_proxy_event(self, event: RouteProxyEvent) -> None:
        """Append a proxy event; runs on the HTTP worker thread."""
        self._proxy_events.append(event)
        if len(self._proxy_events) > 200:
            del self._proxy_events[: len(self._proxy_events) - 200]
        self._proxy_dirty = True

    def _record_account_pool_update(self, pool: AccountPoolSettings) -> None:
        self.session.account_pool = pool
        self._proxy_dirty = True

    def _record_proxy_token_usage(self, settings: RouteProxySettings) -> None:
        self.session.route_proxy = settings
        self._proxy_dirty = True

    def flush_proxy_state(self) -> bool:
        """Persist state changed by the proxy thread; returns True when dirty."""
        if not self._proxy_dirty:
            return False
        self._proxy_dirty = False
        for event in self._proxy_events:
            self.session.record_proxy_event(event)
        self._proxy_events.clear()
        self.persist()
        return True

    # =====================================================================
    # Snapshot for the view models
    # =====================================================================
    def snapshot(self, selected_mcp_name: str = "") -> dict[str, Any]:
        session = self.session
        all_profiles = sorted(session.profiles, key=profile_library_sort_key)
        # The hide filter applies to the library listing only; counts and
        # lookups still see every profile so nothing is silently lost.
        profiles = visible_profiles_for_filter(all_profiles, session.hide_error_profiles)
        selected_profile = session.selected_profile()
        selected_project = session.selected_project()

        # current_status_counts returns (total, healthy, degraded, error).
        _total, healthy_count, degraded_count, error_count = current_status_counts(all_profiles)
        health_summary = {
            "healthy": healthy_count,
            "degraded": degraded_count,
            "restricted": degraded_count,
            "error": error_count,
            "unknown": max(0, len(profiles) - healthy_count - degraded_count - error_count),
        }

        codex_profile = session.global_codex_profile()
        claude_profile = session.global_claude_profile()

        chat_target = selected_profile
        batch_cache = session.model_batch_cache(chat_target.id if chat_target else None)
        wire_api = default_wire_api_for_profile(chat_target) if chat_target else "responses"

        return {
            "profiles": [snapshots.profile_row(item) for item in profiles],
            "profile_choices": snapshots.profile_choice_rows(session.profiles, session.selected_profile_id),
            "codex_choices": [
                {"id": item.id, "name": item.name}
                for item in session.profiles
                if profile_supports_codex(item)
            ],
            "claude_choices": [
                {"id": item.id, "name": item.name}
                for item in session.profiles
                if profile_supports_claude(item)
            ],
            "selected_profile_id": session.selected_profile_id or "",
            "selected_profile_detail": snapshots.profile_detail(selected_profile) if selected_profile else {},
            "global_codex_profile_id": session.selected_codex_global_profile_id or "",
            "global_claude_profile_id": session.selected_claude_global_profile_id or "",
            "global_codex_name": codex_profile.name if codex_profile else "",
            "global_claude_name": claude_profile.name if claude_profile else "",
            "health": health_summary,
            "sign_in": self.sign_in_summary(),
            "hide_error_profiles": bool(session.hide_error_profiles),

            "projects": [snapshots.project_row(item) for item in session.projects],
            "selected_project_id": session.selected_project_id or "",
            "selected_project_detail": (
                snapshots.project_detail(
                    selected_project,
                    codex_profile=session.profile_by_id(project_codex_profile_id(selected_project)),
                    claude_profile=session.profile_by_id(project_claude_profile_id(selected_project)),
                )
                if selected_project
                else {}
            ),
            "mcp_server_names": self.available_mcp_server_names(),

            "proxy": snapshots.proxy_status(session.route_proxy, running=self.proxy_running),
            "proxy_events": [
                snapshots.event_row(item, source="proxy") for item in reversed(session.route_proxy.events[-200:])
            ],

            "account_pool": snapshots.account_pool_summary(
                session.account_pool, project_count=self._account_pool_project_count()
            ),
            "account_pool_groups": [
                snapshots.account_pool_group_row(group, session.account_pool) for group in session.account_pool.groups
            ],
            "account_pool_channels": [
                snapshots.account_pool_channel_row(channel)
                for channel in (
                    session.account_pool.channels_for_group(session.account_pool.selected_group_id)
                    if session.account_pool.selected_group_id
                    else session.account_pool.channels
                )
            ],

            "model_batch": snapshots.batch_cache_snapshot(batch_cache),
            "chat": self._chat_snapshot(chat_target, batch_cache, wire_api),

            "mcp_servers": self._mcp_rows(),
            "mcp_detail": self._mcp_detail(selected_mcp_name),

            "skill_groups": [snapshots.skill_group_row(item) for item in session.skill_groups],
            "skill_repos": [snapshots.skill_repo_row(item) for item in session.skill_market_repos],

            "settings": self._settings_snapshot(),
            "software_update": self._software_update_snapshot(),
            "activity": self._activity_rows(),
            "storage_path": str(self.store.storage_path),
            "version": __version__,
        }

    def _settings_snapshot(self) -> dict[str, Any]:
        session = self.session
        summary = snapshots.settings_summary(
            dark_mode=session.dark_mode,
            hot_update_enabled=session.hot_update_enabled,
            hot_update_interval_minutes=session.hot_update_interval_minutes,
            model_batch_concurrency=session.model_batch_concurrency,
            storage_path=str(self.store.root_dir),
            profile_count=len(session.profiles),
            project_count=len(session.projects),
            event_count=len(session.event_log),
            proxy_running=self.proxy_running,
        )
        summary["agentsDocText"] = session.agents_doc_text
        summary["version"] = __version__
        summary["python"] = _python_version()
        summary["qt"] = _qt_version()
        summary["hotUpdateEventCount"] = len(session.hot_update_events)
        return summary

    def _software_update_snapshot(self) -> dict[str, Any]:
        info = self.software_update_info
        if info is None:
            return {"checked": False, "updateAvailable": False, "version": "", "url": "", "notes": ""}
        try:
            available = bool(info.update_available)
        except Exception:  # noqa: BLE001 - property may need version info
            available = is_newer_version(str(getattr(info, "version", "") or ""), __version__)
        return {
            "checked": True,
            "updateAvailable": available,
            "version": str(getattr(info, "version", "") or ""),
            "url": str(getattr(info, "download_url", "") or getattr(info, "release_url", "") or ""),
            "notes": str(getattr(info, "notes", "") or ""),
        }

    def _chat_snapshot(self, profile: Profile | None, cache: ModelBatchCache | None, wire_api: str) -> dict[str, Any]:
        if profile is None:
            return {
                "available": False,
                "profileName": "未选择配置",
                "wireApi": wire_api,
                "wireApiChoices": list(SUPPORTED_WIRE_APIS),
                "models": [],
                "messages": list(self.session.chat_messages),
            }
        models = list(profile.health.models or [])
        if cache is not None and cache.completed:
            success = [item for item in cache.models if cache.results.get(item, ModelBatchResult()).status == "success"]
            if success:
                models = success
        if not models:
            fallback = (
                profile.claude_display_model
                if wire_api == "anthropic_messages"
                else profile.codex_display_model
            )
            models = [fallback] if fallback else []
        return {
            "available": True,
            "profileId": profile.id,
            "profileName": profile.name,
            "wireApi": wire_api,
            "wireApiChoices": list(SUPPORTED_WIRE_APIS),
            "models": models,
            "messages": list(self.session.chat_messages),
        }

    def _activity_rows(self) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for item in reversed(self.session.event_log[-60:]):
            tone = {"error": "danger", "warning": "warning", "warn": "warning"}.get(
                str(item.get("level", "")).casefold(), "info"
            )
            rows.append(
                {
                    "timestamp": str(item.get("timestamp", "")),
                    "source": str(item.get("source", "")),
                    "level": str(item.get("level", "info")),
                    "tone": tone,
                    "message": str(item.get("message", "")),
                    "detail": str(item.get("detail", "")),
                    "target": str(item.get("target", "")),
                }
            )
        return rows

    # =====================================================================
    # Global / effective MCP helpers
    # =====================================================================
    def _global_mcp_source_toml(self) -> str:
        return self.session.global_mcp_toml.strip() or load_default_global_mcp_toml()

    def available_mcp_server_names(self) -> list[str]:
        try:
            return mcp_server_names_from_toml(self._global_mcp_source_toml())
        except ValueError:
            return []

    def effective_global_mcp_toml(self) -> str:
        session = self.session
        if session.global_mcp_opt_out:
            return ""
        source = self._global_mcp_source_toml()
        if session.global_mcp_server_names is None:
            return source
        try:
            servers = parse_mcp_servers_toml(source)
        except ValueError:
            return ""
        selected = {
            name: servers[name] for name in session.global_mcp_server_names if name in servers
        }
        return render_mcp_servers_toml(selected)

    def effective_project_mcp_toml(self, project: ProjectRecord | None) -> str:
        if project is None:
            return self.effective_global_mcp_toml()
        if project.mcp_server_names is not None:
            return self.template_service.select_project_mcp_toml(
                self.effective_global_mcp_toml(), project.mcp_server_names
            )
        if project.mcp_toml.strip():
            return project.mcp_toml
        return self.effective_global_mcp_toml()

    def available_skill_sources(self) -> list[SkillSource]:
        return discover_skill_sources(default_skill_roots(self.project_root))

    def _mcp_rows(self) -> list[dict[str, Any]]:
        try:
            servers = parse_mcp_servers_toml(self._global_mcp_source_toml())
        except ValueError:
            return []
        return [snapshots.mcp_server_row(name, servers[name]) for name in sorted(servers)]

    def _mcp_detail(self, selected_name: str = "") -> dict[str, Any]:
        """Detail for the selected MCP server, falling back to the first one.

        The selected name comes from the UI; without it the panel would always
        show the first server in alphabetical order regardless of the click.
        """
        try:
            servers = parse_mcp_servers_toml(self._global_mcp_source_toml())
        except ValueError as exc:
            return {"error": f"MCP 配置解析失败：{exc}"}
        names = sorted(servers)
        if not names:
            return {"name": "", "summary": "尚未配置 MCP 服务。", "preview": ""}

        requested = str(selected_name or "").strip()
        name = requested if requested in servers else names[0]
        config = servers[name]
        args = config.get("args") if isinstance(config.get("args"), list) else []
        env = config.get("env") if isinstance(config.get("env"), dict) else {}
        return {
            "name": name,
            "summary": f"共 {len(names)} 个服务 · type: {config.get('type', '-')} · args: {len(args)} · env: {len(env)}",
            "preview": mcp_logic.render_mcp_preview(name, servers),
        }

    # =====================================================================
    # Profiles
    # =====================================================================
    def profile_form_fields(self, profile_id: str) -> list[dict[str, Any]]:
        profile = self.session.profile_by_id(profile_id)
        if profile_id and profile is None:
            raise WorkspaceError("配置不存在或已被删除。")
        return forms.profile_form(profile)

    def save_profile(self, payload: dict[str, Any], *, profile_id: str = "") -> ActionResult:
        session = self.session
        current = session.profile_by_id(profile_id) if profile_id else None
        if profile_id and current is None:
            raise WorkspaceError("配置不存在或已被删除。")
        data = forms.profile_payload(payload, current)
        if current is not None:
            updated = updated_profile_from_dialog(current, data)
            update = profile_collection_after_replace(session.profiles, updated)
            message = f"已保存配置：{updated.name}"
        else:
            created = profile_from_dialog_result(data)
            update = profile_collection_after_add(session.profiles, created)
            message = f"已新增配置：{created.name}"

        session.profiles = update.profiles
        session.selected_profile_id = update.selected_profile_id
        session.normalize_global_profile_ids()
        self.persist()
        return ActionResult(message=message)

    def delete_profile_blocker(self, profile_id: str) -> str:
        """Return why a profile cannot be deleted yet, or '' when it can.

        Used by the UI to warn inside the confirmation dialog instead of letting
        the user confirm a delete that would then be refused.
        """
        if self.session.profile_by_id(profile_id) is None:
            return "配置不存在或已被删除。"
        return profile_delete_error(
            profile_id,
            self.session.projects,
            project_bound_profile_ids=project_bound_profile_ids,
        ) or ""

    def delete_profile(self, profile_id: str) -> ActionResult:
        session = self.session
        profile = session.profile_by_id(profile_id)
        if profile is None:
            raise WorkspaceError("配置不存在或已被删除。")
        # Guard: refuse to orphan projects that still reference this profile.
        blocker = self.delete_profile_blocker(profile_id)
        if blocker:
            raise WorkspaceError(f"{blocker}\n无法删除。")
        session.remove_profile(profile_id)
        session.normalize_global_profile_ids()
        self.persist()
        return ActionResult(message=f"已删除配置：{profile.name}")

    def select_profile(self, profile_id: str) -> None:
        self.session.select_profile(profile_id)
        self.persist()

    def set_hide_error_profiles(self, value: bool) -> ActionResult:
        """Hide profiles whose effective status is 'error' from the library."""
        session = self.session
        session.hide_error_profiles = bool(value)
        self.persist()
        hidden = sum(
            1 for profile in session.profiles if profile.effective_health_status == "error"
        )
        if session.hide_error_profiles:
            return ActionResult(
                message=f"已隐藏 {hidden} 个异常配置。",
                level="info",
            )
        return ActionResult(message="已显示全部配置。", level="info")

    def set_manual_health_status(self, profile_id: str, status: str) -> ActionResult:
        """Override a profile's health status, or clear the override.

        Health checks reflect connectivity only; this lets the user pin a
        status manually without editing ``profiles.json`` by hand. An empty
        value restores the automatic result.
        """
        profile = self.session.profile_by_id(profile_id)
        if profile is None:
            raise WorkspaceError("配置不存在或已被删除。")

        value = str(status or "").strip().lower()
        if value and value not in MANUAL_HEALTH_CHOICES:
            raise WorkspaceError(f"不支持的手动状态：{status}")

        if value:
            profile.manual_health_status = value
            self.persist()
            return ActionResult(
                message=f"已将 {profile.name} 标记为「{MANUAL_HEALTH_LABELS[value]}」。",
            )
        profile.manual_health_status = None
        self.persist()
        return ActionResult(
            message=f"已恢复 {profile.name} 的自动健康状态。",
            level="info",
        )

    def set_global_profile_choice(self, target: str, profile_id: str) -> ActionResult:
        session = self.session
        profile = session.profile_by_id(profile_id)
        label = "Codex" if target == VENDOR_CODEX else "Claude"
        if profile is None:
            if target == VENDOR_CODEX:
                session.selected_codex_global_profile_id = None
            else:
                session.selected_claude_global_profile_id = None
            self.persist()
            return ActionResult(message=f"已清除全局 {label} 配置。", level="info")
        if target == VENDOR_CODEX:
            session.selected_codex_global_profile_id = profile.id
        else:
            session.selected_claude_global_profile_id = profile.id
        self.persist()
        return ActionResult(message=f"已选择全局 {label} 配置：{profile.name}", level="info")

    def apply_profile(self, profile_id: str) -> ActionResult:
        profile = self.session.profile_by_id(profile_id)
        if profile is None:
            raise WorkspaceError("请先选择一个配置项。")
        result = self._apply_profile_to_global(profile)
        session = self.session
        session.selected_profile_id = profile.id
        self.persist()
        return ActionResult(
            message=f"已切换全局配置：{profile.name}",
            detail=global_apply_detail(result),
        )

    def apply_selected_profile(self) -> ActionResult:
        profile = self.session.selected_profile()
        if profile is None:
            raise WorkspaceError("请先选择一个配置项。")
        return self.apply_profile(profile.id)

    def apply_global_profiles(self) -> ActionResult:
        session = self.session
        codex_profile = session.global_codex_profile()
        claude_profile = session.global_claude_profile()
        if codex_profile is None and claude_profile is None:
            raise WorkspaceError("请先为 Codex 或 Claude 选择全局 API 配置。")

        result = GlobalApplyResult()
        if codex_profile is not None:
            self._apply_codex_profile(codex_profile, result)
        if claude_profile is not None:
            self._apply_claude_profile(claude_profile, result)

        chosen = codex_profile or claude_profile
        if chosen is not None:
            session.selected_profile_id = chosen.id
        self.persist()
        return ActionResult(
            message=f"已写入全局配置：{global_apply_targets(result)}",
            detail=global_apply_detail(result),
        )

    def _apply_profile_to_global(self, profile: Profile) -> GlobalApplyResult:
        supports_codex = profile_supports_codex(profile)
        supports_claude = profile_supports_claude(profile)
        error = global_profile_apply_error(supports_codex=supports_codex, supports_claude=supports_claude)
        if error:
            raise WorkspaceError(error)

        result = GlobalApplyResult()
        if supports_codex:
            self._apply_codex_profile(profile, result)
        if supports_claude:
            self._apply_claude_profile(profile, result)
        session = self.session
        if supports_codex:
            session.selected_codex_global_profile_id = profile.id
        if supports_claude:
            session.selected_claude_global_profile_id = profile.id
        return result

    def _apply_codex_profile(self, profile: Profile, result: GlobalApplyResult) -> None:
        session = self.session
        try:
            result.codex_backup_dir = self.codex_manager.apply_profile(
                profile,
                global_mcp_toml=self.effective_global_mcp_toml(),
                previous_managed_mcp_server_names=session.applied_global_mcp_server_names,
            )
        except Exception as exc:  # noqa: BLE001
            raise WorkspaceError(f"写入 Codex 配置失败：{exc}") from exc
        try:
            session.applied_global_mcp_server_names = mcp_server_names_from_toml(
                self.effective_global_mcp_toml()
            )
        except ValueError:
            session.applied_global_mcp_server_names = []

    def _apply_claude_profile(self, profile: Profile, result: GlobalApplyResult) -> None:
        try:
            result.claude_backup_dir = self.claude_manager.apply_profile(profile)
            result.claude_settings_path = self.claude_manager.settings_path
        except Exception as exc:  # noqa: BLE001
            raise WorkspaceError(f"写入 Claude 配置失败：{exc}") from exc

    def open_sign_in_url(self, profile_id: str) -> ActionResult:
        profile = self.session.profile_by_id(profile_id)
        if profile is None or not profile.sign_in_url:
            raise WorkspaceError("该配置没有签到地址。")
        _open_url(profile.sign_in_url)
        return ActionResult(message=f"已在浏览器打开签到地址：{profile.sign_in_url}")

    def mark_signed_in(self, profile_id: str) -> ActionResult:
        session = self.session
        profile = session.profile_by_id(profile_id)
        if profile is None:
            raise WorkspaceError("配置不存在。")
        profile.last_signed_date = today_iso()
        self.persist()
        return ActionResult(message=f"已记录今日签到：{profile.name}")

    def sign_in_pending(self) -> list[Profile]:
        """Profiles that need signing in today and have a usable URL."""
        today = today_iso()
        return [
            profile
            for profile in self.session.profiles
            if profile.requires_sign_in
            and profile.sign_in_url.strip()
            and profile.last_signed_date != today
        ]

    def sign_in_summary(self) -> dict[str, Any]:
        """Counts shown next to the batch sign-in action."""
        today = today_iso()
        with_url = [
            profile
            for profile in self.session.profiles
            if profile.requires_sign_in and profile.sign_in_url.strip()
        ]
        signed = [profile for profile in with_url if profile.last_signed_date == today]
        missing_url = [
            profile
            for profile in self.session.profiles
            if profile.requires_sign_in and not profile.sign_in_url.strip()
        ]
        return {
            "required": len(with_url) + len(missing_url),
            "signedToday": len(signed),
            "pending": len(with_url) - len(signed),
            "missingUrl": len(missing_url),
            "urls": [profile.sign_in_url.strip() for profile in with_url],
        }

    def sign_in_missing_url(self) -> list[str]:
        """Names of profiles that need signing in but have no URL configured."""
        return [
            profile.name
            for profile in self.session.profiles
            if profile.requires_sign_in and not profile.sign_in_url.strip()
        ]

    def open_sign_in_batch(self, profiles: Iterable[Profile]) -> tuple[list[str], list[str]]:
        """Open one batch of sign-in pages, marking each as signed today.

        Returns ``(opened_names, failure_messages)``. A profile is marked signed
        as soon as its page is handed to the browser: opening the tab is the only
        verification available. Failures never abort the batch.
        """
        today = today_iso()
        opened: list[str] = []
        failed: list[str] = []
        for profile in profiles:
            try:
                _open_url(profile.sign_in_url)
            except Exception as exc:  # noqa: BLE001 - keep going for the rest
                failed.append(f"{profile.name}：{exc}")
                continue
            profile.last_signed_date = today
            opened.append(profile.name)

        if opened:
            self.persist()
        return opened, failed

    def sign_in_result(
        self,
        opened: list[str],
        failed: list[str],
        missing_names: list[str] | None = None,
    ) -> ActionResult:
        """Assemble the user-facing outcome of a batched sign-in run."""
        missing_names = list(missing_names or [])
        detail_parts: list[str] = []
        if missing_names:
            detail_parts.append("缺少签到地址：" + "、".join(missing_names))
        if failed:
            detail_parts.append("打开失败：" + "；".join(failed))
        detail = "\n".join(detail_parts)

        if not opened:
            return ActionResult(
                message=f"未能打开任何签到页面（{len(failed)} 个失败）。",
                level="error",
                detail=detail,
            )

        message = f"已打开 {len(opened)} 个签到页面并标记为今日已签到。"
        if missing_names:
            message += f" {len(missing_names)} 个配置缺少签到地址。"
        return ActionResult(
            message=message,
            level="warning" if (missing_names or failed) else "success",
            detail=detail,
        )

    def open_all_sign_in_urls(self) -> ActionResult:
        """Open every pending sign-in page at once and mark those profiles signed.

        Used by tests and by callers that do not need the paced UI behaviour;
        the interface batches through ``open_sign_in_batch`` instead so the
        browser is not flooded.
        """
        pending = self.sign_in_pending()
        missing_names = self.sign_in_missing_url()

        if not pending and not missing_names:
            return ActionResult(
                message="所有需要签到的配置今天都已签到。",
                level="info",
            )

        opened, failed = self.open_sign_in_batch(pending)
        return self.sign_in_result(opened, failed, missing_names)

    # =====================================================================
    # Health checks
    # =====================================================================
    def run_health_check(self, profile_id: str, *, progress: Callable[[str], None] | None = None) -> HealthOutcome:
        profile = self.session.profile_by_id(profile_id)
        if profile is None:
            raise WorkspaceError("请先选择一个配置项。")
        if progress:
            progress(f"正在检测 {profile.name} …")
        result = self.health_checker.check(profile)
        profile.health = result
        self.persist()
        return HealthOutcome(results={profile.id: result})

    def run_health_check_all(self, *, progress: Callable[[str], None] | None = None) -> HealthOutcome:
        outcome = HealthOutcome()
        for profile in list(self.session.profiles):
            if progress:
                progress(f"正在检测 {profile.name} …")
            result = self.health_checker.check(profile)
            profile.health = result
            outcome.results[profile.id] = result
        self.persist()
        return outcome

    # =====================================================================
    # Projects
    # =====================================================================
    def project_form_fields(self, project_id: str) -> list[dict[str, Any]]:
        project = self.session.project_by_id(project_id)
        if project_id and project is None:
            raise WorkspaceError("项目不存在或已被删除。")
        return forms.project_form(
            project,
            profiles=self.session.profiles,
            skill_groups=self.session.skill_groups,
            mcp_names=self.available_mcp_server_names(),
        )

    def save_project(self, payload: dict[str, Any], *, project_id: str = "") -> ActionResult:
        data = forms.project_payload(payload)
        session = self.session

        duplicate = next(
            (
                item
                for item in session.projects
                if item.project_dir.strip().casefold() == data["project_dir"].strip().casefold()
            ),
            None,
        )
        duplicate_error = project_duplicate_dir_error(
            duplicate, current_project_id=project_id or None
        )
        if duplicate_error:
            raise WorkspaceError(duplicate_error)

        if project_id:
            project = session.project_by_id(project_id)
            if project is None:
                raise WorkspaceError("项目不存在或已被删除。")
            plan = build_project_edit_execution_plan(
                project,
                data,
                projects=session.projects,
                updated_at=_now(),
                refresh_route_proxy_rules=lambda item: self.refresh_route_proxy_rules(item),
            )
            update = plan.collection
            session.projects = update.projects
            session.selected_project_id = update.selected_project_id
            message = f"已保存项目：{plan.project.name}"
        else:
            plan = build_project_add_execution_plan(session.projects, data)
            session.projects = plan.collection.projects
            session.selected_project_id = plan.collection.selected_project_id
            message = plan.status_text

        self.persist()
        return ActionResult(message=message)

    def delete_project(self, project_id: str) -> ActionResult:
        session = self.session
        project = session.project_by_id(project_id)
        if project is None:
            raise WorkspaceError("项目不存在或已被删除。")
        plan = build_project_delete_execution_plan(
            session.projects, selected_project_id=session.selected_project_id, project=project
        )
        session.projects = plan.collection.projects
        session.selected_project_id = plan.collection.selected_project_id
        self.persist()
        return ActionResult(message=plan.status_text)

    def select_project(self, project_id: str) -> None:
        self.session.select_project(project_id)
        self.persist()

    def set_project_binding(self, target: str, profile_id: str, *, project_id: str = "") -> ActionResult:
        session = self.session
        project = session.project_by_id(project_id) or session.selected_project()
        if project is None:
            raise WorkspaceError("请先选择一个项目。")
        profile = session.profile_by_id(profile_id)
        label = "Codex" if target == VENDOR_CODEX else "Claude"
        if profile is None:
            raise WorkspaceError(f"请选择一个有效的 {label} 配置。")

        if target == VENDOR_CODEX:
            if not profile_supports_codex(profile):
                raise WorkspaceError("该配置不能用于 Codex。")
            updated = replace(project, codex_profile_id=profile.id, profile_id=profile.id, updated_at=_now())
        else:
            if not profile_supports_claude(profile):
                raise WorkspaceError("该配置不能用于 Claude。")
            updated = replace(project, claude_profile_id=profile.id, updated_at=_now())

        session.projects = [updated if item.id == updated.id else item for item in session.projects]
        self.persist()
        return ActionResult(message=f"已将 {project.name} 的 {label} 配置绑定为 {profile.name}")

    def refresh_route_proxy_rules(self, project: ProjectRecord) -> bool:
        session = self.session
        if not session.route_proxy.project_enabled(project.id):
            return False
        codex_profile = session.profile_by_id(project_codex_profile_id(project))
        claude_profile = session.profile_by_id(project_claude_profile_id(project))
        if codex_profile is None or claude_profile is None:
            return False
        session.route_proxy = refresh_route_proxy_rules_for_project(
            session.route_proxy, project, codex_profile, claude_profile
        )
        return True

    def project_route_proxy_base_url(self, project: ProjectRecord) -> str | None:
        return route_proxy_base_url_for_project(self.session.route_proxy, project)

    def generate_template(self, *, client: str, project_id: str = "") -> ActionResult:
        session = self.session
        project = session.project_by_id(project_id) or session.selected_project()
        if project is None:
            raise WorkspaceError("请先选择一个项目。")

        self.refresh_route_proxy_rules(project)
        route_proxy_base_url = self.project_route_proxy_base_url(project)
        project_mcp_toml = self.effective_project_mcp_toml(project)

        if client == "claude":
            profile = session.profile_by_id(project_claude_profile_id(project))
            if profile is None:
                raise WorkspaceError("当前项目绑定的 Claude 配置已经不存在。")
            claude_model, claude_fallback = self._claude_model_overrides(project)
            plan = build_claude_template_execution_plan(
                project,
                profile,
                project_mcp_toml=project_mcp_toml,
                agents_doc_text=session.agents_doc_text,
                route_proxy_base_url=route_proxy_base_url,
                model_override=claude_model,
                fallback_model_override=claude_fallback,
            )
            spec = build_claude_template_run_spec(plan)
        else:
            codex_profile = session.profile_by_id(project_codex_profile_id(project))
            if codex_profile is None:
                raise WorkspaceError("当前项目绑定的 Codex 配置已经不存在。")
            claude_profile = session.profile_by_id(project_claude_profile_id(project))
            claude_model, claude_fallback = self._claude_model_overrides(project)
            plan = build_codex_template_execution_plan(
                project,
                codex_profile,
                claude_profile,
                project_mcp_toml=project_mcp_toml,
                agents_doc_text=session.agents_doc_text,
                route_proxy_base_url=route_proxy_base_url,
                available_skill_sources=self.available_skill_sources(),
                codex_model_override=self._codex_model_override(project),
                claude_model_override=claude_model,
                claude_fallback_model_override=claude_fallback,
            )
            spec = build_codex_template_run_spec(plan)

        try:
            method = getattr(self.template_service, spec.method_name)
            result = method(*spec.args, **spec.kwargs)
        except Exception as exc:  # noqa: BLE001
            raise WorkspaceError(f"{spec.failure_message_prefix}：{exc}") from exc

        self.persist()
        generated = len(getattr(result, "generated_paths", []) or [])
        return ActionResult(
            message=f"已为 {project.name} 生成 {generated} 个文件。",
            detail=f"备份目录：{getattr(result, 'backup_dir', '')}",
        )

    def _codex_model_override(self, project: ProjectRecord) -> str | None:
        from ..ui.route_proxy_logic import codex_model_override_for_project

        return codex_model_override_for_project(
            self.session.route_proxy, self.session.account_pool, project
        )

    def _claude_model_overrides(self, project: ProjectRecord) -> tuple[str | None, str | None]:
        from ..ui.route_proxy_logic import claude_model_overrides_for_project

        return claude_model_overrides_for_project(
            self.session.route_proxy, self.session.account_pool, project
        )

    # -- launching --------------------------------------------------------
    def open_project_folder(self, project_id: str = "") -> ActionResult:
        project = self.session.project_by_id(project_id) or self.session.selected_project()
        if project is None:
            raise WorkspaceError("请先选择一个项目。")
        result = execute_project_folder_open(project, open_path=_open_path)
        if not result.opened:
            raise WorkspaceError(result.error_message or "打开项目目录失败。")
        return ActionResult(message=result.status_text or "已打开项目目录。")

    def launch_project(self, action: str, project_id: str = "") -> ActionResult:
        session = self.session
        project = session.project_by_id(project_id) or session.selected_project()
        if project is None:
            raise WorkspaceError("请先选择一个项目。")

        if action == "run":
            plan = project_custom_run_launch_plan(project)
            if plan is not None:
                return self._execute_launch(plan, "运行项目命令失败")
            return self.launch_project("codex-cmd", project.id)

        if action == "vscode":
            return self._execute_launch(project_vscode_launch_plan(project), "使用 VS Code 打开项目失败")

        if action == "codex-cmd":
            self.refresh_route_proxy_rules(project)
            if not self._sync_project_api_binding(project, sync_claude=False):
                raise WorkspaceError("同步项目 Codex 绑定失败。")
            return self._execute_launch(
                project_codex_cmd_launch_plan(project),
                "打开 CMD 脚本失败",
                missing_as_info=True,
            )

        if action == "claude-cmd":
            self.refresh_route_proxy_rules(project)
            claude_model, claude_fallback = self._claude_model_overrides(project)
            preparation = build_project_claude_cmd_launch_preparation(
                project,
                profile_by_id=session.profile_by_id,
                supports_claude=profile_supports_claude,
                route_proxy_base_url=self.project_route_proxy_base_url(project),
                model_override=claude_model,
                fallback_model_override=claude_fallback,
                runtime_env_from_profile=lambda profile, base_url, model, fallback: claude_runtime_env_from_profile(
                    profile,
                    route_proxy_base_url=base_url,
                    model_override=model,
                    fallback_model_override=fallback,
                ),
            )
            if preparation.error_message:
                raise WorkspaceError(preparation.error_message)
            try:
                self.template_service.sync_claude_binding(
                    preparation.project_root,
                    preparation.profile,
                    route_proxy_base_url=preparation.route_proxy_base_url,
                    model_override=preparation.model_override,
                    fallback_model_override=preparation.fallback_model_override,
                )
            except Exception as exc:  # noqa: BLE001
                raise WorkspaceError(f"同步 Claude settings.local.json 失败：{exc}") from exc
            env = os.environ.copy()
            env.update(preparation.env_overrides or {})
            return self._execute_launch(
                preparation.launch_plan, "打开 Claude CMD 失败", missing_as_info=True, env=env
            )

        raise WorkspaceError(f"不支持的启动方式：{action}")

    def _execute_launch(
        self,
        plan,
        failure_prefix: str,
        *,
        missing_as_info: bool = False,
        env: dict[str, str] | None = None,
    ) -> ActionResult:
        if plan is None:
            raise WorkspaceError("启动方案不可用。")
        result = execute_project_launch_plan(
            plan, popen=subprocess.Popen, creationflags=_CREATE_NEW_CONSOLE, env=env
        )
        feedback = build_project_launch_feedback(
            result, plan, failure_message_prefix=failure_prefix, missing_as_info=missing_as_info
        )
        if feedback.info_message:
            return ActionResult(message=feedback.info_message, level="info")
        if feedback.error_message:
            raise WorkspaceError(feedback.error_message)
        return ActionResult(message=feedback.status_text or plan.success_status)

    def _sync_project_api_binding(self, project: ProjectRecord, *, sync_claude: bool) -> bool:
        session = self.session
        codex_profile = session.profile_by_id(project_codex_profile_id(project))
        claude_profile = session.profile_by_id(project_claude_profile_id(project))
        claude_model, claude_fallback = self._claude_model_overrides(project)
        plan = build_project_binding_sync_plan(
            project,
            route_proxy_base_url=self.project_route_proxy_base_url(project),
            codex_profile=codex_profile,
            codex_model_override=self._codex_model_override(project),
            claude_profile=claude_profile,
            claude_model_override=claude_model,
            claude_fallback_model_override=claude_fallback,
            sync_codex=True,
            sync_claude=sync_claude,
        )
        result = execute_project_binding_sync(
            plan,
            sync_codex_binding=lambda _plan, task: self.template_service.sync_api_binding(
                _plan.project_root,
                task.profile,
                route_proxy_base_url=_plan.route_proxy_base_url,
                model_override=task.model_override,
            ),
            sync_claude_binding=lambda _plan, task: self.template_service.sync_claude_binding(
                _plan.project_root,
                task.profile,
                route_proxy_base_url=_plan.route_proxy_base_url,
                model_override=task.model_override,
                fallback_model_override=task.fallback_model_override,
            ),
        )
        if result.failure is not None:
            return False
        self.persist()
        return True

    def sync_project_binding(self, project_id: str = "") -> ActionResult:
        session = self.session
        project = session.project_by_id(project_id) or session.selected_project()
        if project is None:
            raise WorkspaceError("请先选择一个项目。")
        self.refresh_route_proxy_rules(project)
        codex_profile = session.profile_by_id(project_codex_profile_id(project))
        claude_profile = session.profile_by_id(project_claude_profile_id(project))
        claude_model, claude_fallback = self._claude_model_overrides(project)
        plan = build_project_binding_sync_plan(
            project,
            route_proxy_base_url=self.project_route_proxy_base_url(project),
            codex_profile=codex_profile,
            codex_model_override=self._codex_model_override(project),
            claude_profile=claude_profile,
            claude_model_override=claude_model,
            claude_fallback_model_override=claude_fallback,
            sync_codex=True,
            sync_claude=True,
        )
        result = execute_project_binding_sync(
            plan,
            sync_codex_binding=lambda _plan, task: self.template_service.sync_api_binding(
                _plan.project_root,
                task.profile,
                route_proxy_base_url=_plan.route_proxy_base_url,
                model_override=task.model_override,
            ),
            sync_claude_binding=lambda _plan, task: self.template_service.sync_claude_binding(
                _plan.project_root,
                task.profile,
                route_proxy_base_url=_plan.route_proxy_base_url,
                model_override=task.model_override,
                fallback_model_override=task.fallback_model_override,
            ),
        )
        if result.failure is not None:
            raise WorkspaceError(result.failure.message if hasattr(result.failure, "message") else "同步绑定失败。")
        self.persist()
        return ActionResult(message=f"已同步 {project.name} 的绑定：{len(result.updated_paths)} 个文件。")

    def sync_project_repo(self, project_id: str = "") -> ActionResult:
        session = self.session
        project = session.project_by_id(project_id) or session.selected_project()
        if project is None:
            raise WorkspaceError("请先选择一个项目。")
        if not project.github_repo:
            raise WorkspaceError("该项目尚未配置 GitHub 仓库。")

        root = Path(project.project_dir)
        if not root.exists():
            raise WorkspaceError("项目目录不存在。")

        def load_project_metadata(current: ProjectRecord, repo_root: Path) -> tuple[ProjectRecord, bool]:
            return current, False

        result = execute_project_repo_update(
            project,
            sync_checkout=lambda repo_root: sync_project_checkout(
                repo_root,
                remote_url=project.github_repo,
                ref=normalize_git_ref(project.github_ref, default=DEFAULT_PROJECT_GITHUB_REF),
                latest_commit=self._project_remote_commit(project),
                default_ref=DEFAULT_PROJECT_GITHUB_REF,
            ),
            verify_project_checksums=lambda repo_root: None,
            load_project_metadata=load_project_metadata,
        )
        if result.failure_detail:
            raise WorkspaceError(result.failure_detail)

        if result.updated_project is not None:
            updated = result.updated_project
            session.projects = [updated if item.id == updated.id else item for item in session.projects]
        self.persist()
        return ActionResult(
            message=result.status_text
            or build_project_repo_update_status_text(
                project.name, result.synced_commit or "", metadata_updated=bool(result.metadata_updated)
            )
        )

    def _project_remote_commit(self, project: ProjectRecord) -> str:
        try:
            return git_remote_commit(
                project.github_repo,
                normalize_git_ref(project.github_ref, default=DEFAULT_PROJECT_GITHUB_REF),
                default_ref=DEFAULT_PROJECT_GITHUB_REF,
            )
        except Exception:  # noqa: BLE001 - offline/failed fetch falls back to a plain pull
            return ""

    # =====================================================================
    # Route proxy
    # =====================================================================
    @property
    def proxy_running(self) -> bool:
        return bool(self.route_proxy_server.is_running)

    def save_proxy_settings(self, payload: dict[str, Any]) -> ActionResult:
        from ..ui.route_proxy_logic import (
            ROUTE_PROXY_ACCOUNT_POOL_STRATEGY_VALUES,
            apply_route_proxy_settings_form,
            normalize_route_proxy_settings_form,
        )

        session = self.session

        def value(key: str, default: str) -> str:
            raw = payload.get(key, default)
            return str(raw if raw is not None else default)

        try:
            form = normalize_route_proxy_settings_form(
                session.route_proxy,
                host_value=value("host", session.route_proxy.host),
                port_value=value("port", str(session.route_proxy.port)),
                strategy_label=value("strategyLabel", "") or session.route_proxy.account_pool_strategy,
                strategy_values=ROUTE_PROXY_ACCOUNT_POOL_STRATEGY_VALUES,
                upstream_timeout_value=value(
                    "upstreamTimeoutSeconds", str(session.route_proxy.upstream_timeout_seconds)
                ),
            )
        except ValueError as exc:
            raise WorkspaceError(str(exc)) from exc

        was_running = self.proxy_running
        apply_route_proxy_settings_form(session.route_proxy, form)
        self.persist()
        if was_running:
            # Port/host changes require a restart to take effect.
            self.route_proxy_server.stop()
            try:
                self.route_proxy_server.start()
            except Exception as exc:  # noqa: BLE001
                session.route_proxy.enabled = False
                self.persist()
                raise WorkspaceError(f"路由代理重启失败：{exc}") from exc
        return ActionResult(message="路由代理设置已保存。")

    def start_proxy(self) -> ActionResult:
        from ..ui.route_proxy_logic import route_proxy_started_status

        session = self.session
        session.route_proxy.enabled = True
        try:
            self.route_proxy_server.start()
        except Exception as exc:  # noqa: BLE001
            session.route_proxy.enabled = False
            self.persist()
            raise WorkspaceError(f"路由代理启动失败：{exc}") from exc
        self.persist()
        return ActionResult(message=route_proxy_started_status(session.route_proxy))

    def stop_proxy(self) -> ActionResult:
        from ..ui.route_proxy_logic import route_proxy_stopped_status

        self.route_proxy_server.stop()
        self.session.route_proxy.enabled = False
        self.flush_proxy_state()
        self.persist()
        return ActionResult(message=route_proxy_stopped_status(), level="info")

    def toggle_proxy(self) -> ActionResult:
        if self.proxy_running:
            return self.stop_proxy()
        return self.start_proxy()

    def set_project_proxy_enabled(self, enabled: bool, project_id: str = "") -> ActionResult:
        session = self.session
        project = session.project_by_id(project_id) or session.selected_project()
        if project is None:
            raise WorkspaceError("请先选择一个项目。")

        if enabled:
            codex_profile = session.profile_by_id(project_codex_profile_id(project))
            claude_profile = session.profile_by_id(project_claude_profile_id(project))
            if codex_profile is None or claude_profile is None:
                raise WorkspaceError("项目绑定的 Codex 或 Claude 配置不存在，无法启用路由代理。")
            plan = build_route_proxy_project_enable_plan(
                session.route_proxy, session.account_pool, project, codex_profile, claude_profile
            )
            session.route_proxy = plan.settings
            message = plan.success_status
        else:
            plan = build_route_proxy_project_disable_plan(session.route_proxy, project)
            session.route_proxy = plan.settings
            message = plan.success_status

        self.persist()
        return ActionResult(message=message)

    def clear_events(self) -> ActionResult:
        self.session.clear_events()
        return ActionResult(message="已清空事件日志。", level="info")

    # =====================================================================
    # Model batch test
    # =====================================================================
    def model_batch_targets(self, profile_id: str = "") -> list[str]:
        profile = self.session.profile_by_id(profile_id) or self.session.selected_profile()
        return model_batch_targets(profile)

    def run_model_batch(
        self,
        *,
        profile_id: str = "",
        progress: Callable[[str, str, str, int], None] | None = None,
        should_cancel: Callable[[], bool] | None = None,
        on_start: Callable[[str], None] | None = None,
    ) -> ActionResult:
        from ..ui.model_batch_logic import MODEL_BATCH_PROMPT  # noqa: F401  (documents the prompt used)

        session = self.session
        profile = session.profile_by_id(profile_id) or session.selected_profile()
        if profile is None:
            raise WorkspaceError("请先选择一个配置用于模型测试。")

        models = model_batch_targets(profile)
        if not models:
            raise WorkspaceError("该配置还没有可用模型，请先执行健康检测。")

        wire_api = default_wire_api_for_profile(profile)
        cache = ModelBatchCache(models=list(models), results={}, completed=False)
        session.model_batch_cache_by_profile[profile.id] = cache

        def handle_start(model: str) -> None:
            if on_start is not None:
                on_start(model)

        def handle_result(model: str, status: str, detail: str, duration_ms: int) -> None:
            cache.results[model] = ModelBatchResult(status=status, detail=detail, duration_ms=duration_ms)
            if progress is not None:
                progress(model, status, detail, duration_ms)

        if should_cancel is not None and should_cancel():
            raise WorkspaceError("模型测试已取消。")

        run_model_batch_requests(
            self.chat_tester,
            profile,
            models,
            wire_api,
            None,
            handle_start,
            handle_result,
            max_workers=clamp_model_batch_concurrency(session.model_batch_concurrency),
        )

        if should_cancel is not None and should_cancel():
            cache.completed = False
            raise WorkspaceError("模型测试已取消。")

        cache.completed = True
        cache.tested_at = _now()
        self.persist()

        success = sum(1 for item in cache.results.values() if item.status == "success")
        return ActionResult(message=f"模型测试完成：{success}/{len(models)} 个模型可用。")

    def send_chat(self, prompt: str, model: str = "", wire_api: str = "") -> ActionResult:
        session = self.session
        profile = session.selected_profile()
        if profile is None:
            raise WorkspaceError("请先选择一个配置。")
        text = str(prompt or "").strip()
        if not text:
            raise WorkspaceError("请输入测试消息。")

        session.chat_messages.append({"role": "user", "text": text})
        effective_wire = str(wire_api or default_wire_api_for_profile(profile))
        result: ChatResult = self.chat_tester.send_message(
            profile,
            text,
            model_override=str(model or "") or None,
            wire_api_override=effective_wire,
        )
        session.chat_messages.append(
            {
                "role": "assistant",
                "text": result.text,
                "ok": bool(result.ok),
                "model": result.model or "",
                "endpoint": result.endpoint or "",
                "detail": result.detail or "",
            }
        )
        if len(session.chat_messages) > 100:
            del session.chat_messages[: len(session.chat_messages) - 100]
        if not result.ok:
            return ActionResult(message=f"聊天测试失败：{result.text}", level="error")
        return ActionResult(message=f"聊天测试成功（{result.model or '默认模型'}）。")

    def clear_chat(self) -> ActionResult:
        self.session.chat_messages.clear()
        return ActionResult(message="已清空对话记录。", level="info")

    # =====================================================================
    # Account pool
    # =====================================================================
    def select_pool_group(self, group_id: str) -> ActionResult:
        session = self.session
        if group_id and session.account_pool.group_by_id(group_id) is None:
            raise WorkspaceError("号池组不存在。")
        session.account_pool.selected_group_id = group_id
        self.persist()
        return ActionResult(message="已切换号池组。", level="info")

    def pool_group_form_fields(self, group_id: str) -> list[dict[str, Any]]:
        group = self.session.account_pool.group_by_id(group_id)
        if group_id and group is None:
            raise WorkspaceError("号池组不存在。")
        return forms.pool_group_form(group)

    def save_pool_group(self, payload: dict[str, Any], *, group_id: str = "") -> ActionResult:
        data = forms.pool_group_payload(payload)
        pool = self.session.account_pool
        if group_id:
            group = pool.group_by_id(group_id)
            if group is None:
                raise WorkspaceError("号池组不存在。")
            group.name = data["name"]
            group.enabled = data["enabled"]
            group.pool_type = data["pool_type"]
            group.default_model = data["default_model"]
            group.claude_model = data["claude_model"]
            group.claude_fallback_model = data["claude_fallback_model"]
            message = f"已保存号池组：{group.name}"
        else:
            created = pool.add_group(
                data["name"],
                pool_type=data["pool_type"],
                default_model=data["default_model"],
                claude_model=data["claude_model"],
                claude_fallback_model=data["claude_fallback_model"],
            )
            created.enabled = data["enabled"]
            pool.selected_group_id = created.id
            message = f"已新增号池组：{created.name}"
        self.persist()
        return ActionResult(message=message)

    def delete_pool_group(self, group_id: str) -> ActionResult:
        pool = self.session.account_pool
        group = pool.group_by_id(group_id)
        if group is None:
            raise WorkspaceError("号池组不存在。")
        bound = [
            project.name
            for project in self.session.projects
            if self.session.route_proxy.project_enabled(project.id)
            and any(rule.account_pool_group_id == group_id for rule in self.session.route_proxy.rules_for_project(project.id))
        ]
        if bound:
            raise WorkspaceError(f"以下项目仍在使用该号池组：{'、'.join(bound)}")
        pool.remove_group(group_id)
        self.persist()
        return ActionResult(message=f"已删除号池组：{group.name}")

    def pool_channel_form_fields(self, channel_id: str) -> list[dict[str, Any]]:
        channel = account_pool_channel_by_id(self.session.account_pool, channel_id)
        if channel_id and channel is None:
            raise WorkspaceError("号池渠道不存在。")
        return forms.pool_channel_form(channel)

    def save_pool_channel(self, payload: dict[str, Any], *, channel_id: str = "") -> ActionResult:
        data = forms.pool_channel_payload(payload)
        pool = self.session.account_pool
        group_id = pool.selected_group_id or (pool.groups[0].id if pool.groups else "")
        if not group_id:
            raise WorkspaceError("请先创建一个号池组。")

        existing = account_pool_channel_by_id(pool, channel_id)
        if channel_id and existing is None:
            raise WorkspaceError("号池渠道不存在。")

        creation = {
            "name": data["name"],
            "base_url": data["base_url"],
            "api_key": data["api_key"],
            "group_id": existing.group_id if existing is not None else group_id,
            "source_type": existing.source_type if existing is not None else ACCOUNT_POOL_CHANNEL_SOURCE_TEMPORARY,
            "source_profile_id": existing.source_profile_id if existing is not None else "",
            "source_profile_name": existing.source_profile_name if existing is not None else "",
            "source_api_key_index": existing.source_api_key_index if existing is not None else 0,
            "wire_api": data["wire_api"],
            "default_model": data["default_model"] or "",
            "custom_headers": dict(existing.custom_headers) if existing is not None else {},
        }
        if existing is not None:
            channel = replace(existing, **creation)
            pool.replace_channel(channel)
            message = f"已保存号池渠道：{channel.name}"
        else:
            channel = AccountPoolChannel.create(**creation)
            pool.channels.append(channel)
            message = f"已新增号池渠道：{channel.name}"
        self.persist()
        return ActionResult(message=message)

    def delete_pool_channel(self, channel_id: str) -> ActionResult:
        pool = self.session.account_pool
        channel = account_pool_channel_by_id(pool, channel_id)
        if channel is None:
            raise WorkspaceError("号池渠道不存在。")
        if channel.source_type == ACCOUNT_POOL_CHANNEL_SOURCE_PROFILE:
            raise WorkspaceError("该渠道来自配置库，请从配置库中管理。")
        pool.remove_channel(channel_id)
        self.persist()
        return ActionResult(message=f"已删除号池渠道：{channel.name}")

    def test_pool_channel(self, channel_id: str) -> ActionResult:
        pool = self.session.account_pool
        channel = account_pool_channel_by_id(pool, channel_id)
        if channel is None:
            raise WorkspaceError("号池渠道不存在。")
        result = check_account_pool_channel(channel, settings=pool, validator=self.account_pool_validator)
        if result.status == "healthy":
            pool.mark_success(channel.id)
            self.persist()
            return ActionResult(message=f"渠道可用：{channel.name}")
        pool.mark_failed(channel.id, result.detail or "检测失败")
        self.persist()
        raise WorkspaceError(f"渠道检测失败：{result.detail or '未知原因'}")

    def test_all_pool_channels(self, *, progress: Callable[[str], None] | None = None) -> ActionResult:
        pool = self.session.account_pool
        channels = list(pool.channels)
        if not channels:
            raise WorkspaceError("号池中还没有渠道。")
        healthy = 0
        failures: list[str] = []
        for channel in channels:
            if progress:
                progress(f"正在检测渠道 {channel.name} …")
            result = check_account_pool_channel(channel, settings=pool, validator=self.account_pool_validator)
            if result.status == "healthy":
                pool.mark_success(channel.id)
                healthy += 1
            else:
                pool.mark_failed(channel.id, result.detail or "检测失败")
                failures.append(f"{channel.name}：{result.detail or '未知原因'}")
        self.persist()
        if failures:
            return ActionResult(
                message=f"号池检测完成：{healthy}/{len(channels)} 个渠道可用。",
                level="warning",
                detail="\n".join(failures),
            )
        return ActionResult(message=f"号池检测完成：{healthy} 个渠道全部可用。")

    def _account_pool_project_count(self) -> int:
        from ..ui.account_pool_logic import account_pool_project_count

        return account_pool_project_count(self.session.projects, self.session.route_proxy)

    # =====================================================================
    # MCP
    # =====================================================================
    def mcp_form_fields(self, name: str) -> list[dict[str, Any]]:
        servers = self._mcp_servers()
        if name and name not in servers:
            raise WorkspaceError("MCP 服务不存在。")
        return forms.mcp_form(name, servers.get(name))

    def _mcp_servers(self) -> dict[str, dict]:
        try:
            return parse_mcp_servers_toml(self._global_mcp_source_toml())
        except ValueError:
            return {}

    def save_mcp(self, payload: dict[str, Any], *, current_name: str = "") -> ActionResult:
        servers = self._mcp_servers()
        existing = servers.get(current_name) if current_name else None
        name, config = forms.mcp_payload(
            payload,
            default_type=str((existing or {}).get("type", "stdio")),
            default_args=(existing or {}).get("args") if isinstance((existing or {}).get("args"), list) else None,
            default_env=(existing or {}).get("env") if isinstance((existing or {}).get("env"), dict) else None,
        )
        conflict = mcp_logic.mcp_name_conflict_error(servers, name, current_name=current_name or None)
        if conflict:
            raise WorkspaceError(conflict)

        mutation = mcp_logic.mcp_collection_after_upsert(
            servers, name, config, current_name=current_name or None
        )
        self._persist_mcp(mutation.page_servers)
        return ActionResult(message=f"已保存 MCP 服务：{name}")

    def delete_mcp(self, name: str) -> ActionResult:
        servers = self._mcp_servers()
        if name not in servers:
            raise WorkspaceError("MCP 服务不存在。")
        mutation = mcp_logic.mcp_collection_after_delete(servers, name)
        self._persist_mcp(mutation.page_servers)
        return ActionResult(message=f"已删除 MCP 服务：{name}")

    def restore_default_mcp(self) -> ActionResult:
        default_toml = load_default_global_mcp_toml()
        try:
            servers = parse_mcp_servers_toml(default_toml)
        except ValueError as exc:
            raise WorkspaceError(f"默认 MCP 配置解析失败：{exc}") from exc
        self._persist_mcp(servers)
        return ActionResult(message=f"已恢复默认 MCP 配置（{len(servers)} 个服务）。")

    def _persist_mcp(self, servers: dict[str, dict]) -> None:
        session = self.session
        state = mcp_logic.build_mcp_persist_state(servers, session.global_mcp_server_names)
        session.global_mcp_toml = state.global_mcp_toml
        session.global_mcp_server_names = state.global_mcp_server_names
        session.global_mcp_opt_out = state.global_mcp_opt_out
        self.persist()

    # =====================================================================
    # Skills
    # =====================================================================
    def skill_group_form_fields(self, group_id: str) -> list[dict[str, Any]]:
        group = self.session.skill_group_by_id(group_id)
        if group_id and group is None:
            raise WorkspaceError("Skills 组不存在。")
        return forms.skill_group_form(group)

    def save_skill_group(self, payload: dict[str, Any], *, group_id: str = "") -> ActionResult:
        data = forms.skill_group_payload(payload)
        session = self.session
        error = skill_group_name_error(data["name"])
        if error:
            raise WorkspaceError(error)

        if group_id:
            group = session.skill_group_by_id(group_id)
            if group is None:
                raise WorkspaceError("Skills 组不存在。")
            updated = skill_group_with_metadata(group, name=data["name"], description=data["description"])
            session.skill_groups = replace_skill_group(session.skill_groups, updated)
            message = f"已保存 Skills 组：{updated.name}"
        else:
            created = SkillGroup.create(data["name"], description=data["description"])
            session.skill_groups = [*session.skill_groups, created]
            message = f"已新增 Skills 组：{created.name}"
        self.persist()
        return ActionResult(message=message)

    def delete_skill_group(self, group_id: str) -> ActionResult:
        session = self.session
        group = session.skill_group_by_id(group_id)
        if group is None:
            raise WorkspaceError("Skills 组不存在。")
        session.skill_groups = remove_skill_group(session.skill_groups, group_id)
        session.skill_market_repos = [
            replace(item, installed_group_id="") if item.installed_group_id == group_id else item
            for item in session.skill_market_repos
        ]
        session.projects = projects_after_skill_group_delete(session.projects, group_id)
        self.persist()
        return ActionResult(message=f"已删除 Skills 组：{group.name}")

    def skill_form_fields(self, group_id: str, skill_id: str = "") -> list[dict[str, Any]]:
        group = self.session.skill_group_by_id(group_id)
        if group is None:
            raise WorkspaceError("Skills 组不存在。")
        skill = next((item for item in group.skills if item.id == skill_id), None) if skill_id else None
        if skill_id and skill is None:
            raise WorkspaceError("Skill 不存在。")
        return forms.skill_form(skill)

    def save_skill(self, payload: dict[str, Any], *, group_id: str, skill_id: str = "") -> ActionResult:
        data = forms.skill_payload(payload)
        session = self.session
        group = session.skill_group_by_id(group_id)
        if group is None:
            raise WorkspaceError("Skills 组不存在。")

        if skill_id:
            existing = next((item for item in group.skills if item.id == skill_id), None)
            if existing is None:
                raise WorkspaceError("Skill 不存在。")
            updated_skill = replace(
                existing,
                name=data["name"],
                type=data["type"],
                version=data["version"],
                content=data["content"],
            )
            updated_group = skill_group_with_replaced_skill(group, skill_id, updated_skill)
            message = f"已保存 Skill：{updated_skill.name}"
        else:
            created = SkillDefinition.create(
                data["name"], type=data["type"], version=data["version"], content=data["content"]
            )
            updated_group = skill_group_with_added_skill(group, created)
            message = f"已新增 Skill：{created.name}"

        session.skill_groups = replace_skill_group(session.skill_groups, updated_group)
        session.projects, _changed = sync_projects_from_skill_groups(session.projects, session.skill_groups)
        self.persist()
        return ActionResult(message=message)

    def delete_skill(self, group_id: str, skill_id: str) -> ActionResult:
        session = self.session
        group = session.skill_group_by_id(group_id)
        if group is None:
            raise WorkspaceError("Skills 组不存在。")
        skill = next((item for item in group.skills if item.id == skill_id), None)
        if skill is None:
            raise WorkspaceError("Skill 不存在。")
        updated_group = skill_group_with_deleted_skill(group, skill_id)
        session.skill_groups = replace_skill_group(session.skill_groups, updated_group)
        session.projects, _changed = sync_projects_from_skill_groups(session.projects, session.skill_groups)
        self.persist()
        return ActionResult(message=f"已删除 Skill：{skill.name}")

    def skill_repo_form_fields(self, repo_id: str) -> list[dict[str, Any]]:
        repo = self.session.skill_repo_by_id(repo_id)
        if repo_id and repo is None:
            raise WorkspaceError("Skills 仓库不存在。")
        return forms.skill_repo_form(repo)

    def save_skill_repo(self, payload: dict[str, Any], *, repo_id: str = "") -> ActionResult:
        data = forms.skill_repo_payload(payload)
        session = self.session
        if repo_id:
            repo = session.skill_repo_by_id(repo_id)
            if repo is None:
                raise WorkspaceError("Skills 仓库不存在。")
            updated = replace(
                repo,
                url=data["url"],
                branch=normalize_git_ref(data["branch"], default=DEFAULT_SKILL_REPO_REF),
                auto_update=data["auto_update"],
            )
            session.skill_market_repos = [
                updated if item.id == updated.id else item for item in session.skill_market_repos
            ]
            message = f"已保存 Skills 仓库：{updated.url}"
        else:
            created = SkillMarketRepo.create(
                data["url"],
                branch=normalize_git_ref(data["branch"], default=DEFAULT_SKILL_REPO_REF),
                auto_update=data["auto_update"],
            )
            session.skill_market_repos = [*session.skill_market_repos, created]
            message = f"已新增 Skills 仓库：{created.url}"
        self.persist()
        return ActionResult(message=message)

    def delete_skill_repo(self, repo_id: str) -> ActionResult:
        session = self.session
        repo = session.skill_repo_by_id(repo_id)
        if repo is None:
            raise WorkspaceError("Skills 仓库不存在。")
        session.skill_market_repos = [item for item in session.skill_market_repos if item.id != repo_id]
        self.persist()
        return ActionResult(message=f"已删除 Skills 仓库：{repo.url}")

    def _skill_repo_cache_dir(self, repo: SkillMarketRepo) -> Path:
        return self.store.root_dir / "skill-market" / repo.id

    def install_skill_repo(self, repo_id: str, *, group_id: str = "") -> ActionResult:
        session = self.session
        repo = session.skill_repo_by_id(repo_id)
        if repo is None:
            raise WorkspaceError("Skills 仓库不存在。")

        group = session.skill_group_by_id(group_id) if group_id else None
        if group is None and repo.installed_group_id:
            group = session.skill_group_by_id(repo.installed_group_id)
        if group is None:
            group = SkillGroup.create(repo.url.rstrip("/").split("/")[-1] or "Skills 仓库")
            session.skill_groups = [*session.skill_groups, group]

        cache_dir = self._skill_repo_cache_dir(repo)
        try:
            target_commit = git_remote_commit(
                repo.url,
                normalize_git_ref(repo.branch, default=DEFAULT_SKILL_REPO_REF),
                default_ref=DEFAULT_SKILL_REPO_REF,
            )
        except Exception as exc:  # noqa: BLE001
            raise WorkspaceError(f"读取仓库远端信息失败：{exc}") from exc

        try:
            synced_commit = sync_repo_cache(
                cache_dir,
                remote_url=repo.url,
                ref=normalize_git_ref(repo.branch, default=DEFAULT_SKILL_REPO_REF),
                target_commit=target_commit,
            )
            sources = discover_skill_sources([cache_dir])
            verify_hot_update_checksums(cache_dir, skill_repo_checksum_required_paths(cache_dir, sources))
        except Exception as exc:  # noqa: BLE001
            raise WorkspaceError(f"安装失败：{exc}") from exc

        self._load_model_metadata_from_repo(cache_dir)
        updated_group, imported = import_skill_sources_to_group(group, sources)

        synced_repo = session.skill_repo_by_id(repo.id) or repo
        updated_repo = replace(synced_repo, last_sync_commit=synced_commit, installed_group_id=updated_group.id)
        session.skill_market_repos = [
            updated_repo if item.id == updated_repo.id else item for item in session.skill_market_repos
        ]
        if imported:
            session.skill_groups = replace_skill_group(session.skill_groups, updated_group)
            session.projects, _changed = sync_projects_from_skill_groups(session.projects, session.skill_groups)
        elif session.skill_group_by_id(updated_group.id) is None:
            session.skill_groups = [*session.skill_groups, updated_group]

        self.persist()
        if imported:
            return ActionResult(message=f"已从仓库安装 {imported} 个 Skills 到 {updated_group.name}。")
        return ActionResult(message="仓库中没有新的 Skills，已绑定到目标组。", level="info")

    def _load_model_metadata_from_repo(self, repo_root: Path) -> bool:
        import json

        for relative_path in MODEL_METADATA_RELATIVE_PATHS:
            metadata_path = repo_root / relative_path
            if not metadata_path.is_file():
                continue
            try:
                payload = json.loads(metadata_path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if not isinstance(payload, dict):
                continue
            profiles, changed = apply_profile_metadata(self.session.profiles, payload)
            if changed:
                self.session.profiles = profiles
                self.session.normalize_global_profile_ids()
            return changed
        return False

    # =====================================================================
    # Settings / updates
    # =====================================================================
    def save_general_settings(self, payload: dict[str, Any]) -> ActionResult:
        session = self.session
        if "hotUpdateEnabled" in payload:
            session.hot_update_enabled = _as_bool(payload.get("hotUpdateEnabled"))
        if "hotUpdateIntervalMinutes" in payload:
            session.hot_update_interval_minutes = normalize_hot_update_interval_minutes(
                payload.get("hotUpdateIntervalMinutes")
            )
        if "modelBatchConcurrency" in payload:
            session.model_batch_concurrency = clamp_model_batch_concurrency(
                payload.get("modelBatchConcurrency")
            )
        self.persist()
        return ActionResult(message="设置已保存。")

    def save_agents_doc(self, text: str) -> ActionResult:
        self.session.agents_doc_text = str(text or "")
        self.persist()
        return ActionResult(message="文档模板已保存。")

    def restore_agents_doc(self) -> ActionResult:
        self.session.agents_doc_text = load_default_agents_doc_text()
        self.persist()
        return ActionResult(message="已恢复默认文档模板。")

    def check_software_update(self) -> ActionResult:
        try:
            info = self.update_checker.check(__version__)
        except Exception as exc:  # noqa: BLE001
            raise WorkspaceError(f"检查软件更新失败：{exc}") from exc
        self.software_update_info = info
        if bool(getattr(info, "update_available", False)):
            return ActionResult(
                message=f"发现新版本 {getattr(info, 'version', '')}。",
                detail=str(getattr(info, "download_url", "") or getattr(info, "release_url", "") or ""),
            )
        return ActionResult(message=f"当前已是最新版本（{__version__}）。", level="info")

    def check_hot_updates(self) -> ActionResult:
        session = self.session
        updated = 0
        pending = 0
        errors: list[str] = []

        for repo in list(session.skill_market_repos):
            outcome = self._check_repo_update(repo)
            if outcome == "updated":
                updated += 1
            elif outcome == "pending":
                pending += 1
            elif outcome:
                errors.append(outcome)

        for project in list(session.projects):
            if not project.github_repo:
                continue
            outcome = self._check_project_update(project)
            if outcome == "updated":
                updated += 1
            elif outcome == "pending":
                pending += 1
            elif outcome:
                errors.append(outcome)

        if errors:
            session.hot_update_events = _append_events(
                session.hot_update_events,
                scope="hot-update",
                target="批量检查",
                status="error",
                detail="；".join(errors),
            )
        self.persist()

        if errors and not updated:
            return ActionResult(
                message=f"仓库同步检查完成，{len(errors)} 项失败。", level="error", detail="\n".join(errors)
            )
        summary = f"仓库同步检查完成：更新 {updated} 项"
        if pending:
            summary += f"，{pending} 项待处理"
        if errors:
            summary += f"，{len(errors)} 项失败"
        return ActionResult(message=summary + "。", level="info" if not errors else "warning", detail="\n".join(errors))

    def _check_repo_update(self, repo: SkillMarketRepo) -> str:
        try:
            update = skill_repo_remote_update(
                repo,
                default_ref=DEFAULT_SKILL_REPO_REF,
                cache_dir=self._skill_repo_cache_dir(repo),
            )
        except Exception as exc:  # noqa: BLE001
            return f"{repo.url}：{exc}"
        if not update.has_update():
            return ""
        if not repo.auto_update:
            self.session.hot_update_events = _append_events(
                self.session.hot_update_events,
                scope="skill-repo",
                target=repo.url,
                status="pending",
                detail=f"发现新版本 {update.short_latest()}",
                commit=update.latest_commit,
            )
            return "pending"
        try:
            result = self.install_skill_repo(repo.id)
        except WorkspaceError as exc:
            return f"{repo.url}：{exc}"
        self.session.hot_update_events = _append_events(
            self.session.hot_update_events,
            scope="skill-repo",
            target=repo.url,
            status="updated",
            detail=result.message,
            commit=update.latest_commit,
            automatic=True,
        )
        return "updated"

    def _check_project_update(self, project: ProjectRecord) -> str:
        try:
            update = project_remote_update(
                project,
                default_ref=DEFAULT_PROJECT_GITHUB_REF,
                project_root=Path(project.project_dir),
            )
        except Exception as exc:  # noqa: BLE001
            return f"{project.name}：{exc}"
        if not update.has_update():
            return ""
        if not project.github_auto_update:
            self.session.hot_update_events = _append_events(
                self.session.hot_update_events,
                scope="project",
                target=project.name,
                status="pending",
                detail=f"发现新版本 {update.short_latest()}",
                commit=update.latest_commit,
            )
            return "pending"
        try:
            self.sync_project_repo(project.id)
        except WorkspaceError as exc:
            return f"{project.name}：{exc}"
        self.session.hot_update_events = _append_events(
            self.session.hot_update_events,
            scope="project",
            target=project.name,
            status="updated",
            detail="已自动同步",
            commit=update.latest_commit,
            automatic=True,
        )
        return "updated"

    def open_local_path(self, path: str) -> ActionResult:
        target = Path(str(path or ""))
        if not target.exists():
            raise WorkspaceError("路径不存在。")
        _open_path(target)
        return ActionResult(message=f"已打开：{target}", level="info")


# -- module helpers ------------------------------------------------------
def _now() -> str:
    from ..models import now_iso

    return now_iso()


def _as_bool(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().casefold() in {"1", "true", "yes", "on", "是"}
    return bool(value)


def _python_version() -> str:
    import platform

    return platform.python_version()


def _qt_version() -> str:
    try:
        from ..ui_v2.qt_compat import QT_AVAILABLE

        if not QT_AVAILABLE:
            return "未安装"
        from PySide6 import __version__ as version  # type: ignore

        return f"PySide6 {version}"
    except Exception:  # noqa: BLE001
        return "未知"


def _append_events(
    events: list[HotUpdateEvent],
    *,
    scope: str,
    target: str,
    status: str,
    detail: str = "",
    commit: str = "",
    automatic: bool = False,
) -> list[HotUpdateEvent]:
    return append_hot_update_event(
        events,
        scope=scope,
        target=target,
        status=status,
        detail=detail,
        commit=commit,
        automatic=automatic,
    )


def _open_path(path: Path) -> None:
    os.startfile(str(path))  # type: ignore[attr-defined]  # Windows-only target


def _open_url(url: str) -> None:
    os.startfile(str(url))  # type: ignore[attr-defined]


__all__ = [
    "ActionResult",
    "HealthOutcome",
    "Workspace",
    "WorkspaceError",
    "existing_repo_files",
    "expanded_skills_for_group_ids",
    "mask_secret",
]
