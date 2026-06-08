from __future__ import annotations

from pathlib import Path
import json
import os

from codex_switch.codex_config import load_default_global_mcp_toml
from codex_switch.models import (
    AccountPoolSettings,
    DEFAULT_HOT_UPDATE_INTERVAL_MINUTES,
    Profile,
    ProjectRecord,
    RouteProxySettings,
    SkillGroup,
    SkillMarketRepo,
    normalize_hot_update_interval_minutes,
)
from codex_switch.project_template import load_default_agents_doc_text


MODEL_BATCH_CONCURRENCY_MIN = 1
MODEL_BATCH_CONCURRENCY_MAX = 5
DEFAULT_MODEL_BATCH_CONCURRENCY = 3


def clamp_model_batch_concurrency(value) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = DEFAULT_MODEL_BATCH_CONCURRENCY
    return max(MODEL_BATCH_CONCURRENCY_MIN, min(MODEL_BATCH_CONCURRENCY_MAX, parsed))


class ProfileStore:
    def __init__(self, root_dir: Path | None = None) -> None:
        if root_dir is None:
            appdata = os.environ.get("APPDATA")
            if appdata:
                root_dir = Path(appdata) / "CodexSwitch"
            else:
                root_dir = Path.home() / ".codex-switch"
        self.root_dir = root_dir
        self.root_dir.mkdir(parents=True, exist_ok=True)
        self.storage_path = self.root_dir / "profiles.json"

    def load(
        self,
    ) -> tuple[
        list[Profile],
        str | None,
        list[ProjectRecord],
        str | None,
        bool,
        str,
        list[str],
        bool,
        str,
        int,
        dict,
        RouteProxySettings,
        list[str] | None,
        str | None,
        str | None,
        AccountPoolSettings,
        list[SkillGroup],
        list[SkillMarketRepo],
        bool,
        int,
    ]:
        default_global_mcp_toml = load_default_global_mcp_toml()
        default_agents_doc_text = load_default_agents_doc_text()
        if not self.storage_path.exists():
            return (
                [],
                None,
                [],
                None,
                False,
                default_global_mcp_toml,
                [],
                False,
                default_agents_doc_text,
                DEFAULT_MODEL_BATCH_CONCURRENCY,
                {},
                RouteProxySettings(),
                None,
                None,
                None,
                AccountPoolSettings(),
                [],
                [],
                False,
                DEFAULT_HOT_UPDATE_INTERVAL_MINUTES,
            )

        try:
            with self.storage_path.open("r", encoding="utf-8") as handle:
                payload = json.load(handle)
        except (json.JSONDecodeError, OSError):
            return (
                [],
                None,
                [],
                None,
                False,
                default_global_mcp_toml,
                [],
                False,
                default_agents_doc_text,
                DEFAULT_MODEL_BATCH_CONCURRENCY,
                {},
                RouteProxySettings(),
                None,
                None,
                None,
                AccountPoolSettings(),
                [],
                [],
                False,
                DEFAULT_HOT_UPDATE_INTERVAL_MINUTES,
            )

        profiles = [Profile.from_dict(item) for item in payload.get("profiles", [])]
        selected_profile_id = payload.get("selected_profile_id")
        projects = [ProjectRecord.from_dict(item) for item in payload.get("projects", [])]
        selected_project_id = payload.get("selected_project_id")
        ui_payload = payload.get("ui", {})
        hide_error_profiles = False
        if isinstance(ui_payload, dict):
            hide_error_profiles = bool(ui_payload.get("hide_error_profiles", False))
        elif "hide_error_profiles" in payload:
            hide_error_profiles = bool(payload.get("hide_error_profiles"))
        settings_payload = payload.get("settings", {})
        global_mcp_toml = default_global_mcp_toml
        applied_global_mcp_server_names: list[str] = []
        global_mcp_opt_out = False
        global_mcp_server_names: list[str] | None = None
        selected_codex_global_profile_id: str | None = None
        selected_claude_global_profile_id: str | None = None
        agents_doc_text = default_agents_doc_text
        model_batch_concurrency = DEFAULT_MODEL_BATCH_CONCURRENCY
        model_batch_cache_by_profile: dict = {}
        route_proxy_settings = RouteProxySettings()
        account_pool_settings = AccountPoolSettings()
        skill_groups: list[SkillGroup] = []
        skill_market_repos: list[SkillMarketRepo] = []
        hot_update_enabled = False
        hot_update_interval_minutes = DEFAULT_HOT_UPDATE_INTERVAL_MINUTES
        if isinstance(settings_payload, dict):
            global_mcp_opt_out = bool(settings_payload.get("global_mcp_opt_out", False))
            if "global_mcp_toml" in settings_payload:
                stored_global_mcp_toml = str(settings_payload.get("global_mcp_toml", "") or "")
                if stored_global_mcp_toml.strip():
                    global_mcp_toml = stored_global_mcp_toml
                elif global_mcp_opt_out:
                    global_mcp_toml = ""
            applied_names = settings_payload.get("applied_global_mcp_server_names", [])
            if isinstance(applied_names, list):
                applied_global_mcp_server_names = [str(item) for item in applied_names if str(item).strip()]
            if "global_mcp_server_names" in settings_payload:
                selected_names = settings_payload.get("global_mcp_server_names")
                if isinstance(selected_names, list):
                    global_mcp_server_names = [str(item) for item in selected_names if str(item).strip()]
                elif selected_names is None:
                    global_mcp_server_names = None
            selected_codex_global_profile_id = str(settings_payload.get("selected_codex_global_profile_id") or "") or None
            selected_claude_global_profile_id = str(settings_payload.get("selected_claude_global_profile_id") or "") or None
            if "agents_doc_text" in settings_payload:
                agents_doc_text = str(settings_payload.get("agents_doc_text") or "")
            model_batch_concurrency = clamp_model_batch_concurrency(
                settings_payload.get("model_batch_concurrency", DEFAULT_MODEL_BATCH_CONCURRENCY)
            )
            stored_model_batch_cache = settings_payload.get("model_batch_cache_by_profile", {})
            if isinstance(stored_model_batch_cache, dict):
                model_batch_cache_by_profile = stored_model_batch_cache
            route_proxy_settings = RouteProxySettings.from_dict(settings_payload.get("route_proxy"))
            account_pool_settings = AccountPoolSettings.from_dict(settings_payload.get("account_pool"))
            raw_skill_groups = settings_payload.get("skill_groups", [])
            if isinstance(raw_skill_groups, list):
                skill_groups = [
                    SkillGroup.from_dict(item)
                    for item in raw_skill_groups
                    if isinstance(item, dict)
                ]
            raw_skill_market_repos = settings_payload.get("skill_market_repos", [])
            if isinstance(raw_skill_market_repos, list):
                skill_market_repos = [
                    SkillMarketRepo.from_dict(item)
                    for item in raw_skill_market_repos
                    if isinstance(item, dict)
                ]
            hot_update_enabled = bool(settings_payload.get("hot_update_enabled", False))
            hot_update_interval_minutes = normalize_hot_update_interval_minutes(
                settings_payload.get("hot_update_interval_minutes")
            )
        return (
            profiles,
            selected_profile_id,
            projects,
            selected_project_id,
            hide_error_profiles,
            global_mcp_toml,
            applied_global_mcp_server_names,
            global_mcp_opt_out,
            agents_doc_text,
            model_batch_concurrency,
            model_batch_cache_by_profile,
            route_proxy_settings,
            global_mcp_server_names,
            selected_codex_global_profile_id,
            selected_claude_global_profile_id,
            account_pool_settings,
            skill_groups,
            skill_market_repos,
            hot_update_enabled,
            hot_update_interval_minutes,
        )

    def save(
        self,
        profiles: list[Profile],
        selected_profile_id: str | None,
        projects: list[ProjectRecord] | None = None,
        selected_project_id: str | None = None,
        hide_error_profiles: bool = False,
        global_mcp_toml: str = "",
        applied_global_mcp_server_names: list[str] | None = None,
        global_mcp_opt_out: bool = False,
        agents_doc_text: str | None = None,
        model_batch_concurrency: int = DEFAULT_MODEL_BATCH_CONCURRENCY,
        model_batch_cache_by_profile: dict | None = None,
        route_proxy_settings: RouteProxySettings | None = None,
        global_mcp_server_names: list[str] | None = None,
        selected_codex_global_profile_id: str | None = None,
        selected_claude_global_profile_id: str | None = None,
        account_pool_settings: AccountPoolSettings | None = None,
        skill_groups: list[SkillGroup] | None = None,
        skill_market_repos: list[SkillMarketRepo] | None = None,
        hot_update_enabled: bool = False,
        hot_update_interval_minutes: int = DEFAULT_HOT_UPDATE_INTERVAL_MINUTES,
    ) -> None:
        if agents_doc_text is None:
            agents_doc_text = load_default_agents_doc_text()
        if route_proxy_settings is None:
            route_proxy_settings = RouteProxySettings()
        if account_pool_settings is None:
            account_pool_settings = AccountPoolSettings()
        payload = {
            "version": 14,
            "selected_profile_id": selected_profile_id,
            "profiles": [profile.to_dict() for profile in profiles],
            "selected_project_id": selected_project_id,
            "projects": [project.to_dict() for project in (projects or [])],
            "ui": {
                "hide_error_profiles": hide_error_profiles,
            },
            "settings": {
                "global_mcp_toml": global_mcp_toml,
                "applied_global_mcp_server_names": list(applied_global_mcp_server_names or []),
                "global_mcp_opt_out": global_mcp_opt_out,
                "global_mcp_server_names": None
                if global_mcp_server_names is None
                else list(global_mcp_server_names),
                "selected_codex_global_profile_id": selected_codex_global_profile_id,
                "selected_claude_global_profile_id": selected_claude_global_profile_id,
                "agents_doc_text": agents_doc_text,
                "model_batch_concurrency": clamp_model_batch_concurrency(model_batch_concurrency),
                "model_batch_cache_by_profile": dict(model_batch_cache_by_profile or {}),
                "route_proxy": route_proxy_settings.to_dict(),
                "account_pool": account_pool_settings.to_dict(),
                "skill_groups": [group.to_dict() for group in (skill_groups or [])],
                "skill_market_repos": [repo.to_dict() for repo in (skill_market_repos or [])],
                "hot_update_enabled": bool(hot_update_enabled),
                "hot_update_interval_minutes": normalize_hot_update_interval_minutes(hot_update_interval_minutes),
            },
        }
        with self.storage_path.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
