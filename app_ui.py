from __future__ import annotations

from dataclasses import replace
import threading
import tkinter as tk
from tkinter import font as tkfont
from tkinter import messagebox, ttk

from app_chat import ChatResult, ChatTester
from app_codex_config import CodexConfigManager
from app_health import HealthChecker
from app_models import CurrentCodexConfig, HealthResult, Profile
from app_storage import ProfileStore


PALETTE = {
    "app_bg": "#F6FAFC",
    "card_bg": "#FFFFFF",
    "card_border": "#D7E5EC",
    "text": "#203240",
    "muted": "#6E7F8C",
    "accent": "#6E98A7",
    "accent_hover": "#5D8695",
    "success": "#2F855A",
    "success_soft": "#E6F6ED",
    "warning": "#B7791F",
    "warning_soft": "#FEF3E2",
    "danger": "#C05668",
    "danger_soft": "#FBEAEC",
    "neutral_soft": "#F2F7FA",
    "neutral_text": "#576877",
    "selection_bg": "#E6F0F5",
    "tag_bg": "#EDF7EA",
    "tag_text": "#47651F",
    "chat_meta": "#7A8A97",
    "status_bg": "#EDF5F8",
}

STATUS_TEXT = {"healthy": "健康", "degraded": "受限", "error": "异常", "unknown": "未检测"}
STATUS_COLORS = {
    "healthy": (PALETTE["success"], PALETTE["success_soft"]),
    "degraded": (PALETTE["warning"], PALETTE["warning_soft"]),
    "error": (PALETTE["danger"], PALETTE["danger_soft"]),
    "unknown": (PALETTE["neutral_text"], PALETTE["neutral_soft"]),
}

HEALTH_OVERRIDE_DISPLAY = {
    "": "自动（跟随检测）",
    "healthy": "手动：健康",
    "degraded": "手动：受限",
    "error": "手动：异常",
    "unknown": "手动：未检测",
}

HEALTH_OVERRIDE_VALUE_BY_DISPLAY = {
    display: value for value, display in HEALTH_OVERRIDE_DISPLAY.items()
}


def compact_text(value: str, limit: int = 54) -> str:
    return value if len(value) <= limit else f"{value[:limit - 1]}…"


def hidden_secret(value: str | None) -> str:
    if not value:
        return "-"
    return "*" * min(max(len(value), 8), 24)


class ProfileDialog(tk.Toplevel):
    def __init__(self, master: tk.Misc, profile: Profile | None = None) -> None:
        super().__init__(master)
        self.title("配置项")
        self.resizable(False, False)
        self.configure(bg=PALETTE["app_bg"])
        self.result: dict | None = None

        defaults = profile or Profile.create(name="", base_url="", api_key="")
        self.name_var = tk.StringVar(value=defaults.name)
        self.base_url_var = tk.StringVar(value=defaults.base_url)
        self.api_key_var = tk.StringVar(value=defaults.api_key)
        self.model_var = tk.StringVar(value=defaults.model)
        self.provider_name_var = tk.StringVar(value=defaults.provider_name)
        self.wire_api_var = tk.StringVar(value=defaults.wire_api)
        self.show_key_var = tk.BooleanVar(value=False)

        card = tk.Frame(self, bg=PALETTE["card_bg"], highlightbackground=PALETTE["card_border"], highlightthickness=1, padx=20, pady=18)
        card.grid(padx=18, pady=18, sticky="nsew")
        tk.Label(card, text="新增或编辑配置", bg=PALETTE["card_bg"], fg=PALETTE["text"], font=("Microsoft YaHei UI", 14, "bold")).grid(row=0, column=0, columnspan=3, sticky="w")
        tk.Label(card, text="默认模型用于切换和测试对话，接口返回模型会在健康检测后单独显示。", bg=PALETTE["card_bg"], fg=PALETTE["muted"], font=("Microsoft YaHei UI", 9)).grid(row=1, column=0, columnspan=3, sticky="w", pady=(4, 14))

        fields = [("名称", self.name_var), ("API 地址", self.base_url_var), ("API Key", self.api_key_var), ("默认模型", self.model_var), ("提供方名称", self.provider_name_var), ("Wire API", self.wire_api_var)]
        self.entries: dict[str, ttk.Entry] = {}
        for index, (label, variable) in enumerate(fields, start=2):
            tk.Label(card, text=label, bg=PALETTE["card_bg"], fg=PALETTE["text"], font=("Microsoft YaHei UI", 10, "bold")).grid(row=index, column=0, sticky="w", pady=6)
            show = "*" if label == "API Key" and not self.show_key_var.get() else ""
            entry = ttk.Entry(card, textvariable=variable, width=48, show=show)
            entry.grid(row=index, column=1, sticky="ew", pady=6)
            self.entries[label] = entry
        ttk.Checkbutton(card, text="显示 Key", variable=self.show_key_var, command=self._toggle_key_visibility).grid(row=4, column=2, padx=(8, 0), sticky="w")

        tk.Label(card, text="备注", bg=PALETTE["card_bg"], fg=PALETTE["text"], font=("Microsoft YaHei UI", 10, "bold")).grid(row=8, column=0, sticky="nw", pady=6)
        self.notes_text = tk.Text(card, width=48, height=4, wrap="word", relief="solid", borderwidth=1, highlightthickness=0, font=("Microsoft YaHei UI", 10), fg=PALETTE["text"])
        self.notes_text.grid(row=8, column=1, columnspan=2, sticky="ew", pady=6)
        if defaults.notes:
            self.notes_text.insert("1.0", defaults.notes)

        buttons = ttk.Frame(card)
        buttons.grid(row=9, column=0, columnspan=3, sticky="e", pady=(14, 0))
        ttk.Button(buttons, text="取消", style="Subtle.TButton", command=self.destroy).grid(row=0, column=0, padx=(0, 8))
        ttk.Button(buttons, text="保存配置", style="Accent.TButton", command=self._on_submit).grid(row=0, column=1)

        card.columnconfigure(1, weight=1)
        self.transient(master)
        self.grab_set()
        self.entries["名称"].focus_set()

    def _toggle_key_visibility(self) -> None:
        self.entries["API Key"].configure(show="" if self.show_key_var.get() else "*")

    def _on_submit(self) -> None:
        name = self.name_var.get().strip()
        base_url = self.base_url_var.get().strip()
        api_key = self.api_key_var.get().strip()
        model = self.model_var.get().strip()
        if not name:
            messagebox.showerror("校验失败", "请输入配置名称。", parent=self)
            return
        if not base_url.startswith(("http://", "https://")):
            messagebox.showerror("校验失败", "API 地址必须以 http:// 或 https:// 开头。", parent=self)
            return
        if not api_key:
            messagebox.showerror("校验失败", "请输入 API Key。", parent=self)
            return
        if not model:
            messagebox.showerror("校验失败", "请至少填写一个默认模型。", parent=self)
            return
        self.result = {
            "name": name,
            "base_url": base_url.rstrip("/"),
            "api_key": api_key,
            "model": model,
            "provider_name": self.provider_name_var.get().strip() or "OpenAI",
            "wire_api": self.wire_api_var.get().strip() or "responses",
            "notes": self.notes_text.get("1.0", "end").strip(),
        }
        self.destroy()


class CodexSwitchApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("Codex Switch")
        self.root.geometry("1280x820")
        self.root.minsize(1120, 720)
        self.root.configure(bg=PALETTE["app_bg"])

        self.store = ProfileStore()
        self.manager = CodexConfigManager()
        self.health_checker = HealthChecker()
        self.chat_tester = ChatTester()
        self.profiles, self.selected_profile_id = self.store.load()
        self.current_config: CurrentCodexConfig | None = None
        self.current_key_visible = False
        self.detail_key_visible = False
        self.chat_profile_id: str | None = None
        self.chat_busy = False

        self.status_var = tk.StringVar(value="准备就绪")
        self.current_name_var = tk.StringVar(value="正在读取当前配置...")
        self.current_meta_var = tk.StringVar(value="")
        self.current_api_var = tk.StringVar(value="")
        self.current_auth_var = tk.StringVar(value="")
        self.current_models_var = tk.StringVar(value="")
        self.current_path_var = tk.StringVar(value="")
        self.current_key_var = tk.StringVar(value="-")
        self.current_key_button_var = tk.StringVar(value="显示")
        self.library_hint_var = tk.StringVar(value="还没有保存的配置。")
        self.detail_title_var = tk.StringVar(value="选择一个配置查看详情")
        self.detail_subtitle_var = tk.StringVar(value="这里展示选中配置、接口状态和 API 返回模型")
        self.detail_health_var = tk.StringVar(value="未检测")
        self.detail_provider_var = tk.StringVar(value="-")
        self.detail_model_var = tk.StringVar(value="-")
        self.detail_api_var = tk.StringVar(value="-")
        self.detail_key_var = tk.StringVar(value="-")
        self.detail_key_button_var = tk.StringVar(value="显示")
        self.detail_wire_var = tk.StringVar(value="-")
        self.detail_endpoint_var = tk.StringVar(value="-")
        self.detail_checked_var = tk.StringVar(value="-")
        self.detail_notes_var = tk.StringVar(value="暂无备注")
        self.detail_result_var = tk.StringVar(value="未检测")
        self.health_override_var = tk.StringVar(value=HEALTH_OVERRIDE_DISPLAY[""])
        self.health_override_note_var = tk.StringVar(value="自动检测仅代表连通性，可在这里手动修正。")
        self.chat_target_var = tk.StringVar(value="未选择测试配置")
        self.chat_model_var = tk.StringVar(value="-")
        self.chat_model_choice_var = tk.StringVar(value="-")
        self.updating_health_override = False

        self._setup_theme()
        self._build_ui()
        self.refresh_current_config()
        self.refresh_profile_list()
        self.refresh_detail_panel()

    def _setup_theme(self) -> None:
        self.hero_font = tkfont.Font(family="Microsoft YaHei UI", size=14, weight="bold")
        self.section_font = tkfont.Font(family="Microsoft YaHei UI", size=11, weight="bold")
        self.body_font = tkfont.Font(family="Microsoft YaHei UI", size=10)
        self.small_font = tkfont.Font(family="Microsoft YaHei UI", size=9)

        style = ttk.Style(self.root)
        style.theme_use("clam")
        style.configure(".", font=self.body_font)
        style.configure("Treeview", rowheight=34, fieldbackground=PALETTE["card_bg"], background=PALETTE["card_bg"])
        style.configure("Treeview.Heading", font=("Microsoft YaHei UI", 10, "bold"), background="#F8FBFD", foreground=PALETTE["text"], relief="flat")
        style.map("Treeview", background=[("selected", PALETTE["selection_bg"])], foreground=[("selected", PALETTE["text"])])
        style.configure("Accent.TButton", background=PALETTE["accent"], foreground="#FFFFFF", borderwidth=0, padding=(14, 8))
        style.map("Accent.TButton", background=[("active", PALETTE["accent_hover"])])
        style.configure("Subtle.TButton", background="#F6FAFC", foreground=PALETTE["text"], borderwidth=1, padding=(12, 8))
        style.map("Subtle.TButton", background=[("active", "#EAF2F6")])

    def _build_ui(self) -> None:
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)

        content = tk.Frame(self.root, bg=PALETTE["app_bg"], padx=18, pady=16)
        content.grid(row=0, column=0, sticky="nsew")
        content.columnconfigure(0, weight=5)
        content.columnconfigure(1, weight=6)
        content.rowconfigure(0, weight=1)

        left = tk.Frame(content, bg=PALETTE["app_bg"])
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
        left.columnconfigure(0, weight=1)
        left.rowconfigure(0, weight=0)
        left.rowconfigure(1, weight=1)

        right = tk.Frame(content, bg=PALETTE["app_bg"])
        right.grid(row=0, column=1, sticky="nsew")
        right.columnconfigure(0, weight=1)
        right.rowconfigure(0, weight=4)
        right.rowconfigure(1, weight=5)

        self._build_current_card(left)
        self._build_library_card(left)
        self._build_detail_card(right)
        self._build_chat_card(right)

        status_bar = tk.Frame(self.root, bg=PALETTE["status_bg"], padx=18, pady=10)
        status_bar.grid(row=1, column=0, sticky="ew")
        tk.Label(status_bar, textvariable=self.status_var, bg=PALETTE["status_bg"], fg=PALETTE["muted"], font=self.body_font).grid(row=0, column=0, sticky="w")

    def _make_card(self, parent: tk.Misc, padx: int = 16, pady: int = 16) -> tk.Frame:
        return tk.Frame(parent, bg=PALETTE["card_bg"], highlightbackground=PALETTE["card_border"], highlightthickness=1, padx=padx, pady=pady)

    def _build_current_card(self, parent: tk.Misc) -> None:
        card = self._make_card(parent, 18, 16)
        card.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        card.columnconfigure(0, weight=1)
        card.columnconfigure(1, weight=1)

        left = tk.Frame(card, bg=PALETTE["card_bg"])
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 18))
        left.columnconfigure(0, weight=1)
        tk.Label(left, text="当前生效配置", bg=PALETTE["card_bg"], fg=PALETTE["text"], font=self.section_font).grid(row=0, column=0, sticky="w")
        tk.Label(left, textvariable=self.current_name_var, bg=PALETTE["card_bg"], fg=PALETTE["text"], font=self.hero_font).grid(row=1, column=0, sticky="w", pady=(8, 2))
        tk.Label(left, textvariable=self.current_meta_var, bg=PALETTE["card_bg"], fg=PALETTE["muted"], font=self.body_font, justify="left").grid(row=2, column=0, sticky="w")
        tk.Label(left, textvariable=self.current_api_var, bg=PALETTE["card_bg"], fg=PALETTE["text"], font=self.body_font, justify="left", wraplength=420).grid(row=3, column=0, sticky="w", pady=(10, 4))
        tk.Label(left, textvariable=self.current_auth_var, bg=PALETTE["card_bg"], fg=PALETTE["muted"], font=self.small_font, justify="left").grid(row=4, column=0, sticky="w")
        tk.Label(left, text="当前 API Key", bg=PALETTE["card_bg"], fg=PALETTE["text"], font=self.section_font).grid(row=5, column=0, sticky="w", pady=(14, 4))
        tk.Label(left, textvariable=self.current_key_var, bg=PALETTE["card_bg"], fg=PALETTE["muted"], font=self.body_font).grid(row=6, column=0, sticky="w")
        tk.Label(left, text="当前配置模型", bg=PALETTE["card_bg"], fg=PALETTE["text"], font=self.section_font).grid(row=7, column=0, sticky="w", pady=(14, 4))
        tk.Label(left, textvariable=self.current_models_var, bg=PALETTE["card_bg"], fg=PALETTE["muted"], font=self.body_font, justify="left", wraplength=420).grid(row=8, column=0, sticky="w")

        right = tk.Frame(card, bg=PALETTE["card_bg"])
        right.grid(row=0, column=1, sticky="nsew")
        right.columnconfigure(0, weight=1)
        tk.Label(right, text="配置文件位置", bg=PALETTE["card_bg"], fg=PALETTE["text"], font=self.section_font).grid(row=0, column=0, sticky="w")
        tk.Label(right, textvariable=self.current_path_var, bg=PALETTE["card_bg"], fg=PALETTE["muted"], font=self.small_font, justify="left", wraplength=380).grid(row=1, column=0, sticky="w", pady=(10, 12))
        self.current_status_badge = tk.Label(right, text="未匹配", bg=PALETTE["neutral_soft"], fg=PALETTE["neutral_text"], font=("Microsoft YaHei UI", 10, "bold"), padx=12, pady=6)
        self.current_status_badge.grid(row=2, column=0, sticky="w")

    def _build_library_card(self, parent: tk.Misc) -> None:
        card = self._make_card(parent, 16, 16)
        card.grid(row=1, column=0, sticky="nsew")
        card.columnconfigure(0, weight=1)
        card.rowconfigure(1, weight=1)

        tk.Label(card, text="配置库", bg=PALETTE["card_bg"], fg=PALETTE["text"], font=self.hero_font).grid(row=0, column=0, sticky="w")
        tk.Label(card, textvariable=self.library_hint_var, bg=PALETTE["card_bg"], fg=PALETTE["muted"], font=self.small_font).grid(row=0, column=0, sticky="e")

        tree_container = tk.Frame(card, bg=PALETTE["card_bg"])
        tree_container.grid(row=1, column=0, sticky="nsew", pady=(12, 0))
        tree_container.columnconfigure(0, weight=1)
        tree_container.rowconfigure(0, weight=1)

        columns = ("name", "base_url", "model", "health")
        self.tree = ttk.Treeview(tree_container, columns=columns, show="headings")
        self.tree.heading("name", text="配置名")
        self.tree.heading("base_url", text="API 地址")
        self.tree.heading("model", text="默认模型")
        self.tree.heading("health", text="健康状态")
        self.tree.column("name", width=150, anchor="w")
        self.tree.column("base_url", width=240, anchor="w")
        self.tree.column("model", width=130, anchor="w")
        self.tree.column("health", width=100, anchor="center")
        self.tree.grid(row=0, column=0, sticky="nsew")
        self.tree.bind("<<TreeviewSelect>>", lambda _event: self.refresh_detail_panel())

        scrollbar = ttk.Scrollbar(tree_container, orient="vertical", command=self.tree.yview)
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.tree.configure(yscrollcommand=scrollbar.set)
        self.tree.tag_configure("healthy", foreground=PALETTE["success"])
        self.tree.tag_configure("degraded", foreground=PALETTE["warning"])
        self.tree.tag_configure("error", foreground=PALETTE["danger"])
        self.tree.tag_configure("unknown", foreground=PALETTE["neutral_text"])

        actions = tk.Frame(card, bg=PALETTE["card_bg"])
        actions.grid(row=2, column=0, sticky="ew", pady=(14, 0))
        for column in range(4):
            actions.columnconfigure(column, weight=1)
        ttk.Button(actions, text="新增", style="Accent.TButton", command=self.add_profile).grid(row=0, column=0, sticky="ew", padx=(0, 8), pady=(0, 8))
        ttk.Button(actions, text="编辑", style="Subtle.TButton", command=self.edit_profile).grid(row=0, column=1, sticky="ew", padx=(0, 8), pady=(0, 8))
        ttk.Button(actions, text="删除", style="Subtle.TButton", command=self.delete_profile).grid(row=0, column=2, sticky="ew", padx=(0, 8), pady=(0, 8))
        ttk.Button(actions, text="刷新", style="Subtle.TButton", command=self.refresh_all).grid(row=0, column=3, sticky="ew", pady=(0, 8))
        ttk.Button(actions, text="设为当前", style="Accent.TButton", command=self.apply_selected_profile).grid(row=1, column=0, columnspan=2, sticky="ew", padx=(0, 8))
        ttk.Button(actions, text="测试选中", style="Subtle.TButton", command=self.test_selected_profile).grid(row=1, column=2, sticky="ew", padx=(0, 8))
        ttk.Button(actions, text="测试全部", style="Subtle.TButton", command=self.test_all_profiles).grid(row=1, column=3, sticky="ew")

    def _build_detail_card(self, parent: tk.Misc) -> None:
        card = self._make_card(parent, 18, 16)
        card.grid(row=0, column=0, sticky="nsew", pady=(0, 10))
        card.columnconfigure(0, weight=1)

        header = tk.Frame(card, bg=PALETTE["card_bg"])
        header.grid(row=0, column=0, sticky="ew")
        header.columnconfigure(0, weight=1)
        tk.Label(header, textvariable=self.detail_title_var, bg=PALETTE["card_bg"], fg=PALETTE["text"], font=self.hero_font).grid(row=0, column=0, sticky="w")
        tk.Label(header, textvariable=self.detail_subtitle_var, bg=PALETTE["card_bg"], fg=PALETTE["muted"], font=self.small_font).grid(row=1, column=0, sticky="w", pady=(4, 0))
        self.detail_badge = tk.Label(header, textvariable=self.detail_health_var, bg=PALETTE["neutral_soft"], fg=PALETTE["neutral_text"], font=("Microsoft YaHei UI", 10, "bold"), padx=12, pady=6)
        self.detail_badge.grid(row=0, column=1, rowspan=2, sticky="e")

        info = tk.Frame(card, bg=PALETTE["card_bg"])
        info.grid(row=1, column=0, sticky="nsew", pady=(14, 0))
        info.columnconfigure(1, weight=1)
        tk.Label(info, text="健康状态判定", bg=PALETTE["card_bg"], fg=PALETTE["muted"], font=self.small_font).grid(row=0, column=0, sticky="nw", padx=(0, 14), pady=4)
        health_override_row = tk.Frame(info, bg=PALETTE["card_bg"])
        health_override_row.grid(row=0, column=1, sticky="ew", pady=4)
        health_override_row.columnconfigure(0, weight=1)
        self.health_override_combo = ttk.Combobox(
            health_override_row,
            textvariable=self.health_override_var,
            state="readonly",
            values=tuple(HEALTH_OVERRIDE_DISPLAY.values()),
            width=22,
        )
        self.health_override_combo.grid(row=0, column=0, sticky="w")
        self.health_override_combo.bind("<<ComboboxSelected>>", self._on_health_override_changed)
        tk.Label(health_override_row, textvariable=self.health_override_note_var, bg=PALETTE["card_bg"], fg=PALETTE["muted"], font=self.small_font, wraplength=220, justify="left").grid(row=1, column=0, sticky="w", pady=(6, 0))

        self._create_info_row(info, 1, "提供方", self.detail_provider_var)
        self._create_info_row(info, 2, "默认模型", self.detail_model_var)
        self._create_info_row(info, 3, "API 地址", self.detail_api_var)

        tk.Label(info, text="API Key", bg=PALETTE["card_bg"], fg=PALETTE["muted"], font=self.small_font).grid(row=4, column=0, sticky="nw", padx=(0, 14), pady=4)
        tk.Label(info, textvariable=self.detail_key_var, bg=PALETTE["card_bg"], fg=PALETTE["text"], font=self.body_font, wraplength=320).grid(row=4, column=1, sticky="w", pady=4)

        self._create_info_row(info, 5, "Wire API", self.detail_wire_var)
        self._create_info_row(info, 6, "检测端点", self.detail_endpoint_var)
        self._create_info_row(info, 7, "最近检测", self.detail_checked_var)
        self._create_info_row(info, 8, "备注", self.detail_notes_var)
        self._create_info_row(info, 9, "检测详情", self.detail_result_var)

    def _build_chat_card(self, parent: tk.Misc) -> None:
        card = self._make_card(parent, 18, 16)
        card.grid(row=1, column=0, sticky="nsew")
        card.columnconfigure(0, weight=1)
        card.rowconfigure(2, weight=1)

        header = tk.Frame(card, bg=PALETTE["card_bg"])
        header.grid(row=0, column=0, sticky="ew")
        header.columnconfigure(0, weight=1)
        tk.Label(header, text="测试对话", bg=PALETTE["card_bg"], fg=PALETTE["text"], font=self.hero_font).grid(row=0, column=0, sticky="w")
        tk.Label(header, text="使用当前选中的配置发送单轮测试消息。切换配置后，对话区域会自动重置。", bg=PALETTE["card_bg"], fg=PALETTE["muted"], font=self.small_font).grid(row=1, column=0, sticky="w", pady=(4, 0))

        meta = tk.Frame(card, bg=PALETTE["card_bg"])
        meta.grid(row=1, column=0, sticky="ew", pady=(12, 10))
        meta.columnconfigure(1, weight=1)
        tk.Label(meta, text="测试配置", bg=PALETTE["card_bg"], fg=PALETTE["muted"], font=self.small_font).grid(row=0, column=0, sticky="w", padx=(0, 12))
        tk.Label(meta, textvariable=self.chat_target_var, bg=PALETTE["card_bg"], fg=PALETTE["text"], font=self.body_font).grid(row=0, column=1, sticky="w")
        tk.Label(meta, text="测试模型", bg=PALETTE["card_bg"], fg=PALETTE["muted"], font=self.small_font).grid(row=1, column=0, sticky="w", padx=(0, 12), pady=(6, 0))
        self.chat_model_combo = ttk.Combobox(meta, textvariable=self.chat_model_choice_var, state="readonly", values=("-" ,), width=32)
        self.chat_model_combo.grid(row=1, column=1, sticky="w", pady=(6, 0))

        history_wrap = tk.Frame(card, bg=PALETTE["card_bg"])
        history_wrap.grid(row=2, column=0, sticky="nsew")
        history_wrap.columnconfigure(0, weight=1)
        history_wrap.rowconfigure(0, weight=1)
        self.chat_history = tk.Text(history_wrap, wrap="word", relief="solid", borderwidth=1, highlightthickness=0, font=self.body_font, bg="#FBFDFE", fg=PALETTE["text"], state="disabled")
        self.chat_history.grid(row=0, column=0, sticky="nsew")
        chat_scroll = ttk.Scrollbar(history_wrap, orient="vertical", command=self.chat_history.yview)
        chat_scroll.grid(row=0, column=1, sticky="ns")
        self.chat_history.configure(yscrollcommand=chat_scroll.set)

        input_wrap = tk.Frame(card, bg=PALETTE["card_bg"])
        input_wrap.grid(row=3, column=0, sticky="ew", pady=(12, 0))
        input_wrap.columnconfigure(0, weight=1)
        self.chat_input = tk.Text(input_wrap, height=4, wrap="word", relief="solid", borderwidth=1, highlightthickness=0, font=self.body_font, fg=PALETTE["text"])
        self.chat_input.grid(row=0, column=0, sticky="ew")
        buttons = tk.Frame(input_wrap, bg=PALETTE["card_bg"])
        buttons.grid(row=0, column=1, sticky="ns", padx=(10, 0))
        self.chat_send_button = ttk.Button(buttons, text="发送测试", style="Accent.TButton", command=self.send_chat_message)
        self.chat_send_button.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        ttk.Button(buttons, text="清空记录", style="Subtle.TButton", command=self.clear_chat_history).grid(row=1, column=0, sticky="ew")

    def _create_info_row(self, parent: tk.Misc, row: int, label: str, variable: tk.StringVar) -> None:
        tk.Label(parent, text=label, bg=PALETTE["card_bg"], fg=PALETTE["muted"], font=self.small_font).grid(row=row, column=0, sticky="nw", padx=(0, 14), pady=4)
        tk.Label(parent, textvariable=variable, bg=PALETTE["card_bg"], fg=PALETTE["text"], font=self.body_font, justify="left", wraplength=320).grid(row=row, column=1, sticky="w", pady=4)

    def _sync_remote_models_scrollregion(self, _event=None) -> None:
        self.detail_remote_canvas.configure(scrollregion=self.detail_remote_canvas.bbox("all"))

    def _sync_remote_models_width(self, event) -> None:
        self.detail_remote_canvas.itemconfigure(self.detail_remote_window, width=event.width)

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

        selected_display = self.health_override_var.get()
        override_value = HEALTH_OVERRIDE_VALUE_BY_DISPLAY.get(selected_display, "")
        profile.manual_health_status = override_value or None
        self.persist_profiles()
        self.refresh_profile_list()
        self.refresh_detail_panel()
        if profile.manual_health_status:
            self.status_var.set(f"已手动标记 {profile.name} 的健康状态：{STATUS_TEXT.get(profile.manual_health_status, '未检测')}")
        else:
            self.status_var.set(f"已恢复 {profile.name} 的自动健康状态。")

    def refresh_all(self) -> None:
        self.refresh_current_config()
        self.refresh_profile_list()
        self.refresh_detail_panel()
        self.status_var.set("已刷新当前配置、配置库、详情和测试对话区域。")

    def refresh_current_config(self) -> None:
        self.current_config = self.manager.read_current_config()
        self.current_key_visible = False
        matched = self.find_matching_profile(self.current_config)
        matched_text = matched.name if matched else "未匹配到已保存配置"
        api_loaded = "已加载" if self.current_config.api_key_loaded else "未加载"
        self.current_name_var.set(matched_text)
        self.current_meta_var.set(f"提供方：{self.current_config.model_provider or '-'}    Wire API：{self.current_config.wire_api or '-'}")
        self.current_api_var.set(f"API 地址：{self.current_config.base_url or '-'}")
        self.current_auth_var.set(f"鉴权：{self.current_config.auth_mode or '-'}    状态：{api_loaded}")
        self.current_path_var.set(f"config.toml\n{self.current_config.config_path}\n\nauth.json\n{self.current_config.auth_path}")
        model_lines: list[str] = []
        if self.current_config.model:
            model_lines.append(f"主模型：{self.current_config.model}")
        if self.current_config.review_model and self.current_config.review_model != self.current_config.model:
            model_lines.append(f"评审模型：{self.current_config.review_model}")
        self.current_models_var.set("\n".join(model_lines) if model_lines else "当前配置里没有模型信息。")
        self._update_current_key_display()
        if matched:
            self.current_status_badge.configure(text="已匹配本地配置库", bg=PALETTE["success_soft"], fg=PALETTE["success"])
        else:
            self.current_status_badge.configure(text="当前配置未收录", bg=PALETTE["warning_soft"], fg=PALETTE["warning"])

    def refresh_profile_list(self) -> None:
        selected = self.get_selected_profile()
        selected_id = selected.id if selected else self.selected_profile_id
        for item in self.tree.get_children():
            self.tree.delete(item)

        healthy_count = 0
        for profile in self.profiles:
            if profile.effective_health_status == "healthy":
                healthy_count += 1
            health_status = profile.effective_health_status
            self.tree.insert(
                "",
                "end",
                iid=profile.id,
                values=(
                    profile.name,
                    compact_text(profile.base_url, 42),
                    compact_text(profile.model or "-", 18),
                    self._health_status_text(profile),
                ),
                tags=(health_status,),
            )

        if selected_id and any(profile.id == selected_id for profile in self.profiles):
            self.tree.selection_set(selected_id)
            self.tree.focus(selected_id)

        self.library_hint_var.set(f"共 {len(self.profiles)} 套配置，健康配置 {healthy_count} 套。")

    def refresh_detail_panel(self) -> None:
        profile = self.get_selected_profile()
        self.detail_key_visible = False
        if not profile:
            self.selected_profile_id = None
            self.detail_title_var.set("选择一个配置查看详情")
            self.detail_subtitle_var.set("这里展示选中配置和接口状态")
            self.detail_health_var.set("未检测")
            self.detail_provider_var.set("-")
            self.detail_model_var.set("-")
            self.detail_api_var.set("-")
            self.detail_key_var.set("-")
            self.detail_wire_var.set("-")
            self.detail_endpoint_var.set("-")
            self.detail_checked_var.set("-")
            self.detail_notes_var.set("暂无备注")
            self.detail_result_var.set("未检测")
            self.detail_badge.configure(bg=PALETTE["neutral_soft"], fg=PALETTE["neutral_text"])
            self.updating_health_override = True
            self.health_override_var.set(HEALTH_OVERRIDE_DISPLAY[""])
            self.health_override_note_var.set(self._health_override_note(None))
            self.health_override_combo.configure(state="disabled")
            self.updating_health_override = False
            self._reset_chat_target(None)
            return

        self.selected_profile_id = profile.id
        self.detail_title_var.set(profile.name)
        self.detail_subtitle_var.set("这里展示选中配置和最近一次健康检测结果。")
        self.detail_health_var.set(self._health_status_text(profile))
        self.detail_provider_var.set(profile.provider_name)
        self.detail_model_var.set(profile.model or "-")
        self.detail_api_var.set(profile.base_url)
        self.detail_wire_var.set(profile.wire_api)
        self.detail_endpoint_var.set(profile.health.endpoint or "-")
        checked_text = profile.health.checked_at or "-"
        if profile.health.latency_ms is not None:
            checked_text = f"{checked_text}    {profile.health.latency_ms} ms"
        self.detail_checked_var.set(checked_text)
        self.detail_notes_var.set(profile.notes or "暂无备注")
        self.detail_result_var.set(profile.health.detail or "未检测")
        badge_fg, badge_bg = STATUS_COLORS.get(profile.effective_health_status, STATUS_COLORS["unknown"])
        self.detail_badge.configure(bg=badge_bg, fg=badge_fg)
        self._update_detail_key_display(profile)
        self.updating_health_override = True
        self.health_override_var.set(HEALTH_OVERRIDE_DISPLAY.get(profile.manual_health_status or "", HEALTH_OVERRIDE_DISPLAY[""]))
        self.health_override_note_var.set(self._health_override_note(profile))
        self.health_override_combo.configure(state="readonly")
        self.updating_health_override = False
        self._reset_chat_target(profile)

    def find_matching_profile(self, current: CurrentCodexConfig) -> Profile | None:
        for profile in self.profiles:
            if (
                profile.base_url.rstrip("/") == (current.base_url or "").rstrip("/")
                and profile.api_key == (current.api_key or "")
                and profile.provider_name == (current.model_provider or "")
            ):
                return profile
        return None

    def get_selected_profile(self) -> Profile | None:
        selection = self.tree.selection()
        if not selection:
            return next((item for item in self.profiles if item.id == self.selected_profile_id), None)
        return next((item for item in self.profiles if item.id == selection[0]), None)

    def _update_current_key_display(self) -> None:
        api_key = self.current_config.api_key if self.current_config else None
        if api_key:
            self.current_key_var.set(hidden_secret(api_key))
        else:
            self.current_key_var.set("-")

    def _update_detail_key_display(self, profile: Profile | None) -> None:
        if profile and profile.api_key:
            self.detail_key_var.set(hidden_secret(profile.api_key))
        else:
            self.detail_key_var.set("-")

    def toggle_current_key_visibility(self) -> None:
        return

    def toggle_detail_key_visibility(self) -> None:
        return

    def persist_profiles(self) -> None:
        self.store.save(self.profiles, self.selected_profile_id)

    def add_profile(self) -> None:
        dialog = ProfileDialog(self.root)
        self.root.wait_window(dialog)
        if not dialog.result:
            return
        profile = Profile.create(**dialog.result)
        self.profiles.append(profile)
        self.selected_profile_id = profile.id
        self.persist_profiles()
        self.refresh_profile_list()
        self.refresh_detail_panel()
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
            api_key=dialog.result["api_key"],
            model=dialog.result["model"],
            provider_name=dialog.result["provider_name"],
            wire_api=dialog.result["wire_api"],
            notes=dialog.result["notes"],
        )
        self.profiles = [updated if item.id == updated.id else item for item in self.profiles]
        self.selected_profile_id = updated.id
        self.persist_profiles()
        self.refresh_profile_list()
        self.refresh_detail_panel()
        self.status_var.set(f"已更新配置：{updated.name}")

    def delete_profile(self) -> None:
        profile = self.get_selected_profile()
        if not profile:
            messagebox.showinfo("提示", "请先选择一个配置项。", parent=self.root)
            return
        if not messagebox.askyesno("确认删除", f"确定要删除配置“{profile.name}”吗？", parent=self.root):
            return
        self.profiles = [item for item in self.profiles if item.id != profile.id]
        if self.selected_profile_id == profile.id:
            self.selected_profile_id = self.profiles[0].id if self.profiles else None
        self.persist_profiles()
        self.refresh_profile_list()
        self.refresh_detail_panel()
        self.status_var.set(f"已删除配置：{profile.name}")

    def apply_selected_profile(self) -> None:
        profile = self.get_selected_profile()
        if not profile:
            messagebox.showinfo("提示", "请先选择一个配置项。", parent=self.root)
            return
        try:
            backup_dir = self.manager.apply_profile(profile)
        except Exception as exc:
            messagebox.showerror("切换失败", f"写入 Codex 配置失败：\n{exc}", parent=self.root)
            self.status_var.set("切换失败")
            return
        self.refresh_current_config()
        self.persist_profiles()
        self.status_var.set(f"已切换到 {profile.name}，并已备份原配置。")
        messagebox.showinfo("切换成功", f"已切换到配置“{profile.name}”。\n\n备份位置：\n{backup_dir}", parent=self.root)

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
                profile = next((item for item in self.profiles if item.id == profile_id), None)
                if profile is None:
                    continue
                result = self.health_checker.check(profile)
                self.root.after(0, self._apply_health_result, profile_id, result)
            self.root.after(0, self._mark_health_check_complete)

        threading.Thread(target=worker, daemon=True).start()

    def _apply_health_result(self, profile_id: str, result: HealthResult) -> None:
        profile = next((item for item in self.profiles if item.id == profile_id), None)
        if profile is None:
            return
        profile.health = result
        self.persist_profiles()
        self.refresh_profile_list()
        self.refresh_detail_panel()

    def _mark_health_check_complete(self) -> None:
        self.status_var.set("健康检测已完成，右上区域展示的是接口返回模型。")

    def _render_model_tags(self, models: list[str], empty_text: str) -> None:
        for child in self.detail_remote_models_frame.winfo_children():
            child.destroy()
        if not models:
            tk.Label(self.detail_remote_models_frame, text=empty_text, bg=PALETTE["neutral_soft"], fg=PALETTE["muted"], font=self.small_font, justify="left", wraplength=360).grid(row=0, column=0, sticky="w")
            return
        row = 0
        column = 0
        budget = 0
        for model in models:
            estimated = max(8, min(len(model) + 4, 26))
            if column > 0 and budget + estimated > 36:
                row += 1
                column = 0
                budget = 0
            tag = tk.Label(self.detail_remote_models_frame, text=f"{model}  复制", bg=PALETTE["tag_bg"], fg=PALETTE["tag_text"], font=("Microsoft YaHei UI", 9, "bold"), padx=10, pady=5, cursor="hand2")
            tag.grid(row=row, column=column, sticky="w", padx=(0, 8), pady=(0, 8))
            tag.bind("<Button-1>", lambda _event, value=model: self.copy_to_clipboard(value))
            column += 1
            budget += estimated

    def _chat_model_options(self, profile: Profile) -> list[str]:
        models: list[str] = []
        if profile.health.models:
            for model in profile.health.models:
                if model not in models:
                    models.append(model)
        if profile.model and profile.model not in models:
            models.insert(0, profile.model)
        return models or ["-"]

    def _reset_chat_target(self, profile: Profile | None) -> None:
        if profile is None:
            self.chat_profile_id = None
            self.chat_target_var.set("未选择测试配置")
            self.chat_model_var.set("-")
            self.chat_model_combo.configure(values=("-",))
            self.chat_model_choice_var.set("-")
            self.chat_model_combo.configure(state="disabled")
            self.chat_send_button.state(["disabled"])
            self.clear_chat_history()
            self._append_chat_line("系统", "请选择左侧配置库中的一套配置，再开始测试对话。")
            return

        options = self._chat_model_options(profile)
        keep_history = self.chat_profile_id == profile.id
        current_choice = self.chat_model_choice_var.get()
        next_choice = current_choice if current_choice in options else options[0]

        self.chat_profile_id = profile.id
        self.chat_target_var.set(profile.name)
        self.chat_model_var.set(profile.model or "-")
        self.chat_model_combo.configure(values=tuple(options))
        self.chat_model_choice_var.set(next_choice)
        self.chat_model_combo.configure(state="readonly")
        self.chat_send_button.state(["!disabled"])

        if not keep_history:
            self.clear_chat_history()
            self._append_chat_line("系统", f"当前测试配置：{profile.name}\n可选模型：{', '.join(options[:])}")

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
            messagebox.showinfo("提示", "请先在左侧选择一套配置。", parent=self.root)
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
        self._append_chat_line("用户", prompt)
        self.chat_input.delete("1.0", "end")
        self._set_chat_busy(True)
        self.status_var.set(f"正在使用 {profile.name} / {selected_model} 测试对话...")

        def worker() -> None:
            try:
                result = self.chat_tester.send_message(profile, prompt, model_override=selected_model)
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

    def _set_chat_busy(self, busy: bool) -> None:
        self.chat_busy = busy
        if busy:
            self.chat_send_button.state(["disabled"])
            self.chat_model_combo.configure(state="disabled")
        elif self.chat_profile_id:
            self.chat_send_button.state(["!disabled"])
            self.chat_model_combo.configure(state="readonly")

    def copy_to_clipboard(self, value: str) -> None:
        self.root.clipboard_clear()
        self.root.clipboard_append(value)
        self.root.update()
        self.status_var.set(f"已复制模型名：{value}")


def run_app() -> None:
    root = tk.Tk()
    CodexSwitchApp(root)
    root.mainloop()
