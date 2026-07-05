from __future__ import annotations

from dataclasses import replace
from importlib.metadata import PackageNotFoundError, version as package_version
from pathlib import Path
import json
import os
import platform
import subprocess
import threading
import tkinter as tk
import tomllib
import webbrowser
import sys
from tkinter import filedialog, font as tkfont
from tkinter import messagebox, simpledialog

from codex_switch import __version__
from codex_switch.chat import (
    SUPPORTED_WIRE_APIS,
    WIRE_API_ANTHROPIC_MESSAGES,
    AccountPoolSessionValidator,
    ChatResult,
    ChatTester,
    default_wire_api_for_profile,
)
from codex_switch.claude_config import ClaudeConfigManager
from codex_switch.codex_config import (
    CodexConfigManager,
    PROJECT_ROOT_PLACEHOLDER,
    load_default_global_mcp_toml,
)
from codex_switch.health import HealthChecker
from codex_switch.models import (
    AccountPoolChannel,
    AccountPoolGroup,
    AccountPoolSettings,
    ACCOUNT_POOL_CHANNEL_SOURCE_PROFILE,
    ACCOUNT_POOL_GROUP_TYPE_CLAUDE,
    ACCOUNT_POOL_GROUP_TYPE_CODEX,
    ACCOUNT_POOL_GROUP_TYPE_LABELS,
    CurrentCodexConfig,
    DEFAULT_CLAUDE_FALLBACK_MODEL,
    DEFAULT_CLAUDE_MODEL,
    DEFAULT_CODEX_MODEL,
    DEFAULT_HOT_UPDATE_INTERVAL_MINUTES,
    HealthResult,
    HOT_UPDATE_EVENT_LIMIT,
    HotUpdateEvent,
    Profile,
    ProjectRecord,
    RouteProxyEvent,
    RouteProxySettings,
    RouteProxyTokenUsageBucket,
    SkillDefinition,
    SkillGroup,
    SkillMarketRepo,
    SKILL_TYPE_LABELS,
    ROUTE_PROXY_ACCOUNT_POOL_STRATEGY_FAILOVER,
    ROUTE_PROXY_ACCOUNT_POOL_STRATEGY_ROUND_ROBIN,
    ROUTE_PROXY_CLIENT_CLAUDE,
    ROUTE_PROXY_CLIENT_CODEX,
    ROUTE_PROXY_PLACEHOLDER_KEY,
    ROUTE_PROXY_PROTOCOL_ANTHROPIC,
    ROUTE_PROXY_PROTOCOL_ANTHROPIC_TO_OPENAI,
    ROUTE_PROXY_PROTOCOL_OPENAI,
    ROUTE_PROXY_PROTOCOL_OPENAI_CHAT_TO_RESPONSES,
    ROUTE_PROXY_PROTOCOL_OPENAI_RESPONSES_TO_CHAT,
    ROUTE_PROXY_UPSTREAM_SOURCE_ACCOUNT_POOL,
    ROUTE_PROXY_UPSTREAM_SOURCE_PROFILE,
    normalize_route_proxy_account_pool_strategy,
    normalize_route_proxy_protocol,
    normalize_route_proxy_upstream_source,
    VENDOR_CLAUDE,
    VENDOR_CODEX,
    VENDOR_GENERIC,
    VENDOR_OTHER,
    normalize_route_proxy_port,
    normalize_route_proxy_upstream_timeout_seconds,
    normalize_account_pool_recovery_interval_minutes,
    normalize_hot_update_interval_minutes,
    normalize_model_vendor_keywords,
    normalize_skill_type,
    now_iso,
    model_vendor_stats,
    models_by_vendor,
    profile_supports_claude,
    profile_supports_codex,
    project_dir_key,
    today_iso,
)
from codex_switch.proxy import RouteProxyServer
from codex_switch.project_template import (
    CODEX_SCRIPT_DIRNAME,
    CLAUDE_API_KEY_ENV_KEY,
    CLAUDE_BASE_URL_ENV_KEY,
    CLAUDE_FALLBACK_MODEL_ENV_KEY,
    CLAUDE_MODEL_ENV_KEY,
    ProjectTemplateService,
    apply_claude_profile_env,
    claude_runtime_env_from_profile,
    load_default_agents_doc_text,
)
from codex_switch.skills import (
    SkillSource,
    default_skill_roots,
    discover_skill_sources,
    skill_selection_summary,
)
from codex_switch.software_update import SoftwareUpdateChecker, SoftwareUpdateInfo
from codex_switch.storage import (
    DEFAULT_MODEL_BATCH_CONCURRENCY,
    MODEL_BATCH_CONCURRENCY_MAX,
    MODEL_BATCH_CONCURRENCY_MIN,
    ProfileStore,
    clamp_model_batch_concurrency,
)
from codex_switch.ui.dialogs import (
    AccountPoolChannelDialog,
    AccountPoolProfileChannelDialog,
    ChatSettingsDialog,
    McpConfigDialog,
    McpSelectionDialog,
    McpServerDialog,
    ModelBatchTestDialog,
    ProfileDialog,
    ProjectDialog,
    SuccessfulModelsDialog,
)
from codex_switch.ui.account_pool_logic import (
    ACCOUNT_POOL_SOURCE_FILTER_ALL,
    ACCOUNT_POOL_SOURCE_FILTER_PROFILE,
    ACCOUNT_POOL_SOURCE_FILTER_TEMPORARY,
    account_pool_channel_rows,
    account_pool_group_delete_error,
    account_pool_group_choices_display,
    account_pool_channel_by_id,
    account_pool_detail_display,
    account_pool_project_count,
    account_pool_summary_text,
    account_pool_visible_channels,
    apply_account_pool_group_settings,
    check_account_pool_channel,
    prepare_account_pool_channel_submission,
    project_account_pool_group_name,
    project_uses_account_pool,
    resolve_account_pool_group_settings_update,
)
from codex_switch.ui.global_logic import (
    claude_settings_env_values,
    global_apply_detail,
    global_apply_targets,
    global_profile_choice_display,
    global_profile_choice_names,
    global_profile_apply_error,
    GlobalApplyResult,
    profile_for_choice_index,
    resolve_global_mcp_server_names,
    resolve_global_profile_id,
)
from codex_switch.ui.model_batch_logic import (
    ModelBatchCache,
    ModelBatchResult,
    model_batch_caches_from_payload,
    model_batch_caches_to_payload,
    model_batch_counts,
    model_batch_health_summary,
    model_batch_targets,
    ordered_model_batch_models,
    run_model_batch_requests,
    successful_model_batch_models,
)
from codex_switch.ui.hot_update_logic import (
    HOT_UPDATE_SCOPE_LABELS,
    HOT_UPDATE_STATUS_LABELS,
    project_manual_hot_update_spec,
    PROJECT_HOT_UPDATE_TEXTS,
    SKILL_REPO_HOT_UPDATE_TEXTS,
    skill_repo_manual_hot_update_spec,
    append_hot_update_event,
    hot_update_event_line,
    hot_update_summary_text,
    process_hot_update_candidate,
)
from codex_switch.ui.library_logic import (
    build_global_tab_display,
    build_library_detail_display,
    build_library_tab_display,
    build_test_detail_display,
    build_test_tab_display,
    current_status_counts,
    health_override_note,
    health_status_text,
    profile_key_summary,
    profile_library_model_summary,
    profile_library_sort_key,
    profile_model_summary,
    profiles_for_library_view,
    visible_profiles_for_filter,
)
from codex_switch.ui.mcp_logic import (
    build_mcp_persist_state,
    load_mcp_tab_state,
    mcp_collection_after_delete,
    mcp_collection_after_upsert,
    mcp_detail_display,
    mcp_contains_project_root,
    mcp_env_summary,
    mcp_list_summary,
    mcp_name_conflict_error,
    mcp_server_rows,
    mcp_summary,
    mcp_tab_display,
    render_mcp_preview,
    safe_mcp_server_names,
)
from codex_switch.ui.styles import (
    BOOTSTRAP_THEME,
    BootstrapWindow,
    HEALTH_OVERRIDE_DISPLAY,
    HEALTH_OVERRIDE_VALUE_BY_DISPLAY,
    PALETTE,
    STATUS_COLORS,
    STATUS_TEXT,
    TopNav,
    configure_theme_styles,
    make_button,
    make_status_badge,
    ttk,
)
from codex_switch.ui.project_logic import (
    build_project_edit_application,
    build_project_binding_sync_plan,
    project_binding_sync_tasks,
    build_claude_template_run_spec,
    build_claude_template_execution_plan,
    build_codex_template_run_spec,
    build_codex_template_execution_plan,
    claude_template_success_message,
    codex_template_success_message,
    project_binding_sync_status,
    project_add_prerequisite_error,
    project_collection_after_add,
    project_collection_after_delete,
    project_collection_after_replace,
    project_duplicate_dir_error,
    preferred_project_script_path,
    project_bound_profile_ids,
    project_claude_binding_changed,
    project_claude_cmd_launch_plan,
    project_claude_cmd_command,
    project_claude_settings_edit_plan,
    project_claude_profile_texts,
    project_claude_profile_id,
    project_codex_config_edit_plan,
    project_codex_cmd_launch_plan,
    project_codex_cmd_command,
    project_codex_binding_changed,
    project_codex_profile_texts,
    project_codex_profile_id,
    project_codex_script_paths,
    project_codex_vscode_launch_plan,
    project_codex_vscode_command,
    project_custom_run_launch_plan,
    project_github_label,
    project_github_update_label,
    project_vscode_launch_plan,
    project_mcp_selection_summary,
    project_from_dialog_result,
    project_detail_display,
    PROJECT_METADATA_RELATIVE_PATHS,
    project_metadata_group_ids,
    project_metadata_profile_ids,
    project_root_path,
    project_skill_selection_summary,
    project_tab_display,
    project_template_display,
    project_text_file_path,
    project_with_metadata_update,
    updated_project_from_dialog,
    project_vscode_open_command,
)
from codex_switch.ui.route_proxy_logic import (
    account_pool_group_for_project_client,
    apply_route_proxy_settings_form,
    apply_route_proxy_project_rules,
    build_route_proxy_project_enable_plan,
    build_route_proxy_project_disable_plan,
    claude_model_overrides_for_project,
    CLAUDE_ROUTE_PROXY_PROTOCOLS,
    ROUTE_PROXY_ACCOUNT_POOL_STRATEGY_LABELS,
    ROUTE_PROXY_ACCOUNT_POOL_STRATEGY_VALUES,
    CODEX_ROUTE_PROXY_PROTOCOLS,
    CODEX_ROUTE_PROXY_UPSTREAM_SOURCE_LABELS,
    CODEX_ROUTE_PROXY_UPSTREAM_SOURCE_VALUES,
    codex_model_override_for_project,
    normalize_route_proxy_settings_form,
    route_proxy_account_pool_choices,
    resolve_route_proxy_project_rule_form,
    route_proxy_tab_display,
    route_proxy_started_status,
    route_proxy_start_failed_status,
    route_proxy_stopped_status,
    refresh_route_proxy_upstream_models,
    route_proxy_detail_display,
    refresh_route_proxy_rules_for_project,
    route_proxy_base_url_for_project,
    route_proxy_group_label_for_id,
    route_proxy_rule_for_project_client,
)
from codex_switch.ui.repo_sync_logic import (
    git_local_commit as repo_git_local_commit,
    git_remote_commit as repo_git_remote_commit,
    project_remote_update as repo_project_remote_update,
    skill_repo_remote_update as repo_skill_repo_remote_update,
    sync_project_checkout as repo_sync_project_checkout,
    sync_repo_cache as repo_sync_repo_cache,
)
from codex_switch.ui.skills_logic import (
    MODEL_METADATA_RELATIVE_PATHS,
    SkillMarketEntry,
    apply_profile_metadata,
    build_skills_tab_display,
    expanded_skills_for_group_ids,
    existing_repo_files,
    filter_skill_market_repos,
    filter_skill_repo_preview_sources,
    import_skill_sources_to_group,
    load_skill_market_entries,
    profile_metadata_entries,
    projects_after_skill_group_delete,
    remove_skill_group,
    replace_skill_group,
    skill_repo_preview_display,
    skill_repo_checksum_required_paths,
    skill_group_with_added_skill,
    skill_group_with_deleted_skill,
    skill_group_name_error,
    skill_group_with_metadata,
    skill_group_with_replaced_skill,
    sync_projects_from_skill_groups,
)
from codex_switch.ui.single_instance import _acquire_single_instance, _release_single_instance, _show_single_instance_message
from codex_switch.ui.update_logic import (
    DEFAULT_PROJECT_GITHUB_REF,
    DEFAULT_SKILL_REPO_REF,
    GitRemoteUpdate,
    checksum_manifest_entries,
    git_fetch_ref_candidates,
    git_remote_ref_patterns,
    is_git_commit_ref,
    normalize_git_ref,
    remote_commit_from_ls_remote,
    same_git_commit,
    build_software_update_finish_plan,
    software_update_error_detail,
    verify_hot_update_checksums,
)
from codex_switch.ui.utils import compact_text, hidden_secret, is_github_repo_url, is_http_url, replace_treeview_rows
from codex_switch.ui.windowing import install_windows_drag_redraw_guard


from codex_switch.ui.skills_logic import build_skill_group_dialog_layout, skill_group_dialog_card_displays, skill_group_detail_text
_CREATE_NEW_CONSOLE = getattr(subprocess, "CREATE_NEW_CONSOLE", 0)
LIBRARY_VIEW_ALL = "all"
LIBRARY_PROFILE_VIEW_TABS = (
    (LIBRARY_VIEW_ALL, "全部"),
    (VENDOR_CODEX, "Codex 配置"),
    (VENDOR_CLAUDE, "Claude 配置"),
    (VENDOR_OTHER, "其他"),
)
LIBRARY_PROFILE_VIEW_VALUES = {view for view, _label in LIBRARY_PROFILE_VIEW_TABS}
LIBRARY_TREE_COLUMNS = ("name", "base_url", "model", "sign_in", "health")
LIBRARY_TREE_COLUMNS_WITH_VENDOR = ("name", "vendor", "base_url", "model", "sign_in", "health")
PROXY_LOG_RENDER_DELAY_MS = 80
PROXY_STATE_FLUSH_DELAY_MS = 250
class CodexSwitchApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("Codex Switch")
        self.root.geometry("1360x900")
        self.root.minsize(1180, 780)
        self.root.configure(bg=PALETTE["panel_bg"])
        install_windows_drag_redraw_guard(self.root)

        self.project_root = Path.cwd()
        self.store = ProfileStore()
        self.manager = CodexConfigManager()
        self.claude_manager = ClaudeConfigManager()
        self.project_template_service = ProjectTemplateService()
        self.health_checker = HealthChecker()
        self.chat_tester = ChatTester()
        self.account_pool_validator = AccountPoolSessionValidator()

        load_state = self.store.load()
        if len(load_state) >= 8:
            (
                self.profiles,
                self.selected_profile_id,
                self.projects,
                self.selected_project_id,
                self.hide_error_profiles,
                self.global_mcp_toml,
                self.applied_global_mcp_server_names,
                self.global_mcp_opt_out,
            ) = load_state[:8]
            self.agents_doc_text = load_state[8] if len(load_state) >= 9 else load_default_agents_doc_text()
            self.model_batch_concurrency = clamp_model_batch_concurrency(
                load_state[9] if len(load_state) >= 10 else DEFAULT_MODEL_BATCH_CONCURRENCY
            )
            raw_model_batch_cache_by_profile = load_state[10] if len(load_state) >= 11 else {}
            self.route_proxy_settings = load_state[11] if len(load_state) >= 12 else RouteProxySettings()
            self.global_mcp_server_names = load_state[12] if len(load_state) >= 13 else None
            raw_codex_global_profile_id = load_state[13] if len(load_state) >= 14 else None
            raw_claude_global_profile_id = load_state[14] if len(load_state) >= 15 else None
            self.account_pool_settings = load_state[15] if len(load_state) >= 16 else AccountPoolSettings()
            self.skill_groups = load_state[16] if len(load_state) >= 17 else []
            self.skill_market_repos = load_state[17] if len(load_state) >= 18 else []
            self.hot_update_enabled = bool(load_state[18]) if len(load_state) >= 19 else False
            self.hot_update_interval_minutes = normalize_hot_update_interval_minutes(
                load_state[19] if len(load_state) >= 20 else DEFAULT_HOT_UPDATE_INTERVAL_MINUTES
            )
            self.model_vendor_keywords = normalize_model_vendor_keywords(
                load_state[20] if len(load_state) >= 21 else None
            )
            self.hot_update_events = load_state[21] if len(load_state) >= 22 else []
        else:
            self.profiles, self.selected_profile_id = load_state  # type: ignore[misc]
            self.projects = []
            self.selected_project_id = None
            self.hide_error_profiles = False
            self.global_mcp_toml = load_default_global_mcp_toml()
            self.applied_global_mcp_server_names = []
            self.global_mcp_opt_out = False
            self.global_mcp_server_names = None
            self.agents_doc_text = load_default_agents_doc_text()
            self.model_batch_concurrency = DEFAULT_MODEL_BATCH_CONCURRENCY
            raw_model_batch_cache_by_profile = {}
            self.route_proxy_settings = RouteProxySettings()
            raw_codex_global_profile_id = None
            raw_claude_global_profile_id = None
            self.account_pool_settings = AccountPoolSettings()
            self.skill_groups = []
            self.skill_market_repos = []
            self.hot_update_enabled = False
            self.hot_update_interval_minutes = DEFAULT_HOT_UPDATE_INTERVAL_MINUTES
            self.model_vendor_keywords = normalize_model_vendor_keywords()
            self.hot_update_events = []
        self.global_codex_profile_id = resolve_global_profile_id(
            raw_codex_global_profile_id,
            self.selected_profile_id,
            self.profiles,
            profile_supports_codex,
        )
        self.global_claude_profile_id = resolve_global_profile_id(
            raw_claude_global_profile_id,
            self.selected_profile_id,
            self.profiles,
            profile_supports_claude,
        )
        self.mcp_page_servers: dict[str, dict] = {}
        self.route_proxy_server = RouteProxyServer(
            lambda: self.route_proxy_settings,
            lambda: self.profiles,
            self._record_route_proxy_event,
            account_pool_provider=lambda: self.account_pool_settings,
            account_pool_update_callback=self._record_account_pool_update,
            project_provider=lambda: self.projects,
            recovery_checker=self.account_pool_validator,
            token_usage_callback=self._record_route_proxy_token_usage,
        )
        self._proxy_log_render_pending = False
        self._route_proxy_token_usage_update_pending = False
        self._account_pool_update_pending = False

        self.current_config: CurrentCodexConfig | None = None
        self.chat_profile_id: str | None = None
        self.chat_busy = False
        self.model_batch_busy = False
        self.model_batch_profile_id: str | None = None
        self.model_batch_running_profile_id: str | None = None
        self.model_batch_cache_by_profile: dict[str, ModelBatchCache] = model_batch_caches_from_payload(raw_model_batch_cache_by_profile)
        self.model_batch_dialog: ModelBatchTestDialog | None = None
        self.model_batch_dialog_profile_id: str | None = None
        self.updating_health_override = False
        self.suppress_selection_events = False
        self.sign_in_status_day = today_iso()
        self.hot_update_check_running = False
        self.software_update_checker = SoftwareUpdateChecker()
        self.software_update_check_running = False
        self.software_update_checked_once = False
        self.skill_market_force_sync = False

        self._init_variables()
        self._setup_theme()
        self._build_ui()
        self.refresh_all()
        self.persist_state()
        self._schedule_sign_in_status_refresh()
        self._schedule_startup_software_update_check()
        self._schedule_hot_update_check()
        if self.route_proxy_settings.enabled:
            self.start_route_proxy(show_errors=False)
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

    def _init_variables(self) -> None:
        self.status_var = tk.StringVar(value="准备就绪")

        self.global_total_var = tk.StringVar(value="0")
        self.global_healthy_var = tk.StringVar(value="0")
        self.global_error_var = tk.StringVar(value="0")
        self.global_degraded_var = tk.StringVar(value="0")
        self.codex_current_api_var = tk.StringVar(value="API 地址：-")
        self.codex_current_models_var = tk.StringVar(value="模型：-")
        self.claude_current_api_var = tk.StringVar(value="API 地址：-")
        self.claude_current_models_var = tk.StringVar(value="模型：-")
        self.current_path_var = tk.StringVar(value="")
        self.global_mcp_var = tk.StringVar(value="-")
        self.global_codex_profile_choice_var = tk.StringVar(value="")
        self.global_claude_profile_choice_var = tk.StringVar(value="")

        self.library_hint_var = tk.StringVar(value="还没有保存的配置。")
        self.library_selected_name_var = tk.StringVar(value="未选择配置")
        self.library_selected_provider_var = tk.StringVar(value="-")
        self.library_selected_category_var = tk.StringVar(value="-")
        self.library_selected_model_var = tk.StringVar(value="-")
        self.library_selected_api_var = tk.StringVar(value="-")
        self.library_selected_key_var = tk.StringVar(value="-")
        self.library_selected_wire_var = tk.StringVar(value="-")
        self.library_selected_sign_in_status_var = tk.StringVar(value="-")
        self.library_selected_sign_in_url_var = tk.StringVar(value="-")
        self.library_selected_notes_var = tk.StringVar(value="暂无备注")
        self.library_models_summary_var = tk.StringVar(value="最近检测尚未返回模型列表。")
        self.library_model_stats_button_var = tk.StringVar(value="展开统计")
        self.library_model_stats_expanded = False
        self.library_model_tag_models: list[str] = []
        self.library_model_tag_widgets: list[tuple[str, tk.Canvas]] = []
        self.hide_error_button_var = tk.StringVar(value="")
        self.library_profile_view = LIBRARY_VIEW_ALL
        self.library_scope_tabs: dict[str, tk.Label] = {}

        self.project_hint_var = tk.StringVar(value="还没有添加项目。")
        self.project_selected_name_var = tk.StringVar(value="未选择项目")
        self.project_selected_dir_var = tk.StringVar(value="-")
        self.project_selected_codex_profile_var = tk.StringVar(value="-")
        self.project_selected_claude_profile_var = tk.StringVar(value="-")
        self.project_selected_codex_model_var = tk.StringVar(value="-")
        self.project_selected_claude_model_var = tk.StringVar(value="-")
        self.project_selected_codex_key_var = tk.StringVar(value="-")
        self.project_selected_claude_key_var = tk.StringVar(value="-")
        self.project_backup_var = tk.StringVar(value="-")
        self.project_generated_var = tk.StringVar(value="-")
        self.project_script_var = tk.StringVar(value="-")
        self.project_run_var = tk.StringVar(value="-")
        self.project_github_var = tk.StringVar(value="-")
        self.project_github_update_var = tk.StringVar(value="-")
        self.project_mcp_var = tk.StringVar(value="-")
        self.project_skills_var = tk.StringVar(value="-")

        self.proxy_status_var = tk.StringVar(value="未启动")
        self.proxy_host_var = tk.StringVar(value=self.route_proxy_settings.host)
        self.proxy_port_var = tk.StringVar(value=str(self.route_proxy_settings.port))
        self.proxy_account_pool_strategy_var = tk.StringVar(
            value=ROUTE_PROXY_ACCOUNT_POOL_STRATEGY_LABELS[
                normalize_route_proxy_account_pool_strategy(self.route_proxy_settings.account_pool_strategy)
            ]
        )
        self.proxy_upstream_timeout_var = tk.StringVar(
            value=str(normalize_route_proxy_upstream_timeout_seconds(self.route_proxy_settings.upstream_timeout_seconds))
        )
        self.proxy_hint_var = tk.StringVar(value="项目级代理默认关闭。启用项目后生成模板会指向本地代理。")
        self.proxy_selected_project_var = tk.StringVar(value="未选择项目")
        self.proxy_selected_rules_var = tk.StringVar(value="-")
        self.proxy_codex_upstream_source_var = tk.StringVar(
            value=CODEX_ROUTE_PROXY_UPSTREAM_SOURCE_LABELS[ROUTE_PROXY_UPSTREAM_SOURCE_PROFILE]
        )
        self.proxy_claude_upstream_source_var = tk.StringVar(
            value=CODEX_ROUTE_PROXY_UPSTREAM_SOURCE_LABELS[ROUTE_PROXY_UPSTREAM_SOURCE_PROFILE]
        )
        self.proxy_codex_protocol_var = tk.StringVar(value=ROUTE_PROXY_PROTOCOL_OPENAI)
        self.proxy_claude_protocol_var = tk.StringVar(value=ROUTE_PROXY_PROTOCOL_ANTHROPIC)
        self.proxy_codex_compact_model_var = tk.StringVar(value="")
        self.stats_total_tokens_var = tk.StringVar(value="0")
        self.stats_today_tokens_var = tk.StringVar(value="0")
        self.stats_project_count_var = tk.StringVar(value="0")
        self.stats_api_count_var = tk.StringVar(value="0")

        self.account_pool_summary_var = tk.StringVar(value="号池未启用。")
        self.account_pool_enabled_var = tk.BooleanVar(value=self.account_pool_settings.enabled)
        self.account_pool_group_var = tk.StringVar(value="")
        self.account_pool_group_enabled_var = tk.BooleanVar(value=True)
        self.account_pool_group_type_var = tk.StringVar(value=ACCOUNT_POOL_GROUP_TYPE_LABELS[ACCOUNT_POOL_GROUP_TYPE_CODEX])
        self.account_pool_group_default_model_var = tk.StringVar(value=DEFAULT_CODEX_MODEL)
        self.account_pool_group_claude_model_var = tk.StringVar(value=DEFAULT_CLAUDE_MODEL)
        self.account_pool_group_claude_fallback_model_var = tk.StringVar(value=DEFAULT_CLAUDE_FALLBACK_MODEL)
        self.account_pool_selected_name_var = tk.StringVar(value="未选择渠道")
        self.account_pool_selected_detail_var = tk.StringVar(value="-")
        self.account_pool_group_choices: dict[str, str] = {}
        self.account_pool_source_filter_var = tk.StringVar(value=ACCOUNT_POOL_SOURCE_FILTER_ALL)

        self.mcp_hint_var = tk.StringVar(value="尚未加载 MCP 配置。")
        self.mcp_selected_name_var = tk.StringVar(value="未选择 MCP 工具")
        self.mcp_selected_summary_var = tk.StringVar(value="选择左侧工具后查看配置预览。")
        self.skills_hint_var = tk.StringVar(value="管理 Skills 仓库、本地组和项目关联。")
        self.skill_market_filter_var = tk.StringVar(value="")
        self.skill_repo_filter_var = tk.StringVar(value="")
        self.skill_repo_detail_var = tk.StringVar(value="未选择仓库")
        self.skill_repo_preview_var = tk.StringVar(value="未选择仓库")
        self.skill_repo_preview_filter_var = tk.StringVar(value="")
        self.skill_repo_preview_sources: list[SkillSource] = []
        self.skill_repo_preview_repo_id = ""
        self.skill_group_detail_var = tk.StringVar(value="未选择 Skills 组")
        self.skill_project_detail_var = tk.StringVar(value="未选择项目")
        self.docs_hint_var = tk.StringVar(value="编辑后的 AGENTS 模板会用于后续项目模板生成。")

        self.settings_hint_var = tk.StringVar(value="模型批量测试设置会从下一次测试开始生效。")
        self.model_batch_concurrency_var = tk.StringVar(value=str(self.model_batch_concurrency))
        self.account_pool_recovery_interval_var = tk.StringVar(
            value=str(self.account_pool_settings.recovery_interval_minutes)
        )
        self.hot_update_enabled_var = tk.BooleanVar(value=self.hot_update_enabled)
        self.hot_update_interval_var = tk.StringVar(value=str(self.hot_update_interval_minutes))
        self.software_update_status_var = tk.StringVar(value=f"当前版本 {__version__}，尚未检查软件更新。")
        self.hot_update_status_var = tk.StringVar(value="仓库同步轮询未启用。")
        self.settings_version_var = tk.StringVar(value="-")
        self.settings_python_var = tk.StringVar(value="-")
        self.settings_tk_var = tk.StringVar(value="-")
        self.settings_ttkbootstrap_var = tk.StringVar(value="-")
        self.settings_storage_path_var = tk.StringVar(value="-")
        self.settings_codex_config_path_var = tk.StringVar(value="-")
        self.settings_codex_auth_path_var = tk.StringVar(value="-")
        self.settings_project_root_var = tk.StringVar(value="-")
        self.settings_platform_var = tk.StringVar(value="-")

        self.test_selected_name_var = tk.StringVar(value="未选择测试配置")
        self.test_detail_health_var = tk.StringVar(value="未检测")
        self.test_detail_provider_var = tk.StringVar(value="-")
        self.test_detail_model_var = tk.StringVar(value="-")
        self.test_detail_api_var = tk.StringVar(value="-")
        self.test_detail_key_var = tk.StringVar(value="-")
        self.test_detail_wire_var = tk.StringVar(value="-")
        self.test_detail_endpoint_var = tk.StringVar(value="-")
        self.test_detail_checked_var = tk.StringVar(value="-")
        self.test_detail_notes_var = tk.StringVar(value="暂无备注")
        self.test_detail_result_var = tk.StringVar(value="未检测")
        self.test_detail_success_models_var = tk.StringVar(value="未批量测试")
        self.health_override_var = tk.StringVar(value=HEALTH_OVERRIDE_DISPLAY[""])
        self.health_override_note_var = tk.StringVar(value="自动检测仅代表连通性，可在这里手动修正。")
        self.chat_target_var = tk.StringVar(value="未选择测试配置")
        self.chat_model_choice_var = tk.StringVar(value="-")
        self.chat_wire_choice_var = tk.StringVar(value=SUPPORTED_WIRE_APIS[0])
        self.chat_settings_summary_var = tk.StringVar(value="模型：-    接口：responses")
        self.chat_request_body_text = ""
        self.proxy_account_pool_group_var = tk.StringVar(value="")
        self.proxy_claude_account_pool_group_var = tk.StringVar(value="")
        self.proxy_account_pool_group_choices: dict[str, str] = {}
        self.proxy_claude_account_pool_group_choices: dict[str, str] = {}

    def _setup_theme(self) -> None:
        self.hero_font = tkfont.Font(family="Microsoft YaHei UI", size=15, weight="bold")
        self.section_font = tkfont.Font(family="Microsoft YaHei UI", size=11, weight="bold")
        self.body_font = tkfont.Font(family="Microsoft YaHei UI", size=10)
        self.small_font = tkfont.Font(family="Microsoft YaHei UI", size=9)

        style = ttk.Style() if BootstrapWindow is not None else ttk.Style(self.root)
        if BootstrapWindow is None:
            style.theme_use("clam")
        configure_theme_styles(style, self.body_font, self.small_font)

    def _build_ui(self) -> None:
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)

        shell = tk.Frame(self.root, bg=PALETTE["panel_bg"], padx=18, pady=16)
        shell.grid(row=0, column=0, sticky="nsew")
        shell.columnconfigure(0, weight=1)
        shell.rowconfigure(1, minsize=46, weight=0)
        shell.rowconfigure(2, weight=1)

        header = tk.Frame(shell, bg=PALETTE["panel_bg"])
        header.grid(row=0, column=0, sticky="ew", pady=(0, 12))
        header.columnconfigure(0, weight=1)
        tk.Label(
            header,
            text="Codex Switch",
            bg=PALETTE["panel_bg"],
            fg=PALETTE["text"],
            font=("Microsoft YaHei UI", 18, "bold"),
        ).grid(row=0, column=0, sticky="w")
        tk.Label(
            header,
            text="本地配置中心",
            bg=PALETTE["neutral_soft"],
            fg=PALETTE["neutral_text"],
            font=("Microsoft YaHei UI", 9, "bold"),
            padx=10,
            pady=4,
        ).grid(row=0, column=1, sticky="e")

        tabs = [
            ("global", "全局配置"),
            ("library", "配置库"),
            ("project", "项目配置"),
            ("proxy", "路由代理"),
            ("stats", "统计"),
            ("account_pool", "号池"),
            ("test", "模型测试"),
            ("mcp", "MCP配置"),
            ("skills", "Skills"),
            ("docs", "文档配置"),
            ("settings", "设置"),
        ]
        self.top_nav = TopNav(shell, tabs, self._show_tab)
        self.top_nav.grid(row=1, column=0, sticky="ew", pady=(0, 10))

        content = tk.Frame(shell, bg=PALETTE["panel_bg"])
        content.grid(row=2, column=0, sticky="nsew")
        content.columnconfigure(0, weight=1)
        content.rowconfigure(0, weight=1)

        self.global_tab = tk.Frame(content, bg=PALETTE["panel_bg"], padx=8, pady=2)
        self.library_tab = tk.Frame(content, bg=PALETTE["panel_bg"], padx=8, pady=2)
        self.project_tab = tk.Frame(content, bg=PALETTE["panel_bg"], padx=8, pady=2)
        self.proxy_tab = tk.Frame(content, bg=PALETTE["panel_bg"], padx=8, pady=2)
        self.stats_tab = tk.Frame(content, bg=PALETTE["panel_bg"], padx=8, pady=2)
        self.account_pool_tab = tk.Frame(content, bg=PALETTE["panel_bg"], padx=8, pady=2)
        self.mcp_tab = tk.Frame(content, bg=PALETTE["panel_bg"], padx=8, pady=2)
        self.skills_tab = tk.Frame(content, bg=PALETTE["panel_bg"], padx=8, pady=2)
        self.docs_tab = tk.Frame(content, bg=PALETTE["panel_bg"], padx=8, pady=2)
        self.settings_tab = tk.Frame(content, bg=PALETTE["panel_bg"], padx=8, pady=2)
        self.test_tab = tk.Frame(content, bg=PALETTE["panel_bg"], padx=8, pady=2)
        self.tab_frames = {
            "global": self.global_tab,
            "library": self.library_tab,
            "project": self.project_tab,
            "proxy": self.proxy_tab,
            "stats": self.stats_tab,
            "account_pool": self.account_pool_tab,
            "mcp": self.mcp_tab,
            "skills": self.skills_tab,
            "docs": self.docs_tab,
            "settings": self.settings_tab,
            "test": self.test_tab,
        }

        self._build_global_tab(self.global_tab)
        self._build_library_tab(self.library_tab)
        self._build_project_tab(self.project_tab)
        self._build_proxy_tab(self.proxy_tab)
        self._build_stats_tab(self.stats_tab)
        self._build_account_pool_tab(self.account_pool_tab)
        self._build_mcp_tab(self.mcp_tab)
        self._build_skills_tab(self.skills_tab)
        self._build_docs_tab(self.docs_tab)
        self._build_settings_tab(self.settings_tab)
        self._build_test_tab(self.test_tab)
        self._show_tab("global")

        status_bar = tk.Frame(self.root, bg=PALETTE["status_bg"], padx=18, pady=10)
        status_bar.grid(row=1, column=0, sticky="ew")
        tk.Label(status_bar, textvariable=self.status_var, bg=PALETTE["status_bg"], fg=PALETTE["muted"], font=self.body_font).grid(row=0, column=0, sticky="w")

    def _show_tab(self, key: str) -> None:
        frame = self.tab_frames.get(key)
        if frame is None:
            return
        for tab_key, tab_frame in self.tab_frames.items():
            if tab_key == key:
                tab_frame.grid(row=0, column=0, sticky="nsew")
            else:
                tab_frame.grid_remove()
        frame.tkraise()
        self.top_nav.select(key)

    def _make_card(self, parent: tk.Misc, padx: int = 18, pady: int = 16) -> tk.Frame:
        return tk.Frame(
            parent,
            bg=PALETTE["card_bg"],
            highlightbackground=PALETTE["card_border"],
            highlightthickness=1,
            bd=0,
            padx=padx,
            pady=pady,
        )

    def _make_metric_card(
        self,
        parent: tk.Misc,
        title: str,
        value_var: tk.StringVar,
        foreground: str,
        background: str,
        value_foreground: str | None = None,
    ) -> tk.Frame:
        card = self._make_card(parent, 10, 8)
        card.columnconfigure(0, weight=1)
        tk.Frame(card, bg=foreground, height=4).grid(row=0, column=0, sticky="ew", pady=(0, 8))
        tk.Label(card, text=title, bg=PALETTE["card_bg"], fg=PALETTE["muted"], font=self.small_font).grid(row=1, column=0, sticky="w")
        value_label = tk.Label(card, textvariable=value_var, bg=PALETTE["card_bg"], font=("Microsoft YaHei UI", 20, "bold"))
        value_label.grid(row=2, column=0, sticky="w", pady=(6, 0))
        value_label.configure(fg=value_foreground or foreground)
        badge = tk.Label(card, text="配置统计", bg=background, fg=foreground, font=("Microsoft YaHei UI", 8, "bold"), padx=8, pady=2)
        badge.grid(row=3, column=0, sticky="w", pady=(6, 0))
        return card

    def _build_global_tab(self, parent: tk.Misc) -> None:
        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(1, weight=1)

        metrics = tk.Frame(parent, bg=PALETTE["panel_bg"])
        metrics.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        for column in range(4):
            metrics.columnconfigure(column, weight=1)

        self._make_metric_card(metrics, "配置总数", self.global_total_var, PALETTE["accent"], PALETTE["selection_bg"]).grid(row=0, column=0, sticky="ew", padx=(0, 8))
        self._make_metric_card(metrics, "健康配置", self.global_healthy_var, PALETTE["success"], PALETTE["success_soft"], value_foreground="#16A34A").grid(row=0, column=1, sticky="ew", padx=(0, 8))
        self._make_metric_card(metrics, "受限配置", self.global_degraded_var, PALETTE["warning"], PALETTE["warning_soft"], value_foreground="#CA8A04").grid(row=0, column=2, sticky="ew", padx=(0, 8))
        self._make_metric_card(metrics, "异常配置", self.global_error_var, PALETTE["danger"], PALETTE["danger_soft"], value_foreground="#DC2626").grid(row=0, column=3, sticky="ew")

        content = tk.Frame(parent, bg=PALETTE["panel_bg"])
        content.grid(row=1, column=0, sticky="nsew")
        content.columnconfigure(0, weight=6)
        content.columnconfigure(1, weight=5)
        content.rowconfigure(0, weight=1)

        current = self._make_card(content)
        current.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
        current.columnconfigure(0, weight=1)
        current.columnconfigure(1, weight=1)

        left = tk.Frame(current, bg=PALETTE["card_bg"])
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 18))
        left.columnconfigure(0, weight=1)
        tk.Label(left, text="Codex 当前生效配置", bg=PALETTE["card_bg"], fg=PALETTE["text"], font=self.section_font).grid(row=0, column=0, sticky="w")
        tk.Label(left, textvariable=self.codex_current_models_var, bg=PALETTE["card_bg"], fg=PALETTE["text"], font=self.body_font, justify="left", wraplength=420).grid(row=1, column=0, sticky="w", pady=(8, 4))
        tk.Label(left, textvariable=self.codex_current_api_var, bg=PALETTE["card_bg"], fg=PALETTE["muted"], font=self.body_font, justify="left", wraplength=420).grid(row=2, column=0, sticky="w")

        tk.Label(left, text="Claude 当前生成配置", bg=PALETTE["card_bg"], fg=PALETTE["text"], font=self.section_font).grid(row=3, column=0, sticky="w", pady=(22, 0))
        tk.Label(left, textvariable=self.claude_current_models_var, bg=PALETTE["card_bg"], fg=PALETTE["text"], font=self.body_font, justify="left", wraplength=420).grid(row=4, column=0, sticky="w", pady=(8, 4))
        tk.Label(left, textvariable=self.claude_current_api_var, bg=PALETTE["card_bg"], fg=PALETTE["muted"], font=self.body_font, justify="left", wraplength=420).grid(row=5, column=0, sticky="w")

        right = tk.Frame(current, bg=PALETTE["card_bg"])
        right.grid(row=0, column=1, sticky="nsew")
        right.columnconfigure(0, weight=1)
        tk.Label(right, text="配置文件位置", bg=PALETTE["card_bg"], fg=PALETTE["text"], font=self.section_font).grid(row=0, column=0, sticky="w")
        tk.Label(right, textvariable=self.current_path_var, bg=PALETTE["card_bg"], fg=PALETTE["muted"], font=self.small_font, justify="left", wraplength=360).grid(row=1, column=0, sticky="w", pady=(10, 12))

        tk.Label(right, text="全局 API 设置", bg=PALETTE["card_bg"], fg=PALETTE["text"], font=self.section_font).grid(row=2, column=0, sticky="w", pady=(18, 8))
        codex_profile_row = tk.Frame(right, bg=PALETTE["card_bg"])
        codex_profile_row.grid(row=3, column=0, sticky="ew")
        codex_profile_row.columnconfigure(0, weight=1)
        tk.Label(codex_profile_row, text="Codex", bg=PALETTE["card_bg"], fg=PALETTE["text"], font=self.small_font).grid(row=0, column=0, sticky="w")
        self.global_codex_profile_combo = ttk.Combobox(
            codex_profile_row,
            textvariable=self.global_codex_profile_choice_var,
            state="readonly",
            width=40,
        )
        self.global_codex_profile_combo.grid(row=1, column=0, sticky="ew", pady=(4, 0))
        self.global_codex_profile_combo.bind("<<ComboboxSelected>>", lambda event: self._on_global_profile_choice_changed(VENDOR_CODEX, event))
        claude_profile_row = tk.Frame(right, bg=PALETTE["card_bg"])
        claude_profile_row.grid(row=4, column=0, sticky="ew", pady=(10, 0))
        claude_profile_row.columnconfigure(0, weight=1)
        tk.Label(claude_profile_row, text="Claude", bg=PALETTE["card_bg"], fg=PALETTE["text"], font=self.small_font).grid(row=0, column=0, sticky="w")
        self.global_claude_profile_combo = ttk.Combobox(
            claude_profile_row,
            textvariable=self.global_claude_profile_choice_var,
            state="readonly",
            width=40,
        )
        self.global_claude_profile_combo.grid(row=1, column=0, sticky="ew", pady=(4, 0))
        self.global_claude_profile_combo.bind("<<ComboboxSelected>>", lambda event: self._on_global_profile_choice_changed(VENDOR_CLAUDE, event))
        global_api_actions = tk.Frame(right, bg=PALETTE["card_bg"])
        global_api_actions.grid(row=5, column=0, sticky="ew", pady=(14, 0))
        for column in range(3):
            global_api_actions.columnconfigure(column, weight=1)
        make_button(global_api_actions, text="写入全局配置", variant="primary", command=self.apply_global_profile).grid(row=0, column=0, sticky="ew", padx=(0, 8))
        make_button(global_api_actions, text="打开 Codex 配置", variant="secondary", command=self.open_global_codex_config).grid(row=0, column=1, sticky="ew", padx=(0, 8))
        make_button(global_api_actions, text="打开 Claude 配置", variant="secondary", command=self.open_global_claude_config).grid(row=0, column=2, sticky="ew")

        mcp_card = self._make_card(content)
        mcp_card.grid(row=0, column=1, sticky="nsew")
        mcp_card.columnconfigure(0, weight=1)
        tk.Label(mcp_card, text="全局 MCP 配置", bg=PALETTE["card_bg"], fg=PALETTE["text"], font=self.hero_font).grid(row=0, column=0, sticky="w")
        tk.Label(
            mcp_card,
            text="用于全局切换时自动注入托管的 MCP 服务器。清空后会显式退出默认注入。",
            bg=PALETTE["card_bg"],
            fg=PALETTE["muted"],
            font=self.small_font,
            justify="left",
            wraplength=360,
        ).grid(row=1, column=0, sticky="w", pady=(6, 12))
        tk.Label(mcp_card, textvariable=self.global_mcp_var, bg=PALETTE["card_bg"], fg=PALETTE["text"], font=self.body_font, justify="left", wraplength=360).grid(row=2, column=0, sticky="w")

        actions = tk.Frame(mcp_card, bg=PALETTE["card_bg"])
        actions.grid(row=3, column=0, sticky="ew", pady=(18, 0))
        for column in range(3):
            actions.columnconfigure(column, weight=1)
        make_button(actions, text="选择 MCP", variant="primary", command=self.select_global_mcp).grid(row=0, column=0, sticky="ew", padx=(0, 8))
        make_button(actions, text="禁用 MCP", variant="danger", command=self.clear_global_mcp).grid(row=0, column=1, sticky="ew", padx=(0, 8))
        make_button(actions, text="刷新", variant="secondary", command=self.refresh_all).grid(row=0, column=2, sticky="ew")

    def _build_library_tab(self, parent: tk.Misc) -> None:
        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(0, weight=1)

        content = tk.Frame(parent, bg=PALETTE["panel_bg"])
        content.grid(row=0, column=0, sticky="nsew")
        content.columnconfigure(0, weight=5)
        content.columnconfigure(1, weight=6)
        content.rowconfigure(0, weight=1)

        left = self._make_card(content)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
        left.columnconfigure(0, weight=1)
        left.rowconfigure(2, weight=1)
        tk.Label(left, text="配置库", bg=PALETTE["card_bg"], fg=PALETTE["text"], font=self.hero_font).grid(row=0, column=0, sticky="w")
        tk.Label(left, textvariable=self.library_hint_var, bg=PALETTE["card_bg"], fg=PALETTE["muted"], font=self.small_font).grid(row=0, column=0, sticky="e")

        library_tabs = tk.Frame(left, bg=PALETTE["card_bg"])
        library_tabs.grid(row=1, column=0, sticky="ew", pady=(12, 0))
        for column, (profile_view, label) in enumerate(LIBRARY_PROFILE_VIEW_TABS):
            tab = tk.Label(
                library_tabs,
                text=label,
                bg=PALETTE["card_bg"],
                fg=PALETTE["text"],
                font=("Microsoft YaHei UI", 10, "bold"),
                padx=16,
                pady=8,
                bd=0,
                highlightthickness=1,
                highlightbackground=PALETTE["card_border"],
                cursor="hand2",
            )
            tab.grid(row=0, column=column, sticky="ew", padx=(0, 8))
            tab.bind("<Button-1>", lambda _event, view=profile_view: self._set_library_profile_view(view))
            self.library_scope_tabs[profile_view] = tab
        library_tabs.columnconfigure(len(LIBRARY_PROFILE_VIEW_TABS), weight=1)

        tree_wrap = tk.Frame(left, bg=PALETTE["card_bg"])
        tree_wrap.grid(row=2, column=0, sticky="nsew", pady=(10, 0))
        tree_wrap.columnconfigure(0, weight=1)
        tree_wrap.rowconfigure(0, weight=1)
        self.profile_tree = ttk.Treeview(tree_wrap, columns=("name", "vendor", "base_url", "model", "sign_in", "health"), show="headings")
        self.profile_tree.heading("name", text="配置名", anchor="w")
        self.profile_tree.heading("vendor", text="供应商", anchor="center")
        self.profile_tree.heading("base_url", text="API 地址", anchor="w")
        self.profile_tree.heading("model", text="默认模型", anchor="center")
        self.profile_tree.heading("sign_in", text="API签到状态", anchor="center")
        self.profile_tree.heading("health", text="状态", anchor="center")
        self.profile_tree.column("name", width=150, anchor="w")
        self.profile_tree.column("vendor", width=72, anchor="center", stretch=False)
        self.profile_tree.column("base_url", width=220, anchor="w")
        self.profile_tree.column("model", width=130, anchor="center")
        self.profile_tree.column("sign_in", width=110, anchor="center")
        self.profile_tree.column("health", width=90, anchor="center")
        self.profile_tree.grid(row=0, column=0, sticky="nsew")
        self.profile_tree.bind("<<TreeviewSelect>>", self._on_profile_selection_changed)

        profile_scroll = ttk.Scrollbar(tree_wrap, orient="vertical", command=self.profile_tree.yview)
        profile_scroll.grid(row=0, column=1, sticky="ns")
        self.profile_tree.configure(yscrollcommand=profile_scroll.set)

        actions = tk.Frame(left, bg=PALETTE["card_bg"])
        actions.grid(row=3, column=0, sticky="ew", pady=(14, 0))
        for column in range(4):
            actions.columnconfigure(column, weight=1)
        make_button(actions, text="新增", variant="primary", command=self.add_profile).grid(row=0, column=0, sticky="ew", padx=(0, 8), pady=(0, 8))
        make_button(actions, text="编辑", variant="secondary", command=self.edit_profile).grid(row=0, column=1, sticky="ew", padx=(0, 8), pady=(0, 8))
        make_button(actions, text="删除", variant="danger", command=self.delete_profile).grid(row=0, column=2, sticky="ew", padx=(0, 8), pady=(0, 8))
        make_button(actions, textvariable=self.hide_error_button_var, variant="secondary", command=self._on_profile_filter_changed).grid(row=0, column=3, sticky="ew", pady=(0, 8))
        make_button(actions, text="设为当前", variant="primary", command=self.apply_selected_profile).grid(row=1, column=0, sticky="ew", padx=(0, 8))
        make_button(actions, text="测试选中", variant="secondary", command=self.test_selected_profile).grid(row=1, column=1, sticky="ew", padx=(0, 8))
        make_button(actions, text="测试全部", variant="secondary", command=self.test_all_profiles).grid(row=1, column=2, sticky="ew", padx=(0, 8))
        make_button(actions, text="刷新", variant="secondary", command=self.refresh_all).grid(row=1, column=3, sticky="ew")

        right = self._make_card(content)
        right.grid(row=0, column=1, sticky="nsew")
        right.columnconfigure(0, weight=1)
        right.columnconfigure(1, weight=1)

        header = tk.Frame(right, bg=PALETTE["card_bg"])
        header.grid(row=0, column=0, columnspan=2, sticky="ew")
        header.columnconfigure(0, weight=1)
        tk.Label(header, textvariable=self.library_selected_name_var, bg=PALETTE["card_bg"], fg=PALETTE["text"], font=self.hero_font).grid(row=0, column=0, sticky="w")
        self.library_health_badge = make_status_badge(header, text="未检测")
        self.library_health_badge.grid(row=0, column=1, sticky="e")
        tk.Label(header, text="这里展示选中配置的连接信息、签到状态和最近检测返回模型。", bg=PALETTE["card_bg"], fg=PALETTE["muted"], font=self.small_font).grid(
            row=1,
            column=0,
            sticky="w",
            pady=(4, 0),
        )

        detail = tk.Frame(right, bg=PALETTE["card_bg"])
        detail.grid(row=1, column=0, columnspan=2, sticky="nsew", pady=(14, 0))
        detail.columnconfigure(1, weight=1)
        detail.columnconfigure(3, weight=1)
        self._create_dual_info_row(detail, 0, "供应商", self.library_selected_provider_var, "分类", self.library_selected_category_var)
        self._create_info_row(detail, 1, "模型", self.library_selected_model_var, wraplength=460)
        self.library_api_link_label = self._create_link_info_row(detail, 2, "API 地址", self.library_selected_api_var, self._open_selected_api_url, wraplength=460)
        self._create_dual_info_row(detail, 3, "活动 Key", self.library_selected_key_var, "Wire API", self.library_selected_wire_var)
        self._create_info_row(detail, 4, "签到状态", self.library_selected_sign_in_status_var, wraplength=460)
        self.library_sign_in_link_label = self._create_link_info_row(detail, 5, "签到地址", self.library_selected_sign_in_url_var, self._open_selected_sign_in_url, wraplength=460)
        self._create_info_row(detail, 6, "备注", self.library_selected_notes_var, wraplength=460)

        tk.Label(detail, text="返回模型", bg=PALETTE["card_bg"], fg=PALETTE["muted"], font=self.small_font).grid(row=7, column=0, sticky="nw", padx=(0, 14), pady=(12, 4))
        models_wrap = tk.Frame(detail, bg=PALETTE["card_bg"])
        models_wrap.grid(row=7, column=1, columnspan=3, sticky="nsew", pady=(12, 4))
        models_wrap.columnconfigure(0, weight=1)
        models_wrap.rowconfigure(1, weight=1)

        models_summary = tk.Frame(models_wrap, bg=PALETTE["card_bg"])
        models_summary.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 8))
        models_summary.columnconfigure(0, weight=1)
        tk.Label(
            models_summary,
            textvariable=self.library_models_summary_var,
            bg=PALETTE["card_bg"],
            fg=PALETTE["text"],
            font=self.small_font,
            justify="left",
            wraplength=520,
        ).grid(row=0, column=0, sticky="w")
        make_button(
            models_summary,
            textvariable=self.library_model_stats_button_var,
            variant="secondary",
            command=self._toggle_library_model_stats,
        ).grid(row=0, column=1, sticky="e", padx=(10, 0))

        self.library_models_canvas = tk.Canvas(
            models_wrap,
            height=176,
            bg="#FBFDFE",
            highlightbackground=PALETTE["card_border"],
            highlightthickness=1,
        )
        self.library_models_canvas.grid(row=1, column=0, sticky="nsew")
        library_models_scroll = ttk.Scrollbar(models_wrap, orient="vertical", command=self.library_models_canvas.yview)
        library_models_scroll.grid(row=1, column=1, sticky="ns")
        self.library_models_canvas.configure(yscrollcommand=library_models_scroll.set)
        self.library_model_tags_frame = tk.Frame(self.library_models_canvas, bg="#FBFDFE")
        self.library_model_tags_window = self.library_models_canvas.create_window((0, 0), window=self.library_model_tags_frame, anchor="nw")
        self.library_model_tags_frame.bind(
            "<Configure>",
            lambda _event: self.library_models_canvas.configure(scrollregion=self.library_models_canvas.bbox("all")),
        )
        self.library_models_canvas.bind("<Configure>", self._on_library_models_canvas_configure)

        self.library_model_stats_text = tk.Text(
            models_wrap,
            height=7,
            wrap="word",
            relief="solid",
            borderwidth=1,
            highlightthickness=0,
            font=self.small_font,
            bg="#FBFDFE",
            fg=PALETTE["text"],
            state="disabled",
        )
        self.library_model_stats_text.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(8, 0))
        self.library_model_stats_text.grid_remove()

    def _build_project_tab(self, parent: tk.Misc) -> None:
        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(0, weight=1)

        content = tk.Frame(parent, bg=PALETTE["panel_bg"])
        content.grid(row=0, column=0, sticky="nsew")
        content.columnconfigure(0, weight=5)
        content.columnconfigure(1, weight=6)
        content.rowconfigure(0, weight=1)

        self._build_project_list_panel(content)
        detail = self._build_project_detail_panel(content)
        self._build_project_actions(detail)

    def _build_project_list_panel(self, parent: tk.Misc) -> None:
        project_list = self._make_card(parent)
        project_list.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
        project_list.columnconfigure(0, weight=1)
        project_list.rowconfigure(1, weight=1)
        tk.Label(project_list, text="项目索引", bg=PALETTE["card_bg"], fg=PALETTE["text"], font=self.hero_font).grid(row=0, column=0, sticky="w")
        tk.Label(project_list, textvariable=self.project_hint_var, bg=PALETTE["card_bg"], fg=PALETTE["muted"], font=self.small_font).grid(row=0, column=0, sticky="e")

        project_tree_wrap = tk.Frame(project_list, bg=PALETTE["card_bg"])
        project_tree_wrap.grid(row=1, column=0, sticky="nsew", pady=(12, 0))
        project_tree_wrap.columnconfigure(0, weight=1)
        project_tree_wrap.rowconfigure(0, weight=1)
        self.project_tree = ttk.Treeview(project_tree_wrap, columns=("name", "dir", "codex", "claude", "mcp"), show="headings")
        self.project_tree.heading("name", text="项目")
        self.project_tree.heading("dir", text="目录")
        self.project_tree.heading("codex", text="绑定 Codex")
        self.project_tree.heading("claude", text="绑定 Claude")
        self.project_tree.heading("mcp", text="MCP")
        self.project_tree.column("name", width=180, anchor="center")
        self.project_tree.column("dir", width=230, anchor="center")
        self.project_tree.column("codex", width=130, anchor="center")
        self.project_tree.column("claude", width=130, anchor="center")
        self.project_tree.column("mcp", width=110, anchor="center")
        self.project_tree.grid(row=0, column=0, sticky="nsew")
        self.project_tree.bind("<<TreeviewSelect>>", self._on_project_selection_changed)
        project_scroll = ttk.Scrollbar(project_tree_wrap, orient="vertical", command=self.project_tree.yview)
        project_scroll.grid(row=0, column=1, sticky="ns")
        self.project_tree.configure(yscrollcommand=project_scroll.set)

        actions = tk.Frame(project_list, bg=PALETTE["card_bg"])
        actions.grid(row=2, column=0, sticky="ew", pady=(14, 0))
        for column in range(3):
            actions.columnconfigure(column, weight=1)
        make_button(actions, text="添加项目", variant="primary", command=self.add_project).grid(row=0, column=0, sticky="ew", padx=(0, 8))
        make_button(actions, text="修改项目", variant="secondary", command=self.edit_project).grid(row=0, column=1, sticky="ew", padx=(0, 8))
        make_button(actions, text="删除项目", variant="danger", command=self.delete_project).grid(row=0, column=2, sticky="ew")

    def _build_project_detail_panel(self, parent: tk.Misc) -> tk.Frame:
        detail = self._make_card(parent)
        detail.grid(row=0, column=1, sticky="nsew")
        detail.columnconfigure(1, weight=1)
        detail.columnconfigure(3, weight=1)

        header = tk.Frame(detail, bg=PALETTE["card_bg"])
        header.grid(row=0, column=0, columnspan=4, sticky="ew")
        header.columnconfigure(0, weight=1)
        tk.Label(header, textvariable=self.project_selected_name_var, bg=PALETTE["card_bg"], fg=PALETTE["text"], font=self.hero_font).grid(row=0, column=0, sticky="w")
        self.project_status_badge = make_status_badge(header, text="未生成")
        self.project_status_badge.grid(row=0, column=1, sticky="e")
        tk.Label(header, text="这里展示项目目录、绑定配置、模板生成状态和项目级 MCP/Skills。", bg=PALETTE["card_bg"], fg=PALETTE["muted"], font=self.small_font).grid(
            row=1,
            column=0,
            sticky="w",
            pady=(4, 0),
        )

        self._create_info_row(detail, 1, "项目目录", self.project_selected_dir_var, wraplength=440)
        self._create_dual_info_row(detail, 2, "绑定 Codex", self.project_selected_codex_profile_var, "绑定 Claude", self.project_selected_claude_profile_var)
        self._create_dual_info_row(detail, 3, "Codex 模型", self.project_selected_codex_model_var, "Claude 模型", self.project_selected_claude_model_var)
        self._create_dual_info_row(detail, 4, "Codex Key", self.project_selected_codex_key_var, "Claude Key", self.project_selected_claude_key_var)
        self._create_dual_info_row(detail, 5, "最近备份", self.project_backup_var, "最近生成", self.project_generated_var)
        self._create_info_row(detail, 6, "运行脚本", self.project_script_var, wraplength=440)
        self._create_info_row(detail, 7, "运行命令", self.project_run_var, wraplength=440)
        self._create_info_row(detail, 8, "GitHub 地址", self.project_github_var, wraplength=440)
        self._create_info_row(detail, 9, "GitHub 更新", self.project_github_update_var, wraplength=440)
        self._create_info_row(detail, 10, "项目 MCP", self.project_mcp_var, wraplength=440)
        self._create_info_row(detail, 11, "项目 Skills", self.project_skills_var, wraplength=440)

        return detail

    def _build_project_actions(self, detail: tk.Misc) -> None:
        actions = tk.Frame(detail, bg=PALETTE["card_bg"])
        actions.grid(row=12, column=0, columnspan=4, sticky="ew", pady=(18, 0))
        actions.columnconfigure(0, weight=1)

        self._create_project_action_group(
            actions,
            0,
            "Codex 相关",
            (
                ("生成 Codex 模板", "primary", self.generate_project_template),
                ("修改 config.toml", "secondary", self.edit_project_codex_config),
                ("VS Code 运行", "secondary", self.run_project_vscode),
                ("CMD 打开 Codex", "secondary", self.run_project_cmd),
            ),
        )
        self._create_project_action_group(
            actions,
            1,
            "Claude 相关",
            (
                ("生成 Claude 模板", "primary", self.generate_claude_template),
                ("修改 settings.local.json", "secondary", self.edit_project_claude_settings),
                ("VS Code 打开", "secondary", self.open_project_vscode),
                ("CMD 打开 Claude", "secondary", self.open_project_claude_cmd),
            ),
        )
        self._create_project_action_group(
            actions,
            2,
            "项目相关",
            (
                ("运行项目", "primary", self.run_project),
                ("打开项目文件夹", "secondary", self.open_project_folder),
                ("检查项目更新", "secondary", self.check_selected_project_update),
            ),
        )

    def _build_proxy_tab(self, parent: tk.Misc) -> None:
        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(0, weight=1)

        content = tk.Frame(parent, bg=PALETTE["panel_bg"])
        content.grid(row=0, column=0, sticky="nsew")
        content.columnconfigure(0, weight=5)
        content.columnconfigure(1, weight=6)
        content.rowconfigure(0, weight=1)

        left = self._make_card(content)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
        left.columnconfigure(0, weight=1)
        left.rowconfigure(9, weight=1)
        tk.Label(left, text="路由代理", bg=PALETTE["card_bg"], fg=PALETTE["text"], font=self.hero_font).grid(row=0, column=0, sticky="w")
        tk.Label(left, textvariable=self.proxy_hint_var, bg=PALETTE["card_bg"], fg=PALETTE["muted"], font=self.small_font).grid(row=1, column=0, sticky="w", pady=(4, 12))

        settings = tk.Frame(left, bg=PALETTE["card_bg"])
        settings.grid(row=2, column=0, sticky="ew")
        settings.columnconfigure(1, weight=1)
        tk.Label(settings, text="监听地址", bg=PALETTE["card_bg"], fg=PALETTE["muted"], font=self.small_font).grid(row=0, column=0, sticky="w", padx=(0, 10), pady=4)
        ttk.Entry(settings, textvariable=self.proxy_host_var, width=18).grid(row=0, column=1, sticky="w", pady=4)
        tk.Label(settings, text="端口", bg=PALETTE["card_bg"], fg=PALETTE["muted"], font=self.small_font).grid(row=0, column=2, sticky="w", padx=(16, 10), pady=4)
        ttk.Entry(settings, textvariable=self.proxy_port_var, width=8).grid(row=0, column=3, sticky="w", pady=4)
        tk.Label(settings, text="号池策略", bg=PALETTE["card_bg"], fg=PALETTE["muted"], font=self.small_font).grid(row=1, column=0, sticky="w", padx=(0, 10), pady=4)
        ttk.Combobox(
            settings,
            textvariable=self.proxy_account_pool_strategy_var,
            values=tuple(ROUTE_PROXY_ACCOUNT_POOL_STRATEGY_VALUES.keys()),
            state="readonly",
            width=12,
        ).grid(row=1, column=1, sticky="w", pady=4)
        tk.Label(settings, text="节点超时(秒)", bg=PALETTE["card_bg"], fg=PALETTE["muted"], font=self.small_font).grid(row=1, column=2, sticky="w", padx=(16, 10), pady=4)
        ttk.Entry(settings, textvariable=self.proxy_upstream_timeout_var, width=8).grid(row=1, column=3, sticky="w", pady=4)
        tk.Label(settings, text="Codex 来源", bg=PALETTE["card_bg"], fg=PALETTE["muted"], font=self.small_font).grid(row=2, column=0, sticky="w", padx=(0, 10), pady=4)
        ttk.Combobox(
            settings,
            textvariable=self.proxy_codex_upstream_source_var,
            values=tuple(CODEX_ROUTE_PROXY_UPSTREAM_SOURCE_VALUES.keys()),
            state="readonly",
            width=28,
        ).grid(row=2, column=1, columnspan=3, sticky="w", pady=4)
        tk.Label(settings, text="Codex 号池组", bg=PALETTE["card_bg"], fg=PALETTE["muted"], font=self.small_font).grid(row=3, column=0, sticky="w", padx=(0, 10), pady=4)
        self.proxy_account_pool_group_combo = ttk.Combobox(
            settings,
            textvariable=self.proxy_account_pool_group_var,
            state="readonly",
            width=28,
        )
        self.proxy_account_pool_group_combo.grid(row=3, column=1, columnspan=3, sticky="w", pady=4)
        tk.Label(settings, text="Codex 协议", bg=PALETTE["card_bg"], fg=PALETTE["muted"], font=self.small_font).grid(row=4, column=0, sticky="w", padx=(0, 10), pady=4)
        ttk.Combobox(
            settings,
            textvariable=self.proxy_codex_protocol_var,
            values=CODEX_ROUTE_PROXY_PROTOCOLS,
            state="readonly",
            width=28,
        ).grid(row=4, column=1, columnspan=3, sticky="w", pady=4)
        tk.Label(settings, text="Compact 模型", bg=PALETTE["card_bg"], fg=PALETTE["muted"], font=self.small_font).grid(row=5, column=0, sticky="w", padx=(0, 10), pady=4)
        ttk.Entry(settings, textvariable=self.proxy_codex_compact_model_var, width=28).grid(row=5, column=1, columnspan=3, sticky="w", pady=4)
        tk.Label(settings, text="Claude 来源", bg=PALETTE["card_bg"], fg=PALETTE["muted"], font=self.small_font).grid(row=6, column=0, sticky="w", padx=(0, 10), pady=4)
        ttk.Combobox(
            settings,
            textvariable=self.proxy_claude_upstream_source_var,
            values=tuple(CODEX_ROUTE_PROXY_UPSTREAM_SOURCE_VALUES.keys()),
            state="readonly",
            width=28,
        ).grid(row=6, column=1, columnspan=3, sticky="w", pady=4)
        tk.Label(settings, text="Claude 号池组", bg=PALETTE["card_bg"], fg=PALETTE["muted"], font=self.small_font).grid(row=7, column=0, sticky="w", padx=(0, 10), pady=4)
        self.proxy_claude_account_pool_group_combo = ttk.Combobox(
            settings,
            textvariable=self.proxy_claude_account_pool_group_var,
            state="readonly",
            width=28,
        )
        self.proxy_claude_account_pool_group_combo.grid(row=7, column=1, columnspan=3, sticky="w", pady=4)
        tk.Label(settings, text="Claude 协议", bg=PALETTE["card_bg"], fg=PALETTE["muted"], font=self.small_font).grid(row=8, column=0, sticky="w", padx=(0, 10), pady=4)
        ttk.Combobox(
            settings,
            textvariable=self.proxy_claude_protocol_var,
            values=CLAUDE_ROUTE_PROXY_PROTOCOLS,
            state="readonly",
            width=28,
        ).grid(row=8, column=1, columnspan=3, sticky="w", pady=4)

        proxy_tree_wrap = tk.Frame(left, bg=PALETTE["card_bg"])
        proxy_tree_wrap.grid(row=9, column=0, sticky="nsew", pady=(12, 0))
        proxy_tree_wrap.columnconfigure(0, weight=1)
        proxy_tree_wrap.rowconfigure(0, weight=1)
        self.proxy_project_tree = ttk.Treeview(proxy_tree_wrap, columns=("name", "codex", "claude", "pool", "enabled"), show="headings")
        for column, title, width in (
            ("name", "项目", 160),
            ("codex", "Codex", 120),
            ("claude", "Claude", 120),
            ("pool", "号池", 80),
            ("enabled", "代理", 80),
        ):
            self.proxy_project_tree.heading(column, text=title)
            self.proxy_project_tree.column(column, width=width, anchor="center")
        self.proxy_project_tree.grid(row=0, column=0, sticky="nsew")
        self.proxy_project_tree.bind("<<TreeviewSelect>>", self._on_proxy_project_selection_changed)
        proxy_scroll = ttk.Scrollbar(proxy_tree_wrap, orient="vertical", command=self.proxy_project_tree.yview)
        proxy_scroll.grid(row=0, column=1, sticky="ns")
        self.proxy_project_tree.configure(yscrollcommand=proxy_scroll.set)

        actions = tk.Frame(left, bg=PALETTE["card_bg"])
        actions.grid(row=10, column=0, sticky="ew", pady=(14, 0))
        for column in range(4):
            actions.columnconfigure(column, weight=1)
        make_button(actions, text="保存设置", variant="secondary", command=self.save_route_proxy_settings).grid(row=0, column=0, sticky="ew", padx=(0, 8))
        make_button(actions, text="启动代理", variant="primary", command=self.start_route_proxy).grid(row=0, column=1, sticky="ew", padx=(0, 8))
        make_button(actions, text="停止代理", variant="danger", command=self.stop_route_proxy).grid(row=0, column=2, sticky="ew", padx=(0, 8))
        make_button(actions, text="刷新", variant="secondary", command=self.refresh_proxy_tab).grid(row=0, column=3, sticky="ew")
        make_button(actions, text="启用项目代理", variant="primary", command=self.enable_route_proxy_for_project).grid(row=1, column=0, columnspan=2, sticky="ew", padx=(0, 8), pady=(8, 0))
        make_button(actions, text="关闭项目代理", variant="secondary", command=self.disable_route_proxy_for_project).grid(row=1, column=2, columnspan=2, sticky="ew", pady=(8, 0))

        right = self._make_card(content)
        right.grid(row=0, column=1, sticky="nsew")
        right.columnconfigure(0, weight=1)
        right.rowconfigure(5, weight=1)
        tk.Label(right, textvariable=self.proxy_status_var, bg=PALETTE["card_bg"], fg=PALETTE["text"], font=self.hero_font).grid(row=0, column=0, sticky="w")
        self._create_info_row(right, 1, "选中项目", self.proxy_selected_project_var, wraplength=460)
        self._create_info_row(right, 2, "当前规则", self.proxy_selected_rules_var, wraplength=460)
        tk.Label(right, text="最近代理日志", bg=PALETTE["card_bg"], fg=PALETTE["text"], font=self.section_font).grid(row=3, column=0, sticky="w", pady=(16, 6))
        log_wrap = tk.Frame(right, bg=PALETTE["card_bg"])
        log_wrap.grid(row=5, column=0, sticky="nsew")
        log_wrap.columnconfigure(0, weight=1)
        log_wrap.rowconfigure(0, weight=1)
        self.proxy_log_text = tk.Text(
            log_wrap,
            height=18,
            wrap="word",
            relief="solid",
            borderwidth=1,
            highlightthickness=0,
            font=self.small_font,
            bg="#FBFDFE",
            fg=PALETTE["text"],
            state="disabled",
        )
        self.proxy_log_text.grid(row=0, column=0, sticky="nsew")
        proxy_log_scroll = ttk.Scrollbar(log_wrap, orient="vertical", command=self.proxy_log_text.yview)
        proxy_log_scroll.grid(row=0, column=1, sticky="ns")
        self.proxy_log_text.configure(yscrollcommand=proxy_log_scroll.set)

    def _build_stats_tab(self, parent: tk.Misc) -> None:
        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(0, weight=1)

        content = tk.Frame(parent, bg=PALETTE["panel_bg"])
        content.grid(row=0, column=0, sticky="nsew")
        content.columnconfigure(0, weight=5)
        content.columnconfigure(1, weight=6)
        content.rowconfigure(1, weight=1)

        metrics = tk.Frame(content, bg=PALETTE["panel_bg"])
        metrics.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 10))
        for column in range(4):
            metrics.columnconfigure(column, weight=1)
        self._make_metric_card(metrics, "总 Token", self.stats_total_tokens_var, PALETTE["accent"], PALETTE["selection_bg"]).grid(
            row=0,
            column=0,
            sticky="ew",
            padx=(0, 8),
        )
        self._make_metric_card(metrics, "今日 Token", self.stats_today_tokens_var, PALETTE["success"], PALETTE["success_soft"], value_foreground="#16A34A").grid(
            row=0,
            column=1,
            sticky="ew",
            padx=(0, 8),
        )
        self._make_metric_card(metrics, "项目数", self.stats_project_count_var, PALETTE["warning"], PALETTE["warning_soft"], value_foreground="#CA8A04").grid(
            row=0,
            column=2,
            sticky="ew",
            padx=(0, 8),
        )
        self._make_metric_card(metrics, "API 数", self.stats_api_count_var, PALETTE["danger"], PALETTE["danger_soft"], value_foreground="#DC2626").grid(
            row=0,
            column=3,
            sticky="ew",
        )

        left = self._make_card(content)
        left.grid(row=1, column=0, sticky="nsew", padx=(0, 10))
        left.columnconfigure(0, weight=1)
        left.rowconfigure(1, weight=1)
        header = tk.Frame(left, bg=PALETTE["card_bg"])
        header.grid(row=0, column=0, sticky="ew")
        header.columnconfigure(0, weight=1)
        tk.Label(header, text="日消耗", bg=PALETTE["card_bg"], fg=PALETTE["text"], font=self.hero_font).grid(row=0, column=0, sticky="w")
        make_button(header, text="刷新", variant="secondary", command=self.refresh_stats_tab).grid(row=0, column=1, sticky="e")
        day_tree_wrap, self.stats_day_tree = self._build_usage_tree(left)
        day_tree_wrap.grid(row=1, column=0, sticky="nsew", pady=(12, 0))

        right = tk.Frame(content, bg=PALETTE["panel_bg"])
        right.grid(row=1, column=1, sticky="nsew")
        right.columnconfigure(0, weight=1)
        right.rowconfigure(0, weight=1)
        right.rowconfigure(1, weight=1)

        project_card = self._make_card(right)
        project_card.grid(row=0, column=0, sticky="nsew", pady=(0, 10))
        project_card.columnconfigure(0, weight=1)
        project_card.rowconfigure(1, weight=1)
        tk.Label(project_card, text="项目消耗", bg=PALETTE["card_bg"], fg=PALETTE["text"], font=self.hero_font).grid(row=0, column=0, sticky="w")
        project_tree_wrap, self.stats_project_tree = self._build_usage_tree(project_card)
        project_tree_wrap.grid(row=1, column=0, sticky="nsew", pady=(12, 0))

        api_card = self._make_card(right)
        api_card.grid(row=1, column=0, sticky="nsew")
        api_card.columnconfigure(0, weight=1)
        api_card.rowconfigure(1, weight=1)
        tk.Label(api_card, text="API 消耗", bg=PALETTE["card_bg"], fg=PALETTE["text"], font=self.hero_font).grid(row=0, column=0, sticky="w")
        api_tree_wrap, self.stats_api_tree = self._build_usage_tree(api_card)
        api_tree_wrap.grid(row=1, column=0, sticky="nsew", pady=(12, 0))

    def _build_usage_tree(self, parent: tk.Misc) -> tuple[tk.Frame, ttk.Treeview]:
        wrap = tk.Frame(parent, bg=PALETTE["card_bg"])
        wrap.columnconfigure(0, weight=1)
        wrap.rowconfigure(0, weight=1)
        tree = ttk.Treeview(
            wrap,
            columns=("label", "input", "output", "total", "requests", "updated"),
            show="headings",
        )
        for column, title, width in (
            ("label", "名称", 180),
            ("input", "输入", 90),
            ("output", "输出", 90),
            ("total", "总计", 90),
            ("requests", "请求", 70),
            ("updated", "最近更新", 140),
        ):
            tree.heading(column, text=title)
            tree.column(column, width=width, anchor="center")
        tree.grid(row=0, column=0, sticky="nsew")
        scroll = ttk.Scrollbar(wrap, orient="vertical", command=tree.yview)
        scroll.grid(row=0, column=1, sticky="ns")
        tree.configure(yscrollcommand=scroll.set)
        return wrap, tree

    def _build_account_pool_tab(self, parent: tk.Misc) -> None:
        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(0, weight=1)

        content = tk.Frame(parent, bg=PALETTE["panel_bg"])
        content.grid(row=0, column=0, sticky="nsew")
        content.columnconfigure(0, weight=7)
        content.columnconfigure(1, weight=4)
        content.rowconfigure(0, weight=1)

        left = self._make_card(content)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
        left.columnconfigure(0, weight=1)
        left.rowconfigure(3, weight=1)
        header = tk.Frame(left, bg=PALETTE["card_bg"])
        header.grid(row=0, column=0, sticky="ew")
        header.columnconfigure(0, weight=1)
        tk.Label(header, text="号池", bg=PALETTE["card_bg"], fg=PALETTE["text"], font=self.hero_font).grid(row=0, column=0, sticky="w")
        ttk.Checkbutton(
            header,
            text="启用号池",
            variable=self.account_pool_enabled_var,
            command=self.save_account_pool_settings,
        ).grid(row=0, column=1, sticky="e")
        tk.Label(left, textvariable=self.account_pool_summary_var, bg=PALETTE["card_bg"], fg=PALETTE["muted"], font=self.small_font).grid(row=1, column=0, sticky="w", pady=(4, 12))

        group_bar = tk.Frame(left, bg=PALETTE["card_bg"])
        group_bar.grid(row=2, column=0, sticky="ew", pady=(0, 10))
        group_bar.columnconfigure(1, weight=1)
        group_bar.columnconfigure(3, weight=1)
        tk.Label(group_bar, text="号池组", bg=PALETTE["card_bg"], fg=PALETTE["muted"], font=self.small_font).grid(row=0, column=0, sticky="w", padx=(0, 8))
        self.account_pool_group_combo = ttk.Combobox(
            group_bar,
            textvariable=self.account_pool_group_var,
            state="readonly",
            width=24,
        )
        self.account_pool_group_combo.grid(row=0, column=1, sticky="ew", padx=(0, 8))
        self.account_pool_group_combo.bind("<<ComboboxSelected>>", self._on_account_pool_group_changed)
        ttk.Checkbutton(
            group_bar,
            text="启用组",
            variable=self.account_pool_group_enabled_var,
            command=self.save_account_pool_group_settings,
        ).grid(row=0, column=2, sticky="w", padx=(0, 8))
        make_button(group_bar, text="新建组", variant="secondary", command=self.add_account_pool_group).grid(row=0, column=3, padx=(0, 8))
        make_button(group_bar, text="删除组", variant="danger", command=self.delete_account_pool_group).grid(row=0, column=4, padx=(0, 8))
        self.account_pool_source_filter_combo = ttk.Combobox(
            group_bar,
            textvariable=self.account_pool_source_filter_var,
            values=(
                ACCOUNT_POOL_SOURCE_FILTER_ALL,
                ACCOUNT_POOL_SOURCE_FILTER_TEMPORARY,
                ACCOUNT_POOL_SOURCE_FILTER_PROFILE,
            ),
            state="readonly",
            width=12,
        )
        self.account_pool_source_filter_combo.grid(row=0, column=5, sticky="e")
        self.account_pool_source_filter_var.trace_add("write", lambda *_args: self.refresh_account_pool_tab())

        tk.Label(group_bar, text="类型", bg=PALETTE["card_bg"], fg=PALETTE["muted"], font=self.small_font).grid(row=1, column=0, sticky="w", padx=(0, 8), pady=(8, 0))
        ttk.Combobox(
            group_bar,
            textvariable=self.account_pool_group_type_var,
            values=tuple(ACCOUNT_POOL_GROUP_TYPE_LABELS.values()),
            state="readonly",
            width=14,
        ).grid(row=1, column=1, sticky="w", padx=(0, 8), pady=(8, 0))
        tk.Label(group_bar, text="Codex 默认模型", bg=PALETTE["card_bg"], fg=PALETTE["muted"], font=self.small_font).grid(row=1, column=2, sticky="w", padx=(0, 8), pady=(8, 0))
        ttk.Entry(group_bar, textvariable=self.account_pool_group_default_model_var, width=24).grid(row=1, column=3, columnspan=3, sticky="ew", pady=(8, 0))
        tk.Label(group_bar, text="Claude 默认模型", bg=PALETTE["card_bg"], fg=PALETTE["muted"], font=self.small_font).grid(row=2, column=0, sticky="w", padx=(0, 8), pady=(8, 0))
        ttk.Entry(group_bar, textvariable=self.account_pool_group_claude_model_var, width=24).grid(row=2, column=1, sticky="ew", padx=(0, 8), pady=(8, 0))
        tk.Label(group_bar, text="Claude 兜底模型", bg=PALETTE["card_bg"], fg=PALETTE["muted"], font=self.small_font).grid(row=2, column=2, sticky="w", padx=(0, 8), pady=(8, 0))
        ttk.Entry(group_bar, textvariable=self.account_pool_group_claude_fallback_model_var, width=24).grid(row=2, column=3, columnspan=3, sticky="ew", pady=(8, 0))
        make_button(group_bar, text="保存组设置", variant="primary", command=self.save_account_pool_group_settings).grid(row=3, column=3, columnspan=3, sticky="e", pady=(8, 0))

        tree_wrap = tk.Frame(left, bg=PALETTE["card_bg"])
        tree_wrap.grid(row=3, column=0, sticky="nsew")
        tree_wrap.columnconfigure(0, weight=1)
        tree_wrap.rowconfigure(0, weight=1)
        self.account_pool_tree = ttk.Treeview(
            tree_wrap,
            columns=("name", "source", "base_url", "wire", "key", "status", "checked", "failure"),
            show="headings",
        )
        for column, title, width in (
            ("name", "名称", 140),
            ("source", "来源", 90),
            ("base_url", "API 地址", 220),
            ("wire", "Wire API", 120),
            ("key", "Key", 120),
            ("status", "状态", 80),
            ("checked", "最后检测", 130),
            ("failure", "失败原因", 220),
        ):
            self.account_pool_tree.heading(column, text=title)
            self.account_pool_tree.column(column, width=width, anchor="center")
        self.account_pool_tree.grid(row=0, column=0, sticky="nsew")
        self.account_pool_tree.bind("<<TreeviewSelect>>", self._on_account_pool_selection_changed)
        pool_scroll = ttk.Scrollbar(tree_wrap, orient="vertical", command=self.account_pool_tree.yview)
        pool_scroll.grid(row=0, column=1, sticky="ns")
        self.account_pool_tree.configure(yscrollcommand=pool_scroll.set)

        actions = tk.Frame(left, bg=PALETTE["card_bg"])
        actions.grid(row=4, column=0, sticky="ew", pady=(14, 0))
        for column in range(6):
            actions.columnconfigure(column, weight=1)
        make_button(actions, text="添加临时", variant="primary", command=self.add_account_pool_channel).grid(row=0, column=0, sticky="ew", padx=(0, 8))
        make_button(actions, text="加入配置库", variant="secondary", command=self.add_account_pool_profile_channel).grid(row=0, column=1, sticky="ew", padx=(0, 8))
        make_button(actions, text="编辑渠道", variant="secondary", command=self.edit_account_pool_channel).grid(row=0, column=2, sticky="ew", padx=(0, 8))
        make_button(actions, text="删除渠道", variant="danger", command=self.delete_account_pool_channel).grid(row=0, column=3, sticky="ew", padx=(0, 8))
        make_button(actions, text="重测异常", variant="secondary", command=self.retest_account_pool_channel).grid(row=0, column=4, sticky="ew", padx=(0, 8))
        make_button(actions, text="刷新", variant="secondary", command=self.refresh_account_pool_tab).grid(row=0, column=5, sticky="ew")

        right = self._make_card(content)
        right.grid(row=0, column=1, sticky="nsew")
        right.columnconfigure(1, weight=1)
        tk.Label(right, textvariable=self.account_pool_selected_name_var, bg=PALETTE["card_bg"], fg=PALETTE["text"], font=self.hero_font).grid(row=0, column=0, columnspan=2, sticky="w")
        self._create_info_row(right, 1, "渠道详情", self.account_pool_selected_detail_var, wraplength=360)

    def _build_mcp_tab(self, parent: tk.Misc) -> None:
        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(0, weight=1)

        content = tk.Frame(parent, bg=PALETTE["panel_bg"])
        content.grid(row=0, column=0, sticky="nsew")
        content.columnconfigure(0, weight=7)
        content.columnconfigure(1, weight=5)
        content.rowconfigure(0, weight=1)

        list_card = self._make_card(content)
        list_card.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
        list_card.columnconfigure(0, weight=1)
        list_card.rowconfigure(1, weight=1)

        tk.Label(list_card, text="MCP配置", bg=PALETTE["card_bg"], fg=PALETTE["text"], font=self.hero_font).grid(row=0, column=0, sticky="w")
        tk.Label(list_card, textvariable=self.mcp_hint_var, bg=PALETTE["card_bg"], fg=PALETTE["muted"], font=self.small_font).grid(row=0, column=0, sticky="e")

        tree_wrap = tk.Frame(list_card, bg=PALETTE["card_bg"])
        tree_wrap.grid(row=1, column=0, sticky="nsew", pady=(12, 0))
        tree_wrap.columnconfigure(0, weight=1)
        tree_wrap.rowconfigure(0, weight=1)

        self.mcp_tree = ttk.Treeview(
            tree_wrap,
            columns=("name", "type", "command", "args", "cwd", "env", "project"),
            show="headings",
        )
        for column, title, width, anchor in (
            ("name", "名称", 130, "w"),
            ("type", "type", 80, "center"),
            ("command", "command", 150, "w"),
            ("args", "args", 230, "w"),
            ("cwd", "cwd", 140, "w"),
            ("env", "env", 130, "w"),
            ("project", "{project_root}", 120, "center"),
        ):
            self.mcp_tree.heading(column, text=title, anchor=anchor)
            self.mcp_tree.column(column, width=width, anchor=anchor)
        self.mcp_tree.grid(row=0, column=0, sticky="nsew")
        self.mcp_tree.bind("<<TreeviewSelect>>", self._on_mcp_server_selection_changed)

        y_scroll = ttk.Scrollbar(tree_wrap, orient="vertical", command=self.mcp_tree.yview)
        y_scroll.grid(row=0, column=1, sticky="ns")
        x_scroll = ttk.Scrollbar(tree_wrap, orient="horizontal", command=self.mcp_tree.xview)
        x_scroll.grid(row=1, column=0, sticky="ew")
        self.mcp_tree.configure(yscrollcommand=y_scroll.set, xscrollcommand=x_scroll.set)

        actions = tk.Frame(list_card, bg=PALETTE["card_bg"])
        actions.grid(row=2, column=0, sticky="ew", pady=(14, 0))
        for column in range(3):
            actions.columnconfigure(column, weight=1)
        make_button(actions, text="新增 MCP", variant="primary", command=self.add_mcp_server).grid(row=0, column=0, sticky="ew", padx=(0, 8), pady=(0, 8))
        make_button(actions, text="修改 MCP", variant="secondary", command=self.edit_mcp_server).grid(row=0, column=1, sticky="ew", padx=(0, 8), pady=(0, 8))
        make_button(actions, text="删除 MCP", variant="danger", command=self.delete_mcp_server).grid(row=0, column=2, sticky="ew", pady=(0, 8))
        make_button(actions, text="保存 MCP", variant="primary", command=self.save_mcp_servers).grid(row=1, column=0, sticky="ew", padx=(0, 8))
        make_button(actions, text="恢复默认", variant="secondary", command=self.restore_default_mcp_servers).grid(row=1, column=1, sticky="ew", padx=(0, 8))
        make_button(actions, text="清空禁用", variant="danger", command=self.disable_global_mcp_from_page).grid(row=1, column=2, sticky="ew")

        detail = self._make_card(content)
        detail.grid(row=0, column=1, sticky="nsew")
        detail.columnconfigure(0, weight=1)
        detail.rowconfigure(3, weight=1)
        tk.Label(detail, textvariable=self.mcp_selected_name_var, bg=PALETTE["card_bg"], fg=PALETTE["text"], font=self.hero_font).grid(row=0, column=0, sticky="w")
        tk.Label(
            detail,
            text=f"在 command、args、cwd、env 或高级字段里写 {PROJECT_ROOT_PLACEHOLDER}，生成项目配置时会替换为项目目录。",
            bg=PALETTE["card_bg"],
            fg=PALETTE["muted"],
            font=self.small_font,
            justify="left",
            wraplength=420,
        ).grid(row=1, column=0, sticky="w", pady=(6, 10))
        tk.Label(detail, textvariable=self.mcp_selected_summary_var, bg=PALETTE["card_bg"], fg=PALETTE["text"], font=self.body_font, justify="left", wraplength=420).grid(row=2, column=0, sticky="w")

        preview_wrap = tk.Frame(detail, bg=PALETTE["card_bg"])
        preview_wrap.grid(row=3, column=0, sticky="nsew", pady=(12, 0))
        preview_wrap.columnconfigure(0, weight=1)
        preview_wrap.rowconfigure(0, weight=1)
        self.mcp_preview_text = tk.Text(
            preview_wrap,
            wrap="none",
            relief="solid",
            borderwidth=1,
            highlightthickness=0,
            font=("Consolas", 10),
            bg="#FBFDFE",
            fg=PALETTE["text"],
        )
        self.mcp_preview_text.grid(row=0, column=0, sticky="nsew")
        preview_y = ttk.Scrollbar(preview_wrap, orient="vertical", command=self.mcp_preview_text.yview)
        preview_y.grid(row=0, column=1, sticky="ns")
        preview_x = ttk.Scrollbar(preview_wrap, orient="horizontal", command=self.mcp_preview_text.xview)
        preview_x.grid(row=1, column=0, sticky="ew")
        self.mcp_preview_text.configure(yscrollcommand=preview_y.set, xscrollcommand=preview_x.set)

    def _build_skills_tab(self, parent: tk.Misc) -> None:
        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(0, weight=1)
        card = self._make_card(parent)
        card.grid(row=0, column=0, sticky="nsew")
        card.columnconfigure(0, weight=1)
        card.rowconfigure(1, weight=1)

        tk.Label(card, text="Skills 管理", bg=PALETTE["card_bg"], fg=PALETTE["text"], font=self.hero_font).grid(row=0, column=0, sticky="w")
        tk.Label(card, textvariable=self.skills_hint_var, bg=PALETTE["card_bg"], fg=PALETTE["muted"], font=self.small_font).grid(row=0, column=0, sticky="e")

        notebook = ttk.Notebook(card)
        notebook.grid(row=1, column=0, sticky="nsew", pady=(14, 0))
        market_tab = tk.Frame(notebook, bg=PALETTE["card_bg"], padx=10, pady=10)
        repo_tab = tk.Frame(notebook, bg=PALETTE["card_bg"], padx=10, pady=10)
        local_tab = tk.Frame(notebook, bg=PALETTE["card_bg"], padx=10, pady=10)
        project_tab = tk.Frame(notebook, bg=PALETTE["card_bg"], padx=10, pady=10)
        notebook.add(market_tab, text="技能市场")
        notebook.add(repo_tab, text="仓库源管理")
        notebook.add(local_tab, text="本地Skills")
        notebook.add(project_tab, text="项目Skills")

        self._build_skill_repos_panel(market_tab)
        self._build_skill_repo_source_panel(repo_tab)
        self._build_local_skills_panel(local_tab)
        self._build_project_skills_panel(project_tab)

    def _build_skill_repos_panel(self, parent: tk.Misc) -> None:
        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(1, weight=1)
        repo_filter_bar = tk.Frame(parent, bg=PALETTE["card_bg"])
        repo_filter_bar.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        repo_filter_bar.columnconfigure(1, weight=1)
        tk.Label(repo_filter_bar, text="筛选 Skill", bg=PALETTE["card_bg"], fg=PALETTE["muted"], font=self.small_font).grid(row=0, column=0, sticky="w", padx=(0, 8))
        self.skill_market_filter_entry = ttk.Entry(repo_filter_bar, textvariable=self.skill_market_filter_var)
        self.skill_market_filter_entry.grid(row=0, column=1, sticky="ew", padx=(0, 8))
        make_button(repo_filter_bar, text="清除", variant="secondary", command=self.clear_skill_market_filter).grid(row=0, column=2, sticky="e")
        self.skill_market_filter_var.trace_add("write", lambda *_args: self.apply_skill_market_filter())
        make_button(repo_filter_bar, text="刷新市场", variant="secondary", command=self.refresh_skill_market_now).grid(row=0, column=3, sticky="e", padx=(8, 0))
        tk.Label(parent, textvariable=self.skill_repo_preview_var, bg=PALETTE["card_bg"], fg=PALETTE["muted"], font=self.small_font).grid(row=2, column=0, sticky="w", pady=(8, 0))

        market_wrap = tk.Frame(parent, bg=PALETTE["card_bg"])
        market_wrap.grid(row=1, column=0, sticky="nsew")
        market_wrap.columnconfigure(0, weight=1)
        market_wrap.rowconfigure(0, weight=1)
        self.skill_market_canvas = tk.Canvas(market_wrap, bg=PALETTE["card_bg"], highlightthickness=0)
        self.skill_market_canvas.grid(row=0, column=0, sticky="nsew")
        market_scroll = ttk.Scrollbar(market_wrap, orient="vertical", command=self.skill_market_canvas.yview)
        market_scroll.grid(row=0, column=1, sticky="ns")
        self.skill_market_canvas.configure(yscrollcommand=market_scroll.set)
        self.skill_market_frame = tk.Frame(self.skill_market_canvas, bg=PALETTE["card_bg"])
        self.skill_market_window = self.skill_market_canvas.create_window((0, 0), window=self.skill_market_frame, anchor="nw")
        self.skill_market_frame.bind(
            "<Configure>",
            lambda _event: self.skill_market_canvas.configure(scrollregion=self.skill_market_canvas.bbox("all")),
        )
        self.skill_market_canvas.bind("<Configure>", self._layout_skill_market_cards)

    def _build_skill_repo_source_panel(self, parent: tk.Misc) -> None:
        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(2, weight=1)
        tk.Label(parent, text="仓库源管理", bg=PALETTE["card_bg"], fg=PALETTE["text"], font=self.section_font).grid(row=0, column=0, sticky="w")

        toolbar = tk.Frame(parent, bg=PALETTE["card_bg"])
        toolbar.grid(row=1, column=0, sticky="ew", pady=(8, 8))
        toolbar.columnconfigure(1, weight=1)
        tk.Label(toolbar, text="筛选仓库", bg=PALETTE["card_bg"], fg=PALETTE["muted"], font=self.small_font).grid(row=0, column=0, sticky="w", padx=(0, 8))
        self.skill_repo_filter_entry = ttk.Entry(toolbar, textvariable=self.skill_repo_filter_var)
        self.skill_repo_filter_entry.grid(row=0, column=1, sticky="ew", padx=(0, 8))
        make_button(toolbar, text="清除", variant="secondary", command=self.clear_skill_repo_filter).grid(row=0, column=2, sticky="e", padx=(0, 8))
        make_button(toolbar, text="新增仓库", variant="primary", command=self.add_skill_market_repo).grid(row=0, column=3, sticky="e", padx=(0, 8))
        make_button(toolbar, text="检查更新", variant="secondary", command=self.check_selected_skill_repo_update).grid(row=0, column=4, sticky="e")
        self.skill_repo_filter_var.trace_add("write", lambda *_args: self.apply_skill_repo_filter())

        repo_wrap = tk.Frame(parent, bg=PALETTE["card_bg"])
        repo_wrap.grid(row=2, column=0, sticky="nsew")
        repo_wrap.columnconfigure(0, weight=1)
        repo_wrap.rowconfigure(0, weight=1)
        self.skill_repo_tree = ttk.Treeview(repo_wrap, columns=("url", "branch", "commit", "auto"), show="headings")
        self.skill_repo_tree.heading("url", text="GitHub 仓库", anchor="w")
        self.skill_repo_tree.heading("branch", text="Ref", anchor="center")
        self.skill_repo_tree.heading("commit", text="最近提交", anchor="center")
        self.skill_repo_tree.heading("auto", text="自动更新", anchor="center")
        self.skill_repo_tree.column("url", width=300, anchor="w")
        self.skill_repo_tree.column("branch", width=90, anchor="center", stretch=False)
        self.skill_repo_tree.column("commit", width=110, anchor="center", stretch=False)
        self.skill_repo_tree.column("auto", width=80, anchor="center", stretch=False)
        self.skill_repo_tree.grid(row=0, column=0, sticky="nsew")
        self.skill_repo_tree.bind("<<TreeviewSelect>>", lambda _event: self._refresh_skill_repo_detail())
        repo_scroll = ttk.Scrollbar(repo_wrap, orient="vertical", command=self.skill_repo_tree.yview)
        repo_scroll.grid(row=0, column=1, sticky="ns")
        self.skill_repo_tree.configure(yscrollcommand=repo_scroll.set)

        repo_actions = tk.Frame(parent, bg=PALETTE["card_bg"])
        repo_actions.grid(row=3, column=0, sticky="ew", pady=(10, 0))
        repo_actions.columnconfigure(0, weight=1)
        tk.Label(repo_actions, textvariable=self.skill_repo_detail_var, bg=PALETTE["card_bg"], fg=PALETTE["muted"], font=self.small_font).grid(row=0, column=0, sticky="w", padx=(0, 8))
        make_button(repo_actions, text="编辑仓库", variant="secondary", command=self.edit_skill_market_repo).grid(row=0, column=1, sticky="e", padx=(0, 8))
        make_button(repo_actions, text="删除仓库", variant="danger", command=self.delete_skill_market_repo).grid(row=0, column=2, sticky="e", padx=(0, 8))
        make_button(repo_actions, text="安装到组", variant="secondary", command=self.install_selected_skill_repo_to_group).grid(row=0, column=3, sticky="e")

    def _build_local_skills_panel(self, parent: tk.Misc) -> None:
        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(0, weight=1)
        wrap = tk.Frame(parent, bg=PALETTE["card_bg"])
        wrap.grid(row=0, column=0, sticky="nsew")
        wrap.columnconfigure(0, weight=1)
        wrap.rowconfigure(0, weight=1)
        self.skill_group_tree = ttk.Treeview(wrap, columns=("name", "count", "description"), show="headings")
        self.skill_group_tree.heading("name", text="组名", anchor="w")
        self.skill_group_tree.heading("count", text="Skills", anchor="center")
        self.skill_group_tree.heading("description", text="描述", anchor="w")
        self.skill_group_tree.column("name", width=180, anchor="w")
        self.skill_group_tree.column("count", width=80, anchor="center", stretch=False)
        self.skill_group_tree.column("description", width=420, anchor="w")
        self.skill_group_tree.grid(row=0, column=0, sticky="nsew")
        self.skill_group_tree.bind("<<TreeviewSelect>>", lambda _event: self._refresh_skill_group_detail())
        group_scroll = ttk.Scrollbar(wrap, orient="vertical", command=self.skill_group_tree.yview)
        group_scroll.grid(row=0, column=1, sticky="ns")
        self.skill_group_tree.configure(yscrollcommand=group_scroll.set)

        actions = tk.Frame(parent, bg=PALETTE["card_bg"])
        actions.grid(row=1, column=0, sticky="ew", pady=(10, 0))
        for column in range(6):
            actions.columnconfigure(column, weight=1)
        make_button(actions, text="新增组", variant="primary", command=self.add_skill_group).grid(row=0, column=0, sticky="ew", padx=(0, 8))
        make_button(actions, text="编辑组", variant="secondary", command=self.edit_skill_group).grid(row=0, column=1, sticky="ew", padx=(0, 8))
        make_button(actions, text="删除组", variant="danger", command=self.delete_skill_group).grid(row=0, column=2, sticky="ew", padx=(0, 8))
        make_button(actions, text="刷新", variant="secondary", command=self.refresh_skills_tab).grid(row=0, column=3, sticky="ew", padx=(0, 8))
        tk.Label(actions, textvariable=self.skill_group_detail_var, bg=PALETTE["card_bg"], fg=PALETTE["muted"], font=self.small_font).grid(row=0, column=4, columnspan=2, sticky="w")

    def _build_project_skills_panel(self, parent: tk.Misc) -> None:
        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(0, weight=1)
        wrap = tk.Frame(parent, bg=PALETTE["card_bg"])
        wrap.grid(row=0, column=0, sticky="nsew")
        wrap.columnconfigure(0, weight=1)
        wrap.rowconfigure(0, weight=1)
        self.skill_project_tree = ttk.Treeview(wrap, columns=("name", "groups", "skills"), show="headings")
        self.skill_project_tree.heading("name", text="项目", anchor="w")
        self.skill_project_tree.heading("groups", text="关联组", anchor="w")
        self.skill_project_tree.heading("skills", text="展开 Skills", anchor="w")
        self.skill_project_tree.column("name", width=180, anchor="w")
        self.skill_project_tree.column("groups", width=260, anchor="w")
        self.skill_project_tree.column("skills", width=360, anchor="w")
        self.skill_project_tree.grid(row=0, column=0, sticky="nsew")
        self.skill_project_tree.bind("<<TreeviewSelect>>", lambda _event: self._refresh_skill_project_detail())
        project_scroll = ttk.Scrollbar(wrap, orient="vertical", command=self.skill_project_tree.yview)
        project_scroll.grid(row=0, column=1, sticky="ns")
        self.skill_project_tree.configure(yscrollcommand=project_scroll.set)

        actions = tk.Frame(parent, bg=PALETTE["card_bg"])
        actions.grid(row=1, column=0, sticky="ew", pady=(10, 0))
        actions.columnconfigure(0, weight=1)
        actions.columnconfigure(1, weight=1)
        actions.columnconfigure(2, weight=3)
        make_button(actions, text="编辑项目关联", variant="primary", command=self.edit_project).grid(row=0, column=0, sticky="ew", padx=(0, 8))
        make_button(actions, text="刷新", variant="secondary", command=self.refresh_skills_tab).grid(row=0, column=1, sticky="ew", padx=(0, 8))
        tk.Label(actions, textvariable=self.skill_project_detail_var, bg=PALETTE["card_bg"], fg=PALETTE["muted"], font=self.small_font).grid(row=0, column=2, sticky="w")

    def _build_docs_tab(self, parent: tk.Misc) -> None:
        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(0, weight=1)

        card = self._make_card(parent)
        card.grid(row=0, column=0, sticky="nsew")
        card.columnconfigure(0, weight=1)
        card.rowconfigure(2, weight=1)

        header = tk.Frame(card, bg=PALETTE["card_bg"])
        header.grid(row=0, column=0, sticky="ew")
        header.columnconfigure(0, weight=1)
        tk.Label(header, text="文档配置", bg=PALETTE["card_bg"], fg=PALETTE["text"], font=self.hero_font).grid(row=0, column=0, sticky="w")
        tk.Label(header, textvariable=self.docs_hint_var, bg=PALETTE["card_bg"], fg=PALETTE["muted"], font=self.small_font).grid(row=1, column=0, sticky="w", pady=(4, 0))

        actions = tk.Frame(card, bg=PALETTE["card_bg"])
        actions.grid(row=1, column=0, sticky="e", pady=(0, 10))
        make_button(actions, text="保存文档", variant="primary", command=self.save_agents_doc).grid(row=0, column=0, padx=(0, 8))
        make_button(actions, text="恢复默认", variant="secondary", command=self.restore_default_agents_doc).grid(row=0, column=1)

        editor_wrap = tk.Frame(card, bg=PALETTE["card_bg"])
        editor_wrap.grid(row=2, column=0, sticky="nsew")
        editor_wrap.columnconfigure(0, weight=1)
        editor_wrap.rowconfigure(0, weight=1)
        self.agents_doc_editor = tk.Text(
            editor_wrap,
            wrap="word",
            relief="solid",
            borderwidth=1,
            highlightthickness=0,
            font=("Consolas", 10),
            bg="#FBFDFE",
            fg=PALETTE["text"],
            undo=True,
        )
        self.agents_doc_editor.grid(row=0, column=0, sticky="nsew")
        self.agents_doc_editor.insert("1.0", self.agents_doc_text)
        doc_scroll = ttk.Scrollbar(editor_wrap, orient="vertical", command=self.agents_doc_editor.yview)
        doc_scroll.grid(row=0, column=1, sticky="ns")
        self.agents_doc_editor.configure(yscrollcommand=doc_scroll.set)

    def _build_settings_tab(self, parent: tk.Misc) -> None:
        parent.columnconfigure(0, weight=1)
        parent.columnconfigure(1, weight=1)
        parent.rowconfigure(1, weight=1)

        settings_card = self._make_card(parent)
        settings_card.grid(row=0, column=0, sticky="nsew", padx=(0, 10), pady=(0, 10))
        settings_card.columnconfigure(1, weight=1)

        tk.Label(settings_card, text="设置", bg=PALETTE["card_bg"], fg=PALETTE["text"], font=self.hero_font).grid(row=0, column=0, columnspan=3, sticky="w")
        tk.Label(settings_card, textvariable=self.settings_hint_var, bg=PALETTE["card_bg"], fg=PALETTE["muted"], font=self.small_font).grid(
            row=1,
            column=0,
            columnspan=3,
            sticky="w",
            pady=(4, 12),
        )
        tk.Label(settings_card, text="模型批量测试同时请求数", bg=PALETTE["card_bg"], fg=PALETTE["muted"], font=self.small_font).grid(
            row=2,
            column=0,
            sticky="w",
            padx=(0, 14),
        )
        tk.Spinbox(
            settings_card,
            from_=MODEL_BATCH_CONCURRENCY_MIN,
            to=MODEL_BATCH_CONCURRENCY_MAX,
            textvariable=self.model_batch_concurrency_var,
            width=8,
            font=self.body_font,
            relief="solid",
            borderwidth=1,
        ).grid(row=2, column=1, sticky="w")
        tk.Label(settings_card, text="号池检测间隔（分钟）", bg=PALETTE["card_bg"], fg=PALETTE["muted"], font=self.small_font).grid(
            row=3,
            column=0,
            sticky="w",
            padx=(0, 14),
            pady=(10, 0),
        )
        tk.Spinbox(
            settings_card,
            from_=1,
            to=1440,
            textvariable=self.account_pool_recovery_interval_var,
            width=8,
            font=self.body_font,
            relief="solid",
            borderwidth=1,
        ).grid(row=3, column=1, sticky="w", pady=(10, 0))
        tk.Label(settings_card, text="软件更新", bg=PALETTE["card_bg"], fg=PALETTE["muted"], font=self.small_font).grid(
            row=4,
            column=0,
            sticky="w",
            padx=(0, 14),
            pady=(10, 0),
        )
        tk.Label(settings_card, textvariable=self.software_update_status_var, bg=PALETTE["card_bg"], fg=PALETTE["muted"], font=self.small_font).grid(
            row=4,
            column=1,
            sticky="w",
            pady=(10, 0),
        )
        make_button(settings_card, text="检查软件更新", variant="secondary", command=self.check_software_update_now).grid(row=4, column=2, sticky="e", pady=(10, 0))
        ttk.Checkbutton(
            settings_card,
            text="启用仓库同步轮询",
            variable=self.hot_update_enabled_var,
        ).grid(row=5, column=0, sticky="w", pady=(10, 0))
        tk.Spinbox(
            settings_card,
            from_=5,
            to=1440,
            textvariable=self.hot_update_interval_var,
            width=8,
            font=self.body_font,
            relief="solid",
            borderwidth=1,
        ).grid(row=5, column=1, sticky="w", pady=(10, 0))
        make_button(settings_card, text="检查仓库同步", variant="secondary", command=self.check_hot_updates_now).grid(row=5, column=2, sticky="e", pady=(10, 0))
        tk.Label(settings_card, textvariable=self.hot_update_status_var, bg=PALETTE["card_bg"], fg=PALETTE["muted"], font=self.small_font).grid(
            row=6,
            column=0,
            columnspan=2,
            sticky="w",
            pady=(8, 0),
        )
        make_button(settings_card, text="保存设置", variant="primary", command=self.save_settings).grid(row=6, column=2, sticky="e", pady=(8, 0))

        info_card = self._make_card(parent)
        info_card.grid(row=0, column=1, sticky="nsew", pady=(0, 10))
        info_card.columnconfigure(1, weight=1)
        info_card.columnconfigure(3, weight=1)
        tk.Label(info_card, text="版本信息 / 系统信息", bg=PALETTE["card_bg"], fg=PALETTE["text"], font=self.hero_font).grid(row=0, column=0, columnspan=4, sticky="w")
        self._create_dual_info_row(info_card, 1, "应用版本", self.settings_version_var, "Python", self.settings_python_var)
        self._create_dual_info_row(info_card, 2, "Tk/Tcl", self.settings_tk_var, "ttkbootstrap", self.settings_ttkbootstrap_var)
        self._create_info_row(info_card, 3, "配置库", self.settings_storage_path_var, wraplength=560)
        self._create_info_row(info_card, 4, "Codex config", self.settings_codex_config_path_var, wraplength=560)
        self._create_info_row(info_card, 5, "Codex auth", self.settings_codex_auth_path_var, wraplength=560)
        self._create_info_row(info_card, 6, "当前工作目录", self.settings_project_root_var, wraplength=560)
        self._create_info_row(info_card, 7, "平台", self.settings_platform_var, wraplength=560)

        hot_update_log_card = self._make_card(parent)
        hot_update_log_card.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(0, 10))
        hot_update_log_card.columnconfigure(0, weight=1)
        tk.Label(hot_update_log_card, text="最近更新与同步记录", bg=PALETTE["card_bg"], fg=PALETTE["text"], font=self.section_font).grid(row=0, column=0, sticky="w")
        hot_update_log_wrap = tk.Frame(hot_update_log_card, bg=PALETTE["card_bg"])
        hot_update_log_wrap.grid(row=1, column=0, sticky="ew", pady=(8, 0))
        hot_update_log_wrap.columnconfigure(0, weight=1)
        self.hot_update_log_text = tk.Text(
            hot_update_log_wrap,
            height=6,
            wrap="word",
            relief="solid",
            borderwidth=1,
            highlightthickness=0,
            font=self.small_font,
            bg="#FBFDFE",
            fg=PALETTE["text"],
            state="disabled",
        )
        self.hot_update_log_text.grid(row=0, column=0, sticky="ew")
        hot_update_log_scroll = ttk.Scrollbar(hot_update_log_wrap, orient="vertical", command=self.hot_update_log_text.yview)
        hot_update_log_scroll.grid(row=0, column=1, sticky="ns")
        self.hot_update_log_text.configure(yscrollcommand=hot_update_log_scroll.set)

    def _build_test_tab(self, parent: tk.Misc) -> None:
        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(0, weight=1)

        content = tk.Frame(parent, bg=PALETTE["panel_bg"])
        content.grid(row=0, column=0, sticky="nsew")
        content.columnconfigure(0, weight=0)
        content.columnconfigure(1, weight=1)
        content.rowconfigure(0, weight=1)
        self.test_layout_content = content
        content.bind("<Configure>", self._sync_test_layout_widths)

        left = self._make_card(content)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
        left.grid_propagate(False)
        left.columnconfigure(0, weight=1)
        left.rowconfigure(1, weight=1)
        self.test_api_panel = left
        test_api_header = tk.Frame(left, bg=PALETTE["card_bg"])
        test_api_header.grid(row=0, column=0, sticky="ew")
        test_api_header.columnconfigure(0, weight=1)
        tk.Label(test_api_header, text="测试 API 选择", bg=PALETTE["card_bg"], fg=PALETTE["text"], font=self.hero_font).grid(row=0, column=0, sticky="w")
        make_button(test_api_header, textvariable=self.hide_error_button_var, variant="secondary", command=self._on_profile_filter_changed).grid(row=0, column=1, sticky="e")

        api_tree_wrap = tk.Frame(left, bg=PALETTE["card_bg"])
        api_tree_wrap.grid(row=1, column=0, sticky="nsew", pady=(12, 0))
        api_tree_wrap.columnconfigure(0, weight=1)
        api_tree_wrap.rowconfigure(0, weight=1)

        self.test_api_tree = ttk.Treeview(api_tree_wrap, columns=("name", "health"), show="headings")
        self.test_api_tree.heading("name", text="API")
        self.test_api_tree.heading("health", text="状态")
        self.test_api_tree.column("name", width=165, minwidth=120, anchor="w")
        self.test_api_tree.column("health", width=78, minwidth=64, anchor="center")
        self.test_api_tree.grid(row=0, column=0, sticky="nsew")
        self.test_api_tree.bind("<<TreeviewSelect>>", self._on_test_api_selection_changed)

        api_scroll = ttk.Scrollbar(api_tree_wrap, orient="vertical", command=self.test_api_tree.yview)
        api_scroll.grid(row=0, column=1, sticky="ns")
        self.test_api_tree.configure(yscrollcommand=api_scroll.set)

        right = tk.Frame(content, bg=PALETTE["panel_bg"])
        right.grid(row=0, column=1, sticky="nsew")
        right.columnconfigure(0, weight=1)
        right.rowconfigure(0, weight=0)
        right.rowconfigure(1, weight=1)

        detail = self._make_card(right)
        detail.grid(row=0, column=0, sticky="nsew", pady=(0, 10))
        detail.columnconfigure(1, weight=1)
        detail.columnconfigure(3, weight=1)

        header = tk.Frame(detail, bg=PALETTE["card_bg"])
        header.grid(row=0, column=0, columnspan=4, sticky="ew")
        header.columnconfigure(0, weight=1)
        tk.Label(header, text="健康检测", bg=PALETTE["card_bg"], fg=PALETTE["text"], font=self.hero_font).grid(row=0, column=0, sticky="w")
        self.test_detail_badge = make_status_badge(header, textvariable=self.test_detail_health_var)
        self.test_detail_badge.grid(row=0, column=1, sticky="e", padx=(10, 8))
        self.model_batch_button = make_button(header, text="测试选中 API 模型", variant="primary", command=self.test_selected_api_models)
        self.model_batch_button.grid(row=0, column=2, sticky="e")
        tk.Label(header, textvariable=self.test_selected_name_var, bg=PALETTE["card_bg"], fg=PALETTE["muted"], font=self.small_font).grid(row=1, column=0, columnspan=3, sticky="w", pady=(4, 0))

        tk.Label(detail, text="健康状态判定", bg=PALETTE["card_bg"], fg=PALETTE["muted"], font=self.small_font).grid(row=1, column=0, sticky="nw", padx=(0, 14), pady=(14, 4))
        override_row = tk.Frame(detail, bg=PALETTE["card_bg"])
        override_row.grid(row=1, column=1, sticky="ew", pady=(14, 4))
        self.health_override_combo = ttk.Combobox(override_row, textvariable=self.health_override_var, state="readonly", values=tuple(HEALTH_OVERRIDE_DISPLAY.values()), width=22)
        self.health_override_combo.grid(row=0, column=0, sticky="w")
        self.health_override_combo.bind("<<ComboboxSelected>>", self._on_health_override_changed)
        tk.Label(override_row, textvariable=self.health_override_note_var, bg=PALETTE["card_bg"], fg=PALETTE["muted"], font=self.small_font, justify="left", wraplength=320).grid(row=1, column=0, sticky="w", pady=(6, 0))

        self._create_dual_info_row(detail, 2, "提供方", self.test_detail_provider_var, "默认模型", self.test_detail_model_var)
        self._create_dual_info_row(detail, 3, "API Key", self.test_detail_key_var, "Wire API", self.test_detail_wire_var)
        self._create_dual_info_row(detail, 4, "最近检测", self.test_detail_checked_var, "最近 endpoint", self.test_detail_endpoint_var)
        self._create_info_row(detail, 5, "API 地址", self.test_detail_api_var, wraplength=520)
        self._create_info_row(detail, 6, "结果详情", self.test_detail_result_var, wraplength=520)
        self._create_success_models_row(detail, 7)
        self._create_info_row(detail, 8, "备注", self.test_detail_notes_var, wraplength=520)

        chat = self._make_card(right)
        chat.grid(row=1, column=0, sticky="nsew")
        chat.columnconfigure(0, weight=1)
        chat.rowconfigure(2, weight=1)

        chat_header = tk.Frame(chat, bg=PALETTE["card_bg"])
        chat_header.grid(row=0, column=0, sticky="ew")
        chat_header.columnconfigure(0, weight=1)
        tk.Label(chat_header, text="聊天测试", bg=PALETTE["card_bg"], fg=PALETTE["text"], font=self.hero_font).grid(row=0, column=0, sticky="w")
        tk.Label(chat_header, text="模型、接口标准和请求体在聊天设置里临时覆盖。", bg=PALETTE["card_bg"], fg=PALETTE["muted"], font=self.small_font).grid(row=1, column=0, sticky="w", pady=(4, 0))
        self.chat_settings_button = make_button(chat_header, text="聊天设置", variant="secondary", command=self.open_chat_settings)
        self.chat_settings_button.grid(row=0, column=1, rowspan=2, sticky="e")

        chat_meta = tk.Frame(chat, bg=PALETTE["card_bg"])
        chat_meta.grid(row=1, column=0, sticky="ew", pady=(12, 10))
        chat_meta.columnconfigure(1, weight=1)
        tk.Label(chat_meta, text="测试配置", bg=PALETTE["card_bg"], fg=PALETTE["muted"], font=self.small_font).grid(row=0, column=0, sticky="w", padx=(0, 12))
        tk.Label(chat_meta, textvariable=self.chat_target_var, bg=PALETTE["card_bg"], fg=PALETTE["text"], font=self.body_font).grid(row=0, column=1, sticky="w")
        tk.Label(chat_meta, text="当前设置", bg=PALETTE["card_bg"], fg=PALETTE["muted"], font=self.small_font).grid(row=1, column=0, sticky="w", padx=(0, 12), pady=(6, 0))
        tk.Label(chat_meta, textvariable=self.chat_settings_summary_var, bg=PALETTE["card_bg"], fg=PALETTE["text"], font=self.body_font, justify="left", wraplength=620).grid(row=1, column=1, sticky="w", pady=(6, 0))

        history_wrap = tk.Frame(chat, bg=PALETTE["card_bg"])
        history_wrap.grid(row=2, column=0, sticky="nsew")
        history_wrap.columnconfigure(0, weight=1)
        history_wrap.rowconfigure(0, weight=1)
        self.chat_history = tk.Text(history_wrap, wrap="word", relief="solid", borderwidth=1, highlightthickness=0, font=self.body_font, bg="#FBFDFE", fg=PALETTE["text"], state="disabled")
        self.chat_history.grid(row=0, column=0, sticky="nsew")
        chat_scroll = ttk.Scrollbar(history_wrap, orient="vertical", command=self.chat_history.yview)
        chat_scroll.grid(row=0, column=1, sticky="ns")
        self.chat_history.configure(yscrollcommand=chat_scroll.set)

        input_wrap = tk.Frame(chat, bg=PALETTE["card_bg"])
        input_wrap.grid(row=3, column=0, sticky="ew", pady=(12, 0))
        input_wrap.columnconfigure(0, weight=1)
        self.chat_input = tk.Text(input_wrap, height=4, wrap="word", relief="solid", borderwidth=1, highlightthickness=0, font=self.body_font, fg=PALETTE["text"])
        self.chat_input.grid(row=0, column=0, sticky="ew")
        buttons = tk.Frame(input_wrap, bg=PALETTE["card_bg"])
        buttons.grid(row=0, column=1, sticky="ns", padx=(10, 0))
        self.chat_send_button = make_button(buttons, text="发送测试", variant="primary", command=self.send_chat_message)
        self.chat_send_button.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        make_button(buttons, text="清空记录", variant="secondary", command=self.clear_chat_history).grid(row=1, column=0, sticky="ew")
        content.after_idle(self._sync_test_layout_widths)

    def _sync_test_layout_widths(self, event: tk.Event | None = None) -> None:
        content = getattr(self, "test_layout_content", None)
        left = getattr(self, "test_api_panel", None)
        if content is None or left is None:
            return
        width = event.width if event is not None else content.winfo_width()
        if width <= 1:
            return
        left_width = max(280, int((width - 10) * 0.25))
        if getattr(self, "_test_layout_left_width", None) == left_width:
            return
        self._test_layout_left_width = left_width
        left.configure(width=left_width)

    def _create_info_row(self, parent: tk.Misc, row: int, label: str, variable: tk.StringVar, wraplength: int = 320) -> None:
        tk.Label(parent, text=label, bg=PALETTE["card_bg"], fg=PALETTE["muted"], font=self.small_font).grid(row=row, column=0, sticky="nw", padx=(0, 14), pady=4)
        tk.Label(parent, textvariable=variable, bg=PALETTE["card_bg"], fg=PALETTE["text"], font=self.body_font, justify="left", wraplength=wraplength).grid(row=row, column=1, columnspan=3, sticky="w", pady=4)

    def _create_project_action_group(
        self,
        parent: tk.Misc,
        row: int,
        label: str,
        actions: tuple[tuple[str, str, object], ...],
    ) -> None:
        group = tk.Frame(parent, bg=PALETTE["card_bg"])
        group.grid(row=row, column=0, sticky="ew", pady=(0, 10))
        group.columnconfigure(0, weight=1)
        tk.Label(group, text=label, bg=PALETTE["card_bg"], fg=PALETTE["muted"], font=self.small_font).grid(row=0, column=0, sticky="w", pady=(0, 6))

        buttons = tk.Frame(group, bg=PALETTE["card_bg"])
        buttons.grid(row=1, column=0, sticky="ew")
        for column in range(len(actions)):
            buttons.columnconfigure(column, weight=1)
        for column, (text, variant, command) in enumerate(actions):
            padx = (0, 8) if column < len(actions) - 1 else 0
            make_button(buttons, text=text, variant=variant, command=command).grid(row=0, column=column, sticky="ew", padx=padx)

    def _create_success_models_row(self, parent: tk.Misc, row: int) -> None:
        tk.Label(parent, text="成功模型", bg=PALETTE["card_bg"], fg=PALETTE["muted"], font=self.small_font).grid(row=row, column=0, sticky="nw", padx=(0, 14), pady=4)
        value_row = tk.Frame(parent, bg=PALETTE["card_bg"])
        value_row.grid(row=row, column=1, columnspan=3, sticky="ew", pady=4)
        value_row.columnconfigure(0, weight=1)
        tk.Label(
            value_row,
            textvariable=self.test_detail_success_models_var,
            bg=PALETTE["card_bg"],
            fg=PALETTE["text"],
            font=self.body_font,
            justify="left",
            wraplength=430,
        ).grid(row=0, column=0, sticky="w")
        self.success_models_button = make_button(
            value_row,
            text="查看成功模型",
            variant="secondary",
            command=self.show_success_models,
        )
        self.success_models_button.grid(row=0, column=1, sticky="e", padx=(10, 0))
        self.success_models_button.state(["disabled"])

    def _create_link_info_row(self, parent: tk.Misc, row: int, label: str, variable: tk.StringVar, command, wraplength: int = 320) -> tk.Label:
        tk.Label(parent, text=label, bg=PALETTE["card_bg"], fg=PALETTE["muted"], font=self.small_font).grid(row=row, column=0, sticky="nw", padx=(0, 14), pady=4)
        link = tk.Label(parent, textvariable=variable, bg=PALETTE["card_bg"], fg=PALETTE["muted"], font=self.body_font, justify="left", wraplength=wraplength)
        link.grid(row=row, column=1, columnspan=3, sticky="w", pady=4)
        link.bind("<Button-1>", lambda _event: command())
        return link

    def _create_dual_info_row(
        self,
        parent: tk.Misc,
        row: int,
        left_label: str,
        left_var: tk.StringVar,
        right_label: str,
        right_var: tk.StringVar,
        wraplength: int = 220,
    ) -> None:
        tk.Label(parent, text=left_label, bg=PALETTE["card_bg"], fg=PALETTE["muted"], font=self.small_font).grid(row=row, column=0, sticky="nw", padx=(0, 14), pady=4)
        tk.Label(parent, textvariable=left_var, bg=PALETTE["card_bg"], fg=PALETTE["text"], font=self.body_font, justify="left", wraplength=wraplength).grid(row=row, column=1, sticky="w", pady=4)
        tk.Label(parent, text=right_label, bg=PALETTE["card_bg"], fg=PALETTE["muted"], font=self.small_font).grid(row=row, column=2, sticky="nw", padx=(16, 14), pady=4)
        tk.Label(parent, textvariable=right_var, bg=PALETTE["card_bg"], fg=PALETTE["text"], font=self.body_font, justify="left", wraplength=wraplength).grid(row=row, column=3, sticky="w", pady=4)

    def _healthy_profiles(self) -> list[Profile]:
        healthy = [profile for profile in self.profiles if profile.effective_health_status == "healthy"]
        return healthy or list(self.profiles)

    def _profile_by_id(self, profile_id: str | None) -> Profile | None:
        return next((item for item in self.profiles if item.id == profile_id), None)

    def _profile_key_summary(self, profile: Profile) -> str:
        return profile_key_summary(profile)

    def _profile_model_summary(self, profile: Profile) -> str:
        return profile_model_summary(profile)

    def _profile_library_model_summary(self, profile: Profile) -> str:
        return profile_library_model_summary(profile, self.library_profile_view)

    def _profiles_for_global_target(self, target: str) -> list[Profile]:
        if target == VENDOR_CODEX:
            return [profile for profile in self.profiles if profile_supports_codex(profile)]
        if target == VENDOR_CLAUDE:
            return [profile for profile in self.profiles if profile_supports_claude(profile)]
        return []

    def _global_profile_choice_var_for(self, target: str) -> tk.StringVar:
        return self.global_codex_profile_choice_var if target == VENDOR_CODEX else self.global_claude_profile_choice_var

    def _global_profile_combo_for(self, target: str):
        return self.global_codex_profile_combo if target == VENDOR_CODEX else self.global_claude_profile_combo

    def _global_profile_id_for(self, target: str) -> str | None:
        return self.global_codex_profile_id if target == VENDOR_CODEX else self.global_claude_profile_id

    def _set_global_profile_id_for(self, target: str, profile_id: str | None) -> None:
        if target == VENDOR_CODEX:
            self.global_codex_profile_id = profile_id
        else:
            self.global_claude_profile_id = profile_id

    def _profile_from_global_choice(self, target: str) -> Profile | None:
        profiles = self._profiles_for_global_target(target)
        profile = profile_for_choice_index(profiles, self._global_profile_combo_for(target).current())
        if profile is not None:
            return profile
        selected = self._profile_by_id(self._global_profile_id_for(target))
        if selected and selected in profiles:
            return selected
        return None

    def _normalize_global_profile_ids(self) -> None:
        self.global_codex_profile_id = resolve_global_profile_id(
            self.global_codex_profile_id,
            None,
            self.profiles,
            profile_supports_codex,
        )
        self.global_claude_profile_id = resolve_global_profile_id(
            self.global_claude_profile_id,
            None,
            self.profiles,
            profile_supports_claude,
        )

    def _sync_global_profile_choice(self) -> None:
        self._sync_global_profile_target(VENDOR_CODEX)
        self._sync_global_profile_target(VENDOR_CLAUDE)

    def _sync_global_profile_target(self, target: str) -> None:
        if target == VENDOR_CODEX and not hasattr(self, "global_codex_profile_combo"):
            return
        if target == VENDOR_CLAUDE and not hasattr(self, "global_claude_profile_combo"):
            return
        combo = self._global_profile_combo_for(target)
        choice_var = self._global_profile_choice_var_for(target)
        profiles = self._profiles_for_global_target(target)
        profile = self._profile_by_id(self._global_profile_id_for(target))
        display = global_profile_choice_display(profiles, profile)
        combo.configure(values=display.labels, state=display.state)
        if display.selected_index is None:
            choice_var.set("")
            return
        choice_var.set(display.selected_label)
        combo.current(display.selected_index)

    def _project_by_id(self, project_id: str | None) -> ProjectRecord | None:
        return next((item for item in self.projects if item.id == project_id), None)

    def _project_by_dir(self, project_dir: str) -> ProjectRecord | None:
        key = project_dir_key(project_dir)
        return next((item for item in self.projects if project_dir_key(item.project_dir) == key), None)

    def _profile_tree_iid(self, group: str, profile: Profile) -> str:
        return f"{group}:{profile.id}"

    def _profile_id_from_tree_item(self, item_id: str) -> str | None:
        if item_id.startswith("__"):
            return None
        if ":" in item_id:
            return item_id.split(":", 1)[1]
        return item_id

    def _sync_library_scope_tabs(self) -> None:
        for profile_view, tab in self.library_scope_tabs.items():
            if profile_view == self.library_profile_view:
                tab.configure(bg=PALETTE["accent"], fg="#FFFFFF", highlightbackground=PALETTE["accent"])
            else:
                tab.configure(bg=PALETTE["card_bg"], fg=PALETTE["text"], highlightbackground=PALETTE["card_border"])

    def _set_library_profile_view(self, profile_view: str) -> None:
        if profile_view not in LIBRARY_PROFILE_VIEW_VALUES:
            return
        if self.library_profile_view == profile_view:
            self._sync_library_scope_tabs()
            return
        self.library_profile_view = profile_view
        self.refresh_library_tab()

    def _sync_profile_tree_selection(self) -> None:
        if not self.selected_profile_id or not self._profile_by_id(self.selected_profile_id):
            return
        item_id = None
        for profile_view in (
            self.library_profile_view,
            LIBRARY_VIEW_ALL,
            VENDOR_CODEX,
            VENDOR_CLAUDE,
            VENDOR_OTHER,
        ):
            candidate = f"{profile_view}:{self.selected_profile_id}"
            if self.profile_tree.exists(candidate):
                item_id = candidate
                break
        if item_id is None and self.profile_tree.exists(self.selected_profile_id):
            item_id = self.selected_profile_id
        if item_id is None:
            return
        if self.profile_tree.selection() == (item_id,):
            return
        self.suppress_selection_events = True
        try:
            self.profile_tree.selection_set(item_id)
            self.profile_tree.focus(item_id)
        finally:
            self.suppress_selection_events = False

    def _sync_test_tree_selection(self) -> None:
        if not self.selected_profile_id or not self._profile_by_id(self.selected_profile_id):
            return
        if not self.test_api_tree.exists(self.selected_profile_id):
            return
        if self.test_api_tree.selection() == (self.selected_profile_id,):
            return
        self.suppress_selection_events = True
        try:
            self.test_api_tree.selection_set(self.selected_profile_id)
            self.test_api_tree.focus(self.selected_profile_id)
        finally:
            self.suppress_selection_events = False

    def _sync_project_tree_selection(self) -> None:
        if not self.selected_project_id or not self._project_by_id(self.selected_project_id):
            return
        if self.project_tree.selection() == (self.selected_project_id,):
            return
        self.suppress_selection_events = True
        try:
            self.project_tree.selection_set(self.selected_project_id)
            self.project_tree.focus(self.selected_project_id)
            self.project_tree.see(self.selected_project_id)
        finally:
            self.suppress_selection_events = False

    def _sync_proxy_project_selection(self) -> None:
        if not hasattr(self, "proxy_project_tree"):
            return
        if not self.selected_project_id or not self._project_by_id(self.selected_project_id):
            return
        if self.proxy_project_tree.selection() == (self.selected_project_id,):
            return
        if not self.proxy_project_tree.exists(self.selected_project_id):
            return
        self.suppress_selection_events = True
        try:
            self.proxy_project_tree.selection_set(self.selected_project_id)
            self.proxy_project_tree.focus(self.selected_project_id)
            self.proxy_project_tree.see(self.selected_project_id)
        finally:
            self.suppress_selection_events = False

    def _current_status_counts(self) -> tuple[int, int, int, int]:
        return current_status_counts(self.profiles)

    def _mcp_summary(self, raw_toml: str | None) -> str:
        return mcp_summary(raw_toml)

    def _safe_mcp_server_names(self, raw_toml: str | None) -> list[str]:
        return safe_mcp_server_names(raw_toml)

    def _global_mcp_source_toml(self) -> str:
        if self.global_mcp_toml.strip():
            return self.global_mcp_toml
        return load_default_global_mcp_toml()

    def _selected_global_mcp_server_names(self) -> list[str]:
        return resolve_global_mcp_server_names(
            self.global_mcp_server_names,
            opt_out=self.global_mcp_opt_out,
            available_names=self._safe_mcp_server_names(self._global_mcp_source_toml()),
        )

    def _effective_global_mcp_toml(self) -> str:
        if self.global_mcp_opt_out:
            return ""
        source_toml = self._global_mcp_source_toml()
        if self.global_mcp_server_names is None:
            return source_toml
        return self.project_template_service.select_project_mcp_toml(
            source_toml,
            self._selected_global_mcp_server_names(),
        )

    def _effective_project_mcp_toml(self, project: ProjectRecord | None) -> str:
        if not project:
            return self._effective_global_mcp_toml()
        if project.mcp_server_names is not None:
            return self.project_template_service.select_project_mcp_toml(
                self._effective_global_mcp_toml(),
                project.mcp_server_names,
            )
        if project.mcp_toml.strip():
            return project.mcp_toml
        return self._effective_global_mcp_toml()

    def _available_mcp_server_names(self) -> list[str]:
        return self._safe_mcp_server_names(self._global_mcp_source_toml())

    def _available_skill_sources(self) -> list[SkillSource]:
        return discover_skill_sources(default_skill_roots(self.project_root))

    def _project_mcp_selection_summary(self, project: ProjectRecord | None) -> str:
        return project_mcp_selection_summary(
            project,
            effective_project_mcp_toml=self._effective_project_mcp_toml(project),
            mcp_summary=self._mcp_summary,
        )

    def _project_skill_selection_summary(self, project: ProjectRecord | None) -> str:
        return project_skill_selection_summary(
            project,
            groups=self.skill_groups,
            available_skill_sources=self._available_skill_sources(),
        )

    def _mcp_contains_project_root(self, value) -> bool:
        return mcp_contains_project_root(value)

    def _mcp_list_summary(self, value, limit: int = 36) -> str:
        return mcp_list_summary(value, limit)

    def _mcp_env_summary(self, value, limit: int = 28) -> str:
        return mcp_env_summary(value, limit)

    def _mcp_selected_name(self) -> str | None:
        selection = self.mcp_tree.selection()
        return selection[0] if selection else None

    def _set_text_content(self, widget: tk.Text, content: str, *, disabled: bool = False) -> None:
        widget.configure(state="normal")
        widget.delete("1.0", "end")
        widget.insert("1.0", content)
        if disabled:
            widget.configure(state="disabled")

    def _render_mcp_preview(self, server_name: str | None) -> str:
        return render_mcp_preview(server_name, self.mcp_page_servers)

    def _refresh_mcp_detail(self) -> None:
        detail = mcp_detail_display(self._mcp_selected_name(), self.mcp_page_servers)
        self.mcp_selected_name_var.set(detail.selected_name_text)
        self.mcp_selected_summary_var.set(detail.summary_text)
        self._set_text_content(self.mcp_preview_text, detail.preview_text, disabled=True)

    def _on_profile_selection_changed(self, _event: object | None = None) -> None:
        if self.suppress_selection_events:
            return
        selection = self.profile_tree.selection()
        if selection:
            profile_id = self._profile_id_from_tree_item(selection[0])
            if profile_id is None:
                return
            self.selected_profile_id = profile_id
            self._sync_global_profile_choice()
            self._sync_test_tree_selection()
            self._refresh_library_detail()
            self._refresh_test_detail()

    def _on_global_profile_choice_changed(self, target: str, _event: object | None = None) -> None:
        profile = self._profile_from_global_choice(target)
        if not profile:
            return
        self._set_global_profile_id_for(target, profile.id)
        self.selected_profile_id = profile.id
        self.persist_state()
        self._sync_profile_tree_selection()
        self._sync_test_tree_selection()
        self._refresh_library_detail()
        self._refresh_test_detail()
        self._sync_global_profile_choice()

    def _on_project_selection_changed(self, _event: object | None = None) -> None:
        if self.suppress_selection_events:
            return
        selection = self.project_tree.selection()
        if selection:
            self.selected_project_id = selection[0]
            self._refresh_project_detail()
            self._sync_proxy_project_selection()
            self._refresh_proxy_detail()

    def _on_proxy_project_selection_changed(self, _event: object | None = None) -> None:
        if self.suppress_selection_events:
            return
        selection = self.proxy_project_tree.selection()
        if selection:
            self.selected_project_id = selection[0]
            self._sync_project_tree_selection()
            self._refresh_project_detail()
            self._refresh_proxy_detail()

    def _on_account_pool_selection_changed(self, _event: object | None = None) -> None:
        if self.suppress_selection_events:
            return
        self._refresh_account_pool_detail()

    def _on_mcp_server_selection_changed(self, _event: object | None = None) -> None:
        if self.suppress_selection_events:
            return
        self._refresh_mcp_detail()

    def _on_test_api_selection_changed(self, _event: object | None = None) -> None:
        if self.suppress_selection_events:
            return
        selection = self.test_api_tree.selection()
        if selection:
            self.selected_profile_id = selection[0]
            self._sync_global_profile_choice()
            self._sync_profile_tree_selection()
            self._refresh_library_detail()
            self._refresh_test_detail()

    def _on_profile_filter_changed(self) -> None:
        self.hide_error_profiles = not self.hide_error_profiles
        self.persist_state()
        self.refresh_library_tab()
        self.refresh_test_tab()

    def _health_status_text(self, profile: Profile) -> str:
        return health_status_text(profile, STATUS_TEXT)

    def _health_override_note(self, profile: Profile | None) -> str:
        return health_override_note(profile)
        return "当前跟随自动检测结果，聊天不可用时可以手动修正。"

    def _on_health_override_changed(self, _event=None) -> None:
        if self.updating_health_override:
            return
        profile = self.get_selected_profile()
        if not profile:
            return

        override_value = HEALTH_OVERRIDE_VALUE_BY_DISPLAY.get(self.health_override_var.get(), "")
        profile.manual_health_status = override_value or None
        self.persist_state()
        self.refresh_library_tab()
        self.refresh_test_tab()
        self.refresh_global_tab()
        if profile.manual_health_status:
            self.status_var.set(f"已手动标记 {profile.name} 的健康状态：{STATUS_TEXT.get(profile.manual_health_status, '未检测')}")
        else:
            self.status_var.set(f"已恢复 {profile.name} 的自动健康状态。")

    def refresh_all(self) -> None:
        self.refresh_global_tab()
        self.refresh_library_tab()
        self.refresh_project_tab()
        self.refresh_proxy_tab()
        self.refresh_stats_tab()
        self.refresh_account_pool_tab()
        self.refresh_mcp_tab()
        self.refresh_skills_tab()
        self.refresh_settings_tab()
        self.refresh_test_tab()
        self.status_var.set("已刷新全局配置、配置库、项目配置、路由代理、统计、号池、MCP配置、Skills、文档配置、设置和模型测试。")

    def refresh_stats_tab(self) -> None:
        if not hasattr(self, "stats_day_tree"):
            return
        stats = self.route_proxy_settings.token_usage
        today_bucket = stats.by_day.get(today_iso())
        self.stats_total_tokens_var.set(self._format_usage_count(stats.total.total_tokens))
        self.stats_today_tokens_var.set(self._format_usage_count(today_bucket.total_tokens if today_bucket else 0))
        self.stats_project_count_var.set(self._format_usage_count(len(stats.by_project)))
        self.stats_api_count_var.set(self._format_usage_count(len(stats.by_api)))
        self._render_usage_tree(
            self.stats_day_tree,
            sorted(stats.by_day.values(), key=lambda bucket: bucket.key, reverse=True),
        )
        self._render_usage_tree(
            self.stats_project_tree,
            sorted(stats.by_project.values(), key=lambda bucket: (-bucket.total_tokens, bucket.label.casefold())),
        )
        self._render_usage_tree(
            self.stats_api_tree,
            sorted(stats.by_api.values(), key=lambda bucket: (-bucket.total_tokens, bucket.label.casefold())),
        )

    def _render_usage_tree(self, tree: ttk.Treeview, buckets: list[RouteProxyTokenUsageBucket]) -> None:
        tree.delete(*tree.get_children())
        if not buckets:
            tree.insert("", "end", values=("暂无统计", "0", "0", "0", "0", "-"))
            return
        for bucket in buckets:
            tree.insert(
                "",
                "end",
                iid=bucket.key,
                values=(
                    bucket.label,
                    self._format_usage_count(bucket.input_tokens),
                    self._format_usage_count(bucket.output_tokens),
                    self._format_usage_count(bucket.total_tokens),
                    self._format_usage_count(bucket.requests),
                    bucket.updated_at.replace("T", " ") if bucket.updated_at else "-",
                ),
            )

    def _format_usage_count(self, value: int) -> str:
        try:
            return f"{int(value):,}"
        except (TypeError, ValueError):
            return "0"

    def refresh_settings_tab(self) -> None:
        self.model_batch_concurrency_var.set(str(self.model_batch_concurrency))
        self.account_pool_recovery_interval_var.set(str(self.account_pool_settings.recovery_interval_minutes))
        self.hot_update_enabled_var.set(self.hot_update_enabled)
        self.hot_update_interval_var.set(str(self.hot_update_interval_minutes))
        self.hot_update_status_var.set(
            f"仓库同步轮询：{'已启用' if self.hot_update_enabled else '未启用'}，间隔 {self.hot_update_interval_minutes} 分钟。"
        )
        if not self.software_update_check_running and not self.software_update_checked_once:
            self.software_update_status_var.set(f"当前版本 {__version__}，尚未检查软件更新。")
        self.settings_version_var.set(__version__)
        self.settings_python_var.set(sys.version.split()[0])
        self.settings_tk_var.set(f"Tcl/Tk {self.root.tk.call('info', 'patchlevel')}")
        try:
            ttkbootstrap_version = package_version("ttkbootstrap")
        except PackageNotFoundError:
            ttkbootstrap_version = "未安装"
        self.settings_ttkbootstrap_var.set(ttkbootstrap_version)
        self.settings_storage_path_var.set(str(self.store.storage_path))
        self.settings_codex_config_path_var.set(str(self.manager.config_path))
        self.settings_codex_auth_path_var.set(str(self.manager.auth_path))
        self.settings_project_root_var.set(str(self.project_root))
        self.settings_platform_var.set(platform.platform())
        self._render_hot_update_log()

    def _schedule_sign_in_status_refresh(self) -> None:
        if not self.root.winfo_exists():
            return
        current_day = today_iso()
        if current_day != self.sign_in_status_day:
            self.sign_in_status_day = current_day
            self.refresh_library_tab()
            self.refresh_test_tab()
        self.root.after(60_000, self._schedule_sign_in_status_refresh)

    def _schedule_startup_software_update_check(self) -> None:
        if not self.root.winfo_exists() or self.software_update_checked_once:
            return
        self.software_update_checked_once = True
        self.root.after(1500, lambda: self._run_software_update_check(automatic=True))

    def _schedule_hot_update_check(self) -> None:
        if not self.root.winfo_exists():
            return
        if self.hot_update_enabled and not self.hot_update_check_running:
            self._run_hot_update_check(automatic=True)
        delay_ms = normalize_hot_update_interval_minutes(self.hot_update_interval_minutes) * 60_000
        self.root.after(delay_ms, self._schedule_hot_update_check)

    def check_hot_updates_now(self) -> None:
        self._run_hot_update_check(automatic=False)

    def check_software_update_now(self) -> None:
        self._run_software_update_check(automatic=False)

    def _run_software_update_check(self, *, automatic: bool) -> None:
        if self.software_update_check_running:
            if not automatic:
                messagebox.showinfo("提示", "软件更新检查正在进行。", parent=self.root)
            return
        self.software_update_check_running = True
        self.software_update_status_var.set("正在检查软件更新...")
        self.status_var.set("正在检查软件更新...")

        def worker() -> None:
            try:
                info = self.software_update_checker.check(__version__)
            except Exception as exc:
                error_message = software_update_error_detail(exc)
                self.root.after(0, lambda: self._finish_software_update_check(None, error_message, automatic=automatic))
                return
            self.root.after(0, lambda: self._finish_software_update_check(info, "", automatic=automatic))

        threading.Thread(target=worker, daemon=True).start()

    def _finish_software_update_check(
        self,
        info: SoftwareUpdateInfo | None,
        error: str,
        *,
        automatic: bool,
    ) -> None:
        self.software_update_check_running = False
        plan = build_software_update_finish_plan(info, error)
        if plan.kind == "error":
            self.software_update_status_var.set(plan.status_text)
            if not automatic:
                messagebox.showerror("软件更新检查失败", plan.event_detail, parent=self.root)
            self.status_var.set(plan.status_text)
            self._record_hot_update_event(
                scope="software",
                target=plan.event_target or "Codex Switch",
                status=plan.event_status or "error",
                detail=plan.event_detail,
                automatic=automatic,
            )
            self.persist_state()
            return
        if plan.kind == "none":
            return
        if plan.kind == "current":
            self.software_update_status_var.set(plan.status_text)
            if not automatic:
                messagebox.showinfo("软件更新", plan.status_text, parent=self.root)
            self.status_var.set(plan.status_text)
            self._record_hot_update_event(
                scope="software",
                target=plan.event_target or "Codex Switch",
                status=plan.event_status or "current",
                detail=plan.event_detail,
                automatic=automatic,
            )
            self.persist_state()
            return

        self.software_update_status_var.set(plan.status_text)
        self.status_var.set(plan.status_text)
        self._record_hot_update_event(
            scope="software",
            target=plan.event_target or "Codex Switch",
            status=plan.event_status or "available",
            detail=plan.event_detail,
            automatic=automatic,
        )
        self.persist_state()
        target_url = plan.prompt_url
        if not target_url:
            messagebox.showinfo("软件更新", f"{plan.status_text}\n\n该 Release 没有可打开的下载地址。", parent=self.root)
            return
        if messagebox.askyesno("发现软件新版本", plan.prompt_message or plan.status_text, parent=self.root):
            webbrowser.open(target_url)
            self._record_hot_update_event(
                scope="software",
                target=plan.event_target or "Codex Switch",
                status="opened",
                detail=target_url,
                automatic=automatic,
            )
            self.persist_state()

    def _record_hot_update_event(
        self,
        *,
        scope: str,
        target: str,
        status: str,
        detail: str = "",
        commit: str = "",
        automatic: bool = False,
    ) -> None:
        self.hot_update_events = append_hot_update_event(
            getattr(self, "hot_update_events", []),
            scope=scope,
            target=target,
            status=status,
            detail=detail,
            commit=commit,
            automatic=automatic,
        )
        self._render_hot_update_log()

    def _hot_update_event_line(self, event: HotUpdateEvent) -> str:
        return hot_update_event_line(event)

    def _render_hot_update_log(self) -> None:
        if not hasattr(self, "hot_update_log_text"):
            return
        lines = [
            self._hot_update_event_line(event)
            for event in reversed(getattr(self, "hot_update_events", [])[-20:])
        ]
        self._set_text_content(
            self.hot_update_log_text,
            "\n".join(lines) if lines else "暂无更新与同步记录。",
            disabled=True,
        )

    def _run_hot_update_check(self, *, automatic: bool) -> None:
        if self.hot_update_check_running:
            if not automatic:
                messagebox.showinfo("提示", "仓库同步检查正在进行。", parent=self.root)
            return
        self.hot_update_check_running = True
        self.hot_update_status_var.set("正在检查仓库同步...")
        summary = "仓库同步检查失败。"
        try:
            summary = self._check_and_apply_hot_updates(automatic=automatic)
        except Exception as exc:
            summary = f"仓库同步检查失败：{exc}"
            self._record_hot_update_event(
                scope="check",
                target="自动检查" if automatic else "手动检查",
                status="error",
                detail=str(exc),
                automatic=automatic,
            )
            self.persist_state()
        finally:
            self.hot_update_check_running = False
        self._finish_hot_update_check(summary)

    def _finish_hot_update_check(self, summary: str) -> None:
        self.hot_update_status_var.set(summary)
        self.status_var.set(summary)
        self.refresh_project_tab()
        self.refresh_skills_tab()
        self._render_hot_update_log()

    def _check_and_apply_hot_updates(self, *, automatic: bool) -> str:
        repo_updates = 0
        project_updates = 0
        pending_repo_updates = 0
        pending_project_updates = 0
        errors: list[str] = []

        for repo in list(self.skill_market_repos):
            try:
                update = self._skill_repo_remote_update(repo)
            except (OSError, RuntimeError, subprocess.TimeoutExpired) as exc:
                detail = str(exc)
                errors.append(f"Skills仓库 {repo.url}: {detail}")
                self._record_hot_update_event(
                    scope="skill_repo",
                    target=repo.url,
                    status="error",
                    detail=detail,
                    automatic=automatic,
                )
                continue
            decision = process_hot_update_candidate(
                has_update=update.has_update,
                latest_commit=update.latest_commit,
                automatic=automatic,
                auto_update_enabled=repo.auto_update,
                texts=SKILL_REPO_HOT_UPDATE_TEXTS,
                apply_update=lambda: self._apply_skill_repo_update(
                    repo,
                    automatic=repo.auto_update,
                    expected_commit=update.latest_commit,
                ),
                set_current_commit=lambda commit: self._set_skill_repo_commit(repo, commit),
                confirm_update=(
                    lambda: messagebox.askyesno(
                        "\u53d1\u73b0 Skills \u4ed3\u5e93\u66f4\u65b0",
                        f"{repo.url}\n\u8fdc\u7aef\u63d0\u4ea4\uff1a{update.short_latest}\n\u662f\u5426\u62c9\u53d6\u5e76\u66f4\u65b0\u672c\u5730\uff1f",
                        parent=self.root,
                    )
                ) if not automatic and not repo.auto_update else None,
            )
            repo_updates += decision.updated_delta
            pending_repo_updates += decision.pending_delta
            if decision.event_status:
                self._record_hot_update_event(
                    scope="skill_repo",
                    target=repo.url,
                    status=decision.event_status,
                    detail=decision.event_detail,
                    commit=decision.commit,
                    automatic=decision.event_automatic,
                )

        for project in list(self.projects):
            if not project.github_repo:
                continue
            try:
                update = self._project_remote_update(project)
            except (OSError, RuntimeError, subprocess.TimeoutExpired) as exc:
                detail = str(exc)
                errors.append(f"项目 {project.name}: {detail}")
                self._record_hot_update_event(
                    scope="project",
                    target=project.name,
                    status="error",
                    detail=detail,
                    automatic=automatic,
                )
                continue
            decision = process_hot_update_candidate(
                has_update=update.has_update,
                latest_commit=update.latest_commit,
                automatic=automatic,
                auto_update_enabled=project.github_auto_update,
                texts=PROJECT_HOT_UPDATE_TEXTS,
                apply_update=lambda: self._apply_project_update(
                    project,
                    update.latest_commit,
                    automatic=project.github_auto_update,
                ),
                set_current_commit=lambda commit: self._set_project_commit(project, commit),
                confirm_update=(
                    lambda: messagebox.askyesno(
                        "\u53d1\u73b0\u9879\u76ee\u66f4\u65b0",
                        f"{project.name}\n\u8fdc\u7aef\u63d0\u4ea4\uff1a{update.short_latest}\n\u662f\u5426\u6267\u884c git pull --ff-only\uff1f",
                        parent=self.root,
                    )
                ) if not automatic and not project.github_auto_update else None,
            )
            project_updates += decision.updated_delta
            pending_project_updates += decision.pending_delta
            if decision.event_status:
                self._record_hot_update_event(
                    scope="project",
                    target=project.name,
                    status=decision.event_status,
                    detail=decision.event_detail,
                    commit=decision.commit,
                    automatic=decision.event_automatic,
                )

        summary = hot_update_summary_text(
            repo_updates=repo_updates,
            project_updates=project_updates,
            pending_repo_updates=pending_repo_updates,
            pending_project_updates=pending_project_updates,
            error_count=len(errors),
        )
        self._record_hot_update_event(
            scope="check",
            target="\u81ea\u52a8\u68c0\u67e5" if automatic else "\u624b\u52a8\u68c0\u67e5",
            status="summary",
            detail=summary,
            automatic=automatic,
        )
        self.persist_state()
        return summary

    def refresh_global_tab(self) -> None:
        self.current_config = self.manager.read_current_config()
        claude_base_url, claude_model, claude_fallback_model = claude_settings_env_values(
            self.claude_manager.load_settings(),
            base_url_key=CLAUDE_BASE_URL_ENV_KEY,
            model_key=CLAUDE_MODEL_ENV_KEY,
            fallback_model_key=CLAUDE_FALLBACK_MODEL_ENV_KEY,
        )
        display = build_global_tab_display(
            self.current_config,
            counts=self._current_status_counts(),
            claude_base_url=claude_base_url,
            claude_model=claude_model,
            claude_fallback_model=claude_fallback_model,
            claude_settings_path=str(self.claude_manager.settings_path),
            global_mcp_text=self._mcp_summary(self._effective_global_mcp_toml()),
        )
        self.global_total_var.set(display.total_text)
        self.global_healthy_var.set(display.healthy_text)
        self.global_degraded_var.set(display.degraded_text)
        self.global_error_var.set(display.error_text)
        self.codex_current_api_var.set(display.codex_current_api_text)
        self.codex_current_models_var.set(display.codex_current_models_text)
        self.claude_current_api_var.set(display.claude_current_api_text)
        self.claude_current_models_var.set(display.claude_current_models_text)
        self.current_path_var.set(display.current_paths_text)
        self.global_mcp_var.set(display.global_mcp_text)
        self._sync_global_profile_choice()

    def refresh_library_tab(self) -> None:
        self.hide_error_button_var.set("显示异常" if self.hide_error_profiles else "隐藏异常")
        self._sync_library_scope_tabs()
        display = build_library_tab_display(
            self.profiles,
            hide_error_profiles=self.hide_error_profiles,
            library_profile_view=self.library_profile_view,
            selected_profile_id=self.selected_profile_id,
            library_view_all=LIBRARY_VIEW_ALL,
            library_tree_columns=LIBRARY_TREE_COLUMNS,
            library_tree_columns_with_vendor=LIBRARY_TREE_COLUMNS_WITH_VENDOR,
            profile_tree_iid=self._profile_tree_iid,
            scope_label_map=dict(LIBRARY_PROFILE_VIEW_TABS),
            status_text=STATUS_TEXT,
        )
        self.profile_tree.configure(displaycolumns=display.display_columns)
        self.selected_profile_id = display.selected_profile_id

        self.suppress_selection_events = True
        try:
            for item in self.profile_tree.get_children():
                self.profile_tree.delete(item)
            for row in display.rows:
                self.profile_tree.insert(
                    "",
                    "end",
                    iid=row.item_id,
                    values=row.values,
                    tags=(row.tag,),
                )
            self.profile_tree.tag_configure("healthy", foreground=PALETTE["success"])
            self.profile_tree.tag_configure("degraded", foreground=PALETTE["warning"])
            self.profile_tree.tag_configure("error", foreground=PALETTE["danger"])
            self.profile_tree.tag_configure("unknown", foreground=PALETTE["neutral_text"])
        finally:
            self.suppress_selection_events = False

        self.library_hint_var.set(display.hint_text)
        self._sync_profile_tree_selection()
        self._sync_global_profile_choice()
        self._refresh_library_detail()

    def _refresh_library_detail(self) -> None:
        detail = build_library_detail_display(
            self.get_selected_profile(),
            status_text=STATUS_TEXT,
        )
        self.library_selected_name_var.set(detail.selected_name)
        self.library_selected_provider_var.set(detail.provider_text)
        self.library_selected_category_var.set(detail.category_text)
        self.library_selected_model_var.set(detail.model_text)
        self.library_selected_api_var.set(detail.api_text)
        self.library_selected_key_var.set(detail.key_text)
        self.library_selected_wire_var.set(detail.wire_text)
        self.library_selected_sign_in_status_var.set(detail.sign_in_status_text)
        self.library_selected_sign_in_url_var.set(detail.sign_in_url_text)
        self.library_selected_notes_var.set(detail.notes_text)
        badge_fg, badge_bg = STATUS_COLORS.get(detail.badge_state, STATUS_COLORS["unknown"])
        self.library_health_badge.configure(text=detail.badge_text, bg=badge_bg, fg=badge_fg)
        self._set_library_api_link_state()
        self._set_library_sign_in_link_state()
        self._render_library_model_tags(detail.model_tags, detail.empty_tags_text)

    def _set_link_label_state(self, label: tk.Label, url: str | None) -> None:
        if url and url != "-" and is_http_url(url):
            label.configure(fg=PALETTE["link"], cursor="hand2")
        else:
            label.configure(fg=PALETTE["muted"], cursor="")

    def _set_library_api_link_state(self) -> None:
        self._set_link_label_state(self.library_api_link_label, self.library_selected_api_var.get())

    def _set_library_sign_in_link_state(self) -> None:
        self._set_link_label_state(self.library_sign_in_link_label, self.library_selected_sign_in_url_var.get())

    def _open_link(self, url: str | None) -> None:
        if not url or url == "-" or not is_http_url(url):
            return
        webbrowser.open(url)

    def _open_existing_file(self, path: Path, label: str) -> None:
        if not path.exists():
            messagebox.showinfo("提示", f"{label} 文件尚不存在：\n{path}", parent=self.root)
            return
        try:
            os.startfile(path)  # type: ignore[attr-defined]
        except Exception as exc:
            messagebox.showerror("打开失败", f"打开 {label} 文件失败：\n{exc}", parent=self.root)
            return
        self.status_var.set(f"已打开 {label} 文件：{path}")

    def open_global_codex_config(self) -> None:
        self._open_existing_file(self.manager.config_path, "Codex config.toml")

    def open_global_claude_config(self) -> None:
        self._open_existing_file(self.claude_manager.settings_path, "Claude settings.json")

    def _open_selected_api_url(self) -> None:
        self._open_link(self.library_selected_api_var.get())

    def _open_selected_sign_in_url(self) -> None:
        profile = self.get_selected_profile()
        if not profile or not profile.sign_in_url:
            return
        self._open_link(profile.sign_in_url)
        profile.last_signed_date = today_iso()
        self.persist_state()
        self.refresh_library_tab()
        self.refresh_test_tab()
        self.status_var.set(f"已打开 {profile.name} 的签到地址。")

    def _on_library_models_canvas_configure(self, event: tk.Event) -> None:
        if hasattr(self, "library_model_tags_window"):
            self.library_models_canvas.itemconfigure(self.library_model_tags_window, width=event.width)
        self._layout_library_model_tags(event.width)

    def _render_library_model_tags(self, models: list[str], empty_text: str) -> None:
        normalized_models = [str(model).strip() for model in models if str(model).strip()]
        if hasattr(self, "library_model_tags_frame"):
            for child in self.library_model_tags_frame.winfo_children():
                child.destroy()
        self.library_model_tag_models = []
        self.library_model_tag_widgets = []
        self._library_model_tag_layout_columns = 0
        self._library_model_tag_layout_count = -1

        if not normalized_models:
            self.library_models_summary_var.set(empty_text)
            self.library_model_stats_button_var.set("展开统计")
            self.library_model_stats_expanded = False
            if hasattr(self, "library_model_stats_text"):
                self._set_text_content(self.library_model_stats_text, empty_text, disabled=True)
                self.library_model_stats_text.grid_remove()
            if hasattr(self, "library_model_tags_frame"):
                tk.Label(
                    self.library_model_tags_frame,
                    text=empty_text,
                    bg="#FBFDFE",
                    fg=PALETTE["muted"],
                    font=self.small_font,
                ).grid(row=0, column=0, sticky="w", padx=10, pady=10)
            return

        visible_models = normalized_models[:20]
        hidden_count = max(0, len(normalized_models) - len(visible_models))
        stats = model_vendor_stats(normalized_models, self.model_vendor_keywords)
        stats_summary = "，".join(f"{vendor} {count}" for vendor, count in stats.items())
        summary = f"共 {len(normalized_models)} 个模型；标签显示前 {len(visible_models)} 个"
        if hidden_count:
            summary += f"，隐藏 {hidden_count} 个"
        if stats_summary:
            summary += f"。{stats_summary}"
        self.library_models_summary_var.set(summary)
        self.library_model_stats_button_var.set("收起统计" if self.library_model_stats_expanded else "展开统计")

        if hasattr(self, "library_model_tags_frame"):
            for model in visible_models:
                tag = tk.Canvas(
                    self.library_model_tags_frame,
                    width=172,
                    height=34,
                    bg="#FBFDFE",
                    highlightthickness=0,
                    cursor="hand2",
                )
                self.library_model_tag_widgets.append((model, tag))
                tag.bind("<Button-1>", lambda _event, name=model: self._select_library_model_tag(name))

        self.library_model_tag_models = visible_models
        width = self.library_models_canvas.winfo_width() if hasattr(self, "library_models_canvas") else 520
        self._layout_library_model_tags(width)
        self._refresh_library_model_tag_styles()
        self._render_library_model_stats(normalized_models)

    def _layout_library_model_tags(self, width: int) -> None:
        if not getattr(self, "library_model_tag_widgets", None) or not hasattr(self, "library_model_tags_frame"):
            return
        tag_width = 172
        gap = 8
        available_width = max(tag_width, width - 12)
        column_count = max(1, available_width // (tag_width + gap))
        tag_count = len(self.library_model_tag_widgets)
        previous_columns = getattr(self, "_library_model_tag_layout_columns", 0)
        if previous_columns == column_count and getattr(self, "_library_model_tag_layout_count", -1) == tag_count:
            return
        self._library_model_tag_layout_columns = column_count
        self._library_model_tag_layout_count = tag_count
        for column in range(max(previous_columns, column_count)):
            self.library_model_tags_frame.columnconfigure(column, weight=1 if column < column_count else 0)
        for index, (_model, tag) in enumerate(self.library_model_tag_widgets):
            tag.grid(row=index // column_count, column=index % column_count, sticky="w", padx=6, pady=6)

    def _refresh_library_model_tag_styles(self) -> None:
        selected_profile = self.get_selected_profile()
        selected_model = ""
        if selected_profile:
            selected_model = (
                selected_profile.codex_display_model
                if profile_supports_codex(selected_profile)
                else selected_profile.claude_display_model
            )
        for model, tag in getattr(self, "library_model_tag_widgets", []):
            tag.delete("all")
            selected = model == selected_model
            fill = PALETTE["selection_bg"] if selected else PALETTE["neutral_soft"]
            outline = PALETTE["accent"] if selected else PALETTE["card_border"]
            text_color = PALETTE["accent"] if selected else PALETTE["text"]
            tag.create_rectangle(1, 1, 171, 33, fill=fill, outline=outline)
            tag.create_text(
                10,
                17,
                text=compact_text(model, 22),
                fill=text_color,
                font=self.small_font,
                anchor="w",
            )

    def _render_library_model_stats(self, models: list[str]) -> None:
        if not hasattr(self, "library_model_stats_text"):
            return
        grouped = models_by_vendor(models, self.model_vendor_keywords)
        lines: list[str] = []
        for vendor, names in grouped.items():
            lines.append(f"{vendor}（{len(names)}）")
            lines.extend(f"  - {name}" for name in names)
        content = "\n".join(lines) if lines else "暂无统计。"
        self._set_text_content(self.library_model_stats_text, content, disabled=True)
        if self.library_model_stats_expanded:
            self.library_model_stats_text.grid()
        else:
            self.library_model_stats_text.grid_remove()

    def _toggle_library_model_stats(self) -> None:
        self.library_model_stats_expanded = not self.library_model_stats_expanded
        self.library_model_stats_button_var.set("收起统计" if self.library_model_stats_expanded else "展开统计")
        if hasattr(self, "library_model_stats_text"):
            if self.library_model_stats_expanded:
                self.library_model_stats_text.grid()
            else:
                self.library_model_stats_text.grid_remove()

    def _select_library_model_tag(self, model: str) -> None:
        profile = self.get_selected_profile()
        if not profile:
            return
        if profile_supports_codex(profile):
            updated = replace(profile, model=model, codex_model=model)
        elif profile_supports_claude(profile):
            updated = replace(profile, claude_model=model)
        else:
            self.status_var.set("当前配置未提供 API，不能回填模型。")
            return
        self.profiles = [updated if item.id == updated.id else item for item in self.profiles]
        self.persist_state()
        self.refresh_global_tab()
        self.refresh_library_tab()
        self.refresh_test_tab()
        self.status_var.set(f"已选择模型：{model}")

    def refresh_project_tab(self) -> None:
        display = project_tab_display(
            self.projects,
            selected_project_id=self.selected_project_id,
            profile_by_id=self._profile_by_id,
            project_codex_profile_id=project_codex_profile_id,
            project_claude_profile_id=project_claude_profile_id,
            project_mcp_summary=self._project_mcp_selection_summary,
            project_status=lambda project: (
                self.project_template_service.inspect(project_root_path(project))
                if project_root_path(project).exists()
                else None
            ),
        )
        self.selected_project_id = display.selected_project_id

        self.suppress_selection_events = True
        try:
            replace_treeview_rows(
                self.project_tree,
                [(row.project_id, row.values) for row in display.rows],
            )
        finally:
            self.suppress_selection_events = False

        self._sync_project_tree_selection()

        self.project_hint_var.set(display.hint_text)
        self._refresh_project_detail()
        self.refresh_proxy_tab()

    def refresh_proxy_tab(self) -> None:
        if not hasattr(self, "proxy_project_tree"):
            return
        self._refresh_proxy_account_pool_group_choices()
        display = route_proxy_tab_display(
            self.route_proxy_settings,
            self.projects,
            is_running=self.route_proxy_server.is_running,
            profile_by_id=self._profile_by_id,
            project_codex_profile_id=project_codex_profile_id,
            project_claude_profile_id=project_claude_profile_id,
            project_account_pool_group_name=self._project_account_pool_group_name,
        )
        self.proxy_host_var.set(display.host)
        self.proxy_port_var.set(display.port_text)
        self.proxy_account_pool_strategy_var.set(display.strategy_label)
        self.proxy_upstream_timeout_var.set(display.upstream_timeout_text)
        self.proxy_status_var.set(display.status_text)
        self.suppress_selection_events = True
        try:
            replace_treeview_rows(
                self.proxy_project_tree,
                [(row.project_id, row.values) for row in display.rows],
            )
        finally:
            self.suppress_selection_events = False
        self._sync_proxy_project_selection()
        self._refresh_proxy_detail()
        self._render_proxy_log()

    def _refresh_proxy_account_pool_group_choices(self) -> None:
        choices = route_proxy_account_pool_choices(
            self.account_pool_settings,
            current_codex_label=self.proxy_account_pool_group_var.get(),
            current_claude_label=self.proxy_claude_account_pool_group_var.get(),
        )
        self.proxy_account_pool_group_choices = choices.codex_choices
        self.proxy_claude_account_pool_group_choices = choices.claude_choices
        if hasattr(self, "proxy_account_pool_group_combo"):
            self.proxy_account_pool_group_combo.configure(values=choices.codex_labels)
        if hasattr(self, "proxy_claude_account_pool_group_combo"):
            self.proxy_claude_account_pool_group_combo.configure(values=choices.claude_labels)
        self.proxy_account_pool_group_var.set(choices.selected_codex_label)
        self.proxy_claude_account_pool_group_var.set(choices.selected_claude_label)

    def _proxy_group_label_for_id(self, group_id: str, *, client_type: str = ROUTE_PROXY_CLIENT_CODEX) -> str:
        self._refresh_proxy_account_pool_group_choices()
        choices = (
            self.proxy_claude_account_pool_group_choices
            if client_type == ROUTE_PROXY_CLIENT_CLAUDE
            else self.proxy_account_pool_group_choices
        )
        return route_proxy_group_label_for_id(group_id, choices)

    def _refresh_proxy_detail(self) -> None:
        detail = route_proxy_detail_display(
            self.get_selected_project(),
            self.route_proxy_settings,
            self.account_pool_settings,
            profile_by_id=self._profile_by_id,
            codex_choices=getattr(self, "proxy_account_pool_group_choices", {}),
            claude_choices=getattr(self, "proxy_claude_account_pool_group_choices", {}),
        )
        self.proxy_selected_project_var.set(detail.selected_project_text)
        self.proxy_selected_rules_var.set(detail.selected_rules_text)
        self.proxy_codex_upstream_source_var.set(detail.codex_upstream_source_label)
        self.proxy_claude_upstream_source_var.set(detail.claude_upstream_source_label)
        self.proxy_codex_protocol_var.set(detail.codex_protocol)
        self.proxy_claude_protocol_var.set(detail.claude_protocol)
        self.proxy_codex_compact_model_var.set(detail.codex_compact_model)
        if detail.codex_group_label:
            self.proxy_account_pool_group_var.set(detail.codex_group_label)
        if detail.claude_group_label:
            self.proxy_claude_account_pool_group_var.set(detail.claude_group_label)

    def _render_proxy_log(self) -> None:
        self._proxy_log_render_pending = False
        if not hasattr(self, "proxy_log_text"):
            return
        lines = [
            f"{event.timestamp} [{event.level}] {event.message}"
            for event in reversed(self.route_proxy_settings.events[-30:])
        ]
        self._set_text_content(self.proxy_log_text, "\n".join(lines) if lines else "暂无代理日志。", disabled=True)

    def _account_pool_channel_by_id(self, channel_id: str | None) -> AccountPoolChannel | None:
        return account_pool_channel_by_id(self.account_pool_settings, channel_id)

    def _selected_account_pool_group(self) -> AccountPoolGroup | None:
        self.account_pool_settings.ensure_default_group()
        choices = getattr(self, "account_pool_group_choices", {})
        group_var = getattr(self, "account_pool_group_var", None)
        group_label = group_var.get() if group_var is not None else ""
        group_id = choices.get(group_label, self.account_pool_settings.selected_group_id)
        return self.account_pool_settings.group_by_id(group_id)

    def _selected_account_pool_group_id(self) -> str:
        group = self._selected_account_pool_group()
        return group.id if group is not None else ""

    def _refresh_account_pool_group_choices(self) -> None:
        self.account_pool_settings.ensure_default_group()
        display = account_pool_group_choices_display(self.account_pool_settings)
        self.account_pool_group_choices = display.choices
        if hasattr(self, "account_pool_group_combo"):
            self.account_pool_group_combo.configure(values=display.labels)
        if display.selected_label:
            self.account_pool_group_var.set(display.selected_label)
        if display.form is not None:
            self.account_pool_group_enabled_var.set(display.form.enabled)
            self.account_pool_group_type_var.set(display.form.group_type_label)
            self.account_pool_group_default_model_var.set(display.form.default_model)
            self.account_pool_group_claude_model_var.set(display.form.claude_model)
            self.account_pool_group_claude_fallback_model_var.set(display.form.claude_fallback_model)

    def _selected_account_pool_channel(self) -> AccountPoolChannel | None:
        if not hasattr(self, "account_pool_tree"):
            return None
        selection = self.account_pool_tree.selection()
        if not selection:
            return None
        return self._account_pool_channel_by_id(selection[0])

    def _project_uses_account_pool(self, project_id: str) -> bool:
        return project_uses_account_pool(self.route_proxy_settings, project_id)

    def _project_account_pool_group_name(self, project_id: str) -> str:
        return project_account_pool_group_name(
            self.route_proxy_settings,
            self.account_pool_settings,
            project_id,
        )

    def refresh_account_pool_tab(self) -> None:
        self.account_pool_settings.ensure_default_group()
        self._refresh_account_pool_group_choices()
        group = self._selected_account_pool_group()
        group_id = group.id if group else ""
        self.account_pool_enabled_var.set(self.account_pool_settings.enabled)
        self.account_pool_summary_var.set(
            account_pool_summary_text(
                self.account_pool_settings,
                group_id=group_id,
                project_count=account_pool_project_count(self.projects, self.route_proxy_settings),
            )
        )
        if not hasattr(self, "account_pool_tree"):
            return
        selected_id = None
        selection = self.account_pool_tree.selection()
        if selection:
            selected_id = selection[0]
        rows = account_pool_channel_rows(
            account_pool_visible_channels(
                self.account_pool_settings,
                group_id,
                self.account_pool_source_filter_var.get(),
            )
        )
        self.suppress_selection_events = True
        try:
            replace_treeview_rows(
                self.account_pool_tree,
                [(row.channel_id, row.values) for row in rows],
            )
        finally:
            self.suppress_selection_events = False
        if selected_id and self.account_pool_tree.exists(selected_id):
            self.account_pool_tree.selection_set(selected_id)
            self.account_pool_tree.focus(selected_id)
        self._refresh_account_pool_detail()

    def _refresh_account_pool_detail(self) -> None:
        channel = self._selected_account_pool_channel()
        if channel is None:
            self.account_pool_selected_name_var.set("未选择渠道")
            self.account_pool_selected_detail_var.set("-")
            return
        detail = account_pool_detail_display(channel)
        self.account_pool_selected_name_var.set(detail.selected_name)
        self.account_pool_selected_detail_var.set(detail.detail_text)

    def _refresh_project_detail(self) -> None:
        project = self.get_selected_project()
        if not project:
            display = project_detail_display(project)
        else:
            codex_profile = self._profile_by_id(project_codex_profile_id(project))
            claude_profile = self._profile_by_id(project_claude_profile_id(project))
            codex_profile_texts = project_codex_profile_texts(
                codex_profile,
                key_summary=self._profile_key_summary,
            )
            claude_profile_texts = project_claude_profile_texts(
                claude_profile,
                key_summary=self._profile_key_summary,
            )
            project_root = project_root_path(project)
            template = project_template_display(
                project_root_exists=project_root.exists(),
                status=self.project_template_service.inspect(project_root) if project_root.exists() else None,
            )
            display = project_detail_display(
                project,
                github_text=project_github_label(project, default_ref=DEFAULT_PROJECT_GITHUB_REF),
                github_update_text=project_github_update_label(project),
                script_text=str(self._get_project_script_path(project)),
                run_text=project.run_command or "未配置",
                mcp_text=self._project_mcp_selection_summary(project),
                skills_text=self._project_skill_selection_summary(project),
                codex_profile_texts=codex_profile_texts,
                claude_profile_texts=claude_profile_texts,
                template_display=template,
            )

        self.project_selected_name_var.set(display.selected_name_text)
        self.project_selected_dir_var.set(display.selected_dir_text)
        self.project_selected_codex_profile_var.set(display.selected_codex_profile_text)
        self.project_selected_claude_profile_var.set(display.selected_claude_profile_text)
        self.project_selected_codex_model_var.set(display.selected_codex_model_text)
        self.project_selected_claude_model_var.set(display.selected_claude_model_text)
        self.project_selected_codex_key_var.set(display.selected_codex_key_text)
        self.project_selected_claude_key_var.set(display.selected_claude_key_text)
        self.project_backup_var.set(display.backup_text)
        self.project_generated_var.set(display.generated_text)
        self.project_script_var.set(display.script_text)
        self.project_run_var.set(display.run_text)
        self.project_github_var.set(display.github_text)
        self.project_github_update_var.set(display.github_update_text)
        self.project_mcp_var.set(display.mcp_text)
        self.project_skills_var.set(display.skills_text)
        badge_colors = {
            "success": (PALETTE["success_soft"], PALETTE["success"]),
            "warning": (PALETTE["warning_soft"], PALETTE["warning"]),
            "neutral": (PALETTE["neutral_soft"], PALETTE["neutral_text"]),
        }
        badge_bg, badge_fg = badge_colors.get(display.badge_state, badge_colors["neutral"])
        self.project_status_badge.configure(text=display.badge_text, bg=badge_bg, fg=badge_fg)

    def refresh_mcp_tab(self, *, reload_from_state: bool = True) -> None:
        selected_name = self._mcp_selected_name()
        display = None
        if reload_from_state:
            load_result = load_mcp_tab_state(
                self._global_mcp_source_toml(),
                selected_name=selected_name,
                global_mcp_opt_out=self.global_mcp_opt_out,
            )
            self.mcp_page_servers = load_result.page_servers
            if load_result.error_text:
                self.mcp_hint_var.set(load_result.error_text)
                for item in self.mcp_tree.get_children():
                    self.mcp_tree.delete(item)
                self._set_text_content(self.mcp_preview_text, "", disabled=True)
                return
            display = load_result.display
        if display is None:
            display = mcp_tab_display(
                self.mcp_page_servers,
                selected_name=selected_name,
                global_mcp_opt_out=self.global_mcp_opt_out,
            )
        self.suppress_selection_events = True
        try:
            replace_treeview_rows(
                self.mcp_tree,
                [(row.server_name, row.values) for row in display.rows],
                selected_id=display.selected_name,
                ensure_visible=True,
            )
        finally:
            self.suppress_selection_events = False

        self.mcp_hint_var.set(display.hint_text)
        self._refresh_mcp_detail()

    def refresh_skills_tab(self) -> None:
        self._sync_projects_from_skill_groups()
        market_entries: list[SkillMarketEntry] = []
        market_errors: list[str] = []
        if hasattr(self, "skill_market_frame"):
            market_entries, market_errors = self._load_skill_market_entries(sync_remote=self.skill_market_force_sync)
            self.skill_market_force_sync = False
            self._render_skill_market_cards(market_entries)
        visible_repos = self._filtered_skill_market_repos() if hasattr(self, "skill_repo_tree") else list(self.skill_market_repos)
        selected_repo_id = self.skill_repo_tree.focus() if hasattr(self, "skill_repo_tree") else None
        selected_group_id = self.skill_group_tree.focus() if hasattr(self, "skill_group_tree") else None
        display = build_skills_tab_display(
            all_repos=self.skill_market_repos,
            visible_repos=visible_repos,
            groups=self.skill_groups,
            projects=self.projects,
            market_entries_count=len(market_entries),
            market_errors_count=len(market_errors),
            repo_filter_active=bool(
                hasattr(self, "skill_repo_filter_var") and self.skill_repo_filter_var.get().strip()
            ),
            selected_repo_id=selected_repo_id,
            selected_group_id=selected_group_id,
        )
        if hasattr(self, "skill_repo_tree"):
            replace_treeview_rows(
                self.skill_repo_tree,
                [(row.repo_id, row.values) for row in display.repo_rows],
                selected_id=display.selected_repo_id,
            )

        if hasattr(self, "skill_group_tree"):
            replace_treeview_rows(
                self.skill_group_tree,
                [(row.group_id, row.values) for row in display.group_rows],
                selected_id=display.selected_group_id,
            )

        if hasattr(self, "skill_project_tree"):
            replace_treeview_rows(
                self.skill_project_tree,
                [(row.project_id, row.values) for row in display.project_rows],
            )
        self.skills_hint_var.set(display.hint_text)
        if hasattr(self, "skill_market_frame"):
            self.skill_repo_preview_var.set(display.preview_status_text)
        if hasattr(self, "skill_repo_tree"):
            self._refresh_skill_repo_detail()
        self._refresh_skill_group_detail()
        self._refresh_skill_project_detail()

    def _load_skill_market_entries(self, *, sync_remote: bool = False) -> tuple[list[SkillMarketEntry], list[str]]:
        query_var = getattr(self, "skill_market_filter_var", None)
        query = query_var.get() if query_var is not None else ""
        entries, errors = load_skill_market_entries(
            self.skill_market_repos,
            sync_remote=sync_remote,
            query=query,
            cache_dir_for_repo=self._skill_repo_cache_dir,
            sync_repo_cache=self._sync_skill_repo_cache,
            verify_repo_checksums=self._verify_skill_repo_checksums,
        )
        if sync_remote and entries:
            self.persist_state()
        return entries, errors


    def refresh_skill_market_now(self) -> None:
        self.skill_market_force_sync = True
        self.refresh_skills_tab()

    def apply_skill_market_filter(self) -> None:
        if hasattr(self, "skill_market_frame"):
            self.refresh_skills_tab()

    def clear_skill_market_filter(self) -> None:
        if hasattr(self, "skill_market_filter_var"):
            self.skill_market_filter_var.set("")

    def _layout_skill_market_cards(self, event: tk.Event | None = None) -> None:
        if not hasattr(self, "skill_market_canvas") or not hasattr(self, "skill_market_frame"):
            return
        width = max(int(getattr(event, "width", 0) or self.skill_market_canvas.winfo_width()), 1)
        self.skill_market_canvas.itemconfigure(self.skill_market_window, width=width)
        columns = max(1, width // 260)
        children = self.skill_market_frame.winfo_children()
        previous_columns = getattr(self, "_skill_market_layout_columns", 0)
        if previous_columns == columns and getattr(self, "_skill_market_layout_count", -1) == len(children):
            return
        self._skill_market_layout_columns = columns
        self._skill_market_layout_count = len(children)
        for index, child in enumerate(children):
            child.grid_configure(row=index // columns, column=index % columns, sticky="ew", padx=6, pady=6)
        for column in range(max(previous_columns, columns)):
            if column < columns:
                self.skill_market_frame.columnconfigure(column, weight=1, uniform="skill_market")
            else:
                self.skill_market_frame.columnconfigure(column, weight=0, uniform="")

    def _render_skill_market_cards(self, entries: list[SkillMarketEntry]) -> None:
        if not hasattr(self, "skill_market_frame"):
            return
        for child in self.skill_market_frame.winfo_children():
            child.destroy()
        self._skill_market_layout_columns = 0
        self._skill_market_layout_count = -1
        if not entries:
            empty = tk.Label(
                self.skill_market_frame,
                text="暂无可显示的 Skills。",
                bg=PALETTE["card_bg"],
                fg=PALETTE["muted"],
                font=self.body_font,
            )
            empty.grid(row=0, column=0, sticky="w", padx=6, pady=6)
            return
        for entry in entries:
            card = tk.Frame(
                self.skill_market_frame,
                bg="#FBFDFE",
                highlightbackground=PALETTE["card_border"],
                highlightthickness=1,
                padx=10,
                pady=10,
            )
            card.columnconfigure(0, weight=1)
            tk.Label(card, text=compact_text(entry.source.display_name or entry.source.name, 28), bg="#FBFDFE", fg=PALETTE["text"], font=self.section_font).grid(row=0, column=0, sticky="w")
            tk.Label(card, text=f"作者：{entry.author}", bg="#FBFDFE", fg=PALETTE["muted"], font=self.small_font).grid(row=1, column=0, sticky="w", pady=(4, 0))
            tk.Label(card, text=compact_text(entry.repo_url, 34), bg="#FBFDFE", fg=PALETTE["muted"], font=self.small_font).grid(row=2, column=0, sticky="w", pady=(2, 8))
            make_button(
                card,
                text="安装",
                variant="secondary",
                command=lambda market_entry=entry: self.install_skill_market_entry_to_group(market_entry),
            ).grid(row=3, column=0, sticky="ew")
        self._layout_skill_market_cards()

    def _filtered_skill_market_repos(self) -> list[SkillMarketRepo]:
        query_var = getattr(self, "skill_repo_filter_var", None)
        query = query_var.get().strip().casefold() if query_var is not None else ""
        return filter_skill_market_repos(
            self.skill_market_repos,
            groups=self.skill_groups,
            query=query,
        )

    def apply_skill_repo_filter(self) -> None:
        self.refresh_skills_tab()

    def clear_skill_repo_filter(self) -> None:
        if hasattr(self, "skill_repo_filter_var"):
            self.skill_repo_filter_var.set("")

    def _clear_skill_repo_preview(self, message: str = "未选择仓库") -> None:
        self.skill_repo_preview_sources = []
        self.skill_repo_preview_repo_id = ""
        if hasattr(self, "skill_repo_preview_filter_var"):
            self.skill_repo_preview_filter_var.set("")
        if hasattr(self, "skill_repo_preview_var"):
            self.skill_repo_preview_var.set(message)
        if hasattr(self, "skill_repo_preview_tree"):
            for item in self.skill_repo_preview_tree.get_children():
                self.skill_repo_preview_tree.delete(item)

    def _render_skill_repo_preview(self, repo: SkillMarketRepo, sources: list[SkillSource]) -> None:
        self.skill_repo_preview_repo_id = repo.id
        self.skill_repo_preview_sources = list(sources)
        self._render_skill_repo_preview_rows(repo, self._filtered_skill_repo_preview_sources(sources))

    def _filtered_skill_repo_preview_sources(self, sources: list[SkillSource] | None = None) -> list[SkillSource]:
        candidates = list(self.skill_repo_preview_sources if sources is None else sources)
        query_var = getattr(self, "skill_repo_preview_filter_var", None)
        query = query_var.get().strip().casefold() if query_var is not None else ""
        return filter_skill_repo_preview_sources(candidates, query=query)

    def _render_skill_repo_preview_rows(self, repo: SkillMarketRepo, sources: list[SkillSource]) -> None:
        if not hasattr(self, "skill_repo_preview_tree"):
            return
        for item in self.skill_repo_preview_tree.get_children():
            self.skill_repo_preview_tree.delete(item)
        query = self.skill_repo_preview_filter_var.get().strip() if hasattr(self, "skill_repo_preview_filter_var") else ""
        display = skill_repo_preview_display(
            repo,
            self.skill_repo_preview_sources,
            sources,
            query=query,
        )
        for row in display.rows:
            self.skill_repo_preview_tree.insert(
                "",
                "end",
                iid=row.source_path,
                values=row.values,
            )
        self.skill_repo_preview_var.set(display.status_text)

    def apply_skill_repo_preview_filter(self) -> None:
        repo = self._skill_repo_by_id(getattr(self, "skill_repo_preview_repo_id", ""))
        if repo is None:
            return
        self._render_skill_repo_preview_rows(repo, self._filtered_skill_repo_preview_sources())

    def clear_skill_repo_preview_filter(self) -> None:
        if hasattr(self, "skill_repo_preview_filter_var"):
            self.skill_repo_preview_filter_var.set("")

    def _sync_skill_repo_preview_cache(self, repo: SkillMarketRepo) -> Path:
        preview_repo = replace(repo, id=f"{repo.id}-preview")
        return self._sync_skill_repo_cache(preview_repo)

    def _preview_skill_repo_sources(self, repo: SkillMarketRepo) -> list[SkillSource]:
        cache_dir = self._sync_skill_repo_preview_cache(repo)
        sources = discover_skill_sources([cache_dir])
        self._verify_skill_repo_checksums(cache_dir, sources)
        return sources

    def _verify_skill_repo_checksums(self, repo_root: Path, sources: list[SkillSource]) -> bool:
        return verify_hot_update_checksums(
            repo_root,
            skill_repo_checksum_required_paths(repo_root, sources),
        )

    def _verify_project_repo_checksums(self, repo_root: Path) -> bool:
        return verify_hot_update_checksums(
            repo_root,
            existing_repo_files(repo_root, PROJECT_METADATA_RELATIVE_PATHS),
        )

    def _selected_skill_repo_preview_sources(self) -> list[SkillSource]:
        if not hasattr(self, "skill_repo_preview_tree"):
            return []
        sources: list[SkillSource] = []
        seen_paths: set[str] = set()
        for item_id in self.skill_repo_preview_tree.selection():
            source_path = Path(str(item_id))
            path_key = str(source_path).casefold()
            if path_key in seen_paths or not (source_path / "SKILL.md").is_file():
                continue
            seen_paths.add(path_key)
            values = self.skill_repo_preview_tree.item(item_id, "values")
            name = str(values[0]).strip() if values else ""
            if not name:
                name = source_path.name
            sources.append(SkillSource(name=name, display_name=name, source_path=source_path))
        return sources

    def _expanded_skills_for_group_ids(self, group_ids: list[str] | None) -> tuple[list[SkillDefinition], list[str]]:
        return expanded_skills_for_group_ids(self.skill_groups, group_ids)

    def _sync_projects_from_skill_groups(self) -> None:
        updated_projects, changed = sync_projects_from_skill_groups(
            self.projects,
            self.skill_groups,
        )
        if changed:
            self.projects = updated_projects
            self.persist_state()

    def _skill_repo_by_id(self, repo_id: str | None) -> SkillMarketRepo | None:
        return next((repo for repo in self.skill_market_repos if repo.id == repo_id), None)

    def _selected_skill_repo(self) -> SkillMarketRepo | None:
        if not hasattr(self, "skill_repo_tree"):
            return None
        selection = self.skill_repo_tree.selection()
        repo_id = selection[0] if selection else self.skill_repo_tree.focus()
        exists = getattr(self.skill_repo_tree, "exists", None)
        if repo_id and callable(exists) and not exists(repo_id):
            return None
        return self._skill_repo_by_id(repo_id)

    def _skill_group_by_id(self, group_id: str | None) -> SkillGroup | None:
        return next((group for group in self.skill_groups if group.id == group_id), None)

    def _selected_skill_group(self) -> SkillGroup | None:
        if not hasattr(self, "skill_group_tree"):
            return None
        selection = self.skill_group_tree.selection()
        return self._skill_group_by_id(selection[0] if selection else self.skill_group_tree.focus())

    def _choose_skill_group(self, title: str) -> SkillGroup | None:
        if not self.skill_groups:
            messagebox.showinfo("提示", "请先在本地 Skills 中创建一个组。", parent=self.root)
            return None
        labels: list[str] = []
        group_by_label: dict[str, SkillGroup] = {}
        for group in self.skill_groups:
            label = f"{group.name}（{len(group.skills)} 个 Skills）"
            labels.append(label)
            group_by_label[label] = group
        dialog = tk.Toplevel(self.root)
        install_windows_drag_redraw_guard(dialog)
        dialog.title(title)
        dialog.transient(self.root)
        dialog.grab_set()
        dialog.configure(bg=PALETTE["card_bg"])
        dialog.resizable(False, False)
        dialog.columnconfigure(0, weight=1)
        tk.Label(dialog, text="选择目标组", bg=PALETTE["card_bg"], fg=PALETTE["text"], font=self.section_font).grid(row=0, column=0, sticky="w", padx=16, pady=(14, 8))
        selected_var = tk.StringVar(value=labels[0])
        combo = ttk.Combobox(dialog, textvariable=selected_var, values=labels, state="readonly", width=44)
        combo.grid(row=1, column=0, sticky="ew", padx=16)
        result: dict[str, SkillGroup | None] = {"group": None}

        def confirm() -> None:
            result["group"] = group_by_label.get(selected_var.get())
            dialog.destroy()

        def cancel() -> None:
            dialog.destroy()

        actions = tk.Frame(dialog, bg=PALETTE["card_bg"])
        actions.grid(row=2, column=0, sticky="e", padx=16, pady=16)
        make_button(actions, text="取消", variant="secondary", command=cancel).grid(row=0, column=0, padx=(0, 8))
        make_button(actions, text="确定", variant="primary", command=confirm).grid(row=0, column=1)
        dialog.bind("<Return>", lambda _event: confirm())
        dialog.bind("<Escape>", lambda _event: cancel())
        combo.focus_set()
        self.root.wait_window(dialog)
        return result["group"]

    def _refresh_skill_repo_detail(self) -> None:
        repo = self._selected_skill_repo()
        if not repo:
            self.skill_repo_detail_var.set("未选择仓库")
            if hasattr(self, "skill_repo_preview_tree"):
                self._clear_skill_repo_preview()
            return
        self.skill_repo_detail_var.set(f"{repo.branch} / {repo.last_sync_commit or '未同步'}")
        if hasattr(self, "skill_repo_preview_tree"):
            self._clear_skill_repo_preview("尚未浏览仓库内容。")

    def _refresh_skill_group_detail(self) -> None:
        group = self._selected_skill_group()
        self.skill_group_detail_var.set(skill_group_detail_text(group))

    def _refresh_skill_project_detail(self) -> None:
        if not hasattr(self, "skill_project_tree"):
            return
        selection = self.skill_project_tree.selection()
        project = self._project_by_id(selection[0]) if selection else None
        if not project:
            self.skill_project_detail_var.set("未选择项目")
            return
        self.skill_project_detail_var.set(self._project_skill_selection_summary(project))

    def add_skill_market_repo(self) -> None:
        url = simpledialog.askstring("Skills仓库", "GitHub 仓库地址：", parent=self.root)
        if not url:
            return
        url = url.strip()
        if not is_github_repo_url(url):
            messagebox.showerror("校验失败", "Skills 仓库必须是可信的 GitHub HTTPS 仓库地址，例如 https://github.com/owner/repo。", parent=self.root)
            return
        branch = simpledialog.askstring("Skills仓库", "分支 / Tag / 完整提交哈希：", initialvalue=DEFAULT_SKILL_REPO_REF, parent=self.root) or DEFAULT_SKILL_REPO_REF
        auto_update = messagebox.askyesno("自动更新", "是否允许该仓库自动检查更新？", parent=self.root)
        repo = SkillMarketRepo.create(url, branch=normalize_git_ref(branch, default=DEFAULT_SKILL_REPO_REF), auto_update=auto_update)
        self.skill_market_repos.append(repo)
        self.persist_state()
        self.refresh_skills_tab()
        self.status_var.set(f"已新增 Skills 仓库：{repo.url}")

    def edit_skill_market_repo(self) -> None:
        repo = self._selected_skill_repo()
        if not repo:
            messagebox.showinfo("提示", "请先选择一个 Skills 仓库。", parent=self.root)
            return
        url = simpledialog.askstring("Skills仓库", "GitHub 仓库地址：", initialvalue=repo.url, parent=self.root)
        if not url:
            return
        if not is_github_repo_url(url.strip()):
            messagebox.showerror("校验失败", "Skills 仓库必须是可信的 GitHub HTTPS 仓库地址，例如 https://github.com/owner/repo。", parent=self.root)
            return
        branch = simpledialog.askstring("Skills仓库", "分支 / Tag / 完整提交哈希：", initialvalue=repo.branch, parent=self.root) or repo.branch
        auto_update = messagebox.askyesno("自动更新", "是否允许该仓库自动检查更新？", parent=self.root)
        repo_url = url.strip()
        repo_ref = normalize_git_ref(branch, default=DEFAULT_SKILL_REPO_REF)
        updated = replace(
            repo,
            url=repo_url,
            branch=repo_ref,
            auto_update=auto_update,
            last_sync_commit="" if repo_url != repo.url or repo_ref != repo.branch else repo.last_sync_commit,
        )
        self.skill_market_repos = [updated if item.id == updated.id else item for item in self.skill_market_repos]
        self.persist_state()
        self.refresh_skills_tab()
        self.status_var.set(f"已更新 Skills 仓库：{updated.url}")

    def delete_skill_market_repo(self) -> None:
        repo = self._selected_skill_repo()
        if not repo:
            messagebox.showinfo("提示", "请先选择一个 Skills 仓库。", parent=self.root)
            return
        if not messagebox.askyesno("确认删除", f"删除仓库配置：{repo.url}？", parent=self.root):
            return
        self.skill_market_repos = [item for item in self.skill_market_repos if item.id != repo.id]
        self.persist_state()
        self.refresh_skills_tab()
        self.status_var.set("已删除 Skills 仓库。")

    def _git_remote_commit(self, url: str, ref: str) -> str:
        return repo_git_remote_commit(
            url,
            ref,
            default_ref=DEFAULT_PROJECT_GITHUB_REF,
            run_command=subprocess.run,
        )

    def _git_local_commit(self, git_root: Path) -> str:
        return repo_git_local_commit(git_root, run_command=subprocess.run)

    def _skill_repo_remote_update(self, repo: SkillMarketRepo) -> GitRemoteUpdate:
        return repo_skill_repo_remote_update(
            repo,
            default_ref=DEFAULT_SKILL_REPO_REF,
            cache_dir=self._skill_repo_cache_dir(repo),
            run_command=subprocess.run,
        )

    def _project_remote_update(self, project: ProjectRecord) -> GitRemoteUpdate:
        return repo_project_remote_update(
            project,
            default_ref=DEFAULT_PROJECT_GITHUB_REF,
            project_root=project_root_path(project),
            run_command=subprocess.run,
        )

    def _run_manual_hot_update_check(
        self,
        *,
        fetch_update,
        spec_builder,
        apply_update,
        set_current_commit,
        refresh_callback,
    ) -> None:
        try:
            update = fetch_update()
        except (OSError, RuntimeError, subprocess.TimeoutExpired) as exc:
            spec = spec_builder(None)
            self._record_hot_update_event(
                scope=spec.scope,
                target=spec.target,
                status="error",
                detail=str(exc),
                automatic=False,
            )
            self.persist_state()
            messagebox.showerror("检查失败", f"{spec.error_message_prefix}：{exc}", parent=self.root)
            return
        spec = spec_builder(update)
        decision = process_hot_update_candidate(
            has_update=update.has_update,
            latest_commit=update.latest_commit,
            automatic=False,
            auto_update_enabled=False,
            texts=spec.texts,
            apply_update=lambda: apply_update(update),
            set_current_commit=set_current_commit,
            confirm_update=lambda: messagebox.askyesno(
                spec.confirm_title,
                spec.confirm_message,
                parent=self.root,
            ),
        )
        if decision.event_status:
            self._record_hot_update_event(
                scope=spec.scope,
                target=spec.target,
                status=decision.event_status,
                detail=decision.event_detail,
                commit=decision.commit,
                automatic=decision.event_automatic,
            )
        if decision.event_status == "current":
            messagebox.showinfo("检查完成", spec.current_info_message, parent=self.root)
        elif update.has_update and decision.event_detail == spec.texts.declined:
            self.status_var.set(spec.declined_status_message)
        self.persist_state()
        refresh_callback()

    def _set_skill_repo_commit(self, repo: SkillMarketRepo, latest_commit: str) -> SkillMarketRepo:
        if repo.last_sync_commit == latest_commit:
            return repo
        updated = replace(repo, last_sync_commit=latest_commit)
        self.skill_market_repos = [updated if item.id == updated.id else item for item in self.skill_market_repos]
        return updated

    def check_selected_skill_repo_update(self) -> None:
        repo = self._selected_skill_repo()
        if not repo:
            messagebox.showinfo("提示", "请先选择一个 Skills 仓库。", parent=self.root)
            return
        self._run_manual_hot_update_check(
            fetch_update=lambda: self._skill_repo_remote_update(repo),
            spec_builder=lambda update: skill_repo_manual_hot_update_spec(
                repo.url,
                update.short_latest if update is not None else "-",
            ),
            apply_update=lambda update: self._apply_skill_repo_update(
                repo,
                automatic=False,
                expected_commit=update.latest_commit,
            ),
            set_current_commit=lambda commit: self._set_skill_repo_commit(repo, commit),
            refresh_callback=self.refresh_skills_tab,
        )

    def preview_selected_skill_repo(self) -> None:
        repo = self._selected_skill_repo()
        if not repo:
            messagebox.showinfo("提示", "请先选择一个 Skills 仓库。", parent=self.root)
            return
        self.skill_repo_preview_var.set("正在同步仓库并扫描 Skills...")
        try:
            sources = self._preview_skill_repo_sources(repo)
        except (OSError, RuntimeError, subprocess.TimeoutExpired) as exc:
            self._clear_skill_repo_preview(f"预览失败：{exc}")
            messagebox.showerror("预览失败", f"无法浏览仓库 Skills：{exc}", parent=self.root)
            return
        self._render_skill_repo_preview(repo, sources)
        if sources:
            self.status_var.set(f"已浏览 Skills 仓库：{repo.url}，发现 {len(sources)} 个 Skills。")
        else:
            self.status_var.set(f"仓库中未发现 Skills：{repo.url}")

    def install_selected_skill_repo_preview_to_group(self) -> None:
        repo = self._selected_skill_repo()
        if not repo:
            messagebox.showinfo("提示", "请先选择一个 Skills 仓库。", parent=self.root)
            return
        sources = self._selected_skill_repo_preview_sources()
        if not sources:
            messagebox.showinfo("提示", "请先在预览列表中选择要安装的 Skill。", parent=self.root)
            return
        group = self._choose_skill_group("安装选中 Skill")
        if group is None:
            return
        updated_group, imported_count = import_skill_sources_to_group(group, sources)
        if not imported_count:
            messagebox.showinfo("提示", "选中的 Skills 已存在于目标组。", parent=self.root)
            return
        self.skill_groups = [updated_group if item.id == updated_group.id else item for item in self.skill_groups]
        self._sync_projects_from_skill_groups()
        self.persist_state()
        self.refresh_project_tab()
        self.refresh_skills_tab()
        self.status_var.set(f"已安装 {imported_count} 个选中 Skill 到 {group.name}。")

    def _skill_repo_cache_dir(self, repo: SkillMarketRepo) -> Path:
        return self.store.root_dir / "skill-market" / repo.id

    def _sync_skill_repo_cache(self, repo: SkillMarketRepo, expected_commit: str | None = None) -> Path:
        cache_dir = self._skill_repo_cache_dir(repo)
        repo_ref = normalize_git_ref(repo.branch, default=DEFAULT_SKILL_REPO_REF)
        target_commit = expected_commit or self._git_remote_commit(repo.url, repo_ref)
        synced_commit = repo_sync_repo_cache(
            cache_dir,
            remote_url=repo.url,
            ref=repo_ref,
            target_commit=target_commit,
            run_command=subprocess.run,
        )
        updated = replace(repo, last_sync_commit=synced_commit)
        self.skill_market_repos = [updated if item.id == updated.id else item for item in self.skill_market_repos]
        return cache_dir

    def _load_profile_metadata_from_payload(self, payload: dict) -> bool:
        profiles, changed = apply_profile_metadata(self.profiles, payload)
        if changed:
            self.profiles = profiles
            if hasattr(self, "global_codex_profile_id") and hasattr(self, "global_claude_profile_id"):
                self._normalize_global_profile_ids()
        return changed

    def _load_model_metadata_from_repo(self, repo_root: Path) -> bool:
        for relative_path in MODEL_METADATA_RELATIVE_PATHS:
            metadata_path = repo_root / relative_path
            if not metadata_path.exists() or not metadata_path.is_file():
                continue
            try:
                payload = json.loads(metadata_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if not isinstance(payload, dict):
                continue
            changed = False
            handled = False
            raw_keywords = payload.get("model_vendor_keywords") or payload.get("vendor_keywords")
            if raw_keywords is not None:
                handled = True
                updated_keywords = normalize_model_vendor_keywords(raw_keywords)
                if updated_keywords != self.model_vendor_keywords:
                    self.model_vendor_keywords = updated_keywords
                    changed = True
            if profile_metadata_entries(payload):
                handled = True
                changed = self._load_profile_metadata_from_payload(payload) or changed
            if handled:
                return changed
        return False

    def _load_project_metadata_from_repo(self, project: ProjectRecord, repo_root: Path) -> tuple[ProjectRecord, bool]:
        for relative_path in PROJECT_METADATA_RELATIVE_PATHS:
            metadata_path = repo_root / relative_path
            if not metadata_path.exists() or not metadata_path.is_file():
                continue
            try:
                payload = json.loads(metadata_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if not isinstance(payload, dict):
                continue
            has_group_metadata = "skill_group_ids" in payload or "skill_groups" in payload
            has_profile_metadata = any(
                key in payload
                for key in ("profile_id", "codex_profile_id", "claude_profile_id")
            )
            if not has_group_metadata and not has_profile_metadata:
                continue
            if has_group_metadata:
                group_ids = project_metadata_group_ids(payload, {group.id for group in self.skill_groups})
                if group_ids is None:
                    continue
                skills, names = self._expanded_skills_for_group_ids(group_ids)
            else:
                group_ids = project.skill_group_ids
                skills = list(project.skills)
                names = None if project.skill_names is None else list(project.skill_names)
            codex_profile_id, claude_profile_id = project_metadata_profile_ids(
                payload,
                project,
                profile_by_id=lambda profile_id: self._profile_by_id(profile_id),
                supports_codex=profile_supports_codex,
                supports_claude=profile_supports_claude,
            )
            updated = project_with_metadata_update(
                project,
                skill_group_ids=group_ids,
                skills=skills,
                skill_names=names,
                codex_profile_id=codex_profile_id,
                claude_profile_id=claude_profile_id,
                updated_at=now_iso(),
            )
            if updated is None:
                return project, False
            self.projects = project_collection_after_replace(self.projects, updated).projects
            return updated, True
        return project, False

    def _apply_skill_repo_update(self, repo: SkillMarketRepo, *, automatic: bool, expected_commit: str | None = None) -> bool:
        if not repo.installed_group_id:
            if not automatic:
                messagebox.showinfo("提示", "该仓库尚未绑定本地 Skills 组，请先使用“安装到组”。", parent=self.root)
            return False
        group = self._skill_group_by_id(repo.installed_group_id)
        if group is None:
            if not automatic:
                messagebox.showinfo("提示", "仓库绑定的本地 Skills 组已不存在。", parent=self.root)
            return False
        try:
            cache_dir = self._sync_skill_repo_cache(repo, expected_commit)
            sources = discover_skill_sources([cache_dir])
            self._verify_skill_repo_checksums(cache_dir, sources)
        except RuntimeError as exc:
            if not automatic:
                messagebox.showerror("更新失败", str(exc), parent=self.root)
            return False
        metadata_updated = self._load_model_metadata_from_repo(cache_dir)
        updated_group, imported_count = import_skill_sources_to_group(
            group,
            sources,
            replace_existing_from_root=cache_dir,
        )
        self.skill_groups = [updated_group if item.id == updated_group.id else item for item in self.skill_groups]
        self._sync_projects_from_skill_groups()
        self.persist_state()
        if metadata_updated:
            self.refresh_library_tab()
        self.refresh_project_tab()
        self.refresh_skills_tab()
        if not automatic:
            metadata_text = "，模型元数据已更新" if metadata_updated else ""
            self.status_var.set(f"已重载 Skills 仓库：{repo.url}，导入 {imported_count} 个 Skills{metadata_text}。")
        return True

    def install_selected_skill_repo_to_group(self) -> None:
        repo = self._selected_skill_repo()
        if not repo:
            messagebox.showinfo("提示", "请先选择一个 Skills 仓库。", parent=self.root)
            return
        group = self._choose_skill_group("安装仓库 Skills")
        if group is None:
            return
        self._install_skill_repo_sources_to_group(repo, group)

    def install_skill_market_entry_to_group(self, entry: SkillMarketEntry) -> None:
        group = self._choose_skill_group("安装 Skill")
        if group is None:
            return
        updated_group, imported_count = import_skill_sources_to_group(group, [entry.source])
        if not imported_count:
            messagebox.showinfo("提示", "该 Skill 已存在于目标组。", parent=self.root)
            return
        self.skill_groups = [updated_group if item.id == updated_group.id else item for item in self.skill_groups]
        self._sync_projects_from_skill_groups()
        self.persist_state()
        self.refresh_project_tab()
        self.refresh_skills_tab()
        self.status_var.set(f"已安装 {entry.source.name} 到 {group.name}。")

    def _set_project_commit(self, project: ProjectRecord, latest_commit: str) -> ProjectRecord:
        if project.github_last_sync_commit == latest_commit:
            return project
        updated = replace(project, github_last_sync_commit=latest_commit, updated_at=now_iso())
        self.projects = [updated if item.id == updated.id else item for item in self.projects]
        return updated

    def _apply_project_update(self, project: ProjectRecord, latest_commit: str, *, automatic: bool) -> bool:
        project_root = project_root_path(project)
        if not (project_root / ".git").exists():
            if not automatic:
                messagebox.showinfo("提示", "项目目录不是 Git 仓库，无法自动拉取。", parent=self.root)
            return False
        github_ref = normalize_git_ref(project.github_ref, default=DEFAULT_PROJECT_GITHUB_REF)
        try:
            synced_commit = repo_sync_project_checkout(
                project_root,
                remote_url=project.github_repo,
                ref=github_ref,
                latest_commit=latest_commit,
                default_ref=DEFAULT_PROJECT_GITHUB_REF,
                run_command=subprocess.run,
            )
        except RuntimeError as exc:
            if not automatic:
                messagebox.showerror("更新失败", str(exc), parent=self.root)
            return False
        try:
            self._verify_project_repo_checksums(project_root)
        except RuntimeError as exc:
            if not automatic:
                messagebox.showerror("更新失败", str(exc), parent=self.root)
            return False
        previous_codex_profile_id = project_codex_profile_id(project)
        previous_claude_profile_id = project_claude_profile_id(project)
        updated_project, project_metadata_updated = self._load_project_metadata_from_repo(project, project_root)
        sync_codex = project_codex_profile_id(updated_project) != previous_codex_profile_id
        sync_claude = project_claude_profile_id(updated_project) != previous_claude_profile_id
        if sync_codex or sync_claude:
            if not self._sync_project_api_binding(
                updated_project,
                sync_codex=sync_codex,
                sync_claude=sync_claude,
            ):
                self.projects = [project if item.id == updated_project.id else item for item in self.projects]
                return False
        self._set_project_commit(updated_project, synced_commit)
        self.persist_state()
        self.refresh_project_tab()
        self.refresh_skills_tab()
        if not automatic:
            metadata_text = "，项目元数据已同步" if project_metadata_updated else ""
            self.status_var.set(f"已更新项目源码：{project.name} @ {synced_commit[:12]}{metadata_text}")
        return True

    def check_selected_project_update(self) -> None:
        project = self.get_selected_project()
        if not project:
            messagebox.showinfo("提示", "请先选择一个项目。", parent=self.root)
            return
        if not project.github_repo:
            messagebox.showinfo("提示", "该项目未配置 GitHub 地址。", parent=self.root)
            return
        self._run_manual_hot_update_check(
            fetch_update=lambda: self._project_remote_update(project),
            spec_builder=lambda update: project_manual_hot_update_spec(
                project.name,
                update.short_latest if update is not None else "-",
            ),
            apply_update=lambda update: self._apply_project_update(
                project,
                update.latest_commit,
                automatic=False,
            ),
            set_current_commit=lambda commit: self._set_project_commit(project, commit),
            refresh_callback=self.refresh_project_tab,
        )

    def add_skill_group(self) -> None:
        name = simpledialog.askstring("Skills组", "组名：", parent=self.root)
        if not name:
            return
        name_error = skill_group_name_error(name)
        if name_error:
            messagebox.showinfo("提示", name_error, parent=self.root)
            return
        description = simpledialog.askstring("Skills组", "描述：", parent=self.root) or ""
        group = SkillGroup.create(name.strip(), description=description)
        self.skill_groups.append(group)
        self.persist_state()
        self.refresh_skills_tab()
        self.status_var.set(f"已新增 Skills 组：{group.name}")

    def edit_skill_group(self) -> None:
        group = self._selected_skill_group()
        if not group:
            messagebox.showinfo("提示", "请先选择一个 Skills 组。", parent=self.root)
            return
        self.open_skill_group_dialog(group)

    def open_skill_group_dialog(self, group: SkillGroup) -> None:
        dialog = tk.Toplevel(self.root)
        install_windows_drag_redraw_guard(dialog)
        dialog.title(f"编辑 Skills 组 - {group.name}")
        dialog.transient(self.root)
        dialog.grab_set()
        dialog.configure(bg=PALETTE["card_bg"])
        dialog.geometry("900x640")
        dialog.minsize(760, 520)
        dialog.columnconfigure(0, weight=1)
        dialog.rowconfigure(2, weight=1)

        name_var = tk.StringVar(value=group.name)
        description_var = tk.StringVar(value=group.description)
        form = tk.Frame(dialog, bg=PALETTE["card_bg"])
        form.grid(row=0, column=0, sticky="ew", padx=16, pady=(16, 8))
        form.columnconfigure(1, weight=1)
        tk.Label(form, text="组名", bg=PALETTE["card_bg"], fg=PALETTE["muted"], font=self.small_font).grid(row=0, column=0, sticky="w", padx=(0, 8))
        ttk.Entry(form, textvariable=name_var).grid(row=0, column=1, sticky="ew")
        tk.Label(form, text="描述", bg=PALETTE["card_bg"], fg=PALETTE["muted"], font=self.small_font).grid(row=1, column=0, sticky="w", padx=(0, 8), pady=(8, 0))
        ttk.Entry(form, textvariable=description_var).grid(row=1, column=1, sticky="ew", pady=(8, 0))

        canvas_wrap = tk.Frame(dialog, bg=PALETTE["card_bg"])
        canvas_wrap.grid(row=2, column=0, sticky="nsew", padx=16)
        canvas_wrap.columnconfigure(0, weight=1)
        canvas_wrap.rowconfigure(0, weight=1)
        canvas = tk.Canvas(canvas_wrap, bg=PALETTE["card_bg"], highlightthickness=0)
        canvas.grid(row=0, column=0, sticky="nsew")
        scroll = ttk.Scrollbar(canvas_wrap, orient="vertical", command=canvas.yview)
        scroll.grid(row=0, column=1, sticky="ns")
        canvas.configure(yscrollcommand=scroll.set)
        cards_frame = tk.Frame(canvas, bg=PALETTE["card_bg"])
        window_id = canvas.create_window((0, 0), window=cards_frame, anchor="nw")
        cards_frame.bind("<Configure>", lambda _event: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda event: self._layout_skill_group_dialog_cards(cards_frame, event.width, window_id, canvas))
        self._render_skill_group_dialog_cards(group, cards_frame)

        actions = tk.Frame(dialog, bg=PALETTE["card_bg"])
        actions.grid(row=1, column=0, sticky="ew", padx=16, pady=(0, 8))
        for column in range(5):
            actions.columnconfigure(column, weight=1)
        make_button(actions, text="新增 Skill", variant="primary", command=lambda: (self.add_skill_to_group(group), self._render_skill_group_dialog_cards(group, cards_frame))).grid(row=0, column=0, sticky="ew", padx=(0, 8))
        make_button(actions, text="安装 GitHub Skills", variant="secondary", command=lambda: (self.install_skill_repo_to_specific_group(group), self._render_skill_group_dialog_cards(group, cards_frame))).grid(row=0, column=1, sticky="ew", padx=(0, 8))
        make_button(actions, text="导入本地文件", variant="secondary", command=lambda: (self.import_local_skill_file_to_group(group), self._render_skill_group_dialog_cards(group, cards_frame))).grid(row=0, column=2, sticky="ew", padx=(0, 8))
        make_button(actions, text="导入扫描Skills", variant="secondary", command=lambda: (self.import_scanned_skills_to_group(group), self._render_skill_group_dialog_cards(group, cards_frame))).grid(row=0, column=3, sticky="ew", padx=(0, 8))
        make_button(actions, text="刷新", variant="secondary", command=lambda: self._render_skill_group_dialog_cards(group, cards_frame)).grid(row=0, column=4, sticky="ew")

        footer = tk.Frame(dialog, bg=PALETTE["card_bg"])
        footer.grid(row=3, column=0, sticky="e", padx=16, pady=16)

        def save_group() -> None:
            current = self._skill_group_by_id(group.id)
            if current is None:
                dialog.destroy()
                return
            name = name_var.get().strip()
            name_error = skill_group_name_error(name)
            if name_error:
                messagebox.showinfo("提示", name_error, parent=dialog)
                return
            updated = skill_group_with_metadata(current, name=name, description=description_var.get())
            self.skill_groups = replace_skill_group(self.skill_groups, updated)
            self._sync_projects_from_skill_groups()
            self.persist_state()
            self.refresh_project_tab()
            self.refresh_skills_tab()
            self.status_var.set(f"已更新 Skills 组：{updated.name}")
            dialog.destroy()

        make_button(footer, text="取消", variant="secondary", command=dialog.destroy).grid(row=0, column=0, padx=(0, 8))
        make_button(footer, text="保存", variant="primary", command=save_group).grid(row=0, column=1)

    def _layout_skill_group_dialog_cards(
        self,
        cards_frame: tk.Frame,
        width: int,
        window_id: int,
        canvas: tk.Canvas,
    ) -> None:
        canvas.itemconfigure(window_id, width=max(width, 1))
        children = cards_frame.winfo_children()
        previous_columns = getattr(cards_frame, "_codex_switch_layout_columns", 0)
        layout = build_skill_group_dialog_layout(
            width=width,
            card_count=len(children),
            previous_columns=previous_columns,
            previous_count=getattr(cards_frame, "_codex_switch_layout_count", -1),
        )
        if not layout.relayout_required:
            return
        setattr(cards_frame, "_codex_switch_layout_columns", layout.columns)
        setattr(cards_frame, "_codex_switch_layout_count", layout.card_count)
        for index, child in enumerate(children):
            child.grid_configure(
                row=index // layout.columns,
                column=index % layout.columns,
                sticky="ew",
                padx=6,
                pady=6,
            )
        for column in range(max(previous_columns, layout.columns)):
            if column < layout.columns:
                cards_frame.columnconfigure(column, weight=1, uniform="skill_group_dialog")
            else:
                cards_frame.columnconfigure(column, weight=0, uniform="")

    def _render_skill_group_dialog_cards(self, group: SkillGroup, cards_frame: tk.Frame) -> None:
        current = self._skill_group_by_id(group.id) or group
        for child in cards_frame.winfo_children():
            child.destroy()
        setattr(cards_frame, "_codex_switch_layout_columns", 0)
        setattr(cards_frame, "_codex_switch_layout_count", -1)
        card_displays = skill_group_dialog_card_displays(current)
        if not card_displays:
            tk.Label(
                cards_frame,
                text="该组暂无 Skills。",
                bg=PALETTE["card_bg"],
                fg=PALETTE["muted"],
                font=self.body_font,
            ).grid(row=0, column=0, sticky="w", padx=6, pady=6)
            return
        for skill, display in zip(current.skills, card_displays):
            card = tk.Frame(
                cards_frame,
                bg="#FBFDFE",
                highlightbackground=PALETTE["card_border"],
                highlightthickness=1,
                padx=10,
                pady=10,
            )
            card.columnconfigure(0, weight=1)
            tk.Label(card, text=display.title, bg="#FBFDFE", fg=PALETTE["text"], font=self.section_font).grid(row=0, column=0, sticky="w")
            tk.Label(card, text=display.type_version_text, bg="#FBFDFE", fg=PALETTE["muted"], font=self.small_font).grid(row=1, column=0, sticky="w", pady=(4, 0))
            tk.Label(card, text=display.source_text, bg="#FBFDFE", fg=PALETTE["muted"], font=self.small_font).grid(row=2, column=0, sticky="w", pady=(2, 8))
            buttons = tk.Frame(card, bg="#FBFDFE")
            buttons.grid(row=3, column=0, sticky="ew")
            buttons.columnconfigure(0, weight=1)
            buttons.columnconfigure(1, weight=1)
            make_button(
                buttons,
                text="编辑",
                variant="secondary",
                command=lambda item=skill: (self.edit_skill_in_group(current, item), self._render_skill_group_dialog_cards(current, cards_frame)),
            ).grid(row=0, column=0, sticky="ew", padx=(0, 6))
            make_button(
                buttons,
                text="删除",
                variant="danger",
                command=lambda item=skill: (self.delete_skill_from_group(current, item), self._render_skill_group_dialog_cards(current, cards_frame)),
            ).grid(row=0, column=1, sticky="ew")

    def delete_skill_group(self) -> None:
        group = self._selected_skill_group()
        if not group:
            messagebox.showinfo("提示", "请先选择一个 Skills 组。", parent=self.root)
            return
        if not messagebox.askyesno("确认删除", f"删除 Skills 组：{group.name}？", parent=self.root):
            return
        self.skill_groups = remove_skill_group(self.skill_groups, group.id)
        self.projects = projects_after_skill_group_delete(self.projects, group.id)
        self.persist_state()
        self.refresh_project_tab()
        self.refresh_skills_tab()
        self.status_var.set("已删除 Skills 组并清理项目关联。")

    def add_skill_to_group(self, group: SkillGroup | None = None) -> None:
        group = self._skill_group_by_id(group.id) if group is not None else self._selected_skill_group()
        if not group:
            messagebox.showinfo("提示", "请先选择一个 Skills 组。", parent=self.root)
            return
        name = simpledialog.askstring("Skill", "Skill 名称：", parent=self.root)
        if not name:
            return
        skill_type = normalize_skill_type(
            simpledialog.askstring("Skill", "类型（script/config）：", initialvalue="script", parent=self.root)
        )
        version = simpledialog.askstring("Skill", "版本：", initialvalue="1.0.0", parent=self.root) or "1.0.0"
        content = simpledialog.askstring("Skill", "内容：", parent=self.root) or ""
        skill = SkillDefinition.create(name, type=skill_type, version=version, content=content)
        updated = skill_group_with_added_skill(group, skill)
        self.skill_groups = replace_skill_group(self.skill_groups, updated)
        self.persist_state()
        self.refresh_skills_tab()
        self.status_var.set(f"已新增 Skill：{skill.name}")

    def edit_skill_in_group(self, group: SkillGroup | None = None, existing: SkillDefinition | None = None) -> None:
        group = self._skill_group_by_id(group.id) if group is not None else self._selected_skill_group()
        if not group:
            messagebox.showinfo("提示", "请先选择一个 Skills 组。", parent=self.root)
            return
        if existing is None:
            name = simpledialog.askstring("Skill", "要编辑的 Skill 名称：", parent=self.root)
            if not name:
                return
            existing = next((skill for skill in group.skills if skill.name == name.strip()), None)
        else:
            existing = next((skill for skill in group.skills if skill.id == existing.id), existing)
        if existing is None:
            messagebox.showinfo("提示", "组内没有这个 Skill。", parent=self.root)
            return
        new_name = simpledialog.askstring("Skill", "Skill 名称：", initialvalue=existing.name, parent=self.root)
        if not new_name:
            return
        skill_type = normalize_skill_type(
            simpledialog.askstring("Skill", "类型（script/config）：", initialvalue=existing.type, parent=self.root)
        )
        version = simpledialog.askstring("Skill", "版本：", initialvalue=existing.version, parent=self.root) or existing.version
        content = simpledialog.askstring("Skill", "内容：", initialvalue=existing.content, parent=self.root) or ""
        updated_skill = replace(
            existing,
            name=new_name.strip(),
            type=skill_type,
            version=version.strip() or "1.0.0",
            content=content,
        )
        updated = skill_group_with_replaced_skill(group, existing.id, updated_skill)
        self.skill_groups = replace_skill_group(self.skill_groups, updated)
        self.persist_state()
        self.refresh_skills_tab()
        self.status_var.set(f"已更新 Skill：{updated_skill.name}")

    def delete_skill_from_group(self, group: SkillGroup | None = None, skill: SkillDefinition | None = None) -> None:
        group = self._skill_group_by_id(group.id) if group is not None else self._selected_skill_group()
        if not group:
            messagebox.showinfo("提示", "请先选择一个 Skills 组。", parent=self.root)
            return
        if skill is None:
            name = simpledialog.askstring("Skill", "要删除的 Skill 名称：", parent=self.root)
            if not name:
                return
            skill = next((item for item in group.skills if item.name == name.strip()), None)
        else:
            skill = next((item for item in group.skills if item.id == skill.id), skill)
        if skill is None:
            messagebox.showinfo("提示", "组内没有这个 Skill。", parent=self.root)
            return
        if not messagebox.askyesno("确认删除", f"删除 Skill：{skill.name}？", parent=self.root):
            return
        updated = skill_group_with_deleted_skill(group, skill.id)
        self.skill_groups = replace_skill_group(self.skill_groups, updated)
        self._sync_projects_from_skill_groups()
        self.persist_state()
        self.refresh_project_tab()
        self.refresh_skills_tab()

    def import_scanned_skills_to_group(self, group: SkillGroup | None = None) -> None:
        group = self._skill_group_by_id(group.id) if group is not None else self._selected_skill_group()
        if not group:
            messagebox.showinfo("提示", "请先选择一个 Skills 组。", parent=self.root)
            return
        sources = self._available_skill_sources()
        if not sources:
            messagebox.showinfo("提示", "未扫描到可导入的 Skills。", parent=self.root)
            return
        existing_names = {skill.name for skill in group.skills}
        imported: list[SkillDefinition] = []
        for source in sources:
            if source.name in existing_names:
                continue
            skill_file = source.source_path / "SKILL.md"
            try:
                content = skill_file.read_text(encoding="utf-8")
            except OSError:
                content = ""
            imported.append(
                SkillDefinition.create(
                    source.name,
                    content=content,
                    source_path=str(source.source_path),
                )
            )
        if not imported:
            messagebox.showinfo("提示", "没有新的 Skills 可导入。", parent=self.root)
            return
        updated = replace(group, skills=[*group.skills, *imported])
        self.skill_groups = [updated if item.id == updated.id else item for item in self.skill_groups]
        self._sync_projects_from_skill_groups()
        self.persist_state()
        self.refresh_project_tab()
        self.refresh_skills_tab()
        self.status_var.set(f"已导入 {len(imported)} 个 Skills 到 {group.name}。")

    def _choose_skill_market_repo(self, title: str) -> SkillMarketRepo | None:
        if not self.skill_market_repos:
            messagebox.showinfo("提示", "请先在设置页添加一个 Skills 仓库。", parent=self.root)
            return None
        labels: list[str] = []
        repo_by_label: dict[str, SkillMarketRepo] = {}
        for repo in self.skill_market_repos:
            label = f"{repo.url} @ {repo.branch}"
            labels.append(label)
            repo_by_label[label] = repo
        dialog = tk.Toplevel(self.root)
        install_windows_drag_redraw_guard(dialog)
        dialog.title(title)
        dialog.transient(self.root)
        dialog.grab_set()
        dialog.configure(bg=PALETTE["card_bg"])
        dialog.resizable(False, False)
        dialog.columnconfigure(0, weight=1)
        tk.Label(dialog, text="选择 GitHub Skills 仓库", bg=PALETTE["card_bg"], fg=PALETTE["text"], font=self.section_font).grid(row=0, column=0, sticky="w", padx=16, pady=(14, 8))
        selected_var = tk.StringVar(value=labels[0])
        combo = ttk.Combobox(dialog, textvariable=selected_var, values=labels, state="readonly", width=64)
        combo.grid(row=1, column=0, sticky="ew", padx=16)
        result: dict[str, SkillMarketRepo | None] = {"repo": None}

        def confirm() -> None:
            result["repo"] = repo_by_label.get(selected_var.get())
            dialog.destroy()

        def cancel() -> None:
            dialog.destroy()

        actions = tk.Frame(dialog, bg=PALETTE["card_bg"])
        actions.grid(row=2, column=0, sticky="e", padx=16, pady=16)
        make_button(actions, text="取消", variant="secondary", command=cancel).grid(row=0, column=0, padx=(0, 8))
        make_button(actions, text="确定", variant="primary", command=confirm).grid(row=0, column=1)
        dialog.bind("<Return>", lambda _event: confirm())
        dialog.bind("<Escape>", lambda _event: cancel())
        combo.focus_set()
        self.root.wait_window(dialog)
        return result["repo"]

    def install_skill_repo_to_specific_group(self, group: SkillGroup) -> None:
        current_group = self._skill_group_by_id(group.id)
        if current_group is None:
            messagebox.showinfo("提示", "目标 Skills 组已不存在。", parent=self.root)
            return
        repo = self._choose_skill_market_repo("安装 GitHub Skills")
        if repo is None:
            return
        self._install_skill_repo_sources_to_group(repo, current_group)

    def _install_skill_repo_sources_to_group(self, repo: SkillMarketRepo, group: SkillGroup) -> bool:
        try:
            cache_dir = self._sync_skill_repo_cache(repo)
            sources = discover_skill_sources([cache_dir])
            self._verify_skill_repo_checksums(cache_dir, sources)
        except RuntimeError as exc:
            messagebox.showerror("安装失败", str(exc), parent=self.root)
            return False
        metadata_updated = self._load_model_metadata_from_repo(cache_dir)
        updated_group, imported_count = import_skill_sources_to_group(group, sources)
        synced_repo = self._skill_repo_by_id(repo.id) or repo
        updated_repo = replace(synced_repo, installed_group_id=group.id)
        self.skill_market_repos = [updated_repo if item.id == updated_repo.id else item for item in self.skill_market_repos]
        if imported_count:
            self.skill_groups = [updated_group if item.id == updated_group.id else item for item in self.skill_groups]
            self._sync_projects_from_skill_groups()
        self.persist_state()
        if metadata_updated:
            self.refresh_library_tab()
        self.refresh_project_tab()
        self.refresh_skills_tab()
        if imported_count:
            self.status_var.set(f"已从仓库安装 {imported_count} 个 Skills 到 {group.name}。")
        else:
            messagebox.showinfo("提示", "仓库中没有新的 Skills，已绑定到目标组。", parent=self.root)
        return True

    def import_local_skill_file_to_group(self, group: SkillGroup) -> None:
        current_group = self._skill_group_by_id(group.id)
        if current_group is None:
            messagebox.showinfo("提示", "目标 Skills 组已不存在。", parent=self.root)
            return
        selected_files = filedialog.askopenfilenames(
            parent=self.root,
            title="导入本地 Skill 文件",
            filetypes=(("Text files", "*.md *.txt *.py *.json *.toml *.yaml *.yml"), ("All files", "*.*")),
        )
        if not selected_files:
            return
        existing_names = {skill.name for skill in current_group.skills}
        imported: list[SkillDefinition] = []
        errors: list[str] = []
        for selected in selected_files:
            path = Path(selected)
            try:
                content = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError) as exc:
                errors.append(f"{path.name}: {exc}")
                continue
            name = path.parent.name if path.name.casefold() == "skill.md" else path.stem
            if not name or name in existing_names:
                continue
            existing_names.add(name)
            imported.append(SkillDefinition.create(name, content=content, source_path=str(path)))
        if errors:
            messagebox.showerror("导入失败", "\n".join(errors[:6]), parent=self.root)
        if not imported:
            messagebox.showinfo("提示", "没有新的本地文件可导入。", parent=self.root)
            return
        updated = replace(current_group, skills=[*current_group.skills, *imported])
        self.skill_groups = [updated if item.id == updated.id else item for item in self.skill_groups]
        self._sync_projects_from_skill_groups()
        self.persist_state()
        self.refresh_project_tab()
        self.refresh_skills_tab()
        self.status_var.set(f"已导入 {len(imported)} 个本地文件到 {current_group.name}。")

    def refresh_test_tab(self) -> None:
        display = build_test_tab_display(
            self.profiles,
            hide_error_profiles=self.hide_error_profiles,
            selected_profile_id=self.selected_profile_id,
            status_text=STATUS_TEXT,
        )
        self.selected_profile_id = display.selected_profile_id

        self.suppress_selection_events = True
        try:
            for item in self.test_api_tree.get_children():
                self.test_api_tree.delete(item)
            for row in display.rows:
                self.test_api_tree.insert(
                    "",
                    "end",
                    iid=row.profile_id,
                    values=row.values,
                    tags=(row.tag,),
                )
            self.test_api_tree.tag_configure("healthy", foreground=PALETTE["success"])
            self.test_api_tree.tag_configure("degraded", foreground=PALETTE["warning"])
            self.test_api_tree.tag_configure("error", foreground=PALETTE["danger"])
            self.test_api_tree.tag_configure("unknown", foreground=PALETTE["neutral_text"])
            if display.selected_profile_id and self.test_api_tree.exists(display.selected_profile_id):
                self.test_api_tree.selection_set(display.selected_profile_id)
                self.test_api_tree.focus(display.selected_profile_id)
                self.test_api_tree.see(display.selected_profile_id)
        finally:
            self.suppress_selection_events = False

        self._refresh_test_detail()

    def _refresh_test_detail(self) -> None:
        profile = self.get_selected_profile()
        detail = build_test_detail_display(
            profile,
            status_text=STATUS_TEXT,
            key_summary=self._profile_key_summary,
            model_summary=self._profile_model_summary,
            success_models_text=self._model_batch_health_summary(profile),
            health_override_display_map=HEALTH_OVERRIDE_DISPLAY,
        )
        self.test_selected_name_var.set(detail.selected_name)
        self.test_detail_health_var.set(detail.health_text)
        self.test_detail_provider_var.set(detail.provider_text)
        self.test_detail_model_var.set(detail.model_text)
        self.test_detail_api_var.set(detail.api_text)
        self.test_detail_key_var.set(detail.key_text)
        self.test_detail_wire_var.set(detail.wire_text)
        self.test_detail_endpoint_var.set(detail.endpoint_text)
        self.test_detail_checked_var.set(detail.checked_text)
        self.test_detail_notes_var.set(detail.notes_text)
        self.test_detail_result_var.set(detail.result_text)
        self.test_detail_success_models_var.set(detail.success_models_text)
        self._sync_success_models_button(profile)
        badge_fg, badge_bg = STATUS_COLORS.get(detail.badge_state, STATUS_COLORS["unknown"])
        self.test_detail_badge.configure(bg=badge_bg, fg=badge_fg)
        self.updating_health_override = True
        self.health_override_var.set(detail.health_override_value)
        self.health_override_note_var.set(detail.health_override_note_text)
        self.health_override_combo.configure(state=detail.health_override_state)
        self.updating_health_override = False
        self._reset_model_batch_for_profile(profile)
        self._reset_chat_target(profile)

    def _batch_model_options(self, profile: Profile | None) -> list[str]:
        return model_batch_targets(profile)

    def _model_batch_cache(self, profile: Profile | None) -> ModelBatchCache | None:
        if profile is None:
            return None
        return self.model_batch_cache_by_profile.get(profile.id)

    def _create_model_batch_cache(self, profile: Profile) -> ModelBatchCache:
        models = self._batch_model_options(profile)
        cache = ModelBatchCache(
            models=models,
            results={model: ModelBatchResult() for model in models},
        )
        self.model_batch_cache_by_profile[profile.id] = cache
        return cache

    def _model_batch_health_summary(self, profile: Profile | None) -> str:
        return model_batch_health_summary(self._model_batch_cache(profile))
    def _successful_models_for_profile(self, profile: Profile | None) -> list[str]:
        return successful_model_batch_models(self._model_batch_cache(profile))

    def _sync_success_models_button(self, profile: Profile | None) -> None:
        button = getattr(self, "success_models_button", None)
        if button is None:
            return
        if self._successful_models_for_profile(profile):
            button.state(["!disabled"])
        else:
            button.state(["disabled"])

    def _reset_model_batch_for_profile(self, profile: Profile | None) -> None:
        profile_id = profile.id if profile else None
        self.model_batch_profile_id = profile_id
        self._sync_model_batch_button(profile)

    def _sync_model_batch_button(self, profile: Profile | None) -> None:
        if profile is None:
            self.model_batch_button.state(["disabled"])
        else:
            self.model_batch_button.state(["!disabled"])

    def _model_batch_counts(self, cache: ModelBatchCache) -> tuple[int, int]:
        return model_batch_counts(cache)
    def _refresh_model_batch_health_display(self, profile_id: str) -> None:
        if self.selected_profile_id == profile_id:
            profile = self._profile_by_id(profile_id)
            self.test_detail_success_models_var.set(self._model_batch_health_summary(profile))
            self._sync_success_models_button(profile)

    def find_matching_profile(self, current: CurrentCodexConfig) -> Profile | None:
        for profile in self.profiles:
            if not profile_supports_codex(profile):
                continue
            if (
                profile.base_url.rstrip("/") == (current.base_url or "").rstrip("/")
                and profile.api_key == (current.api_key or "")
                and profile.provider_name == (current.model_provider or "")
            ):
                return profile
        return None

    def get_selected_profile(self) -> Profile | None:
        return self._profile_by_id(self.selected_profile_id)

    def get_selected_project(self) -> ProjectRecord | None:
        return self._project_by_id(self.selected_project_id)

    def persist_state(self) -> None:
        self.store.save(
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
            model_batch_caches_to_payload(
                {
                    profile_id: cache
                    for profile_id, cache in self.model_batch_cache_by_profile.items()
                    if self._profile_by_id(profile_id) is not None
                }
            ),
            self.route_proxy_settings,
            global_mcp_server_names=self.global_mcp_server_names,
            selected_codex_global_profile_id=self.global_codex_profile_id,
            selected_claude_global_profile_id=self.global_claude_profile_id,
            account_pool_settings=self.account_pool_settings,
            skill_groups=self.skill_groups,
            skill_market_repos=self.skill_market_repos,
            hot_update_enabled=self.hot_update_enabled,
            hot_update_interval_minutes=self.hot_update_interval_minutes,
            model_vendor_keywords=self.model_vendor_keywords,
            hot_update_events=self.hot_update_events,
        )

    def save_settings(self) -> None:
        self.model_batch_concurrency = clamp_model_batch_concurrency(self.model_batch_concurrency_var.get())
        self.model_batch_concurrency_var.set(str(self.model_batch_concurrency))
        self.account_pool_settings.recovery_interval_minutes = normalize_account_pool_recovery_interval_minutes(
            self.account_pool_recovery_interval_var.get()
        )
        self.account_pool_recovery_interval_var.set(str(self.account_pool_settings.recovery_interval_minutes))
        self.hot_update_enabled = bool(self.hot_update_enabled_var.get())
        self.hot_update_interval_minutes = normalize_hot_update_interval_minutes(self.hot_update_interval_var.get())
        self.hot_update_interval_var.set(str(self.hot_update_interval_minutes))
        self.persist_state()
        self.settings_hint_var.set(
            f"已保存设置：模型批量测试最多 {self.model_batch_concurrency} 个并发请求，"
            f"号池检测间隔 {self.account_pool_settings.recovery_interval_minutes} 分钟，"
            f"仓库同步轮询 {'开启' if self.hot_update_enabled else '关闭'}。"
        )
        self.hot_update_status_var.set(
            f"仓库同步轮询：{'已启用' if self.hot_update_enabled else '未启用'}，间隔 {self.hot_update_interval_minutes} 分钟。"
        )
        self.status_var.set("已保存设置。")

    def on_close(self) -> None:
        self.route_proxy_server.stop()
        self.persist_state()
        _release_single_instance()
        self.root.destroy()

    def _selected_proxy_project(self) -> ProjectRecord | None:
        if hasattr(self, "proxy_project_tree"):
            selection = self.proxy_project_tree.selection()
            if selection:
                return self._project_by_id(selection[0])
        return self.get_selected_project()

    def _route_proxy_base_url_for_project(self, project: ProjectRecord) -> str | None:
        return route_proxy_base_url_for_project(self.route_proxy_settings, project)

    def _refresh_route_proxy_rules_for_project(self, project: ProjectRecord) -> bool:
        if not self.route_proxy_settings.project_enabled(project.id):
            return False
        codex_profile = self._profile_by_id(project_codex_profile_id(project))
        claude_profile = self._profile_by_id(project_claude_profile_id(project))
        if codex_profile is None or claude_profile is None:
            return False
        self.route_proxy_settings = refresh_route_proxy_rules_for_project(
            self.route_proxy_settings,
            project,
            codex_profile,
            claude_profile,
        )
        return True

    def _refresh_route_proxy_upstream_models(self, project: ProjectRecord) -> None:
        codex_profile = self._profile_by_id(project_codex_profile_id(project))
        claude_profile = self._profile_by_id(project_claude_profile_id(project))
        claude_pool_model, _fallback = self._claude_model_overrides_for_project(project)
        refresh_route_proxy_upstream_models(
            self.route_proxy_settings,
            project,
            codex_profile,
            claude_profile,
            codex_pool_model=self._codex_model_override_for_project(project),
            claude_pool_model=claude_pool_model,
        )

    def _route_proxy_rule_for_project_client(self, project: ProjectRecord, client_type: str) -> RouteProxyRule | None:
        return route_proxy_rule_for_project_client(self.route_proxy_settings, project, client_type)

    def _account_pool_group_for_project_client(self, project: ProjectRecord, client_type: str) -> AccountPoolGroup | None:
        return account_pool_group_for_project_client(
            self.route_proxy_settings,
            self.account_pool_settings,
            project,
            client_type,
        )

    def _codex_model_override_for_project(self, project: ProjectRecord) -> str | None:
        return codex_model_override_for_project(
            self.route_proxy_settings,
            self.account_pool_settings,
            project,
        )

    def _claude_model_overrides_for_project(self, project: ProjectRecord) -> tuple[str | None, str | None]:
        return claude_model_overrides_for_project(
            self.route_proxy_settings,
            self.account_pool_settings,
            project,
        )

    def _record_route_proxy_event(self, event: RouteProxyEvent) -> None:
        self.route_proxy_settings.append_event(event)
        if getattr(self, "_proxy_log_render_pending", False):
            return
        self._proxy_log_render_pending = True
        self.root.after(PROXY_LOG_RENDER_DELAY_MS, self._render_proxy_log)

    def _record_route_proxy_token_usage(self, settings: RouteProxySettings) -> None:
        self.route_proxy_settings = settings
        if hasattr(self, "root") and self.root.winfo_exists():
            if getattr(self, "_route_proxy_token_usage_update_pending", False):
                return
            self._route_proxy_token_usage_update_pending = True
            self.root.after(PROXY_STATE_FLUSH_DELAY_MS, self._apply_route_proxy_token_usage_update)

    def _apply_route_proxy_token_usage_update(self) -> None:
        self._route_proxy_token_usage_update_pending = False
        self.persist_state()
        self.refresh_stats_tab()

    def save_route_proxy_settings(self, *, save_project_rules: bool = True) -> bool:
        try:
            form = normalize_route_proxy_settings_form(
                self.route_proxy_settings,
                host_value=self.proxy_host_var.get(),
                port_value=self.proxy_port_var.get(),
                strategy_label=self.proxy_account_pool_strategy_var.get(),
                strategy_values=ROUTE_PROXY_ACCOUNT_POOL_STRATEGY_VALUES,
                upstream_timeout_value=self.proxy_upstream_timeout_var.get(),
            )
        except ValueError as exc:
            messagebox.showerror("更新失败", str(exc), parent=self.root)
            return False
        apply_route_proxy_settings_form(self.route_proxy_settings, form)
        if save_project_rules:
            self._save_selected_route_proxy_project_rules()
        self.persist_state()
        self.refresh_proxy_tab()
        self.status_var.set("路由代理设置已保存。")
        return True

    def _save_selected_route_proxy_project_rules(self) -> None:
        project = self._selected_proxy_project()
        if project is None:
            return
        proxy_group_choices = getattr(self, "proxy_account_pool_group_choices", {})
        proxy_group_var = getattr(self, "proxy_account_pool_group_var", None)
        claude_group_choices = getattr(self, "proxy_claude_account_pool_group_choices", {})
        claude_group_var = getattr(self, "proxy_claude_account_pool_group_var", None)
        form = resolve_route_proxy_project_rule_form(
            self.account_pool_settings,
            codex_protocol=self.proxy_codex_protocol_var.get(),
            codex_source_label=self.proxy_codex_upstream_source_var.get(),
            codex_source_values=CODEX_ROUTE_PROXY_UPSTREAM_SOURCE_VALUES,
            codex_group_label=proxy_group_var.get() if proxy_group_var is not None else "",
            codex_group_choices=proxy_group_choices,
            claude_protocol=self.proxy_claude_protocol_var.get(),
            claude_source_label=self.proxy_claude_upstream_source_var.get(),
            claude_source_values=CODEX_ROUTE_PROXY_UPSTREAM_SOURCE_VALUES,
            claude_group_label=claude_group_var.get() if claude_group_var is not None else "",
            claude_group_choices=claude_group_choices,
            compact_model=self.proxy_codex_compact_model_var.get().strip(),
        )
        codex_profile = self._profile_by_id(project_codex_profile_id(project))
        claude_profile = self._profile_by_id(project_claude_profile_id(project))
        apply_route_proxy_project_rules(
            self.route_proxy_settings,
            project,
            codex_protocol=form.codex_protocol,
            codex_source=form.codex_source,
            codex_account_pool_group_id=form.codex_account_pool_group_id,
            claude_protocol=form.claude_protocol,
            claude_source=form.claude_source,
            claude_account_pool_group_id=form.claude_account_pool_group_id,
            compact_model=form.compact_model,
            codex_profile=codex_profile,
            claude_profile=claude_profile,
            codex_pool_model=form.codex_pool_model,
            claude_pool_model=form.claude_pool_model,
        )

    def start_route_proxy(self, show_errors: bool = True) -> None:
        if not self.save_route_proxy_settings(save_project_rules=show_errors):
            return
        self.route_proxy_settings.enabled = True
        try:
            self.route_proxy_server.start()
        except Exception as exc:
            self.route_proxy_settings.enabled = False
            if show_errors:
                messagebox.showerror("启动失败", f"路由代理启动失败：\n{exc}", parent=self.root)
            self.status_var.set(route_proxy_start_failed_status())
            self.persist_state()
            return
        self.persist_state()
        self.refresh_proxy_tab()
        self.status_var.set(route_proxy_started_status(self.route_proxy_settings))

    def stop_route_proxy(self) -> None:
        self.route_proxy_server.stop()
        self.route_proxy_settings.enabled = False
        self.persist_state()
        self.refresh_proxy_tab()
        self.status_var.set(route_proxy_stopped_status())

    def _record_account_pool_update(self, settings: AccountPoolSettings) -> None:
        self.account_pool_settings = settings
        if hasattr(self, "root") and self.root.winfo_exists():
            if getattr(self, "_account_pool_update_pending", False):
                return
            self._account_pool_update_pending = True
            self.root.after(PROXY_STATE_FLUSH_DELAY_MS, self._apply_account_pool_update)

    def _apply_account_pool_update(self) -> None:
        self._account_pool_update_pending = False
        self.persist_state()
        self.refresh_account_pool_tab()
        self.refresh_proxy_tab()

    def _on_account_pool_group_changed(self, _event: object | None = None) -> None:
        group_id = self.account_pool_group_choices.get(self.account_pool_group_var.get())
        if not group_id:
            return
        self.account_pool_settings.selected_group_id = group_id
        group = self.account_pool_settings.group_by_id(group_id)
        if group is not None:
            self.account_pool_group_enabled_var.set(group.enabled)
            self.account_pool_group_type_var.set(
                ACCOUNT_POOL_GROUP_TYPE_LABELS.get(group.pool_type, ACCOUNT_POOL_GROUP_TYPE_LABELS[ACCOUNT_POOL_GROUP_TYPE_CODEX])
            )
            self.account_pool_group_default_model_var.set(group.default_model or DEFAULT_CODEX_MODEL)
            self.account_pool_group_claude_model_var.set(group.claude_model or DEFAULT_CLAUDE_MODEL)
            self.account_pool_group_claude_fallback_model_var.set(
                group.claude_fallback_model or DEFAULT_CLAUDE_FALLBACK_MODEL
            )
        self.refresh_account_pool_tab()

    def save_account_pool_group_settings(self) -> None:
        group = self._selected_account_pool_group()
        if group is None:
            return
        update = resolve_account_pool_group_settings_update(
            enabled=self.account_pool_group_enabled_var.get(),
            group_type_label=self.account_pool_group_type_var.get(),
            default_model_value=self.account_pool_group_default_model_var.get(),
            claude_model_value=self.account_pool_group_claude_model_var.get(),
            claude_fallback_model_value=self.account_pool_group_claude_fallback_model_var.get(),
        )
        apply_account_pool_group_settings(group, update)
        self.persist_state()
        self.refresh_account_pool_tab()
        self.refresh_proxy_tab()
        self.status_var.set(f"已保存号池组：{group.name}")

    def add_account_pool_group(self) -> None:
        name = simpledialog.askstring("新建号池组", "请输入号池组名称：", parent=self.root)
        if not name or not name.strip():
            return
        group = self.account_pool_settings.add_group(name.strip())
        self.persist_state()
        self.refresh_account_pool_tab()
        self.refresh_proxy_tab()
        self.status_var.set(f"已新建号池组：{group.name}")

    def delete_account_pool_group(self) -> None:
        group = self._selected_account_pool_group()
        if group is None:
            return
        delete_error = account_pool_group_delete_error(self.account_pool_settings, group.id)
        if delete_error == "至少保留一个号池组。":
            messagebox.showinfo("提示", delete_error, parent=self.root)
            return
        if delete_error:
            messagebox.showerror("无法删除", delete_error, parent=self.root)
            return
        if not messagebox.askyesno("确认删除", f"确定要删除号池组“{group.name}”吗？", parent=self.root):
            return
        self.account_pool_settings.remove_group(group.id)
        self.persist_state()
        self.refresh_account_pool_tab()
        self.refresh_proxy_tab()
        self.status_var.set(f"已删除号池组：{group.name}")

    def save_account_pool_settings(self) -> None:
        self.account_pool_settings.enabled = self.account_pool_enabled_var.get()
        self.persist_state()
        self.refresh_account_pool_tab()
        self.refresh_proxy_tab()
        self.status_var.set("已保存号池设置。")

    def _check_account_pool_channel(self, channel: AccountPoolChannel) -> HealthResult:
        validator = getattr(self, "account_pool_validator", None) or getattr(self, "health_checker", None)
        return check_account_pool_channel(
            channel,
            settings=self.account_pool_settings,
            validator=validator,
        )

    def _prepare_account_pool_channel_submission(
        self,
        result: dict,
        existing: AccountPoolChannel | None = None,
    ):
        validator = getattr(self, "account_pool_validator", None) or getattr(self, "health_checker", None)
        return prepare_account_pool_channel_submission(
            result,
            selected_group_id=self._selected_account_pool_group_id(),
            settings=self.account_pool_settings,
            existing=existing,
            validator=validator,
        )

    def add_account_pool_channel(self) -> None:
        try:
            dialog = AccountPoolChannelDialog(self.root, group=self._selected_account_pool_group())
        except TypeError:
            dialog = AccountPoolChannelDialog(self.root)
        self.root.wait_window(dialog)
        if not dialog.result:
            return
        submission = self._prepare_account_pool_channel_submission(dialog.result)
        if submission.health_result.status != "healthy":
            messagebox.showerror("真实会话验证失败", submission.health_result.detail, parent=self.root)
            return
        self.account_pool_settings.channels.append(submission.channel)
        self.persist_state()
        self.refresh_account_pool_tab()
        self.status_var.set(f"已新增号池渠道：{submission.channel.name}")

    def add_account_pool_profile_channel(self) -> None:
        group = self._selected_account_pool_group()
        try:
            dialog = AccountPoolProfileChannelDialog(
                self.root,
                self.profiles,
                group_type=group.pool_type if group is not None else ACCOUNT_POOL_GROUP_TYPE_CODEX,
            )
        except TypeError:
            dialog = AccountPoolProfileChannelDialog(self.root, self.profiles)
        self.root.wait_window(dialog)
        if not dialog.result:
            return
        submission = self._prepare_account_pool_channel_submission(dialog.result)
        if submission.health_result.status != "healthy":
            messagebox.showerror("真实会话验证失败", submission.health_result.detail, parent=self.root)
            return
        self.account_pool_settings.channels.append(submission.channel)
        self.persist_state()
        self.refresh_account_pool_tab()
        self.status_var.set(f"已从配置库加入号池：{submission.channel.name}")

    def edit_account_pool_channel(self) -> None:
        channel = self._selected_account_pool_channel()
        if channel is None:
            messagebox.showinfo("提示", "请先选择一个号池渠道。", parent=self.root)
            return
        if channel.source_type == ACCOUNT_POOL_CHANNEL_SOURCE_PROFILE:
            messagebox.showinfo("提示", "配置库号池渠道是加入时的快照；如需更换配置或 Key，请删除后重新加入。", parent=self.root)
            return
        try:
            dialog = AccountPoolChannelDialog(
                self.root,
                channel=channel,
                group=self.account_pool_settings.group_by_id(channel.group_id),
            )
        except TypeError:
            dialog = AccountPoolChannelDialog(self.root, channel=channel)
        self.root.wait_window(dialog)
        if not dialog.result:
            return
        submission = self._prepare_account_pool_channel_submission(dialog.result, existing=channel)
        if submission.health_result.status != "healthy":
            messagebox.showerror("真实会话验证失败", submission.health_result.detail, parent=self.root)
            return
        self.account_pool_settings.replace_channel(submission.channel)
        self.persist_state()
        self.refresh_account_pool_tab()
        self.status_var.set(f"已更新号池渠道：{submission.channel.name}")

    def delete_account_pool_channel(self) -> None:
        channel = self._selected_account_pool_channel()
        if channel is None:
            messagebox.showinfo("提示", "请先选择一个号池渠道。", parent=self.root)
            return
        if not messagebox.askyesno("确认删除", f"确定要删除号池渠道“{channel.name}”吗？", parent=self.root):
            return
        self.account_pool_settings.remove_channel(channel.id)
        self.persist_state()
        self.refresh_account_pool_tab()
        self.status_var.set(f"已删除号池渠道：{channel.name}")

    def retest_account_pool_channel(self) -> None:
        channel = self._selected_account_pool_channel()
        if channel is None:
            messagebox.showinfo("提示", "请先选择一个号池渠道。", parent=self.root)
            return
        if channel.is_normal:
            messagebox.showinfo("提示", "当前渠道状态正常，无需重测异常。", parent=self.root)
            return
        result = self._check_account_pool_channel(channel)
        if result.status == "healthy":
            self.account_pool_settings.mark_recovered(channel.id)
            self.status_var.set(f"号池渠道已恢复：{channel.name}")
        else:
            self.account_pool_settings.mark_failed(channel.id, result.detail)
            messagebox.showerror("重测失败", result.detail, parent=self.root)
        self.persist_state()
        self.refresh_account_pool_tab()

    def enable_route_proxy_for_project(self) -> None:
        project = self._selected_proxy_project()
        if not project:
            messagebox.showinfo("提示", "请先选择一个项目。", parent=self.root)
            return
        codex_profile_id = project_codex_profile_id(project)
        codex_profile = self._profile_by_id(codex_profile_id)
        if codex_profile is None:
            messagebox.showerror("无法启用", "当前项目绑定的 Codex 配置已经不存在。", parent=self.root)
            return
        claude_profile = self._profile_by_id(project_claude_profile_id(project))
        if claude_profile is None:
            messagebox.showerror("无法启用", "当前项目绑定的 Claude 配置已经不存在。", parent=self.root)
            return
        plan = build_route_proxy_project_enable_plan(
            self.route_proxy_settings,
            self.account_pool_settings,
            project,
            codex_profile,
            claude_profile,
        )
        self.proxy_codex_protocol_var.set(plan.codex_protocol)
        self.proxy_claude_protocol_var.set(plan.claude_protocol)
        self.route_proxy_settings = plan.settings
        self._save_selected_route_proxy_project_rules()
        self.persist_state()
        self.refresh_proxy_tab()
        if self._sync_project_api_binding(project):
            self.refresh_project_tab()
            self.refresh_proxy_tab()
            self.status_var.set(plan.success_status)

    def disable_route_proxy_for_project(self) -> None:
        project = self._selected_proxy_project()
        if not project:
            messagebox.showinfo("提示", "请先选择一个项目。", parent=self.root)
            return
        plan = build_route_proxy_project_disable_plan(self.route_proxy_settings, project)
        self.route_proxy_settings = plan.settings
        self.persist_state()
        self.refresh_proxy_tab()
        if self._sync_project_api_binding(project):
            self.refresh_project_tab()
            self.refresh_proxy_tab()
            self.status_var.set(plan.success_status)

    def ensure_window_visible(self) -> None:
        self.root.update_idletasks()
        self.root.deiconify()
        self.root.state("normal")

        width = max(self.root.winfo_width(), 1180)
        height = max(self.root.winfo_height(), 780)
        screen_width = self.root.winfo_screenwidth()
        screen_height = self.root.winfo_screenheight()
        x = max((screen_width - width) // 2, 0)
        y = max((screen_height - height) // 2, 0)
        self.root.geometry(f"{width}x{height}+{x}+{y}")
        self.root.lift()
        try:
            self.root.attributes("-topmost", True)
            self.root.after(300, lambda: self.root.attributes("-topmost", False))
        except tk.TclError:
            pass
        try:
            self.root.focus_force()
        except tk.TclError:
            pass

    def select_global_mcp(self) -> None:
        available_names = self._available_mcp_server_names()
        if not available_names:
            messagebox.showinfo("提示", "尚未保存 MCP 工具，请先到 MCP 配置页新增并保存。", parent=self.root)
            return
        dialog = McpSelectionDialog(
            self.root,
            available_names,
            selected_names=self._selected_global_mcp_server_names(),
            title="选择全局 MCP",
            subtitle="从已保存的 MCP 工具中选择要写入 Codex 全局配置的服务。",
        )
        self.root.wait_window(dialog)
        if dialog.result is None:
            return
        self.global_mcp_server_names = dialog.result
        self.global_mcp_opt_out = not bool(dialog.result)
        self.persist_state()
        self.refresh_global_tab()
        self.refresh_project_tab()
        self.refresh_mcp_tab()
        self.status_var.set("已更新全局 MCP 选择。")

    def clear_global_mcp(self) -> None:
        if not messagebox.askyesno("确认禁用", "禁用后将不会向 Codex 全局配置注入托管 MCP，是否继续？", parent=self.root):
            return
        self.global_mcp_server_names = []
        self.global_mcp_opt_out = True
        self.persist_state()
        self.refresh_global_tab()
        self.refresh_project_tab()
        self.refresh_mcp_tab()
        self.status_var.set("已禁用全局 MCP。")

    def add_mcp_server(self) -> None:
        dialog = McpServerDialog(self.root)
        self.root.wait_window(dialog)
        if dialog.result is None:
            return
        server_name = dialog.result["name"]
        conflict_error = mcp_name_conflict_error(self.mcp_page_servers, server_name)
        if conflict_error:
            messagebox.showerror("名称重复", conflict_error, parent=self.root)
            return
        mutation = mcp_collection_after_upsert(
            self.mcp_page_servers,
            server_name,
            dialog.result["config"],
        )
        self.mcp_page_servers = mutation.page_servers
        self.refresh_mcp_tab(reload_from_state=False)
        if mutation.selected_name:
            self.mcp_tree.selection_set(mutation.selected_name)
            self.mcp_tree.focus(mutation.selected_name)
        self._refresh_mcp_detail()
        self.status_var.set(f"已添加 MCP 工具：{server_name}")

    def edit_mcp_server(self) -> None:
        server_name = self._mcp_selected_name()
        if not server_name:
            messagebox.showinfo("提示", "请先选择一个 MCP 工具。", parent=self.root)
            return
        dialog = McpServerDialog(self.root, server_name, self.mcp_page_servers.get(server_name, {}))
        self.root.wait_window(dialog)
        if dialog.result is None:
            return
        updated_name = dialog.result["name"]
        conflict_error = mcp_name_conflict_error(
            self.mcp_page_servers,
            updated_name,
            current_name=server_name,
        )
        if conflict_error:
            messagebox.showerror("名称重复", conflict_error, parent=self.root)
            return
        mutation = mcp_collection_after_upsert(
            self.mcp_page_servers,
            updated_name,
            dialog.result["config"],
            current_name=server_name,
        )
        self.mcp_page_servers = mutation.page_servers
        self.refresh_mcp_tab(reload_from_state=False)
        if mutation.selected_name:
            self.mcp_tree.selection_set(mutation.selected_name)
            self.mcp_tree.focus(mutation.selected_name)
        self._refresh_mcp_detail()
        self.status_var.set(f"已更新 MCP 工具：{updated_name}")

    def delete_mcp_server(self) -> None:
        server_name = self._mcp_selected_name()
        if not server_name:
            messagebox.showinfo("提示", "请先选择一个 MCP 工具。", parent=self.root)
            return
        if not messagebox.askyesno("确认删除", f"确定要删除 MCP 工具“{server_name}”吗？", parent=self.root):
            return
        mutation = mcp_collection_after_delete(self.mcp_page_servers, server_name)
        self.mcp_page_servers = mutation.page_servers
        self.refresh_mcp_tab(reload_from_state=False)
        if mutation.selected_name:
            self.mcp_tree.selection_set(mutation.selected_name)
            self.mcp_tree.focus(mutation.selected_name)
        self.status_var.set(f"已删除 MCP 工具：{server_name}")

    def save_mcp_servers(self) -> None:
        persist_state = build_mcp_persist_state(
            self.mcp_page_servers,
            self.global_mcp_server_names,
        )
        self.global_mcp_toml = persist_state.global_mcp_toml
        self.global_mcp_server_names = persist_state.global_mcp_server_names
        self.global_mcp_opt_out = persist_state.global_mcp_opt_out
        self.persist_state()
        self.refresh_global_tab()
        self.refresh_project_tab()
        self.refresh_mcp_tab()
        self.status_var.set("已保存 MCP 配置。")

    def restore_default_mcp_servers(self) -> None:
        if not messagebox.askyesno("恢复默认", "确定要恢复默认全局 MCP 配置并保存吗？", parent=self.root):
            return
        self.global_mcp_toml = load_default_global_mcp_toml()
        self.global_mcp_opt_out = False
        self.global_mcp_server_names = None
        self.persist_state()
        self.refresh_global_tab()
        self.refresh_project_tab()
        self.refresh_mcp_tab()
        self.status_var.set("已恢复默认 MCP 配置。")

    def disable_global_mcp_from_page(self) -> None:
        self.clear_global_mcp()

    def save_agents_doc(self) -> None:
        self.agents_doc_text = self.agents_doc_editor.get("1.0", "end-1c")
        self.persist_state()
        self.docs_hint_var.set(f"已保存 AGENTS 模板，共 {len(self.agents_doc_text)} 个字符。")
        self.status_var.set("已保存文档配置。")

    def restore_default_agents_doc(self) -> None:
        self._set_text_content(self.agents_doc_editor, load_default_agents_doc_text())
        self.docs_hint_var.set("已恢复默认模板内容，点击“保存文档”后生效。")
        self.status_var.set("已恢复默认 AGENTS 模板预览。")

    def add_profile(self) -> None:
        initial_vendor = (
            self.library_profile_view
            if self.library_profile_view in {VENDOR_CODEX, VENDOR_CLAUDE, VENDOR_OTHER}
            else None
        )
        dialog = ProfileDialog(self.root, initial_vendor=initial_vendor)
        self.root.wait_window(dialog)
        if not dialog.result:
            return
        profile = Profile.create(**dialog.result)
        self.profiles.append(profile)
        self.selected_profile_id = profile.id
        self.persist_state()
        self.refresh_global_tab()
        self.refresh_library_tab()
        self.refresh_test_tab()
        self.status_var.set(f"已新增配置：{profile.name}")

    def edit_profile(self) -> None:
        profile = self.get_selected_profile()
        if not profile:
            messagebox.showinfo("提示", "请先选择一个配置项。", parent=self.root)
            return
        dialog = ProfileDialog(self.root, profile=profile)
        self.root.wait_window(dialog)
        if not dialog.result:
            return
        updated = replace(
            profile,
            name=dialog.result["name"],
            base_url=dialog.result["base_url"],
            api_keys=dialog.result["api_keys"],
            active_api_key_index=dialog.result["active_api_key_index"],
            model=dialog.result["model"],
            vendor=dialog.result["vendor"],
            codex_model=dialog.result["codex_model"],
            claude_model=dialog.result["claude_model"],
            claude_fallback_model=dialog.result["claude_fallback_model"],
            provider_name=dialog.result["provider_name"],
            category=dialog.result["category"],
            api_provided=dialog.result["api_provided"],
            wire_api=dialog.result["wire_api"],
            custom_headers=dialog.result["custom_headers"],
            requires_sign_in=dialog.result["requires_sign_in"],
            sign_in_url=dialog.result["sign_in_url"],
            last_signed_date=dialog.result["last_signed_date"],
            notes=dialog.result["notes"],
        )
        self.profiles = [updated if item.id == updated.id else item for item in self.profiles]
        self.selected_profile_id = updated.id
        self._normalize_global_profile_ids()
        self.persist_state()
        self.refresh_global_tab()
        self.refresh_library_tab()
        self.refresh_project_tab()
        self.refresh_test_tab()
        self.status_var.set(f"已更新配置：{updated.name}")

    def delete_profile(self) -> None:
        profile = self.get_selected_profile()
        if not profile:
            messagebox.showinfo("提示", "请先选择一个配置项。", parent=self.root)
            return
        bound_projects = [
            project.name
            for project in self.projects
            if profile.id in project_bound_profile_ids(project)
        ]
        if bound_projects:
            messagebox.showerror("无法删除", f"以下项目仍绑定此配置：\n{', '.join(bound_projects)}", parent=self.root)
            return
        if not messagebox.askyesno("确认删除", f"确定要删除配置“{profile.name}”吗？", parent=self.root):
            return
        self.profiles = [item for item in self.profiles if item.id != profile.id]
        if self.selected_profile_id == profile.id:
            self.selected_profile_id = self.profiles[0].id if self.profiles else None
        self._normalize_global_profile_ids()
        self.persist_state()
        self.refresh_global_tab()
        self.refresh_library_tab()
        self.refresh_test_tab()
        self.status_var.set(f"已删除配置：{profile.name}")

    def add_project(self) -> None:
        profiles = self._healthy_profiles()
        prerequisite_error = project_add_prerequisite_error(
            profiles,
            supports_codex=profile_supports_codex,
            supports_claude=profile_supports_claude,
        )
        if prerequisite_error:
            messagebox.showinfo("提示", prerequisite_error, parent=self.root)
            return
        dialog = ProjectDialog(
            self.root,
            profiles=profiles,
            mcp_server_names=self._available_mcp_server_names(),
            skill_sources=self._available_skill_sources(),
            skill_groups=self.skill_groups,
        )
        self.root.wait_window(dialog)
        if not dialog.result:
            return
        duplicate_error = project_duplicate_dir_error(self._project_by_dir(dialog.result["project_dir"]))
        if duplicate_error:
            messagebox.showerror("重复项目", duplicate_error, parent=self.root)
            return
        project = project_from_dialog_result(dialog.result)
        collection = project_collection_after_add(self.projects, project)
        self.projects = collection.projects
        self.selected_project_id = collection.selected_project_id
        self.persist_state()
        self.refresh_project_tab()
        self.status_var.set(f"已新增项目：{project.name}")

    def _sync_project_api_binding(
        self,
        project: ProjectRecord,
        *,
        sync_codex: bool = True,
        sync_claude: bool = True,
    ) -> bool:
        plan = build_project_binding_sync_plan(
            project,
            route_proxy_base_url=self._route_proxy_base_url_for_project(project),
            codex_profile=self._profile_by_id(project_codex_profile_id(project)),
            codex_model_override=self._codex_model_override_for_project(project),
            claude_profile=self._profile_by_id(project_claude_profile_id(project)),
            claude_model_override=self._claude_model_overrides_for_project(project)[0],
            claude_fallback_model_override=self._claude_model_overrides_for_project(project)[1],
            sync_codex=sync_codex,
            sync_claude=sync_claude,
        )
        updated_paths: list[Path] = []
        for task in project_binding_sync_tasks(plan):
            if task.profile is None:
                messagebox.showerror("无法同步", task.missing_message, parent=self.root)
                return False
            try:
                if task.target == "codex":
                    updated_paths.extend(
                        self.project_template_service.sync_api_binding(
                            plan.project_root,
                            task.profile,
                            route_proxy_base_url=plan.route_proxy_base_url,
                            model_override=task.model_override,
                        )
                    )
                else:
                    updated_paths.extend(
                        self.project_template_service.sync_claude_binding(
                            plan.project_root,
                            task.profile,
                            route_proxy_base_url=plan.route_proxy_base_url,
                            model_override=task.model_override,
                            fallback_model_override=task.fallback_model_override,
                        )
                    )
            except Exception as exc:
                messagebox.showerror("同步失败", f"项目记录已保存，但同步 {task.failure_label} 失败：\n{exc}", parent=self.root)
                self.status_var.set(task.failure_status)
                return False

        self.status_var.set(project_binding_sync_status(project.name, updated_paths))
        return True

    def edit_project(self) -> None:
        project = self.get_selected_project()
        if not project:
            messagebox.showinfo("提示", "请先选择一个项目。", parent=self.root)
            return
        dialog = ProjectDialog(
            self.root,
            profiles=self._healthy_profiles(),
            mcp_server_names=self._available_mcp_server_names(),
            skill_sources=self._available_skill_sources(),
            skill_groups=self.skill_groups,
            project=project,
        )
        self.root.wait_window(dialog)
        if not dialog.result:
            return
        duplicate_error = project_duplicate_dir_error(
            self._project_by_dir(dialog.result["project_dir"]),
            current_project_id=project.id,
        )
        if duplicate_error:
            messagebox.showerror("重复项目", duplicate_error, parent=self.root)
            return
        application = build_project_edit_application(
            project,
            dialog.result,
            updated_at=now_iso(),
        )
        updated = application.project
        api_binding_changed = application.sync_codex
        claude_binding_changed = application.sync_claude
        route_proxy_rules_changed = False
        if api_binding_changed or claude_binding_changed:
            route_proxy_rules_changed = self._refresh_route_proxy_rules_for_project(updated)
        collection = project_collection_after_replace(self.projects, updated)
        self.projects = collection.projects
        self.selected_project_id = collection.selected_project_id
        self.persist_state()
        self.refresh_project_tab()
        if route_proxy_rules_changed:
            self.refresh_proxy_tab()
        if api_binding_changed or claude_binding_changed:
            if self._sync_project_api_binding(
                updated,
                sync_codex=api_binding_changed,
                sync_claude=claude_binding_changed,
            ):
                self.refresh_project_tab()
                if route_proxy_rules_changed:
                    self.refresh_proxy_tab()
                    self.status_var.set(f"已同步项目配置并刷新路由代理：{updated.name}")
            return
        self.status_var.set(f"已更新项目：{updated.name}")

    def delete_project(self) -> None:
        project = self.get_selected_project()
        if not project:
            messagebox.showinfo("提示", "请先选择一个项目。", parent=self.root)
            return
        if not messagebox.askyesno("确认删除", f"确定要删除项目“{project.name}”吗？", parent=self.root):
            return
        update = project_collection_after_delete(
            self.projects,
            selected_project_id=self.selected_project_id,
            deleted_project_id=project.id,
        )
        self.projects = update.projects
        self.selected_project_id = update.selected_project_id
        self.persist_state()
        self.refresh_project_tab()
        self.status_var.set(f"已删除项目：{project.name}")

    def _apply_codex_profile_to_global_config(self, profile: Profile, result: GlobalApplyResult) -> bool:
        effective_global_mcp = self._effective_global_mcp_toml()
        try:
            result.codex_backup_dir = self.manager.apply_profile(
                profile,
                global_mcp_toml=effective_global_mcp,
                previous_managed_mcp_server_names=self.applied_global_mcp_server_names,
            )
        except Exception as exc:
            messagebox.showerror("切换失败", f"写入 Codex 配置失败：\n{exc}", parent=self.root)
            self.status_var.set("切换失败")
            return False
        self.applied_global_mcp_server_names = self._safe_mcp_server_names(effective_global_mcp)
        self.global_codex_profile_id = profile.id
        return True

    def _apply_claude_profile_to_global_config(self, profile: Profile, result: GlobalApplyResult) -> bool:
        try:
            result.claude_backup_dir = self.claude_manager.apply_profile(profile)
            result.claude_settings_path = self.claude_manager.settings_path
        except Exception as exc:
            messagebox.showerror("切换失败", f"写入 Claude 配置失败：\n{exc}", parent=self.root)
            self.status_var.set("切换失败")
            return False
        self.global_claude_profile_id = profile.id
        return True

    def _apply_profile_to_global_config(self, profile: Profile) -> GlobalApplyResult | None:
        supports_codex = profile_supports_codex(profile)
        supports_claude = profile_supports_claude(profile)
        apply_error = global_profile_apply_error(
            supports_codex=supports_codex,
            supports_claude=supports_claude,
        )
        if apply_error:
            messagebox.showerror("切换失败", apply_error, parent=self.root)
            return None
        result = GlobalApplyResult()
        if supports_codex and not self._apply_codex_profile_to_global_config(profile, result):
            return None
        if supports_claude and not self._apply_claude_profile_to_global_config(profile, result):
            return None
        self.selected_profile_id = profile.id
        self.persist_state()
        self.refresh_global_tab()
        self.refresh_library_tab()
        self.refresh_test_tab()
        return result

    def _apply_selected_global_profiles(self) -> GlobalApplyResult | None:
        codex_profile = self._profile_from_global_choice(VENDOR_CODEX)
        claude_profile = self._profile_from_global_choice(VENDOR_CLAUDE)
        if not codex_profile and not claude_profile:
            messagebox.showinfo("提示", "请先为 Codex 或 Claude 选择全局 API 配置。", parent=self.root)
            return None
        result = GlobalApplyResult()
        if codex_profile and not self._apply_codex_profile_to_global_config(codex_profile, result):
            return None
        if claude_profile and not self._apply_claude_profile_to_global_config(claude_profile, result):
            return None
        self.selected_profile_id = (codex_profile or claude_profile).id
        self.persist_state()
        self.refresh_global_tab()
        self.refresh_library_tab()
        self.refresh_test_tab()
        return result

    def apply_global_profile(self) -> None:
        result = self._apply_selected_global_profiles()
        if result is None:
            return
        targets = global_apply_targets(result)
        self.status_var.set(f"已写入全局配置：{targets}")
        messagebox.showinfo("写入成功", f"已写入全局配置：{targets}\n\n{global_apply_detail(result)}", parent=self.root)

    def apply_selected_profile(self) -> None:
        profile = self.get_selected_profile()
        if not profile:
            messagebox.showinfo("提示", "请先选择一个配置项。", parent=self.root)
            return
        if not (profile_supports_codex(profile) or profile_supports_claude(profile)):
            messagebox.showinfo("提示", "当前配置不能设为全局配置。", parent=self.root)
            return
        result = self._apply_profile_to_global_config(profile)
        if result is None:
            return
        targets = global_apply_targets(result)
        self.status_var.set(f"已切换到 {profile.name}（{targets}），并已备份原配置。")
        messagebox.showinfo("切换成功", f"已切换到配置“{profile.name}”。\n\n{global_apply_detail(result)}", parent=self.root)

    def _refresh_project_proxy_rules_before_action(self, project: ProjectRecord) -> None:
        if self._refresh_route_proxy_rules_for_project(project):
            self._refresh_route_proxy_upstream_models(project)
            self.persist_state()

    def _run_project_template_spec(self, spec, *, success_message_builder):
        try:
            method = getattr(self.project_template_service, spec.method_name)
            result = method(*spec.args, **spec.kwargs)
        except Exception as exc:
            messagebox.showerror("生成失败", f"{spec.failure_message_prefix}：\n{exc}", parent=self.root)
            self.status_var.set(spec.failure_status)
            return None
        self.refresh_project_tab()
        self.status_var.set(spec.success_status)
        messagebox.showinfo("生成成功", success_message_builder(result), parent=self.root)
        return result

    def generate_project_template(self) -> None:
        project = self.get_selected_project()
        if not project:
            messagebox.showinfo("提示", "请先选择一个项目。", parent=self.root)
            return
        profile = self._profile_by_id(project_codex_profile_id(project))
        if not profile:
            messagebox.showerror("无法生成", "当前项目绑定的 Codex 配置已经不存在。", parent=self.root)
            return
        claude_profile = self._profile_by_id(project_claude_profile_id(project))
        self._refresh_project_proxy_rules_before_action(project)
        project_mcp_toml = self._effective_project_mcp_toml(project)
        claude_model, claude_fallback_model = self._claude_model_overrides_for_project(project)
        plan = build_codex_template_execution_plan(
            project,
            profile,
            claude_profile,
            project_mcp_toml=project_mcp_toml,
            agents_doc_text=self.agents_doc_text,
            route_proxy_base_url=self._route_proxy_base_url_for_project(project),
            available_skill_sources=self._available_skill_sources(),
            codex_model_override=self._codex_model_override_for_project(project),
            claude_model_override=claude_model,
            claude_fallback_model_override=claude_fallback_model,
        )
        spec = build_codex_template_run_spec(plan)
        self._run_project_template_spec(
            spec,
            success_message_builder=lambda result: codex_template_success_message(plan.project_name, result),
        )

    def generate_claude_template(self) -> None:
        project = self.get_selected_project()
        if not project:
            messagebox.showinfo("提示", "请先选择一个项目。", parent=self.root)
            return
        profile = self._profile_by_id(project_claude_profile_id(project))
        if not profile:
            messagebox.showerror("无法生成", "当前项目绑定的 Claude 配置已经不存在。", parent=self.root)
            return
        self._refresh_project_proxy_rules_before_action(project)
        claude_model, claude_fallback_model = self._claude_model_overrides_for_project(project)
        plan = build_claude_template_execution_plan(
            project,
            profile,
            project_mcp_toml=self._effective_project_mcp_toml(project),
            agents_doc_text=self.agents_doc_text,
            route_proxy_base_url=self._route_proxy_base_url_for_project(project),
            model_override=claude_model,
            fallback_model_override=claude_fallback_model,
        )
        spec = build_claude_template_run_spec(plan)
        self._run_project_template_spec(
            spec,
            success_message_builder=lambda result: claude_template_success_message(plan.project_name, result),
        )

    def _edit_project_text_file(self, *, plan, validator) -> None:
        project = self.get_selected_project()
        if not project:
            messagebox.showinfo("提示", "请先选择一个项目。", parent=self.root)
            return
        target = plan.path
        if not target.exists():
            messagebox.showinfo("提示", plan.missing_message, parent=self.root)
            return
        try:
            initial_text = target.read_text(encoding="utf-8")
        except OSError as exc:
            messagebox.showerror("读失败", f"读取配置文件失败：\n{exc}", parent=self.root)
            return
        dialog = McpConfigDialog(
            self.root,
            title=plan.title,
            subtitle=str(target),
            initial_text=initial_text,
            validator=validator,
        )
        self.root.wait_window(dialog)
        if dialog.result is None:
            return
        try:
            target.write_text(dialog.result.rstrip("\n") + "\n", encoding="utf-8")
        except OSError as exc:
            messagebox.showerror("保存失败", f"写入配置文件失败：\n{exc}", parent=self.root)
            return
        self.status_var.set(f"已保存：{target}")

    def edit_project_codex_config(self) -> None:
        project = self.get_selected_project()
        if not project:
            messagebox.showinfo("提示", "请先选择一个项目。", parent=self.root)
            return
        self._edit_project_text_file(
            plan=project_codex_config_edit_plan(project),
            validator=tomllib.loads,
        )

    def edit_project_claude_settings(self) -> None:
        def validate_json(content: str):
            payload = json.loads(content)
            if not isinstance(payload, dict):
                raise ValueError("settings.local.json 必须是一个 JSON object。")
            return payload

        project = self.get_selected_project()
        if not project:
            messagebox.showinfo("提示", "请先选择一个项目。", parent=self.root)
            return
        self._edit_project_text_file(
            plan=project_claude_settings_edit_plan(project),
            validator=validate_json,
        )

    def _get_project_script_path(self, project: ProjectRecord) -> Path:
        return preferred_project_script_path(project)

    def open_project_folder(self) -> None:
        project = self.get_selected_project()
        if not project:
            messagebox.showinfo("提示", "请先选择一个项目。", parent=self.root)
            return
        project_root = project_root_path(project)
        if not project_root.exists():
            messagebox.showerror("打开失败", "项目目录不存在。", parent=self.root)
            return
        try:
            os.startfile(project_root)  # type: ignore[attr-defined]
        except Exception as exc:
            messagebox.showerror("打开失败", f"打开项目文件夹失败：\n{exc}", parent=self.root)
            return
        self.status_var.set(f"已打开项目文件夹：{project.name}")

    def open_project_vscode(self) -> None:
        project = self.get_selected_project()
        if not project:
            messagebox.showinfo("提示", "请先选择一个项目。", parent=self.root)
            return
        plan = project_vscode_launch_plan(project)
        try:
            subprocess.Popen(
                plan.command,
                cwd=project.project_dir,
                creationflags=_CREATE_NEW_CONSOLE,
            )
        except Exception as exc:
            messagebox.showerror("打开失败", f"使用 VS Code 打开项目失败：\n{exc}", parent=self.root)
            return
        self.status_var.set(plan.success_status)

    def open_project_claude_cmd(self) -> None:
        project = self.get_selected_project()
        if not project:
            messagebox.showinfo("提示", "请先选择一个项目。", parent=self.root)
            return
        profile = self._profile_by_id(project_claude_profile_id(project))
        if not profile:
            messagebox.showerror("启动失败", "项目绑定的 Claude 配置已删除。", parent=self.root)
            return
        if not profile_supports_claude(profile):
            messagebox.showerror("启动失败", "项目绑定的配置不支持 Claude。", parent=self.root)
            return
        self._refresh_project_proxy_rules_before_action(project)
        route_proxy_base_url = self._route_proxy_base_url_for_project(project)
        claude_model, claude_fallback_model = self._claude_model_overrides_for_project(project)
        try:
            self.project_template_service.sync_claude_binding(
                project_root_path(project),
                profile,
                route_proxy_base_url=route_proxy_base_url,
                model_override=claude_model,
                fallback_model_override=claude_fallback_model,
            )
        except Exception as exc:
            messagebox.showerror("启动失败", f"同步 Claude settings.local.json 失败：\n{exc}", parent=self.root)
            return
        env = os.environ.copy()
        env.update(
            claude_runtime_env_from_profile(
                profile,
                route_proxy_base_url=route_proxy_base_url,
                model_override=claude_model,
                fallback_model_override=claude_fallback_model,
            )
        )
        plan = project_claude_cmd_launch_plan(project)
        try:
            subprocess.Popen(
                plan.command,
                cwd=project.project_dir,
                env=env,
                creationflags=_CREATE_NEW_CONSOLE,
            )
        except Exception as exc:
            messagebox.showerror("启动失败", f"打开 Claude CMD 失败：\n{exc}", parent=self.root)
            return
        self.status_var.set(plan.success_status)

    def run_project(self) -> None:
        project = self.get_selected_project()
        if not project:
            messagebox.showinfo("提示", "请先选择一个项目。", parent=self.root)
            return
        plan = project_custom_run_launch_plan(project)
        if plan is not None:
            try:
                subprocess.Popen(
                    plan.command,
                    cwd=project.project_dir,
                    creationflags=_CREATE_NEW_CONSOLE,
                )
            except Exception as exc:
                messagebox.showerror("运行失败", f"运行项目命令失败：\n{exc}", parent=self.root)
                return
            self.status_var.set(plan.success_status)
            return
        self.run_project_cmd()

    def run_project_vscode(self) -> None:
        project = self.get_selected_project()
        if not project:
            messagebox.showinfo("提示", "请先选择一个项目。", parent=self.root)
            return
        plan = project_codex_vscode_launch_plan(project)
        if plan.required_path is not None and not plan.required_path.exists():
            messagebox.showinfo("提示", plan.missing_message, parent=self.root)
            return
        try:
            subprocess.Popen(
                plan.command,
                cwd=project.project_dir,
                creationflags=_CREATE_NEW_CONSOLE,
            )
        except Exception as exc:
            messagebox.showerror("运行失败", f"打开 VS Code 脚本失败：\n{exc}", parent=self.root)
            return
        self.status_var.set(plan.success_status)

    def run_project_cmd(self) -> None:
        project = self.get_selected_project()
        if not project:
            messagebox.showinfo("提示", "请先选择一个项目。", parent=self.root)
            return
        self._refresh_project_proxy_rules_before_action(project)
        if not self._sync_project_api_binding(project, sync_claude=False):
            return
        plan = project_codex_cmd_launch_plan(project)
        if plan.required_path is not None and not plan.required_path.exists():
            messagebox.showinfo("提示", plan.missing_message, parent=self.root)
            return
        try:
            subprocess.Popen(
                plan.command,
                cwd=project.project_dir,
                creationflags=_CREATE_NEW_CONSOLE,
            )
        except Exception as exc:
            messagebox.showerror("运行失败", f"打开 CMD 脚本失败：\n{exc}", parent=self.root)
            return
        self.status_var.set(plan.success_status)

    def test_selected_profile(self) -> None:
        profile = self.get_selected_profile()
        if not profile:
            messagebox.showinfo("提示", "请先选择一个配置项。", parent=self.root)
            return
        if not profile.api_provided:
            messagebox.showinfo("提示", "当前配置未提供 API，无法执行健康检测。", parent=self.root)
            return
        self._run_health_check([profile.id])

    def test_all_profiles(self) -> None:
        if not self.profiles:
            messagebox.showinfo("提示", "请先添加配置项。", parent=self.root)
            return
        testable_profiles = [profile for profile in self.profiles if profile.api_provided]
        if not testable_profiles:
            messagebox.showinfo("提示", "当前没有提供 API 的配置项。", parent=self.root)
            return
        self._run_health_check([profile.id for profile in testable_profiles])

    def _run_health_check(self, profile_ids: list[str]) -> None:
        self.status_var.set("正在检测 API 健康状态，请稍候...")

        def worker() -> None:
            for profile_id in profile_ids:
                profile = self._profile_by_id(profile_id)
                if profile is None:
                    continue
                result = self.health_checker.check(profile)
                self.root.after(0, self._apply_health_result, profile_id, result)
            self.root.after(0, self._mark_health_check_complete)

        threading.Thread(target=worker, daemon=True).start()

    def _apply_health_result(self, profile_id: str, result: HealthResult) -> None:
        profile = self._profile_by_id(profile_id)
        if profile is None:
            return
        profile.health = result
        self.persist_state()
        self.refresh_global_tab()
        self.refresh_library_tab()
        self.refresh_test_tab()

    def _mark_health_check_complete(self) -> None:
        self.status_var.set("健康检测已完成，模型测试页会同步显示接口返回模型。")

    def _chat_model_options(self, profile: Profile, wire_api: str | None = None) -> list[str]:
        cache = self._model_batch_cache(profile)
        if cache is not None and cache.completed:
            success_models = successful_model_batch_models(cache)
            return success_models or ["-"]
        models: list[str] = []
        if profile.health.models:
            for model in profile.health.models:
                if model not in models:
                    models.append(model)
        if models:
            return models
        effective_wire_api = wire_api or self.chat_wire_choice_var.get().strip() or default_wire_api_for_profile(profile)
        fallback_model = (
            profile.claude_display_model
            if effective_wire_api == WIRE_API_ANTHROPIC_MESSAGES
            else profile.codex_display_model
        )
        return [fallback_model] if fallback_model else ["-"]

    def _chat_payload_templates(self) -> dict[str, str]:
        templates: dict[str, str] = {}
        for wire_api in SUPPORTED_WIRE_APIS:
            templates[wire_api] = json.dumps(
                self.chat_tester.build_payload_template(wire_api),
                ensure_ascii=False,
                indent=2,
            )
        return templates

    def _refresh_chat_settings_summary(self) -> None:
        self.chat_settings_summary_var.set(
            f"模型：{self.chat_model_choice_var.get() or '-'}    接口：{self.chat_wire_choice_var.get() or '-'}"
        )

    def _has_chat_model_choice(self) -> bool:
        selected_model = self.chat_model_choice_var.get().strip()
        return bool(selected_model and selected_model != "-")

    def _refresh_chat_request_body_template(self, _event: object | None = None) -> None:
        wire_api = self.chat_wire_choice_var.get().strip() or SUPPORTED_WIRE_APIS[0]
        try:
            template = self.chat_tester.build_payload_template(wire_api)
        except ValueError:
            wire_api = SUPPORTED_WIRE_APIS[0]
            self.chat_wire_choice_var.set(wire_api)
            template = self.chat_tester.build_payload_template(wire_api)
        self.chat_request_body_text = json.dumps(template, ensure_ascii=False, indent=2)
        self._refresh_chat_settings_summary()

    def open_chat_settings(self) -> None:
        if self.chat_busy:
            return
        profile = self.get_selected_profile()
        if not profile:
            messagebox.showinfo("提示", "请先选择一套测试配置。", parent=self.root)
            return
        selected_wire = self.chat_wire_choice_var.get().strip() or default_wire_api_for_profile(profile)
        options = self._chat_model_options(profile, selected_wire)
        dialog = ChatSettingsDialog(
            self.root,
            model_values=options,
            selected_model=self.chat_model_choice_var.get().strip(),
            wire_values=SUPPORTED_WIRE_APIS,
            selected_wire=self.chat_wire_choice_var.get().strip() or profile.wire_api,
            payload_text=self.chat_request_body_text,
            payload_templates=self._chat_payload_templates(),
        )
        self.root.wait_window(dialog)
        if dialog.result is None:
            return
        self.chat_model_choice_var.set(dialog.result["model"] or "-")
        self.chat_wire_choice_var.set(dialog.result["wire_api"] or SUPPORTED_WIRE_APIS[0])
        self.chat_request_body_text = dialog.result["payload_text"]
        self._refresh_chat_settings_summary()
        if self.chat_profile_id and self._has_chat_model_choice() and not self.chat_busy:
            self.chat_send_button.state(["!disabled"])
        else:
            self.chat_send_button.state(["disabled"])
        self.status_var.set("已更新聊天测试设置。")

    def _reset_chat_target(self, profile: Profile | None) -> None:
        if profile is None:
            self.chat_profile_id = None
            self.chat_target_var.set("未选择测试配置")
            self.chat_model_choice_var.set("-")
            self.chat_wire_choice_var.set(SUPPORTED_WIRE_APIS[0])
            self._refresh_chat_request_body_template()
            self.chat_send_button.state(["disabled"])
            self.chat_settings_button.state(["disabled"])
            self.clear_chat_history()
            self._append_chat_line("系统", "请选择左侧测试列表中的一套配置，再开始测试对话。")
            return

        keep_history = self.chat_profile_id == profile.id
        current_wire = self.chat_wire_choice_var.get().strip()
        default_wire = default_wire_api_for_profile(profile)
        next_wire = current_wire if keep_history and current_wire in SUPPORTED_WIRE_APIS else default_wire
        options = self._chat_model_options(profile, next_wire)
        current_choice = self.chat_model_choice_var.get().strip()
        next_choice = current_choice if keep_history and current_choice and current_choice != "-" else options[0]
        should_reset_payload = not keep_history or next_wire != current_wire or not self.chat_request_body_text.strip()

        self.chat_profile_id = profile.id
        self.chat_target_var.set(profile.name)
        self.chat_model_choice_var.set(next_choice)
        self.chat_wire_choice_var.set(next_wire)
        if should_reset_payload:
            self._refresh_chat_request_body_template()
        else:
            self._refresh_chat_settings_summary()
        if self._has_chat_model_choice() and not self.chat_busy:
            self.chat_send_button.state(["!disabled"])
        else:
            self.chat_send_button.state(["disabled"])
        if self.chat_busy:
            self.chat_settings_button.state(["disabled"])
        else:
            self.chat_settings_button.state(["!disabled"])

        if not keep_history:
            self.clear_chat_history()
            if options == ["-"]:
                self._append_chat_line("系统", f"当前测试配置：{profile.name}\n还没有可用的 API 返回模型，请先执行健康检测。")
            else:
                self._append_chat_line("系统", f"当前测试配置：{profile.name}\n可选模型：{', '.join(options)}")

    def clear_chat_history(self) -> None:
        self.chat_history.configure(state="normal")
        self.chat_history.delete("1.0", "end")
        self.chat_history.configure(state="disabled")

    def _append_chat_line(self, role: str, text: str) -> None:
        self.chat_history.configure(state="normal")
        prefix = "你" if role == "用户" else ("接口" if role == "助手" else role)
        self.chat_history.insert("end", f"{prefix}\n", ("role",))
        self.chat_history.insert("end", f"{text.strip()}\n\n", ("body",))
        self.chat_history.tag_configure("role", foreground=PALETTE["chat_meta"], font=("Microsoft YaHei UI", 9, "bold"))
        self.chat_history.tag_configure("body", foreground=PALETTE["text"], font=self.body_font, spacing3=4)
        self.chat_history.configure(state="disabled")
        self.chat_history.see("end")

    def send_chat_message(self) -> None:
        if self.chat_busy:
            return
        profile = self.get_selected_profile()
        if not profile:
            messagebox.showinfo("提示", "请先选择一套测试配置。", parent=self.root)
            return
        prompt = self.chat_input.get("1.0", "end").strip()
        if not prompt:
            messagebox.showinfo("提示", "请输入测试消息。", parent=self.root)
            return
        self._reset_chat_target(profile)
        selected_model = self.chat_model_choice_var.get().strip()
        if not selected_model or selected_model == "-":
            messagebox.showinfo("提示", "请选择一个测试模型。", parent=self.root)
            return
        selected_wire_api = self.chat_wire_choice_var.get().strip() or profile.wire_api
        payload_text = self.chat_request_body_text.strip() or None
        self._append_chat_line("用户", prompt)
        self.chat_input.delete("1.0", "end")
        self._set_chat_busy(True)
        self.status_var.set(f"正在使用 {profile.name} / {selected_model} / {selected_wire_api} 测试对话...")

        def worker() -> None:
            try:
                result = self.chat_tester.send_message(
                    profile,
                    prompt,
                    model_override=selected_model,
                    wire_api_override=selected_wire_api,
                    payload_override_text=payload_text,
                )
            except Exception as exc:
                result = ChatResult(ok=False, text=f"测试异常：{exc}", model=selected_model)
            self.root.after(0, self._handle_chat_result, profile.id, result)

        threading.Thread(target=worker, daemon=True).start()

    def _handle_chat_result(self, profile_id: str, result: ChatResult) -> None:
        self._set_chat_busy(False)
        if self.chat_profile_id != profile_id:
            return
        if result.ok:
            self._append_chat_line("助手", result.text)
            self.status_var.set(f"测试对话已完成，模型：{result.model or '-'}")
        else:
            detail = f"\n\n明细：{result.detail}" if result.detail else ""
            self._append_chat_line("系统", f"{result.text}{detail}")
            self.status_var.set(result.text)

    def test_selected_api_models(self) -> None:
        if self.model_batch_busy:
            running_profile = self._profile_by_id(self.model_batch_running_profile_id)
            running_cache = self._model_batch_cache(running_profile)
            if running_profile is not None and running_cache is not None:
                self._open_model_batch_dialog(running_profile, running_cache)
            return
        profile = self.get_selected_profile()
        if not profile:
            messagebox.showinfo("提示", "请先选择一套测试配置。", parent=self.root)
            return
        models = self._batch_model_options(profile)
        if not models:
            messagebox.showinfo("提示", "最近健康检测尚未返回模型列表，请先执行健康检测。", parent=self.root)
            return
        cached = self._model_batch_cache(profile)
        if cached is not None:
            self._open_model_batch_dialog(profile, cached)
            return
        self._start_model_batch_test(profile)

    def show_success_models(self) -> None:
        profile = self.get_selected_profile()
        models = self._successful_models_for_profile(profile)
        if profile is None or not models:
            messagebox.showinfo("提示", "当前 API 暂无成功模型。", parent=self.root)
            return
        dialog = SuccessfulModelsDialog(
            self.root,
            profile_name=profile.name,
            models=models,
            copy_command=self.copy_to_clipboard,
        )
        dialog.focus_set()
        dialog.lift()

    def _start_model_batch_test(self, profile: Profile) -> None:
        models = self._batch_model_options(profile)
        if not models:
            messagebox.showinfo("提示", "最近健康检测尚未返回模型列表，请先执行健康检测。", parent=self.root)
            return
        wire_api = self.chat_wire_choice_var.get().strip() or profile.wire_api
        payload_text = self.chat_request_body_text.strip() or None
        max_workers = self.model_batch_concurrency
        self.model_batch_profile_id = profile.id
        self.model_batch_running_profile_id = profile.id
        cache = self._create_model_batch_cache(profile)
        self._open_model_batch_dialog(profile, cache)
        self._set_model_batch_busy(True)
        self._refresh_model_batch_health_display(profile.id)
        self.status_var.set(f"正在批量测试 {profile.name} 的 {len(models)} 个模型...")

        def worker() -> None:
            run_model_batch_requests(
                self.chat_tester,
                profile,
                models,
                wire_api,
                payload_text,
                lambda model: self.root.after(0, self._apply_model_batch_result, profile.id, model, "running", ""),
                lambda model, status, detail, duration_ms: self.root.after(0, self._apply_model_batch_result, profile.id, model, status, detail, duration_ms),
                max_workers=max_workers,
            )
            self.root.after(0, self._mark_model_batch_complete, profile.id)

        threading.Thread(target=worker, daemon=True).start()

    def _restart_model_batch_test(self, profile_id: str) -> None:
        if self.model_batch_busy:
            return
        profile = self._profile_by_id(profile_id)
        if profile is None:
            return
        self.model_batch_cache_by_profile.pop(profile_id, None)
        self.persist_state()
        self._start_model_batch_test(profile)

    def _open_model_batch_dialog(self, profile: Profile, cache: ModelBatchCache) -> None:
        if (
            self.model_batch_dialog is not None
            and self.model_batch_dialog.winfo_exists()
            and self.model_batch_dialog_profile_id == profile.id
        ):
            dialog = self.model_batch_dialog
            dialog.lift()
        else:
            if self.model_batch_dialog is not None and self.model_batch_dialog.winfo_exists():
                self.model_batch_dialog.destroy()
            dialog = ModelBatchTestDialog(
                self.root,
                profile_name=profile.name,
                models=ordered_model_batch_models(cache.models, cache.results, cache.completed),
                retest_command=lambda profile_id=profile.id: self._restart_model_batch_test(profile_id),
            )
            dialog.bind("<Destroy>", lambda event, active_dialog=dialog: self._clear_model_batch_dialog(active_dialog, event), add="+")
            self.model_batch_dialog = dialog
            self.model_batch_dialog_profile_id = profile.id
        self._render_model_batch_dialog(cache)

    def _render_model_batch_dialog(self, cache: ModelBatchCache) -> None:
        if self.model_batch_dialog is None or not self.model_batch_dialog.winfo_exists():
            return
        ordered_models = ordered_model_batch_models(cache.models, cache.results, cache.completed)
        self.model_batch_dialog.render_models(ordered_models)
        for model in ordered_models:
            result = cache.results.get(model, ModelBatchResult())
            self.model_batch_dialog.set_status(model, result.status, result.detail, result.duration_ms)
        self._refresh_model_batch_dialog_summary(running=not cache.completed)
        self.model_batch_dialog.set_retest_enabled(cache.completed and not self.model_batch_busy)

    def _set_model_batch_busy(self, busy: bool) -> None:
        self.model_batch_busy = busy
        self._sync_model_batch_button(self.get_selected_profile())

    def _clear_model_batch_dialog(self, dialog: ModelBatchTestDialog, event: tk.Event) -> None:
        if event.widget is dialog and self.model_batch_dialog is dialog:
            self.model_batch_dialog = None
            self.model_batch_dialog_profile_id = None

    def _apply_model_batch_result(self, profile_id: str, model: str, status: str, detail: str = "", duration_ms: int | None = None) -> None:
        if profile_id != self.model_batch_running_profile_id:
            return
        cache = self.model_batch_cache_by_profile.get(profile_id)
        if cache is None:
            return
        cache.results[model] = ModelBatchResult(status=status, detail=detail, duration_ms=duration_ms)
        if self.model_batch_dialog is not None and self.model_batch_dialog.winfo_exists() and self.model_batch_dialog_profile_id == profile_id:
            self.model_batch_dialog.set_status(model, status, detail, duration_ms)
            self._refresh_model_batch_dialog_summary(running=True)
        self._refresh_model_batch_health_display(profile_id)

    def _mark_model_batch_complete(self, profile_id: str) -> None:
        if profile_id != self.model_batch_running_profile_id:
            return
        cache = self.model_batch_cache_by_profile.get(profile_id)
        if cache is None:
            return
        cache.completed = True
        cache.tested_at = now_iso()
        self.model_batch_busy = False
        self.model_batch_running_profile_id = None
        self.persist_state()
        self._sync_model_batch_button(self.get_selected_profile())
        self._render_model_batch_dialog(cache)
        self._refresh_model_batch_health_display(profile_id)
        profile = self._profile_by_id(profile_id)
        if profile is not None and self.selected_profile_id == profile_id:
            self._reset_chat_target(profile)
        success_count, error_count = self._model_batch_counts(cache)
        self.status_var.set(f"模型批量测试完成：成功 {success_count} 个，失败 {error_count} 个。")

    def _refresh_model_batch_dialog_summary(self, *, running: bool) -> None:
        if self.model_batch_dialog is None or not self.model_batch_dialog.winfo_exists():
            return
        cache = self.model_batch_cache_by_profile.get(self.model_batch_dialog_profile_id or "")
        if cache is None:
            return
        success_count, error_count = self._model_batch_counts(cache)
        self.model_batch_dialog.set_summary(
            total=len(cache.models),
            success_count=success_count,
            error_count=error_count,
            running=running,
        )

    def _set_chat_busy(self, busy: bool) -> None:
        self.chat_busy = busy
        if busy:
            self.chat_send_button.state(["disabled"])
            self.chat_settings_button.state(["disabled"])
        else:
            profile = self.get_selected_profile()
            if profile:
                self.chat_settings_button.state(["!disabled"])
            else:
                self.chat_settings_button.state(["disabled"])
            if self.chat_profile_id and self._has_chat_model_choice():
                self.chat_send_button.state(["!disabled"])
            else:
                self.chat_send_button.state(["disabled"])

    def copy_to_clipboard(self, value: str) -> None:
        self.root.clipboard_clear()
        self.root.clipboard_append(value)
        self.root.update()
        self.status_var.set(f"已复制：{value}")


def run_app() -> None:
    if not _acquire_single_instance():
        _show_single_instance_message()
        return
    root = BootstrapWindow(themename=BOOTSTRAP_THEME) if BootstrapWindow is not None else tk.Tk()
    try:
        app = CodexSwitchApp(root)
        app.ensure_window_visible()
        try:
            root.mainloop()
        except KeyboardInterrupt:
            try:
                root.destroy()
            except tk.TclError:
                pass
    finally:
        _release_single_instance()
