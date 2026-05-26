from __future__ import annotations

from collections.abc import Callable
import tkinter as tk
from tkinter import font as tkfont

try:
    import ttkbootstrap as ttk
    from ttkbootstrap import Window as BootstrapWindow
except ImportError:  # pragma: no cover
    from tkinter import ttk

    BootstrapWindow = None

PALETTE = {
    "app_bg": "#F8FAFC",
    "panel_bg": "#E7EDF5",
    "card_bg": "#FFFFFF",
    "card_border": "#CBD5E1",
    "text": "#0F172A",
    "muted": "#64748B",
    "accent": "#2563EB",
    "accent_hover": "#1D4ED8",
    "success": "#059669",
    "success_soft": "#D1FAE5",
    "warning": "#B45309",
    "warning_soft": "#FEF3C7",
    "danger": "#E11D48",
    "danger_soft": "#FFE4E6",
    "neutral_soft": "#E2E8F0",
    "neutral_text": "#475569",
    "selection_bg": "#DBEAFE",
    "tag_bg": "#DCFCE7",
    "tag_text": "#166534",
    "chat_meta": "#64748B",
    "status_bg": "#F8FAFC",
    "tab_idle": "#E2E8F0",
    "tab_active": "#FFFFFF",
    "link": "#1D4ED8",
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

BOOTSTRAP_THEME = "flatly"
BUTTON_STYLE = {
    "primary": "Accent.TButton",
    "small_primary": "SmallAccent.TButton",
    "secondary": "Subtle.TButton",
    "danger": "Danger.TButton",
}

def make_button(
    parent: tk.Misc,
    *,
    command,
    variant: str = "secondary",
    text: str | None = None,
    textvariable: tk.StringVar | None = None,
    width: int | None = None,
) -> ttk.Button:
    options = {"command": command}
    if text is not None:
        options["text"] = text
    if textvariable is not None:
        options["textvariable"] = textvariable
    if width is not None:
        options["width"] = width

    options["style"] = BUTTON_STYLE.get(variant, BUTTON_STYLE["secondary"])
    return ttk.Button(parent, **options)

def configure_theme_styles(style: ttk.Style, body_font: tkfont.Font, small_font: tkfont.Font) -> None:
    style.configure(".", font=body_font)
    style.configure("TFrame", background=PALETTE["card_bg"])
    style.configure("TLabelframe", background=PALETTE["card_bg"], borderwidth=1)
    style.configure("TLabelframe.Label", font=small_font, foreground=PALETTE["muted"])
    style.configure("TEntry", padding=(8, 5), fieldbackground="#FFFFFF", bordercolor=PALETTE["card_border"])
    style.configure("TCombobox", padding=(8, 5), fieldbackground="#FFFFFF", bordercolor=PALETTE["card_border"])
    style.configure("TCheckbutton", font=body_font)
    style.configure("Vertical.TScrollbar", width=12)
    style.configure("Horizontal.TScrollbar", width=12)
    style.configure(
        "Treeview",
        rowheight=34,
        font=body_font,
        fieldbackground=PALETTE["card_bg"],
        background=PALETTE["card_bg"],
        borderwidth=0,
        relief="flat",
    )
    style.configure(
        "Treeview.Heading",
        font=("Microsoft YaHei UI", 10, "bold"),
        background="#EEF2FF",
        foreground=PALETTE["text"],
        padding=(8, 8),
        relief="flat",
    )
    style.map("Treeview", background=[("selected", PALETTE["selection_bg"])], foreground=[("selected", PALETTE["text"])])
    style.configure(
        "Accent.TButton",
        background=PALETTE["accent"],
        foreground="#FFFFFF",
        borderwidth=0,
        padding=(16, 9),
    )
    style.map(
        "Accent.TButton",
        background=[("disabled", "#CBD5E1"), ("active", PALETTE["accent_hover"])],
        foreground=[("disabled", PALETTE["muted"]), ("!disabled", "#FFFFFF")],
    )
    style.configure(
        "SmallAccent.TButton",
        background=PALETTE["accent"],
        foreground="#FFFFFF",
        borderwidth=0,
        padding=(6, 3),
    )
    style.map(
        "SmallAccent.TButton",
        background=[("disabled", "#CBD5E1"), ("active", PALETTE["accent_hover"])],
        foreground=[("disabled", PALETTE["muted"]), ("!disabled", "#FFFFFF")],
    )
    style.configure("Subtle.TButton", background="#FFFFFF", foreground=PALETTE["text"], borderwidth=1, padding=(14, 9))
    style.map(
        "Subtle.TButton",
        background=[("disabled", "#F8FAFC"), ("active", "#F1F5F9")],
        foreground=[("disabled", PALETTE["muted"]), ("!disabled", PALETTE["text"])],
    )
    style.configure("Danger.TButton", background="#FFFFFF", foreground=PALETTE["danger"], borderwidth=1, padding=(14, 9))
    style.map(
        "Danger.TButton",
        background=[("disabled", "#F8FAFC"), ("active", PALETTE["danger_soft"])],
        foreground=[("disabled", PALETTE["muted"]), ("!disabled", PALETTE["danger"])],
    )
    style.configure("TNotebook", background=PALETTE["panel_bg"], borderwidth=0, tabmargins=(0, 0, 0, 0))
    style.configure(
        "TNotebook.Tab",
        background=PALETTE["tab_idle"],
        foreground=PALETTE["neutral_text"],
        padding=(22, 12),
        borderwidth=0,
        relief="flat",
    )
    style.map(
        "TNotebook.Tab",
        background=[("selected", PALETTE["tab_active"]), ("!selected", PALETTE["tab_idle"])],
        foreground=[("selected", PALETTE["text"]), ("!selected", PALETTE["neutral_text"])],
        padding=[("selected", (22, 12)), ("!selected", (22, 12))],
    )

def make_status_badge(
    parent: tk.Misc,
    *,
    text: str | None = None,
    textvariable: tk.StringVar | None = None,
) -> tk.Label:
    options = {
        "bg": PALETTE["neutral_soft"],
        "fg": PALETTE["neutral_text"],
        "font": ("Microsoft YaHei UI", 10, "bold"),
        "padx": 12,
        "pady": 6,
    }
    if textvariable is not None:
        options["textvariable"] = textvariable
    else:
        options["text"] = text or "未检测"
    return tk.Label(parent, **options)

class TopNav(tk.Frame):
    def __init__(self, parent: tk.Misc, tabs: list[tuple[str, str]], command: Callable[[str], None]) -> None:
        super().__init__(parent, bg=PALETTE["panel_bg"])
        self.command = command
        self.active_key = ""
        self.items: dict[str, tk.Label] = {}
        for column, (key, label) in enumerate(tabs):
            item = tk.Label(
                self,
                text=label,
                bg=PALETTE["card_bg"],
                fg=PALETTE["text"],
                font=("Microsoft YaHei UI", 10, "bold"),
                padx=18,
                pady=9,
                bd=0,
                highlightthickness=1,
                highlightbackground=PALETTE["card_border"],
                cursor="hand2",
            )
            item.grid(row=0, column=column, sticky="ew", padx=(0, 8))
            item.bind("<Button-1>", lambda _event, tab_key=key: self.command(tab_key))
            item.bind("<Enter>", lambda _event, tab_key=key: self._set_hover(tab_key, True))
            item.bind("<Leave>", lambda _event, tab_key=key: self._set_hover(tab_key, False))
            self.items[key] = item
        self.columnconfigure(len(tabs), weight=1)

    def select(self, key: str) -> None:
        self.active_key = key
        for tab_key, item in self.items.items():
            if tab_key == key:
                item.configure(bg=PALETTE["accent"], fg="#FFFFFF", highlightbackground=PALETTE["accent"])
            else:
                item.configure(bg=PALETTE["card_bg"], fg=PALETTE["text"], highlightbackground=PALETTE["card_border"])

    def _set_hover(self, key: str, active: bool) -> None:
        if key == self.active_key:
            return
        item = self.items[key]
        if active:
            item.configure(bg=PALETTE["selection_bg"], fg=PALETTE["accent"], highlightbackground=PALETTE["accent"])
        else:
            item.configure(bg=PALETTE["card_bg"], fg=PALETTE["text"], highlightbackground=PALETTE["card_border"])
