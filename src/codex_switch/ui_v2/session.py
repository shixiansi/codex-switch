"""In-memory application state.

The session is the single mutable owner of everything the UI shows. It mirrors
``ProfileStore`` exactly (no new fields in ``profiles.json``) and adds only
transient runtime state such as the event log and background-task status.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..models import (
    AccountPoolSettings,
    HotUpdateEvent,
    Profile,
    ProjectRecord,
    RouteProxyEvent,
    RouteProxySettings,
    SkillGroup,
    SkillMarketRepo,
    normalize_hot_update_interval_minutes,
    normalize_model_vendor_keywords,
    profile_supports_claude,
    profile_supports_codex,
)
from ..storage import DEFAULT_MODEL_BATCH_CONCURRENCY, ProfileStore
from ..ui.global_logic import resolve_global_profile_id
from ..ui.model_batch_logic import ModelBatchCache, model_batch_caches_from_payload, model_batch_caches_to_payload
from ..ui.profile_logic import profile_collection_after_delete
from ..ui.project_logic import resolve_selected_project_id

DEFAULT_HOT_UPDATE_INTERVAL_MINUTES = 30


# Order must match ProfileStore.load()'s tuple.
SESSION_FIELDS = (
    "profiles",
    "selected_profile_id",
    "projects",
    "selected_project_id",
    "hide_error_profiles",
    "global_mcp_toml",
    "applied_global_mcp_server_names",
    "global_mcp_opt_out",
    "agents_doc_text",
    "model_batch_concurrency",
    "model_batch_cache_by_profile",
    "route_proxy",
    "global_mcp_server_names",
    "selected_codex_global_profile_id",
    "selected_claude_global_profile_id",
    "account_pool",
    "skill_groups",
    "skill_market_repos",
    "hot_update_enabled",
    "hot_update_interval_minutes",
    "model_vendor_keywords",
    "hot_update_events",
)

EVENT_LOG_LIMIT = 300


@dataclass
class AppSession:
    """Named, typed wrapper around ``ProfileStore.load()``/``save()``."""

    profiles: list[Profile] = field(default_factory=list)
    selected_profile_id: str | None = None
    projects: list[ProjectRecord] = field(default_factory=list)
    selected_project_id: str | None = None
    hide_error_profiles: bool = False
    global_mcp_toml: str = ""
    applied_global_mcp_server_names: list[str] = field(default_factory=list)
    global_mcp_opt_out: bool = False
    agents_doc_text: str = ""
    model_batch_concurrency: int = DEFAULT_MODEL_BATCH_CONCURRENCY
    model_batch_cache_by_profile: dict[str, ModelBatchCache] = field(default_factory=dict)
    route_proxy: RouteProxySettings = field(default_factory=RouteProxySettings)
    global_mcp_server_names: list[str] | None = None
    selected_codex_global_profile_id: str | None = None
    selected_claude_global_profile_id: str | None = None
    account_pool: AccountPoolSettings = field(default_factory=AccountPoolSettings)
    skill_groups: list[SkillGroup] = field(default_factory=list)
    skill_market_repos: list[SkillMarketRepo] = field(default_factory=list)
    hot_update_enabled: bool = False
    hot_update_interval_minutes: int = DEFAULT_HOT_UPDATE_INTERVAL_MINUTES
    model_vendor_keywords: dict[str, list[str]] = field(default_factory=dict)
    hot_update_events: list[HotUpdateEvent] = field(default_factory=list)

    # -- transient runtime state (never persisted) ------------------------
    dark_mode: bool = False
    proxy_running: bool = False
    event_log: list[dict[str, Any]] = field(default_factory=list)
    chat_messages: list[dict[str, Any]] = field(default_factory=list)

    # -- construction -----------------------------------------------------
    @classmethod
    def from_store(cls, store: ProfileStore) -> "AppSession":
        values = store.load()
        payload: dict[str, Any] = dict(zip(SESSION_FIELDS, values))
        payload["model_batch_cache_by_profile"] = model_batch_caches_from_payload(
            payload.get("model_batch_cache_by_profile")
        )
        session = cls(**payload)
        session.account_pool.ensure_default_group()
        session.model_vendor_keywords = normalize_model_vendor_keywords(session.model_vendor_keywords)
        session.hot_update_interval_minutes = normalize_hot_update_interval_minutes(
            session.hot_update_interval_minutes
        )
        session.selected_project_id = resolve_selected_project_id(
            session.projects, session.selected_project_id
        )
        session.normalize_global_profile_ids()
        session.dark_mode = load_dark_mode(store)
        return session

    def persist(self, store: ProfileStore) -> None:
        store.save(
            self.profiles,
            self.selected_profile_id,
            self.projects,
            self.selected_project_id,
            self.hide_error_profiles,
            self.global_mcp_toml,
            self.applied_global_mcp_server_names,
            self.global_mcp_opt_out,
            self.agents_doc_text,
            self.model_batch_concurrency,
            model_batch_caches_to_payload(self.model_batch_cache_by_profile),
            self.route_proxy,
            global_mcp_server_names=self.global_mcp_server_names,
            selected_codex_global_profile_id=self.selected_codex_global_profile_id,
            selected_claude_global_profile_id=self.selected_claude_global_profile_id,
            account_pool_settings=self.account_pool,
            skill_groups=self.skill_groups,
            skill_market_repos=self.skill_market_repos,
            hot_update_enabled=self.hot_update_enabled,
            hot_update_interval_minutes=self.hot_update_interval_minutes,
            model_vendor_keywords=self.model_vendor_keywords,
            hot_update_events=self.hot_update_events,
        )
        save_dark_mode(store, self.dark_mode)

    # -- lookups ----------------------------------------------------------
    def profile_by_id(self, profile_id: str | None) -> Profile | None:
        if not profile_id:
            return None
        return next((item for item in self.profiles if item.id == profile_id), None)

    def project_by_id(self, project_id: str | None) -> ProjectRecord | None:
        if not project_id:
            return None
        return next((item for item in self.projects if item.id == project_id), None)

    def selected_profile(self) -> Profile | None:
        return self.profile_by_id(self.selected_profile_id)

    def selected_project(self) -> ProjectRecord | None:
        return self.project_by_id(self.selected_project_id)

    def skill_group_by_id(self, group_id: str | None) -> SkillGroup | None:
        if not group_id:
            return None
        return next((item for item in self.skill_groups if item.id == group_id), None)

    def skill_repo_by_id(self, repo_id: str | None) -> SkillMarketRepo | None:
        if not repo_id:
            return None
        return next((item for item in self.skill_market_repos if item.id == repo_id), None)

    def model_batch_cache(self, profile_id: str | None) -> ModelBatchCache | None:
        if not profile_id:
            return None
        return self.model_batch_cache_by_profile.get(profile_id)

    def global_codex_profile(self) -> Profile | None:
        return self.profile_by_id(self.selected_codex_global_profile_id)

    def global_claude_profile(self) -> Profile | None:
        return self.profile_by_id(self.selected_claude_global_profile_id)

    def codex_capable_profiles(self) -> list[Profile]:
        return [item for item in self.profiles if profile_supports_codex(item)]

    def claude_capable_profiles(self) -> list[Profile]:
        return [item for item in self.profiles if profile_supports_claude(item)]

    # -- mutation helpers -------------------------------------------------
    def normalize_global_profile_ids(self) -> None:
        """Drop global selections whose profile vanished or lost capability."""
        self.selected_codex_global_profile_id = resolve_global_profile_id(
            self.selected_codex_global_profile_id,
            self.selected_profile_id,
            self.profiles,
            profile_supports_codex,
        )
        self.selected_claude_global_profile_id = resolve_global_profile_id(
            self.selected_claude_global_profile_id,
            self.selected_profile_id,
            self.profiles,
            profile_supports_claude,
        )

    def remove_profile(self, profile_id: str) -> None:
        update = profile_collection_after_delete(
            self.profiles,
            selected_profile_id=self.selected_profile_id,
            deleted_profile_id=profile_id,
        )
        self.profiles = update.profiles
        self.selected_profile_id = update.selected_profile_id
        self.model_batch_cache_by_profile.pop(profile_id, None)

    def select_profile(self, profile_id: str | None) -> None:
        self.selected_profile_id = profile_id or None

    def select_project(self, project_id: str | None) -> None:
        self.selected_project_id = project_id or None

    # -- event log --------------------------------------------------------
    def record_event(
        self,
        *,
        source: str,
        level: str,
        message: str,
        detail: str = "",
        target: str = "",
    ) -> None:
        from ..models import now_iso

        self.event_log.append(
            {
                "timestamp": now_iso(),
                "source": str(source or "app"),
                "level": str(level or "info"),
                "message": str(message or ""),
                "detail": str(detail or ""),
                "target": str(target or ""),
            }
        )
        if len(self.event_log) > EVENT_LOG_LIMIT:
            del self.event_log[: len(self.event_log) - EVENT_LOG_LIMIT]

    def record_proxy_event(self, event: RouteProxyEvent) -> None:
        self.record_event(
            source="proxy",
            level=str(getattr(event, "level", "info") or "info"),
            message=str(getattr(event, "message", "") or ""),
            detail=str(getattr(event, "path", "") or ""),
            target=str(getattr(event, "project_id", "") or ""),
        )

    def record_hot_update_event(self, event: HotUpdateEvent) -> None:
        self.record_event(
            source="update",
            level="error" if str(getattr(event, "status", "")) == "error" else "info",
            message=str(getattr(event, "target", "") or ""),
            detail=str(getattr(event, "detail", "") or ""),
            target=str(getattr(event, "scope", "") or ""),
        )

    def clear_events(self) -> None:
        self.event_log.clear()


# -- theme preference (own file; profiles.json stays untouched) ----------
def _prefs_path(store: ProfileStore):
    return store.root_dir / "ui_prefs.json"


def load_dark_mode(store: ProfileStore) -> bool:
    path = _prefs_path(store)
    if not path.exists():
        return False
    import json

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return bool(payload.get("dark_mode", False)) if isinstance(payload, dict) else False


def save_dark_mode(store: ProfileStore, dark_mode: bool) -> None:
    import json

    path = _prefs_path(store)
    try:
        path.write_text(json.dumps({"dark_mode": bool(dark_mode)}, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:
        # Theme preference is cosmetic; never fail a save because of it.
        pass


__all__ = ["AppSession", "EVENT_LOG_LIMIT", "SESSION_FIELDS", "load_dark_mode", "save_dark_mode"]
