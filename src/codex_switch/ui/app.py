from __future__ import annotations

from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from dataclasses import dataclass, replace
from importlib.metadata import PackageNotFoundError, version as package_version
from pathlib import Path
from time import perf_counter
import ctypes
from ctypes import wintypes
import json
import os
import platform
import subprocess
import threading
import tkinter as tk
import tomllib
import webbrowser
import sys
from tkinter import font as tkfont
from tkinter import messagebox

from codex_switch import __version__
from codex_switch.chat import SUPPORTED_WIRE_APIS, ChatResult, ChatTester
from codex_switch.codex_config import (
    CodexConfigManager,
    PROJECT_ROOT_PLACEHOLDER,
    load_default_global_mcp_toml,
    mcp_server_names_from_toml,
    parse_mcp_servers_toml,
    render_mcp_servers_toml,
)
from codex_switch.health import HealthChecker
from codex_switch.models import (
    CurrentCodexConfig,
    HealthResult,
    Profile,
    ProjectRecord,
    RouteProxyEvent,
    RouteProxyRule,
    RouteProxySettings,
    ROUTE_PROXY_CLIENT_CLAUDE,
    ROUTE_PROXY_CLIENT_CODEX,
    ROUTE_PROXY_PLACEHOLDER_KEY,
    ROUTE_PROXY_PROTOCOL_ANTHROPIC,
    ROUTE_PROXY_PROTOCOL_ANTHROPIC_TO_OPENAI,
    ROUTE_PROXY_PROTOCOL_OPENAI,
    ROUTE_PROXY_PROTOCOL_OPENAI_CHAT_TO_RESPONSES,
    ROUTE_PROXY_PROTOCOL_OPENAI_RESPONSES_TO_CHAT,
    VENDOR_CLAUDE,
    VENDOR_CODEX,
    VENDOR_GENERIC,
    VENDOR_OTHER,
    normalize_route_proxy_port,
    now_iso,
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
    ProjectTemplateService,
    apply_claude_profile_env,
    load_default_agents_doc_text,
)
from codex_switch.storage import (
    DEFAULT_MODEL_BATCH_CONCURRENCY,
    MODEL_BATCH_CONCURRENCY_MAX,
    MODEL_BATCH_CONCURRENCY_MIN,
    ProfileStore,
    clamp_model_batch_concurrency,
)
from codex_switch.ui.dialogs import (
    ChatSettingsDialog,
    McpConfigDialog,
    McpServerDialog,
    ModelBatchTestDialog,
    ProfileDialog,
    ProjectDialog,
    SuccessfulModelsDialog,
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
from codex_switch.ui.utils import compact_text, hidden_secret, is_http_url, project_start_script_paths, resolve_mcp_editor_text


_SINGLE_INSTANCE_HANDLE = None
_CREATE_NEW_CONSOLE = getattr(subprocess, "CREATE_NEW_CONSOLE", 0)
MODEL_BATCH_PROMPT = "ping"
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


@dataclass
class ModelBatchResult:
    status: str = "pending"
    detail: str = ""
    duration_ms: int | None = None


@dataclass
class ModelBatchCache:
    models: list[str]
    results: dict[str, ModelBatchResult]
    completed: bool = False
    tested_at: str | None = None


def visible_profiles_for_filter(profiles: list[Profile], hide_error_profiles: bool) -> list[Profile]:
    if not hide_error_profiles:
        return list(profiles)
    return [profile for profile in profiles if profile.effective_health_status != "error"]


def profiles_for_library_view(profiles: list[Profile], profile_view: str) -> list[Profile]:
    if profile_view == LIBRARY_VIEW_ALL:
        return list(profiles)
    if profile_view == VENDOR_CODEX:
        return [profile for profile in profiles if profile_supports_codex(profile)]
    if profile_view == VENDOR_CLAUDE:
        return [profile for profile in profiles if profile_supports_claude(profile)]
    if profile_view == VENDOR_OTHER:
        return [profile for profile in profiles if profile.vendor == VENDOR_OTHER]
    return []


def profile_library_sort_key(profile: Profile) -> tuple[int, str, str]:
    sign_in_rank = {
        "未签到": 0,
        "已签到": 1,
        "无需签到": 2,
    }.get(profile.sign_in_status, 3)
    return sign_in_rank, profile.name.casefold(), profile.id


def model_batch_targets(profile: Profile | None) -> list[str]:
    if profile is None:
        return []
    models: list[str] = []
    for model in profile.health.models:
        model_name = str(model).strip()
        if model_name and model_name not in models:
            models.append(model_name)
    return models


def ordered_model_batch_models(models: list[str], results: dict[str, ModelBatchResult], completed: bool) -> list[str]:
    if not completed:
        return list(models)
    order = {model: index for index, model in enumerate(models)}
    return sorted(models, key=lambda model: (0 if results.get(model, ModelBatchResult()).status == "success" else 1, order.get(model, 0)))


def successful_model_batch_models(cache: ModelBatchCache | None) -> list[str]:
    if cache is None or not cache.completed:
        return []
    return [model for model in ordered_model_batch_models(cache.models, cache.results, True) if cache.results.get(model, ModelBatchResult()).status == "success"]


def route_proxy_rules_for_project(
    project: ProjectRecord,
    codex_profile: Profile,
    claude_profile: Profile,
    codex_protocol: str,
    claude_protocol: str,
) -> list[RouteProxyRule]:
    codex_conversion_protocols = {
        ROUTE_PROXY_PROTOCOL_OPENAI_CHAT_TO_RESPONSES,
        ROUTE_PROXY_PROTOCOL_OPENAI_RESPONSES_TO_CHAT,
    }
    codex_upstream_model = (
        codex_profile.codex_display_model
        if codex_protocol in codex_conversion_protocols
        else ""
    )
    claude_upstream_model = (
        claude_profile.claude_display_model
        if claude_protocol == ROUTE_PROXY_PROTOCOL_ANTHROPIC_TO_OPENAI
        else ""
    )
    return [
        RouteProxyRule.create(
            project_id=project.id,
            client_type=ROUTE_PROXY_CLIENT_CODEX,
            primary_profile_id=codex_profile.id,
            upstream_protocol=codex_protocol,
            upstream_model=codex_upstream_model,
        ),
        RouteProxyRule.create(
            project_id=project.id,
            client_type=ROUTE_PROXY_CLIENT_CLAUDE,
            primary_profile_id=claude_profile.id,
            upstream_protocol=claude_protocol,
            upstream_model=claude_upstream_model,
        ),
    ]


def route_proxy_codex_wire_api_override(protocol: str) -> str | None:
    if protocol == ROUTE_PROXY_PROTOCOL_OPENAI_CHAT_TO_RESPONSES:
        return "chat_completions"
    if protocol == ROUTE_PROXY_PROTOCOL_OPENAI_RESPONSES_TO_CHAT:
        return "responses"
    return None


def model_batch_caches_from_payload(payload) -> dict[str, ModelBatchCache]:
    if not isinstance(payload, dict):
        return {}

    caches: dict[str, ModelBatchCache] = {}
    for profile_id, cache_payload in payload.items():
        if not str(profile_id).strip() or not isinstance(cache_payload, dict):
            continue
        if not bool(cache_payload.get("completed", False)):
            continue

        raw_models = cache_payload.get("models", [])
        if not isinstance(raw_models, list):
            continue
        models = [str(model).strip() for model in raw_models if str(model).strip()]
        if not models:
            continue

        raw_results = cache_payload.get("results", {})
        if not isinstance(raw_results, dict):
            raw_results = {}
        results: dict[str, ModelBatchResult] = {}
        for model in models:
            result_payload = raw_results.get(model, {})
            if not isinstance(result_payload, dict):
                result_payload = {}
            status = str(result_payload.get("status", "pending") or "pending")
            if status not in {"pending", "running", "success", "error"}:
                status = "pending"
            raw_duration_ms = result_payload.get("duration_ms")
            try:
                duration_ms = int(raw_duration_ms) if raw_duration_ms is not None else None
            except (TypeError, ValueError):
                duration_ms = None
            if duration_ms is not None and duration_ms < 0:
                duration_ms = None
            results[model] = ModelBatchResult(
                status=status,
                detail=str(result_payload.get("detail", "") or ""),
                duration_ms=duration_ms,
            )

        caches[str(profile_id)] = ModelBatchCache(
            models=models,
            results=results,
            completed=True,
            tested_at=str(cache_payload.get("tested_at") or "") or None,
        )
    return caches


def model_batch_caches_to_payload(caches: dict[str, ModelBatchCache]) -> dict[str, dict]:
    payload: dict[str, dict] = {}
    for profile_id, cache in caches.items():
        if not cache.completed:
            continue
        models = [str(model).strip() for model in cache.models if str(model).strip()]
        if not models:
            continue
        results_payload: dict[str, dict] = {}
        for model in models:
            result = cache.results.get(model, ModelBatchResult())
            results_payload[model] = {
                "status": result.status,
                "detail": result.detail,
                "duration_ms": result.duration_ms,
            }
        payload[str(profile_id)] = {
            "models": models,
            "results": results_payload,
            "completed": True,
            "tested_at": cache.tested_at,
        }
    return payload


def run_model_batch_requests(
    chat_tester: ChatTester,
    profile: Profile,
    models: list[str],
    wire_api: str,
    payload_text: str | None,
    on_start,
    on_result,
    *,
    max_workers: int = DEFAULT_MODEL_BATCH_CONCURRENCY,
) -> None:
    if not models:
        return

    worker_count = max(1, min(max_workers, len(models)))

    def test_model(model: str) -> tuple[str, str, str, int]:
        started = perf_counter()
        try:
            result = chat_tester.send_message(
                profile,
                MODEL_BATCH_PROMPT,
                model_override=model,
                wire_api_override=wire_api,
                payload_override_text=payload_text,
            )
            status = "success" if result.ok else "error"
            detail = result.text
            if result.detail:
                detail = f"{detail}  {result.detail}"
        except Exception:
            status = "error"
            detail = "测试异常"
        duration_ms = int((perf_counter() - started) * 1000)
        return model, status, detail, duration_ms

    with ThreadPoolExecutor(max_workers=worker_count) as executor:
        pending_models = iter(models)
        future_by_model = {}

        def submit_next() -> None:
            try:
                model = next(pending_models)
            except StopIteration:
                return
            on_start(model)
            future_by_model[executor.submit(test_model, model)] = model

        for _ in range(worker_count):
            submit_next()

        while future_by_model:
            done, _ = wait(future_by_model, return_when=FIRST_COMPLETED)
            for future in done:
                model = future_by_model.pop(future)
                try:
                    result_model, status, detail, duration_ms = future.result()
                except Exception:
                    result_model, status, detail, duration_ms = model, "error", "测试异常", 0
                on_result(result_model, status, detail, duration_ms)
                submit_next()


def _has_visible_codex_window() -> bool:
    if os.name != "nt":
        return False
    try:
        user32 = ctypes.windll.user32
        user32.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
        user32.FindWindowW.restype = wintypes.HWND
        user32.IsWindowVisible.argtypes = [wintypes.HWND]
        user32.IsWindowVisible.restype = wintypes.BOOL
        is_hung = getattr(user32, "IsHungAppWindow", None)
        hwnd = user32.FindWindowW(None, "Codex Switch")
        if not hwnd:
            return False
        if not user32.IsWindowVisible(hwnd):
            return False
        if is_hung and is_hung(hwnd):
            return False
        return True
    except Exception:
        return False


def _activate_existing_codex_window() -> bool:
    if os.name != "nt":
        return False
    try:
        user32 = ctypes.windll.user32
        user32.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
        user32.FindWindowW.restype = wintypes.HWND
        user32.IsWindowVisible.argtypes = [wintypes.HWND]
        user32.IsWindowVisible.restype = wintypes.BOOL
        user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
        user32.ShowWindow.restype = wintypes.BOOL
        user32.SetForegroundWindow.argtypes = [wintypes.HWND]
        user32.SetForegroundWindow.restype = wintypes.BOOL
        user32.BringWindowToTop.argtypes = [wintypes.HWND]
        user32.BringWindowToTop.restype = wintypes.BOOL
        is_hung = getattr(user32, "IsHungAppWindow", None)
        hwnd = user32.FindWindowW(None, "Codex Switch")
        if not hwnd:
            return False
        if not user32.IsWindowVisible(hwnd):
            return False
        if is_hung and is_hung(hwnd):
            return False

        SW_RESTORE = 9
        user32.ShowWindow(hwnd, SW_RESTORE)
        user32.SetForegroundWindow(hwnd)
        user32.BringWindowToTop(hwnd)
        return True
    except Exception:
        return False


def _acquire_single_instance() -> bool:
    global _SINGLE_INSTANCE_HANDLE
    if os.name != "nt":
        return True
    try:
        if _SINGLE_INSTANCE_HANDLE is not None:
            return True
        mutex_name = "Global\\CodexSwitchSingleInstance"
        handle = ctypes.windll.kernel32.CreateMutexW(None, False, mutex_name)
        if not handle:
            return True
        if ctypes.windll.kernel32.GetLastError() == 183:
            if _has_visible_codex_window():
                ctypes.windll.kernel32.CloseHandle(handle)
                return False
        _SINGLE_INSTANCE_HANDLE = handle
        return True
    except Exception:
        return True


def _release_single_instance() -> None:
    global _SINGLE_INSTANCE_HANDLE
    if os.name != "nt" or _SINGLE_INSTANCE_HANDLE is None:
        return
    try:
        ctypes.windll.kernel32.CloseHandle(_SINGLE_INSTANCE_HANDLE)
    finally:
        _SINGLE_INSTANCE_HANDLE = None


def _show_single_instance_message() -> None:
    root = tk.Tk()
    root.withdraw()
    try:
        messagebox.showinfo("Codex Switch", "Codex Switch 已经在运行。")
    finally:
        root.destroy()


class CodexSwitchApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("Codex Switch")
        self.root.geometry("1360x900")
        self.root.minsize(1180, 780)
        self.root.configure(bg=PALETTE["panel_bg"])

        self.project_root = Path.cwd()
        self.store = ProfileStore()
        self.manager = CodexConfigManager()
        self.project_template_service = ProjectTemplateService()
        self.health_checker = HealthChecker()
        self.chat_tester = ChatTester()

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
        else:
            self.profiles, self.selected_profile_id = load_state  # type: ignore[misc]
            self.projects = []
            self.selected_project_id = None
            self.hide_error_profiles = False
            self.global_mcp_toml = load_default_global_mcp_toml()
            self.applied_global_mcp_server_names = []
            self.global_mcp_opt_out = False
            self.agents_doc_text = load_default_agents_doc_text()
            self.model_batch_concurrency = DEFAULT_MODEL_BATCH_CONCURRENCY
            raw_model_batch_cache_by_profile = {}
            self.route_proxy_settings = RouteProxySettings()
        self.mcp_page_servers: dict[str, dict] = {}
        self.route_proxy_server = RouteProxyServer(
            lambda: self.route_proxy_settings,
            lambda: self.profiles,
            self._record_route_proxy_event,
        )

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

        self._init_variables()
        self._setup_theme()
        self._build_ui()
        self.refresh_all()
        self.persist_state()
        self._schedule_sign_in_status_refresh()
        if self.route_proxy_settings.enabled:
            self.start_route_proxy(show_errors=False)
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

    def _init_variables(self) -> None:
        self.status_var = tk.StringVar(value="准备就绪")

        self.current_name_var = tk.StringVar(value="正在读取当前配置...")
        self.current_meta_var = tk.StringVar(value="")
        self.current_api_var = tk.StringVar(value="")
        self.current_auth_var = tk.StringVar(value="")
        self.current_models_var = tk.StringVar(value="")
        self.current_path_var = tk.StringVar(value="")
        self.current_key_var = tk.StringVar(value="-")
        self.current_mcp_var = tk.StringVar(value="-")
        self.global_mcp_var = tk.StringVar(value="-")
        self.global_profile_choice_var = tk.StringVar(value="")
        self.global_profile_summary_var = tk.StringVar(value="尚未选择全局 API 配置。")
        self.current_match_var = tk.StringVar(value="未匹配")
        self.global_total_var = tk.StringVar(value="0")
        self.global_healthy_var = tk.StringVar(value="0")
        self.global_error_var = tk.StringVar(value="0")
        self.global_degraded_var = tk.StringVar(value="0")

        self.library_hint_var = tk.StringVar(value="还没有保存的配置。")
        self.library_selected_name_var = tk.StringVar(value="未选择配置")
        self.library_selected_provider_var = tk.StringVar(value="-")
        self.library_selected_model_var = tk.StringVar(value="-")
        self.library_selected_api_var = tk.StringVar(value="-")
        self.library_selected_key_var = tk.StringVar(value="-")
        self.library_selected_wire_var = tk.StringVar(value="-")
        self.library_selected_sign_in_status_var = tk.StringVar(value="-")
        self.library_selected_sign_in_url_var = tk.StringVar(value="-")
        self.library_selected_notes_var = tk.StringVar(value="暂无备注")
        self.library_models_summary_var = tk.StringVar(value="最近检测尚未返回模型列表。")
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
        self.project_mcp_var = tk.StringVar(value="-")

        self.proxy_status_var = tk.StringVar(value="未启动")
        self.proxy_host_var = tk.StringVar(value=self.route_proxy_settings.host)
        self.proxy_port_var = tk.StringVar(value=str(self.route_proxy_settings.port))
        self.proxy_hint_var = tk.StringVar(value="项目级代理默认关闭。启用项目后生成模板会指向本地代理。")
        self.proxy_selected_project_var = tk.StringVar(value="未选择项目")
        self.proxy_selected_rules_var = tk.StringVar(value="-")
        self.proxy_codex_protocol_var = tk.StringVar(value=ROUTE_PROXY_PROTOCOL_OPENAI)
        self.proxy_claude_protocol_var = tk.StringVar(value=ROUTE_PROXY_PROTOCOL_ANTHROPIC)

        self.mcp_hint_var = tk.StringVar(value="尚未加载 MCP 配置。")
        self.mcp_selected_name_var = tk.StringVar(value="未选择 MCP 工具")
        self.mcp_selected_summary_var = tk.StringVar(value="选择左侧工具后查看配置预览。")
        self.docs_hint_var = tk.StringVar(value="编辑后的 AGENTS 模板会用于后续项目模板生成。")

        self.settings_hint_var = tk.StringVar(value="模型批量测试设置会从下一次测试开始生效。")
        self.model_batch_concurrency_var = tk.StringVar(value=str(self.model_batch_concurrency))
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
            ("test", "模型测试"),
            ("mcp", "MCP配置"),
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
        self.mcp_tab = tk.Frame(content, bg=PALETTE["panel_bg"], padx=8, pady=2)
        self.docs_tab = tk.Frame(content, bg=PALETTE["panel_bg"], padx=8, pady=2)
        self.settings_tab = tk.Frame(content, bg=PALETTE["panel_bg"], padx=8, pady=2)
        self.test_tab = tk.Frame(content, bg=PALETTE["panel_bg"], padx=8, pady=2)
        self.tab_frames = {
            "global": self.global_tab,
            "library": self.library_tab,
            "project": self.project_tab,
            "proxy": self.proxy_tab,
            "mcp": self.mcp_tab,
            "docs": self.docs_tab,
            "settings": self.settings_tab,
            "test": self.test_tab,
        }
        for frame in self.tab_frames.values():
            frame.grid(row=0, column=0, sticky="nsew")

        self._build_global_tab(self.global_tab)
        self._build_library_tab(self.library_tab)
        self._build_project_tab(self.project_tab)
        self._build_proxy_tab(self.proxy_tab)
        self._build_mcp_tab(self.mcp_tab)
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

    def _make_metric_card(self, parent: tk.Misc, title: str, value_var: tk.StringVar, foreground: str, background: str) -> tk.Frame:
        card = self._make_card(parent, 14, 14)
        card.columnconfigure(0, weight=1)
        tk.Frame(card, bg=foreground, height=4).grid(row=0, column=0, sticky="ew", pady=(0, 12))
        tk.Label(card, text=title, bg=PALETTE["card_bg"], fg=PALETTE["muted"], font=self.small_font).grid(row=1, column=0, sticky="w")
        tk.Label(card, textvariable=value_var, bg=PALETTE["card_bg"], fg=foreground, font=("Microsoft YaHei UI", 20, "bold")).grid(row=2, column=0, sticky="w", pady=(10, 0))
        badge = tk.Label(card, text="配置统计", bg=background, fg=foreground, font=("Microsoft YaHei UI", 8, "bold"), padx=10, pady=4)
        badge.grid(row=3, column=0, sticky="w", pady=(10, 0))
        return card

    def _build_global_tab(self, parent: tk.Misc) -> None:
        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(1, weight=1)

        metrics = tk.Frame(parent, bg=PALETTE["panel_bg"])
        metrics.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        for column in range(4):
            metrics.columnconfigure(column, weight=1)

        self._make_metric_card(metrics, "配置总数", self.global_total_var, PALETTE["text"], PALETTE["neutral_soft"]).grid(row=0, column=0, sticky="ew", padx=(0, 8))
        self._make_metric_card(metrics, "健康配置", self.global_healthy_var, PALETTE["success"], PALETTE["success_soft"]).grid(row=0, column=1, sticky="ew", padx=(0, 8))
        self._make_metric_card(metrics, "受限配置", self.global_degraded_var, PALETTE["warning"], PALETTE["warning_soft"]).grid(row=0, column=2, sticky="ew", padx=(0, 8))
        self._make_metric_card(metrics, "异常配置", self.global_error_var, PALETTE["danger"], PALETTE["danger_soft"]).grid(row=0, column=3, sticky="ew")

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
        tk.Label(left, text="当前生效配置", bg=PALETTE["card_bg"], fg=PALETTE["text"], font=self.section_font).grid(row=0, column=0, sticky="w")
        tk.Label(left, textvariable=self.current_name_var, bg=PALETTE["card_bg"], fg=PALETTE["text"], font=self.hero_font).grid(row=1, column=0, sticky="w", pady=(8, 2))
        tk.Label(left, textvariable=self.current_meta_var, bg=PALETTE["card_bg"], fg=PALETTE["muted"], font=self.body_font, justify="left").grid(row=2, column=0, sticky="w")
        tk.Label(left, textvariable=self.current_api_var, bg=PALETTE["card_bg"], fg=PALETTE["text"], font=self.body_font, justify="left", wraplength=420).grid(row=3, column=0, sticky="w", pady=(10, 4))
        tk.Label(left, textvariable=self.current_auth_var, bg=PALETTE["card_bg"], fg=PALETTE["muted"], font=self.small_font, justify="left").grid(row=4, column=0, sticky="w")
        tk.Label(left, text="当前 API Key", bg=PALETTE["card_bg"], fg=PALETTE["text"], font=self.section_font).grid(row=5, column=0, sticky="w", pady=(14, 4))
        tk.Label(left, textvariable=self.current_key_var, bg=PALETTE["card_bg"], fg=PALETTE["muted"], font=self.body_font).grid(row=6, column=0, sticky="w")
        tk.Label(left, text="当前模型", bg=PALETTE["card_bg"], fg=PALETTE["text"], font=self.section_font).grid(row=7, column=0, sticky="w", pady=(14, 4))
        tk.Label(left, textvariable=self.current_models_var, bg=PALETTE["card_bg"], fg=PALETTE["muted"], font=self.body_font, justify="left", wraplength=420).grid(row=8, column=0, sticky="w")

        right = tk.Frame(current, bg=PALETTE["card_bg"])
        right.grid(row=0, column=1, sticky="nsew")
        right.columnconfigure(0, weight=1)
        tk.Label(right, text="配置文件位置", bg=PALETTE["card_bg"], fg=PALETTE["text"], font=self.section_font).grid(row=0, column=0, sticky="w")
        tk.Label(right, textvariable=self.current_path_var, bg=PALETTE["card_bg"], fg=PALETTE["muted"], font=self.small_font, justify="left", wraplength=360).grid(row=1, column=0, sticky="w", pady=(10, 12))
        tk.Label(right, text="当前 MCP", bg=PALETTE["card_bg"], fg=PALETTE["text"], font=self.section_font).grid(row=2, column=0, sticky="w")
        tk.Label(right, textvariable=self.current_mcp_var, bg=PALETTE["card_bg"], fg=PALETTE["muted"], font=self.body_font, justify="left", wraplength=360).grid(row=3, column=0, sticky="w", pady=(10, 12))
        self.current_status_badge = make_status_badge(right, textvariable=self.current_match_var)
        self.current_status_badge.grid(row=4, column=0, sticky="w")

        tk.Label(right, text="全局 API 设置", bg=PALETTE["card_bg"], fg=PALETTE["text"], font=self.section_font).grid(row=5, column=0, sticky="w", pady=(18, 8))
        global_profile_row = tk.Frame(right, bg=PALETTE["card_bg"])
        global_profile_row.grid(row=6, column=0, sticky="ew")
        global_profile_row.columnconfigure(0, weight=1)
        self.global_profile_combo = ttk.Combobox(
            global_profile_row,
            textvariable=self.global_profile_choice_var,
            state="readonly",
            width=40,
        )
        self.global_profile_combo.grid(row=0, column=0, sticky="ew")
        self.global_profile_combo.bind("<<ComboboxSelected>>", self._on_global_profile_choice_changed)
        tk.Label(
            right,
            textvariable=self.global_profile_summary_var,
            bg=PALETTE["card_bg"],
            fg=PALETTE["muted"],
            font=self.small_font,
            justify="left",
            wraplength=360,
        ).grid(row=7, column=0, sticky="w", pady=(8, 0))

        global_api_actions = tk.Frame(right, bg=PALETTE["card_bg"])
        global_api_actions.grid(row=8, column=0, sticky="ew", pady=(12, 0))
        for column in range(3):
            global_api_actions.columnconfigure(column, weight=1)
        make_button(global_api_actions, text="新增 API", variant="secondary", command=self.add_profile).grid(row=0, column=0, sticky="ew", padx=(0, 8))
        make_button(global_api_actions, text="编辑 API", variant="secondary", command=self.edit_profile).grid(row=0, column=1, sticky="ew", padx=(0, 8))
        make_button(global_api_actions, text="写入全局配置", variant="primary", command=self.apply_global_profile).grid(row=0, column=2, sticky="ew")

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
        make_button(actions, text="编辑 MCP", variant="primary", command=self.edit_global_mcp).grid(row=0, column=0, sticky="ew", padx=(0, 8))
        make_button(actions, text="清空 MCP", variant="danger", command=self.clear_global_mcp).grid(row=0, column=1, sticky="ew", padx=(0, 8))
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
        self._create_dual_info_row(detail, 0, "供应商", self.library_selected_provider_var, "模型", self.library_selected_model_var)
        self.library_api_link_label = self._create_link_info_row(detail, 1, "API 地址", self.library_selected_api_var, self._open_selected_api_url, wraplength=460)
        self._create_dual_info_row(detail, 2, "活动 Key", self.library_selected_key_var, "Wire API", self.library_selected_wire_var)
        self._create_info_row(detail, 3, "签到状态", self.library_selected_sign_in_status_var, wraplength=460)
        self.library_sign_in_link_label = self._create_link_info_row(detail, 4, "签到地址", self.library_selected_sign_in_url_var, self._open_selected_sign_in_url, wraplength=460)
        self._create_info_row(detail, 5, "备注", self.library_selected_notes_var, wraplength=460)

        tk.Label(detail, text="返回模型", bg=PALETTE["card_bg"], fg=PALETTE["muted"], font=self.small_font).grid(row=6, column=0, sticky="nw", padx=(0, 14), pady=(12, 4))
        models_wrap = tk.Frame(detail, bg=PALETTE["card_bg"])
        models_wrap.grid(row=6, column=1, columnspan=3, sticky="nsew", pady=(12, 4))
        models_wrap.columnconfigure(0, weight=1)
        models_wrap.rowconfigure(0, weight=1)
        self.library_models_text = tk.Text(
            models_wrap,
            height=12,
            wrap="word",
            relief="solid",
            borderwidth=1,
            highlightthickness=0,
            font=self.small_font,
            bg="#FBFDFE",
            fg=PALETTE["text"],
            state="disabled",
        )
        self.library_models_text.grid(row=0, column=0, sticky="nsew")
        library_models_scroll = ttk.Scrollbar(models_wrap, orient="vertical", command=self.library_models_text.yview)
        library_models_scroll.grid(row=0, column=1, sticky="ns")
        self.library_models_text.configure(yscrollcommand=library_models_scroll.set)

    def _build_project_tab(self, parent: tk.Misc) -> None:
        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(0, weight=1)

        content = tk.Frame(parent, bg=PALETTE["panel_bg"])
        content.grid(row=0, column=0, sticky="nsew")
        content.columnconfigure(0, weight=5)
        content.columnconfigure(1, weight=6)
        content.rowconfigure(0, weight=1)

        project_list = self._make_card(content)
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

        detail = self._make_card(content)
        detail.grid(row=0, column=1, sticky="nsew")
        detail.columnconfigure(1, weight=1)
        detail.columnconfigure(3, weight=1)

        header = tk.Frame(detail, bg=PALETTE["card_bg"])
        header.grid(row=0, column=0, columnspan=4, sticky="ew")
        header.columnconfigure(0, weight=1)
        tk.Label(header, textvariable=self.project_selected_name_var, bg=PALETTE["card_bg"], fg=PALETTE["text"], font=self.hero_font).grid(row=0, column=0, sticky="w")
        self.project_status_badge = make_status_badge(header, text="未生成")
        self.project_status_badge.grid(row=0, column=1, sticky="e")
        tk.Label(header, text="这里展示项目目录、绑定配置、模板生成状态和项目级 MCP。", bg=PALETTE["card_bg"], fg=PALETTE["muted"], font=self.small_font).grid(
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
        self._create_info_row(detail, 8, "项目 MCP", self.project_mcp_var, wraplength=440)

        actions = tk.Frame(detail, bg=PALETTE["card_bg"])
        actions.grid(row=9, column=0, columnspan=4, sticky="ew", pady=(18, 0))
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
        left.rowconfigure(3, weight=1)
        tk.Label(left, text="路由代理", bg=PALETTE["card_bg"], fg=PALETTE["text"], font=self.hero_font).grid(row=0, column=0, sticky="w")
        tk.Label(left, textvariable=self.proxy_hint_var, bg=PALETTE["card_bg"], fg=PALETTE["muted"], font=self.small_font).grid(row=1, column=0, sticky="w", pady=(4, 12))

        settings = tk.Frame(left, bg=PALETTE["card_bg"])
        settings.grid(row=2, column=0, sticky="ew")
        settings.columnconfigure(1, weight=1)
        tk.Label(settings, text="监听地址", bg=PALETTE["card_bg"], fg=PALETTE["muted"], font=self.small_font).grid(row=0, column=0, sticky="w", padx=(0, 10), pady=4)
        ttk.Entry(settings, textvariable=self.proxy_host_var, width=18).grid(row=0, column=1, sticky="w", pady=4)
        tk.Label(settings, text="端口", bg=PALETTE["card_bg"], fg=PALETTE["muted"], font=self.small_font).grid(row=0, column=2, sticky="w", padx=(16, 10), pady=4)
        ttk.Entry(settings, textvariable=self.proxy_port_var, width=8).grid(row=0, column=3, sticky="w", pady=4)
        tk.Label(settings, text="Codex 上游", bg=PALETTE["card_bg"], fg=PALETTE["muted"], font=self.small_font).grid(row=1, column=0, sticky="w", padx=(0, 10), pady=4)
        ttk.Combobox(
            settings,
            textvariable=self.proxy_codex_protocol_var,
            values=(
                ROUTE_PROXY_PROTOCOL_OPENAI,
                ROUTE_PROXY_PROTOCOL_OPENAI_CHAT_TO_RESPONSES,
                ROUTE_PROXY_PROTOCOL_OPENAI_RESPONSES_TO_CHAT,
            ),
            state="readonly",
            width=28,
        ).grid(row=1, column=1, columnspan=3, sticky="w", pady=4)
        tk.Label(settings, text="Claude 上游", bg=PALETTE["card_bg"], fg=PALETTE["muted"], font=self.small_font).grid(row=2, column=0, sticky="w", padx=(0, 10), pady=4)
        ttk.Combobox(
            settings,
            textvariable=self.proxy_claude_protocol_var,
            values=(ROUTE_PROXY_PROTOCOL_ANTHROPIC, ROUTE_PROXY_PROTOCOL_ANTHROPIC_TO_OPENAI),
            state="readonly",
            width=28,
        ).grid(row=2, column=1, columnspan=3, sticky="w", pady=4)

        proxy_tree_wrap = tk.Frame(left, bg=PALETTE["card_bg"])
        proxy_tree_wrap.grid(row=3, column=0, sticky="nsew", pady=(12, 0))
        proxy_tree_wrap.columnconfigure(0, weight=1)
        proxy_tree_wrap.rowconfigure(0, weight=1)
        self.proxy_project_tree = ttk.Treeview(proxy_tree_wrap, columns=("name", "codex", "claude", "enabled"), show="headings")
        for column, title, width in (
            ("name", "项目", 160),
            ("codex", "Codex", 120),
            ("claude", "Claude", 120),
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
        actions.grid(row=4, column=0, sticky="ew", pady=(14, 0))
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
        parent.rowconfigure(1, weight=1)

        settings_card = self._make_card(parent)
        settings_card.grid(row=0, column=0, sticky="ew", pady=(0, 10))
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
        make_button(settings_card, text="保存设置", variant="primary", command=self.save_settings).grid(row=2, column=2, sticky="e")

        info_card = self._make_card(parent)
        info_card.grid(row=1, column=0, sticky="nsew")
        info_card.columnconfigure(1, weight=1)
        info_card.columnconfigure(3, weight=1)
        tk.Label(info_card, text="版本与环境", bg=PALETTE["card_bg"], fg=PALETTE["text"], font=self.hero_font).grid(row=0, column=0, columnspan=4, sticky="w")
        self._create_dual_info_row(info_card, 1, "应用版本", self.settings_version_var, "Python", self.settings_python_var)
        self._create_dual_info_row(info_card, 2, "Tk/Tcl", self.settings_tk_var, "ttkbootstrap", self.settings_ttkbootstrap_var)
        self._create_info_row(info_card, 3, "配置库", self.settings_storage_path_var, wraplength=900)
        self._create_info_row(info_card, 4, "Codex config", self.settings_codex_config_path_var, wraplength=900)
        self._create_info_row(info_card, 5, "Codex auth", self.settings_codex_auth_path_var, wraplength=900)
        self._create_info_row(info_card, 6, "当前工作目录", self.settings_project_root_var, wraplength=900)
        self._create_info_row(info_card, 7, "平台", self.settings_platform_var, wraplength=900)

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
        summary = hidden_secret(profile.api_key)
        key_count = len(profile.api_keys)
        if key_count > 1:
            return f"{summary}（Key {profile.effective_active_api_key_index + 1}/{key_count}）"
        return summary

    def _profile_model_summary(self, profile: Profile) -> str:
        if profile.vendor == VENDOR_CODEX:
            return f"Codex：{profile.codex_display_model}"
        if profile.vendor == VENDOR_CLAUDE:
            return f"Claude：{profile.claude_display_model} / 兜底：{profile.claude_display_fallback_model}"
        if profile.vendor == VENDOR_OTHER:
            return "-"
        return (
            f"Codex：{profile.codex_display_model}\n"
            f"Claude：{profile.claude_display_model} / 兜底：{profile.claude_display_fallback_model}"
        )

    def _profile_library_model_summary(self, profile: Profile) -> str:
        if self.library_profile_view == VENDOR_CODEX:
            return profile.codex_display_model
        if self.library_profile_view == VENDOR_CLAUDE:
            return profile.claude_display_model
        if profile.vendor == VENDOR_CODEX:
            return profile.codex_display_model
        if profile.vendor == VENDOR_CLAUDE:
            return profile.claude_display_model
        if profile.vendor == VENDOR_GENERIC:
            return f"{profile.codex_display_model} / {profile.claude_display_model}"
        return "-"

    def _global_profile_choice_label(self, profile: Profile) -> str:
        return f"{profile.name} | {profile.codex_display_model or '-'} | {compact_text(profile.base_url, 42)}"

    def _profile_from_global_choice(self) -> Profile | None:
        choice = self.global_profile_choice_var.get().strip()
        for profile in self.profiles:
            if not profile_supports_codex(profile):
                continue
            if self._global_profile_choice_label(profile) == choice:
                return profile
        selected = self.get_selected_profile()
        if selected and profile_supports_codex(selected):
            return selected
        return None

    def _sync_global_profile_choice(self) -> None:
        if not hasattr(self, "global_profile_combo"):
            return
        profiles = [profile for profile in self.profiles if profile_supports_codex(profile)]
        labels = tuple(self._global_profile_choice_label(profile) for profile in profiles)
        self.global_profile_combo.configure(values=labels, state="readonly" if labels else "disabled")
        profile = self.get_selected_profile()
        if not profile or not profile_supports_codex(profile):
            profile = profiles[0] if profiles else None
        if not profile:
            self.global_profile_choice_var.set("")
            self.global_profile_summary_var.set("尚未选择全局 API 配置。")
            return
        self.global_profile_choice_var.set(self._global_profile_choice_label(profile))
        self.global_profile_summary_var.set(
            f"将写入：{profile.provider_name} / {profile.wire_api}\n"
            f"模型：{profile.codex_display_model or '-'}\n"
            f"API：{profile.base_url}\n"
            f"活动 Key：{self._profile_key_summary(profile)}"
        )

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
        total = len(self.profiles)
        healthy = sum(1 for profile in self.profiles if profile.effective_health_status == "healthy")
        degraded = sum(1 for profile in self.profiles if profile.effective_health_status == "degraded")
        error = sum(1 for profile in self.profiles if profile.effective_health_status == "error")
        return total, healthy, degraded, error

    def _mcp_summary(self, raw_toml: str | None) -> str:
        names = self._safe_mcp_server_names(raw_toml)
        if not names:
            return "未配置"
        label = ", ".join(names[:4])
        suffix = " …" if len(names) > 4 else ""
        return f"{len(names)} 个服务：{label}{suffix}"

    def _safe_mcp_server_names(self, raw_toml: str | None) -> list[str]:
        try:
            return mcp_server_names_from_toml(raw_toml)
        except ValueError:
            return []

    def _effective_global_mcp_toml(self) -> str:
        if self.global_mcp_opt_out:
            return ""
        if self.global_mcp_toml.strip():
            return self.global_mcp_toml
        return load_default_global_mcp_toml()

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
        return self._safe_mcp_server_names(self._effective_global_mcp_toml())

    def _project_mcp_selection_summary(self, project: ProjectRecord | None) -> str:
        if not project:
            return "-"
        if project.mcp_server_names is None:
            return self._mcp_summary(self._effective_project_mcp_toml(project))
        if not project.mcp_server_names:
            return "未启用"
        label = ", ".join(project.mcp_server_names[:4])
        suffix = " …" if len(project.mcp_server_names) > 4 else ""
        return f"{len(project.mcp_server_names)} 个服务：{label}{suffix}"

    def _mcp_contains_project_root(self, value) -> bool:
        if isinstance(value, str):
            return PROJECT_ROOT_PLACEHOLDER in value
        if isinstance(value, list):
            return any(self._mcp_contains_project_root(item) for item in value)
        if isinstance(value, dict):
            return any(self._mcp_contains_project_root(item) for item in value.values())
        return False

    def _mcp_list_summary(self, value, limit: int = 36) -> str:
        if not isinstance(value, list) or not value:
            return "-"
        return compact_text(" ".join(str(item) for item in value), limit)

    def _mcp_env_summary(self, value, limit: int = 28) -> str:
        if not isinstance(value, dict) or not value:
            return "-"
        return compact_text(", ".join(str(key) for key in value.keys()), limit)

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
        if not server_name:
            return ""
        server_config = self.mcp_page_servers.get(server_name)
        if not isinstance(server_config, dict):
            return ""
        return render_mcp_servers_toml({server_name: server_config})

    def _refresh_mcp_detail(self) -> None:
        server_name = self._mcp_selected_name()
        if not server_name:
            self.mcp_selected_name_var.set("未选择 MCP 工具")
            self.mcp_selected_summary_var.set("选择左侧工具后查看配置预览。")
            self._set_text_content(self.mcp_preview_text, "", disabled=True)
            return

        server_config = self.mcp_page_servers.get(server_name, {})
        args_count = len(server_config.get("args", [])) if isinstance(server_config.get("args"), list) else 0
        env_count = len(server_config.get("env", {})) if isinstance(server_config.get("env"), dict) else 0
        self.mcp_selected_name_var.set(server_name)
        self.mcp_selected_summary_var.set(
            f"type: {server_config.get('type', '-') or '-'}    args: {args_count}    env: {env_count}"
        )
        self._set_text_content(self.mcp_preview_text, self._render_mcp_preview(server_name), disabled=True)

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

    def _on_global_profile_choice_changed(self, _event: object | None = None) -> None:
        profile = self._profile_from_global_choice()
        if not profile:
            return
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
        label = STATUS_TEXT.get(profile.effective_health_status, "未检测")
        return f"{label}（手动）" if profile.has_manual_health_override else label

    def _health_override_note(self, profile: Profile | None) -> str:
        if profile is None:
            return "自动检测仅代表连通性，可在这里手动修正。"
        if profile.has_manual_health_override:
            return "当前以手动状态为准，自动检测结果仍保留在检测详情中。"
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
        self.refresh_mcp_tab()
        self.refresh_settings_tab()
        self.refresh_test_tab()
        self.status_var.set("已刷新全局配置、配置库、项目配置、路由代理、MCP配置、文档配置、设置和模型测试。")

    def refresh_settings_tab(self) -> None:
        self.model_batch_concurrency_var.set(str(self.model_batch_concurrency))
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

    def _schedule_sign_in_status_refresh(self) -> None:
        if not self.root.winfo_exists():
            return
        current_day = today_iso()
        if current_day != self.sign_in_status_day:
            self.sign_in_status_day = current_day
            self.refresh_library_tab()
            self.refresh_test_tab()
        self.root.after(60_000, self._schedule_sign_in_status_refresh)

    def refresh_global_tab(self) -> None:
        self.current_config = self.manager.read_current_config()
        matched = self.find_matching_profile(self.current_config)
        total, healthy, degraded, error = self._current_status_counts()

        self.global_total_var.set(str(total))
        self.global_healthy_var.set(str(healthy))
        self.global_degraded_var.set(str(degraded))
        self.global_error_var.set(str(error))

        self.current_name_var.set(matched.name if matched else "未匹配到已保存配置")
        self.current_meta_var.set(f"提供方：{self.current_config.model_provider or '-'}    Wire API：{self.current_config.wire_api or '-'}")
        self.current_api_var.set(f"API 地址：{self.current_config.base_url or '-'}")
        auth_loaded = "已加载" if self.current_config.api_key_loaded else "未加载"
        self.current_auth_var.set(f"鉴权：{self.current_config.auth_mode or '-'}    状态：{auth_loaded}")
        self.current_key_var.set(hidden_secret(self.current_config.api_key))
        self.current_path_var.set(f"config.toml\n{self.current_config.config_path}\n\nauth.json\n{self.current_config.auth_path}")

        model_lines: list[str] = []
        if self.current_config.model:
            model_lines.append(f"主模型：{self.current_config.model}")
        if self.current_config.review_model and self.current_config.review_model != self.current_config.model:
            model_lines.append(f"评审模型：{self.current_config.review_model}")
        self.current_models_var.set("\n".join(model_lines) if model_lines else "当前配置里没有模型信息。")
        self.current_mcp_var.set(self._mcp_summary(self._effective_global_mcp_toml()) if self.current_config.mcp_server_names else "当前配置未启用托管 MCP")
        self.global_mcp_var.set(self._mcp_summary(self._effective_global_mcp_toml()))
        self._sync_global_profile_choice()

        if matched:
            self.current_match_var.set("已匹配本地配置库")
            self.current_status_badge.configure(bg=PALETTE["success_soft"], fg=PALETTE["success"])
        else:
            self.current_match_var.set("当前配置未收录")
            self.current_status_badge.configure(bg=PALETTE["warning_soft"], fg=PALETTE["warning"])

    def refresh_library_tab(self) -> None:
        self.hide_error_button_var.set("显示异常" if self.hide_error_profiles else "隐藏异常")
        self._sync_library_scope_tabs()
        selected_id = self.selected_profile_id

        visible_profiles = visible_profiles_for_filter(self.profiles, self.hide_error_profiles)
        scope_profiles = profiles_for_library_view(visible_profiles, self.library_profile_view)
        scope_label = dict(LIBRARY_PROFILE_VIEW_TABS).get(self.library_profile_view, "配置")
        display_columns = (
            LIBRARY_TREE_COLUMNS_WITH_VENDOR if self.library_profile_view == LIBRARY_VIEW_ALL else LIBRARY_TREE_COLUMNS
        )
        self.profile_tree.configure(displaycolumns=display_columns)

        if selected_id and not any(profile.id == selected_id for profile in scope_profiles):
            selected_id = scope_profiles[0].id if scope_profiles else None
            self.selected_profile_id = selected_id

        self.suppress_selection_events = True
        try:
            for item in self.profile_tree.get_children():
                self.profile_tree.delete(item)
            for profile in sorted(scope_profiles, key=profile_library_sort_key):
                self.profile_tree.insert(
                    "",
                    "end",
                    iid=self._profile_tree_iid(self.library_profile_view, profile),
                    values=(
                        profile.name,
                        profile.vendor_label,
                        compact_text(profile.base_url, 42),
                        compact_text(self._profile_library_model_summary(profile) or "-", 18),
                        profile.sign_in_status,
                        self._health_status_text(profile),
                    ),
                    tags=(profile.effective_health_status,),
                )
            self.profile_tree.tag_configure("healthy", foreground=PALETTE["success"])
            self.profile_tree.tag_configure("degraded", foreground=PALETTE["warning"])
            self.profile_tree.tag_configure("error", foreground=PALETTE["danger"])
            self.profile_tree.tag_configure("unknown", foreground=PALETTE["neutral_text"])
        finally:
            self.suppress_selection_events = False

        visible_healthy = sum(1 for profile in scope_profiles if profile.effective_health_status == "healthy")
        if self.hide_error_profiles:
            self.library_hint_var.set(f"{scope_label} 显示 {len(scope_profiles)} 套配置，健康配置 {visible_healthy} 套。")
        else:
            self.library_hint_var.set(f"{scope_label} 共 {len(scope_profiles)} 套配置，健康配置 {visible_healthy} 套。")
        self._sync_profile_tree_selection()
        self._sync_global_profile_choice()
        self._refresh_library_detail()

    def _refresh_library_detail(self) -> None:
        profile = self.get_selected_profile()
        if not profile:
            self.library_selected_name_var.set("未选择配置")
            self.library_selected_provider_var.set("-")
            self.library_selected_model_var.set("-")
            self.library_selected_api_var.set("-")
            self.library_selected_key_var.set("-")
            self.library_selected_wire_var.set("-")
            self.library_selected_sign_in_status_var.set("-")
            self.library_selected_sign_in_url_var.set("-")
            self.library_selected_notes_var.set("暂无备注")
            self.library_health_badge.configure(text="未检测", bg=PALETTE["neutral_soft"], fg=PALETTE["neutral_text"])
            self._set_library_api_link_state()
            self._set_library_sign_in_link_state()
            self._render_library_model_tags([], "最近检测尚未返回模型列表。")
            return

        self.library_selected_name_var.set(profile.name)
        self.library_selected_provider_var.set(f"{profile.vendor_label} / {profile.provider_name}")
        self.library_selected_model_var.set(self._profile_model_summary(profile))
        self.library_selected_api_var.set(profile.base_url)
        self.library_selected_key_var.set(self._profile_key_summary(profile))
        self.library_selected_wire_var.set(profile.wire_api)
        self.library_selected_sign_in_status_var.set(profile.sign_in_status)
        self.library_selected_sign_in_url_var.set(profile.sign_in_url or "-")
        self.library_selected_notes_var.set(profile.notes or "暂无备注")
        badge_fg, badge_bg = STATUS_COLORS.get(profile.effective_health_status, STATUS_COLORS["unknown"])
        self.library_health_badge.configure(text=self._health_status_text(profile), bg=badge_bg, fg=badge_fg)
        self._set_library_api_link_state()
        self._set_library_sign_in_link_state()
        self._render_library_model_tags(profile.health.models, "最近检测尚未返回模型列表。")

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

    def _render_library_model_tags(self, models: list[str], empty_text: str) -> None:
        normalized_models = [str(model).strip() for model in models if str(model).strip()]
        if not normalized_models:
            self.library_models_summary_var.set(empty_text)
            if hasattr(self, "library_models_text"):
                self._set_text_content(self.library_models_text, empty_text, disabled=True)
            return
        summary_lines = [f"共 {len(normalized_models)} 个模型。"]
        summary_lines.extend(f"- {model}" for model in normalized_models)
        content = "\n".join(summary_lines)
        self.library_models_summary_var.set(content)
        if hasattr(self, "library_models_text"):
            self._set_text_content(self.library_models_text, content, disabled=True)

    def refresh_project_tab(self) -> None:
        selected_id = self.selected_project_id
        generated_count = 0

        if selected_id and not any(project.id == selected_id for project in self.projects):
            selected_id = self.projects[0].id if self.projects else None
            self.selected_project_id = selected_id

        self.suppress_selection_events = True
        try:
            for item in self.project_tree.get_children():
                self.project_tree.delete(item)
            for project in self.projects:
                codex_profile = self._profile_by_id(project.codex_profile_id or project.profile_id)
                claude_profile = self._profile_by_id(project.claude_profile_id or project.profile_id)
                codex_name = codex_profile.name if codex_profile else "配置已删除"
                claude_name = claude_profile.name if claude_profile else "配置已删除"
                self.project_tree.insert(
                    "",
                    "end",
                    iid=project.id,
                    values=(
                        project.name,
                        compact_text(project.project_dir, 42),
                        compact_text(codex_name, 16),
                        compact_text(claude_name, 16),
                        compact_text(self._project_mcp_selection_summary(project), 16),
                    ),
                )
                if Path(project.project_dir).exists():
                    status = self.project_template_service.inspect(Path(project.project_dir))
                    if status.generated_paths:
                        generated_count += 1
        finally:
            self.suppress_selection_events = False

        self._sync_project_tree_selection()

        self.project_hint_var.set(f"共 {len(self.projects)} 个项目，已生成模板 {generated_count} 个。")
        self._refresh_project_detail()
        self.refresh_proxy_tab()

    def refresh_proxy_tab(self) -> None:
        if not hasattr(self, "proxy_project_tree"):
            return
        self.proxy_host_var.set(self.route_proxy_settings.host)
        self.proxy_port_var.set(str(self.route_proxy_settings.port))
        self.proxy_status_var.set(
            f"代理运行中：{self.route_proxy_settings.base_url}"
            if self.route_proxy_server.is_running
            else f"代理未启动：{self.route_proxy_settings.base_url}"
        )
        self.suppress_selection_events = True
        try:
            for item in self.proxy_project_tree.get_children():
                self.proxy_project_tree.delete(item)
            for project in self.projects:
                codex_profile = self._profile_by_id(project.codex_profile_id or project.profile_id)
                claude_profile = self._profile_by_id(project.claude_profile_id or project.profile_id)
                self.proxy_project_tree.insert(
                    "",
                    "end",
                    iid=project.id,
                    values=(
                        project.name,
                        compact_text(codex_profile.name if codex_profile else "配置已删除", 16),
                        compact_text(claude_profile.name if claude_profile else "配置已删除", 16),
                        "已启用" if self.route_proxy_settings.project_enabled(project.id) else "未启用",
                    ),
                )
        finally:
            self.suppress_selection_events = False
        self._sync_proxy_project_selection()
        self._refresh_proxy_detail()
        self._render_proxy_log()

    def _refresh_proxy_detail(self) -> None:
        project = self.get_selected_project()
        if not project:
            self.proxy_selected_project_var.set("未选择项目")
            self.proxy_selected_rules_var.set("-")
            return
        self.proxy_selected_project_var.set(f"{project.name}    {project.project_dir}")
        rules = self.route_proxy_settings.rules_for_project(project.id)
        if not rules:
            self.proxy_selected_rules_var.set("未启用代理。")
            return
        summaries: list[str] = []
        for rule in rules:
            if rule.client_type == ROUTE_PROXY_CLIENT_CODEX:
                self.proxy_codex_protocol_var.set(rule.upstream_protocol or ROUTE_PROXY_PROTOCOL_OPENAI)
            elif rule.client_type == ROUTE_PROXY_CLIENT_CLAUDE:
                self.proxy_claude_protocol_var.set(rule.upstream_protocol or ROUTE_PROXY_PROTOCOL_ANTHROPIC)
            profile = self._profile_by_id(rule.primary_profile_id)
            profile_name = profile.name if profile else "配置已删除"
            summaries.append(f"{rule.client_type} / {rule.model_pattern} / {rule.upstream_protocol} -> {profile_name}")
        self.proxy_selected_rules_var.set("\n".join(summaries))

    def _render_proxy_log(self) -> None:
        if not hasattr(self, "proxy_log_text"):
            return
        lines = [
            f"{event.timestamp} [{event.level}] {event.message}"
            for event in reversed(self.route_proxy_settings.events[-30:])
        ]
        self._set_text_content(self.proxy_log_text, "\n".join(lines) if lines else "暂无代理日志。", disabled=True)

    def _refresh_project_detail(self) -> None:
        project = self.get_selected_project()
        if not project:
            self.project_selected_name_var.set("未选择项目")
            self.project_selected_dir_var.set("-")
            self.project_selected_codex_profile_var.set("-")
            self.project_selected_claude_profile_var.set("-")
            self.project_selected_codex_model_var.set("-")
            self.project_selected_claude_model_var.set("-")
            self.project_selected_codex_key_var.set("-")
            self.project_selected_claude_key_var.set("-")
            self.project_backup_var.set("-")
            self.project_generated_var.set("-")
            self.project_script_var.set("-")
            self.project_run_var.set("-")
            self.project_mcp_var.set("-")
            self.project_status_badge.configure(text="未生成", bg=PALETTE["neutral_soft"], fg=PALETTE["neutral_text"])
            return

        self.project_selected_name_var.set(project.name)
        self.project_selected_dir_var.set(project.project_dir)
        self.project_run_var.set(project.run_command or "未配置")
        self.project_script_var.set(str(self._get_project_script_path(project)))
        self.project_mcp_var.set(self._project_mcp_selection_summary(project))

        codex_profile = self._profile_by_id(project.codex_profile_id or project.profile_id)
        claude_profile = self._profile_by_id(project.claude_profile_id or project.profile_id)
        if codex_profile:
            self.project_selected_codex_profile_var.set(f"{codex_profile.name} / {codex_profile.vendor_label}")
            self.project_selected_codex_model_var.set(codex_profile.codex_display_model)
            self.project_selected_codex_key_var.set(self._profile_key_summary(codex_profile))
        else:
            self.project_selected_codex_profile_var.set("绑定配置已删除")
            self.project_selected_codex_model_var.set("-")
            self.project_selected_codex_key_var.set("-")
        if claude_profile:
            self.project_selected_claude_profile_var.set(f"{claude_profile.name} / {claude_profile.vendor_label}")
            self.project_selected_claude_model_var.set(
                f"{claude_profile.claude_display_model} / 兜底：{claude_profile.claude_display_fallback_model}"
            )
            self.project_selected_claude_key_var.set(self._profile_key_summary(claude_profile))
        else:
            self.project_selected_claude_profile_var.set("绑定配置已删除")
            self.project_selected_claude_model_var.set("-")
            self.project_selected_claude_key_var.set("-")

        project_root = Path(project.project_dir)
        if not project_root.exists():
            self.project_backup_var.set("项目目录不存在")
            self.project_generated_var.set("项目目录不存在，尚未生成模板。")
            self.project_status_badge.configure(text="目录缺失", bg=PALETTE["warning_soft"], fg=PALETTE["warning"])
            return

        status = self.project_template_service.inspect(project_root)
        self.project_backup_var.set(str(status.backup_dir) if status.backup_dir else "暂无备份")
        if status.generated_paths:
            preview = ", ".join(path.name for path in status.generated_paths[:4])
            suffix = " …" if len(status.generated_paths) > 4 else ""
            self.project_generated_var.set(f"{len(status.generated_paths)} 个文件：{preview}{suffix}")
            self.project_status_badge.configure(text="已生成", bg=PALETTE["success_soft"], fg=PALETTE["success"])
        else:
            self.project_generated_var.set("尚未生成项目模板。")
            self.project_status_badge.configure(text="未生成", bg=PALETTE["neutral_soft"], fg=PALETTE["neutral_text"])

    def refresh_mcp_tab(self, *, reload_from_state: bool = True) -> None:
        selected_name = self._mcp_selected_name()
        if reload_from_state:
            try:
                self.mcp_page_servers = parse_mcp_servers_toml(self._effective_global_mcp_toml())
            except ValueError as exc:
                self.mcp_page_servers = {}
                self.mcp_hint_var.set(f"MCP 配置解析失败：{exc}")
                for item in self.mcp_tree.get_children():
                    self.mcp_tree.delete(item)
                self._set_text_content(self.mcp_preview_text, "", disabled=True)
                return

        self.suppress_selection_events = True
        try:
            for item in self.mcp_tree.get_children():
                self.mcp_tree.delete(item)
            for server_name, server_config in sorted(self.mcp_page_servers.items()):
                self.mcp_tree.insert(
                    "",
                    "end",
                    iid=server_name,
                    values=(
                        server_name,
                        server_config.get("type", "-") or "-",
                        compact_text(str(server_config.get("command", "-") or "-"), 24),
                        self._mcp_list_summary(server_config.get("args")),
                        compact_text(str(server_config.get("cwd", "-") or "-"), 24),
                        self._mcp_env_summary(server_config.get("env")),
                        "是" if self._mcp_contains_project_root(server_config) else "否",
                    ),
                )
            if selected_name in self.mcp_page_servers:
                self.mcp_tree.selection_set(selected_name)
                self.mcp_tree.focus(selected_name)
                self.mcp_tree.see(selected_name)
            elif self.mcp_page_servers:
                first_name = sorted(self.mcp_page_servers.keys())[0]
                self.mcp_tree.selection_set(first_name)
                self.mcp_tree.focus(first_name)
        finally:
            self.suppress_selection_events = False

        if self.global_mcp_opt_out:
            self.mcp_hint_var.set("全局 MCP 已显式禁用。")
        else:
            self.mcp_hint_var.set(f"共 {len(self.mcp_page_servers)} 个 MCP 工具。")
        self._refresh_mcp_detail()

    def refresh_test_tab(self) -> None:
        selected_id = self.selected_profile_id
        visible_profiles = visible_profiles_for_filter(self.profiles, self.hide_error_profiles)
        if selected_id and not any(profile.id == selected_id for profile in visible_profiles):
            selected_id = visible_profiles[0].id if visible_profiles else None
            self.selected_profile_id = selected_id
        if not selected_id and visible_profiles:
            selected_id = visible_profiles[0].id
            self.selected_profile_id = selected_id

        self.suppress_selection_events = True
        try:
            for item in self.test_api_tree.get_children():
                self.test_api_tree.delete(item)
            for profile in visible_profiles:
                self.test_api_tree.insert(
                    "",
                    "end",
                    iid=profile.id,
                    values=(profile.name, self._health_status_text(profile)),
                    tags=(profile.effective_health_status,),
                )
            self.test_api_tree.tag_configure("healthy", foreground=PALETTE["success"])
            self.test_api_tree.tag_configure("degraded", foreground=PALETTE["warning"])
            self.test_api_tree.tag_configure("error", foreground=PALETTE["danger"])
            self.test_api_tree.tag_configure("unknown", foreground=PALETTE["neutral_text"])
            if selected_id and self.test_api_tree.exists(selected_id):
                self.test_api_tree.selection_set(selected_id)
                self.test_api_tree.focus(selected_id)
                self.test_api_tree.see(selected_id)
        finally:
            self.suppress_selection_events = False

        self._refresh_test_detail()

    def _refresh_test_detail(self) -> None:
        profile = self.get_selected_profile()
        if not profile:
            self.test_selected_name_var.set("未选择测试配置")
            self.test_detail_health_var.set("未检测")
            self.test_detail_provider_var.set("-")
            self.test_detail_model_var.set("-")
            self.test_detail_api_var.set("-")
            self.test_detail_key_var.set("-")
            self.test_detail_wire_var.set("-")
            self.test_detail_endpoint_var.set("-")
            self.test_detail_checked_var.set("-")
            self.test_detail_notes_var.set("暂无备注")
            self.test_detail_result_var.set("未检测")
            self.test_detail_success_models_var.set("未批量测试")
            self._sync_success_models_button(None)
            self.test_detail_badge.configure(bg=PALETTE["neutral_soft"], fg=PALETTE["neutral_text"])
            self.updating_health_override = True
            self.health_override_var.set(HEALTH_OVERRIDE_DISPLAY[""])
            self.health_override_note_var.set(self._health_override_note(None))
            self.health_override_combo.configure(state="disabled")
            self.updating_health_override = False
            self._reset_model_batch_for_profile(None)
            self._reset_chat_target(None)
            return

        self.test_selected_name_var.set(profile.name)
        self.test_detail_health_var.set(self._health_status_text(profile))
        self.test_detail_provider_var.set(profile.provider_name)
        self.test_detail_model_var.set(self._profile_model_summary(profile))
        self.test_detail_api_var.set(profile.base_url)
        self.test_detail_key_var.set(self._profile_key_summary(profile))
        self.test_detail_wire_var.set(profile.wire_api)
        self.test_detail_endpoint_var.set(profile.health.endpoint or "-")
        checked_text = profile.health.checked_at or "-"
        if profile.health.latency_ms is not None:
            checked_text = f"{checked_text}    {profile.health.latency_ms} ms"
        self.test_detail_checked_var.set(checked_text)
        self.test_detail_notes_var.set(profile.notes or "暂无备注")
        self.test_detail_result_var.set(profile.health.detail or "未检测")
        self.test_detail_success_models_var.set(self._model_batch_health_summary(profile))
        self._sync_success_models_button(profile)
        badge_fg, badge_bg = STATUS_COLORS.get(profile.effective_health_status, STATUS_COLORS["unknown"])
        self.test_detail_badge.configure(bg=badge_bg, fg=badge_fg)
        self.updating_health_override = True
        self.health_override_var.set(HEALTH_OVERRIDE_DISPLAY.get(profile.manual_health_status or "", HEALTH_OVERRIDE_DISPLAY[""]))
        self.health_override_note_var.set(self._health_override_note(profile))
        self.health_override_combo.configure(state="readonly")
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
        cache = self._model_batch_cache(profile)
        if profile is None or cache is None:
            return "未批量测试"
        if not cache.completed:
            finished = sum(1 for item in cache.results.values() if item.status in {"success", "error"})
            success_count = sum(1 for item in cache.results.values() if item.status == "success")
            return f"测试中：已完成 {finished}/{len(cache.models)}，成功 {success_count}"
        success_models = successful_model_batch_models(cache)
        if not success_models:
            return "无成功模型"
        return compact_text(", ".join(success_models), 140)

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
        success_count = sum(1 for item in cache.results.values() if item.status == "success")
        error_count = sum(1 for item in cache.results.values() if item.status == "error")
        return success_count, error_count

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
        )

    def save_settings(self) -> None:
        self.model_batch_concurrency = clamp_model_batch_concurrency(self.model_batch_concurrency_var.get())
        self.model_batch_concurrency_var.set(str(self.model_batch_concurrency))
        self.persist_state()
        self.settings_hint_var.set(f"已保存设置：模型批量测试最多 {self.model_batch_concurrency} 个并发请求。")
        self.status_var.set("已保存设置。")

    def on_close(self) -> None:
        self.route_proxy_server.stop()
        _release_single_instance()
        self.root.destroy()

    def _selected_proxy_project(self) -> ProjectRecord | None:
        if hasattr(self, "proxy_project_tree"):
            selection = self.proxy_project_tree.selection()
            if selection:
                return self._project_by_id(selection[0])
        return self.get_selected_project()

    def _route_proxy_base_url_for_project(self, project: ProjectRecord) -> str | None:
        if not self.route_proxy_settings.project_enabled(project.id):
            return None
        return self.route_proxy_settings.project_base_url(project.id)

    def _record_route_proxy_event(self, event: RouteProxyEvent) -> None:
        self.route_proxy_settings.append_event(event)
        self.root.after(0, self._render_proxy_log)

    def save_route_proxy_settings(self) -> bool:
        self.route_proxy_settings.host = self.proxy_host_var.get().strip() or self.route_proxy_settings.host
        raw_port = self.proxy_port_var.get().strip() or str(self.route_proxy_settings.port)
        try:
            int(raw_port)
        except ValueError:
            messagebox.showerror("保存失败", "代理端口必须是数字。", parent=self.root)
            return False
        self.route_proxy_settings.port = normalize_route_proxy_port(raw_port)
        self.persist_state()
        self.refresh_proxy_tab()
        self.status_var.set("路由代理设置已保存。")
        return True

    def start_route_proxy(self, show_errors: bool = True) -> None:
        if not self.save_route_proxy_settings():
            return
        self.route_proxy_settings.enabled = True
        try:
            self.route_proxy_server.start()
        except Exception as exc:
            self.route_proxy_settings.enabled = False
            if show_errors:
                messagebox.showerror("启动失败", f"路由代理启动失败：\n{exc}", parent=self.root)
            self.status_var.set("路由代理启动失败")
            self.persist_state()
            return
        self.persist_state()
        self.refresh_proxy_tab()
        self.status_var.set(f"路由代理已启动：{self.route_proxy_settings.base_url}")

    def stop_route_proxy(self) -> None:
        self.route_proxy_server.stop()
        self.route_proxy_settings.enabled = False
        self.persist_state()
        self.refresh_proxy_tab()
        self.status_var.set("路由代理已停止。")

    def enable_route_proxy_for_project(self) -> None:
        project = self._selected_proxy_project()
        if not project:
            messagebox.showinfo("提示", "请先选择一个项目。", parent=self.root)
            return
        codex_profile_id = project.codex_profile_id or project.profile_id
        codex_profile = self._profile_by_id(codex_profile_id)
        if codex_profile is None:
            messagebox.showerror("无法启用", "当前项目绑定的 Codex 配置已经不存在。", parent=self.root)
            return
        codex_protocol = self.proxy_codex_protocol_var.get().strip() or ROUTE_PROXY_PROTOCOL_OPENAI
        claude_protocol = self.proxy_claude_protocol_var.get().strip() or ROUTE_PROXY_PROTOCOL_ANTHROPIC
        claude_profile = self._profile_by_id(project.claude_profile_id or project.profile_id)
        if claude_profile is None:
            messagebox.showerror("无法启用", "当前项目绑定的 Claude 配置已经不存在。", parent=self.root)
            return
        self.route_proxy_settings = self.route_proxy_settings.without_project_rules(project.id)
        self.route_proxy_settings.rules.extend(route_proxy_rules_for_project(project, codex_profile, claude_profile, codex_protocol, claude_protocol))
        self.persist_state()
        self.refresh_proxy_tab()
        if self._sync_project_api_binding(project):
            self.refresh_project_tab()
            self.refresh_proxy_tab()
            self.status_var.set(f"已启用项目路由代理并同步配置：{project.name}")

    def disable_route_proxy_for_project(self) -> None:
        project = self._selected_proxy_project()
        if not project:
            messagebox.showinfo("提示", "请先选择一个项目。", parent=self.root)
            return
        self.route_proxy_settings = self.route_proxy_settings.without_project_rules(project.id)
        self.persist_state()
        self.refresh_proxy_tab()
        if self._sync_project_api_binding(project):
            self.refresh_project_tab()
            self.refresh_proxy_tab()
            self.status_var.set(f"已关闭项目路由代理并同步配置：{project.name}")

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

    def edit_global_mcp(self) -> None:
        dialog = McpConfigDialog(
            self.root,
            title="编辑全局 MCP",
            subtitle="只支持 [mcp_servers.<name>] 相关 TOML 配置。为空时会回退到默认全局 MCP；如需显式禁用，请使用“清空 MCP”。",
            initial_text=resolve_mcp_editor_text(self.global_mcp_toml, load_default_global_mcp_toml()),
        )
        self.root.wait_window(dialog)
        if dialog.result is None:
            return
        self.global_mcp_toml = dialog.result or load_default_global_mcp_toml()
        self.global_mcp_opt_out = False
        self.persist_state()
        self.refresh_global_tab()
        self.refresh_project_tab()
        self.refresh_mcp_tab()
        self.status_var.set("已更新全局 MCP 配置。")

    def clear_global_mcp(self) -> None:
        if not messagebox.askyesno("确认清空", "清空后将显式禁用默认全局 MCP 注入，是否继续？", parent=self.root):
            return
        self.global_mcp_toml = ""
        self.global_mcp_opt_out = True
        self.applied_global_mcp_server_names = []
        self.persist_state()
        self.refresh_global_tab()
        self.refresh_project_tab()
        self.refresh_mcp_tab()
        self.status_var.set("已清空全局 MCP 配置。")

    def add_mcp_server(self) -> None:
        dialog = McpServerDialog(self.root)
        self.root.wait_window(dialog)
        if dialog.result is None:
            return
        server_name = dialog.result["name"]
        if server_name in self.mcp_page_servers:
            messagebox.showerror("名称重复", f"MCP 工具“{server_name}”已经存在。", parent=self.root)
            return
        self.mcp_page_servers[server_name] = dialog.result["config"]
        self.refresh_mcp_tab(reload_from_state=False)
        self.mcp_tree.selection_set(server_name)
        self.mcp_tree.focus(server_name)
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
        if updated_name != server_name and updated_name in self.mcp_page_servers:
            messagebox.showerror("名称重复", f"MCP 工具“{updated_name}”已经存在。", parent=self.root)
            return
        if updated_name != server_name:
            self.mcp_page_servers.pop(server_name, None)
        self.mcp_page_servers[updated_name] = dialog.result["config"]
        self.refresh_mcp_tab(reload_from_state=False)
        self.mcp_tree.selection_set(updated_name)
        self.mcp_tree.focus(updated_name)
        self._refresh_mcp_detail()
        self.status_var.set(f"已更新 MCP 工具：{updated_name}")

    def delete_mcp_server(self) -> None:
        server_name = self._mcp_selected_name()
        if not server_name:
            messagebox.showinfo("提示", "请先选择一个 MCP 工具。", parent=self.root)
            return
        if not messagebox.askyesno("确认删除", f"确定要删除 MCP 工具“{server_name}”吗？", parent=self.root):
            return
        self.mcp_page_servers.pop(server_name, None)
        self.refresh_mcp_tab(reload_from_state=False)
        self.status_var.set(f"已删除 MCP 工具：{server_name}")

    def save_mcp_servers(self) -> None:
        self.global_mcp_toml = render_mcp_servers_toml(self.mcp_page_servers)
        self.global_mcp_opt_out = not bool(self.mcp_page_servers)
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
            wire_api=dialog.result["wire_api"],
            requires_sign_in=dialog.result["requires_sign_in"],
            sign_in_url=dialog.result["sign_in_url"],
            last_signed_date=dialog.result["last_signed_date"],
            notes=dialog.result["notes"],
        )
        self.profiles = [updated if item.id == updated.id else item for item in self.profiles]
        self.selected_profile_id = updated.id
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
            if profile.id in {project.profile_id, project.codex_profile_id, project.claude_profile_id}
        ]
        if bound_projects:
            messagebox.showerror("无法删除", f"以下项目仍绑定此配置：\n{', '.join(bound_projects)}", parent=self.root)
            return
        if not messagebox.askyesno("确认删除", f"确定要删除配置“{profile.name}”吗？", parent=self.root):
            return
        self.profiles = [item for item in self.profiles if item.id != profile.id]
        if self.selected_profile_id == profile.id:
            self.selected_profile_id = self.profiles[0].id if self.profiles else None
        self.persist_state()
        self.refresh_global_tab()
        self.refresh_library_tab()
        self.refresh_test_tab()
        self.status_var.set(f"已删除配置：{profile.name}")

    def add_project(self) -> None:
        profiles = self._healthy_profiles()
        if not profiles:
            messagebox.showinfo("提示", "请先添加至少一套可用配置。", parent=self.root)
            return
        if not any(profile_supports_codex(profile) for profile in profiles) or not any(profile_supports_claude(profile) for profile in profiles):
            messagebox.showinfo("提示", "请先准备可用于 Codex 和 Claude 的配置。通用配置可同时用于两侧。", parent=self.root)
            return
        dialog = ProjectDialog(self.root, profiles=profiles, mcp_server_names=self._available_mcp_server_names())
        self.root.wait_window(dialog)
        if not dialog.result:
            return
        if self._project_by_dir(dialog.result["project_dir"]):
            messagebox.showerror("重复项目", "该项目目录已经添加过了。", parent=self.root)
            return
        project = ProjectRecord.create(
            project_dir=dialog.result["project_dir"],
            profile_id=dialog.result["profile_id"],
            name=dialog.result["name"],
            run_command=dialog.result["run_command"],
            mcp_server_names=dialog.result["mcp_server_names"],
            codex_profile_id=dialog.result["codex_profile_id"],
            claude_profile_id=dialog.result["claude_profile_id"],
        )
        self.projects.append(project)
        self.selected_project_id = project.id
        self.persist_state()
        self.refresh_project_tab()
        self.status_var.set(f"已新增项目：{project.name}")

    def _route_proxy_codex_wire_api_override_for_project(self, project: ProjectRecord) -> str | None:
        for rule in self.route_proxy_settings.rules_for_project(project.id):
            if rule.enabled and rule.client_type == ROUTE_PROXY_CLIENT_CODEX:
                return route_proxy_codex_wire_api_override(rule.upstream_protocol)
        return None

    def _sync_project_api_binding(
        self,
        project: ProjectRecord,
        *,
        sync_codex: bool = True,
        sync_claude: bool = True,
    ) -> bool:
        updated_paths: list[Path] = []
        route_proxy_base_url = self._route_proxy_base_url_for_project(project)
        if sync_codex:
            codex_profile = self._profile_by_id(project.codex_profile_id or project.profile_id)
            if codex_profile is None:
                messagebox.showerror("无法同步", "当前项目绑定的 Codex 配置已经不存在。", parent=self.root)
                return False
            try:
                updated_paths.extend(
                    self.project_template_service.sync_api_binding(
                        Path(project.project_dir),
                        codex_profile,
                        route_proxy_base_url=route_proxy_base_url,
                        wire_api_override=self._route_proxy_codex_wire_api_override_for_project(project),
                    )
                )
            except Exception as exc:
                messagebox.showerror("同步失败", f"项目记录已保存，但同步 Codex API 配置失败：\n{exc}", parent=self.root)
                self.status_var.set("Codex API 配置同步失败")
                return False

        if sync_claude:
            claude_profile = self._profile_by_id(project.claude_profile_id or project.profile_id)
            if claude_profile is None:
                messagebox.showerror("无法同步", "当前项目绑定的 Claude 配置已经不存在。", parent=self.root)
                return False
            try:
                updated_paths.extend(
                    self.project_template_service.sync_claude_binding(
                        Path(project.project_dir),
                        claude_profile,
                        route_proxy_base_url=route_proxy_base_url,
                    )
                )
            except Exception as exc:
                messagebox.showerror("同步失败", f"项目记录已保存，但同步 Claude settings.local.json 失败：\n{exc}", parent=self.root)
                self.status_var.set("Claude settings.local.json 同步失败")
                return False

        if updated_paths:
            self.status_var.set(f"已同步项目配置：{project.name}")
        else:
            self.status_var.set(f"已更新项目：{project.name}")
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
            project=project,
        )
        self.root.wait_window(dialog)
        if not dialog.result:
            return
        duplicate = self._project_by_dir(dialog.result["project_dir"])
        if duplicate and duplicate.id != project.id:
            messagebox.showerror("重复项目", "该项目目录已经绑定到另一个项目。", parent=self.root)
            return
        updated = replace(
            project,
            name=dialog.result["name"],
            project_dir=dialog.result["project_dir"],
            profile_id=dialog.result["profile_id"],
            codex_profile_id=dialog.result["codex_profile_id"],
            claude_profile_id=dialog.result["claude_profile_id"],
            run_command=dialog.result["run_command"],
            mcp_server_names=dialog.result["mcp_server_names"],
            updated_at=now_iso(),
        )
        api_binding_changed = (
            updated.profile_id != project.profile_id
            or updated.codex_profile_id != project.codex_profile_id
            or updated.project_dir != project.project_dir
        )
        claude_binding_changed = (
            updated.claude_profile_id != project.claude_profile_id
            or updated.project_dir != project.project_dir
        )
        self.projects = [updated if item.id == updated.id else item for item in self.projects]
        self.selected_project_id = updated.id
        self.persist_state()
        self.refresh_project_tab()
        if api_binding_changed or claude_binding_changed:
            if self._sync_project_api_binding(
                updated,
                sync_codex=api_binding_changed,
                sync_claude=claude_binding_changed,
            ):
                self.refresh_project_tab()
            return
        self.status_var.set(f"已更新项目：{updated.name}")

    def delete_project(self) -> None:
        project = self.get_selected_project()
        if not project:
            messagebox.showinfo("提示", "请先选择一个项目。", parent=self.root)
            return
        if not messagebox.askyesno("确认删除", f"确定要删除项目“{project.name}”吗？", parent=self.root):
            return
        self.projects = [item for item in self.projects if item.id != project.id]
        if self.selected_project_id == project.id:
            self.selected_project_id = self.projects[0].id if self.projects else None
        self.persist_state()
        self.refresh_project_tab()
        self.status_var.set(f"已删除项目：{project.name}")

    def _apply_profile_to_global_config(self, profile: Profile) -> Path | None:
        if not profile_supports_codex(profile):
            messagebox.showerror("切换失败", "Claude 专用配置不能写入 Codex 全局配置。", parent=self.root)
            return None
        effective_global_mcp = self._effective_global_mcp_toml()
        try:
            backup_dir = self.manager.apply_profile(
                profile,
                global_mcp_toml=effective_global_mcp,
                previous_managed_mcp_server_names=self.applied_global_mcp_server_names,
            )
        except Exception as exc:
            messagebox.showerror("切换失败", f"写入 Codex 配置失败：\n{exc}", parent=self.root)
            self.status_var.set("切换失败")
            return None
        self.applied_global_mcp_server_names = self._safe_mcp_server_names(effective_global_mcp)
        self.selected_profile_id = profile.id
        self.persist_state()
        self.refresh_global_tab()
        self.refresh_library_tab()
        self.refresh_test_tab()
        return backup_dir

    def apply_global_profile(self) -> None:
        profile = self._profile_from_global_choice()
        if not profile:
            messagebox.showinfo("提示", "请先新增或选择一套全局 API 配置。", parent=self.root)
            return
        backup_dir = self._apply_profile_to_global_config(profile)
        if backup_dir is None:
            return
        self.status_var.set(f"已写入全局 Codex 配置：{profile.name}")
        messagebox.showinfo("写入成功", f"已写入全局 Codex 配置“{profile.name}”。\n\n备份位置：\n{backup_dir}", parent=self.root)

    def apply_selected_profile(self) -> None:
        profile = self.get_selected_profile()
        if not profile:
            messagebox.showinfo("提示", "请先选择一个配置项。", parent=self.root)
            return
        if not profile_supports_codex(profile):
            messagebox.showinfo("提示", "Claude 专用配置不能设为 Codex 当前配置。", parent=self.root)
            return
        backup_dir = self._apply_profile_to_global_config(profile)
        if backup_dir is None:
            return
        self.status_var.set(f"已切换到 {profile.name}，并已备份原配置。")
        messagebox.showinfo("切换成功", f"已切换到配置“{profile.name}”。\n\n备份位置：\n{backup_dir}", parent=self.root)

    def generate_project_template(self) -> None:
        project = self.get_selected_project()
        if not project:
            messagebox.showinfo("提示", "请先选择一个项目。", parent=self.root)
            return
        profile = self._profile_by_id(project.codex_profile_id or project.profile_id)
        if not profile:
            messagebox.showerror("无法生成", "当前项目绑定的 Codex 配置已经不存在。", parent=self.root)
            return
        claude_profile = self._profile_by_id(project.claude_profile_id or project.profile_id)
        project_mcp_toml = self._effective_project_mcp_toml(project)
        route_proxy_base_url = self._route_proxy_base_url_for_project(project)
        try:
            result = self.project_template_service.generate(
                Path(project.project_dir),
                profile,
                global_mcp_toml=project_mcp_toml,
                project_mcp_toml=project_mcp_toml,
                agents_doc_text=self.agents_doc_text,
                claude_profile=claude_profile,
                route_proxy_base_url=route_proxy_base_url,
                codex_wire_api_override=self._route_proxy_codex_wire_api_override_for_project(project),
            )
        except Exception as exc:
            messagebox.showerror("生成失败", f"写入项目模板失败：\n{exc}", parent=self.root)
            self.status_var.set("项目模板生成失败")
            return
        self.refresh_project_tab()
        self.status_var.set(f"已生成项目模板：{project.name}")
        messagebox.showinfo(
            "生成成功",
            f"已为项目“{project.name}”生成模板。\n\n启动脚本：\n{result.start_script_path}\n\n备份目录：\n{result.backup_dir}",
            parent=self.root,
        )

    def generate_claude_template(self) -> None:
        project = self.get_selected_project()
        if not project:
            messagebox.showinfo("提示", "请先选择一个项目。", parent=self.root)
            return
        profile = self._profile_by_id(project.claude_profile_id or project.profile_id)
        if not profile:
            messagebox.showerror("无法生成", "当前项目绑定的 Claude 配置已经不存在。", parent=self.root)
            return
        try:
            result = self.project_template_service.generate_claude_template(
                Path(project.project_dir),
                profile,
                project_mcp_toml=self._effective_project_mcp_toml(project),
                agents_doc_text=self.agents_doc_text,
                route_proxy_base_url=self._route_proxy_base_url_for_project(project),
            )
        except Exception as exc:
            messagebox.showerror("生成失败", f"写入 Claude 项目模板失败：\n{exc}", parent=self.root)
            self.status_var.set("Claude 项目模板生成失败")
            return
        self.refresh_project_tab()
        self.status_var.set(f"已生成 Claude 项目模板：{project.name}")
        generated = "\n".join(str(path) for path in result.generated_paths)
        messagebox.showinfo(
            "生成成功",
            f"已为项目“{project.name}”生成 Claude 模板。\n\n生成文件：\n{generated}\n\n备份目录：\n{result.backup_dir}",
            parent=self.root,
        )

    def _edit_project_text_file(self, *, relative_path: str, title: str, missing_message: str, validator) -> None:
        project = self.get_selected_project()
        if not project:
            messagebox.showinfo("提示", "请先选择一个项目。", parent=self.root)
            return
        target = Path(project.project_dir) / relative_path
        if not target.exists():
            messagebox.showinfo("提示", missing_message, parent=self.root)
            return
        try:
            initial_text = target.read_text(encoding="utf-8")
        except OSError as exc:
            messagebox.showerror("打开失败", f"读取配置文件失败：\n{exc}", parent=self.root)
            return
        dialog = McpConfigDialog(
            self.root,
            title=title,
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
        self._edit_project_text_file(
            relative_path=".codex/home/config.toml",
            title="修改 config.toml",
            missing_message="未找到 .codex/home/config.toml，请先生成 Codex 模板。",
            validator=tomllib.loads,
        )

    def edit_project_claude_settings(self) -> None:
        def validate_json(content: str):
            payload = json.loads(content)
            if not isinstance(payload, dict):
                raise ValueError("settings.local.json 必须是一个 JSON object。")
            return payload

        self._edit_project_text_file(
            relative_path=".claude/settings.local.json",
            title="修改 settings.local.json",
            missing_message="未找到 .claude/settings.local.json，请先生成 Claude 模板。",
            validator=validate_json,
        )

    def _get_project_script_path(self, project: ProjectRecord) -> Path:
        ps1_path, cmd_path = project_start_script_paths(project.project_dir)
        if cmd_path.exists():
            return cmd_path
        return ps1_path

    def open_project_folder(self) -> None:
        project = self.get_selected_project()
        if not project:
            messagebox.showinfo("提示", "请先选择一个项目。", parent=self.root)
            return
        project_root = Path(project.project_dir)
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
        try:
            subprocess.Popen(
                ["cmd.exe", "/c", "code.cmd", str(Path(project.project_dir))],
                cwd=project.project_dir,
                creationflags=_CREATE_NEW_CONSOLE,
            )
        except Exception as exc:
            messagebox.showerror("启动失败", f"使用 VS Code 打开项目失败：\n{exc}", parent=self.root)
            return
        self.status_var.set(f"已用 VS Code 打开项目：{project.name}")

    def open_project_claude_cmd(self) -> None:
        project = self.get_selected_project()
        if not project:
            messagebox.showinfo("提示", "请先选择一个项目。", parent=self.root)
            return
        profile = self._profile_by_id(project.claude_profile_id or project.profile_id)
        if not profile:
            messagebox.showerror("启动失败", "项目绑定的 Claude 配置已删除。", parent=self.root)
            return
        if not profile_supports_claude(profile):
            messagebox.showerror("启动失败", "项目绑定的配置不支持 Claude。", parent=self.root)
            return
        route_proxy_base_url = self._route_proxy_base_url_for_project(project)
        try:
            self.project_template_service.sync_claude_binding(
                Path(project.project_dir),
                profile,
                route_proxy_base_url=route_proxy_base_url,
            )
        except Exception as exc:
            messagebox.showerror("启动失败", f"同步 Claude settings.local.json 失败：\n{exc}", parent=self.root)
            return
        env = apply_claude_profile_env(os.environ.copy(), profile)
        if route_proxy_base_url:
            env[CLAUDE_BASE_URL_ENV_KEY] = route_proxy_base_url
            env[CLAUDE_API_KEY_ENV_KEY] = ROUTE_PROXY_PLACEHOLDER_KEY
        try:
            subprocess.Popen(
                ["cmd.exe", "/k", "claude"],
                cwd=project.project_dir,
                env=env,
                creationflags=_CREATE_NEW_CONSOLE,
            )
        except Exception as exc:
            messagebox.showerror("启动失败", f"打开 Claude CMD 失败：\n{exc}", parent=self.root)
            return
        self.status_var.set(f"已打开 Claude CMD：{project.name}")

    def run_project(self) -> None:
        project = self.get_selected_project()
        if not project:
            messagebox.showinfo("提示", "请先选择一个项目。", parent=self.root)
            return
        if project.run_command.strip():
            try:
                subprocess.Popen(
                    ["cmd.exe", "/k", project.run_command],
                    cwd=project.project_dir,
                    creationflags=_CREATE_NEW_CONSOLE,
                )
            except Exception as exc:
                messagebox.showerror("运行失败", f"启动运行命令失败：\n{exc}", parent=self.root)
                return
            self.status_var.set(f"已在新窗口启动项目命令：{project.name}")
            return
        self.run_project_cmd()

    def run_project_vscode(self) -> None:
        project = self.get_selected_project()
        if not project:
            messagebox.showinfo("提示", "请先选择一个项目。", parent=self.root)
            return
        ps1_path, _cmd_path = project_start_script_paths(project.project_dir)
        if not ps1_path.exists():
            messagebox.showinfo("提示", "尚未找到 start-codex.ps1，请先生成项目模板。", parent=self.root)
            return
        try:
            subprocess.Popen(
                ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(ps1_path)],
                cwd=project.project_dir,
                creationflags=_CREATE_NEW_CONSOLE,
            )
        except Exception as exc:
            messagebox.showerror("启动失败", f"启动 VS Code 脚本失败：\n{exc}", parent=self.root)
            return
        self.status_var.set(f"已通过 PowerShell 启动项目：{project.name}")

    def run_project_cmd(self) -> None:
        project = self.get_selected_project()
        if not project:
            messagebox.showinfo("提示", "请先选择一个项目。", parent=self.root)
            return
        _ps1_path, cmd_path = project_start_script_paths(project.project_dir)
        if not cmd_path.exists():
            messagebox.showinfo("提示", "尚未找到 start-codex.cmd，请先生成项目模板。", parent=self.root)
            return
        try:
            subprocess.Popen(
                ["cmd.exe", "/k", str(cmd_path)],
                cwd=project.project_dir,
                creationflags=_CREATE_NEW_CONSOLE,
            )
        except Exception as exc:
            messagebox.showerror("启动失败", f"启动 CMD 脚本失败：\n{exc}", parent=self.root)
            return
        self.status_var.set(f"已通过 CMD 启动项目：{project.name}")

    def test_selected_profile(self) -> None:
        profile = self.get_selected_profile()
        if not profile:
            messagebox.showinfo("提示", "请先选择一个配置项。", parent=self.root)
            return
        self._run_health_check([profile.id])

    def test_all_profiles(self) -> None:
        if not self.profiles:
            messagebox.showinfo("提示", "请先添加配置项。", parent=self.root)
            return
        self._run_health_check([profile.id for profile in self.profiles])

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

    def _chat_model_options(self, profile: Profile) -> list[str]:
        cache = self._model_batch_cache(profile)
        if cache is not None and cache.completed:
            success_models = successful_model_batch_models(cache)
            return success_models or ["-"]
        models: list[str] = []
        if profile.health.models:
            for model in profile.health.models:
                if model not in models:
                    models.append(model)
        return models or ["-"]

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
        options = self._chat_model_options(profile)
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

        options = self._chat_model_options(profile)
        keep_history = self.chat_profile_id == profile.id
        current_choice = self.chat_model_choice_var.get().strip()
        next_choice = current_choice if keep_history and current_choice and current_choice != "-" else options[0]
        current_wire = self.chat_wire_choice_var.get().strip()
        default_wire = profile.wire_api if profile.wire_api in SUPPORTED_WIRE_APIS else SUPPORTED_WIRE_APIS[0]
        next_wire = current_wire if keep_history and current_wire in SUPPORTED_WIRE_APIS else default_wire
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
