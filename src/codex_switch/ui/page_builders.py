from __future__ import annotations

import tkinter as tk
from typing import Any

from codex_switch.codex_config import PROJECT_ROOT_PLACEHOLDER
from codex_switch.models import ACCOUNT_POOL_GROUP_TYPE_LABELS, VENDOR_CLAUDE, VENDOR_CODEX
from codex_switch.storage import MODEL_BATCH_CONCURRENCY_MAX, MODEL_BATCH_CONCURRENCY_MIN
from codex_switch.ui.account_pool_logic import (
    ACCOUNT_POOL_SOURCE_FILTER_ALL,
    ACCOUNT_POOL_SOURCE_FILTER_PROFILE,
    ACCOUNT_POOL_SOURCE_FILTER_TEMPORARY,
)
from codex_switch.ui.styles import HEALTH_OVERRIDE_DISPLAY, PALETTE, make_button, make_status_badge, ttk


from codex_switch.models import VENDOR_CLAUDE, VENDOR_CODEX


from codex_switch.ui.route_proxy_logic import (
    CLAUDE_ROUTE_PROXY_PROTOCOLS,
    CODEX_ROUTE_PROXY_PROTOCOLS,
    CODEX_ROUTE_PROXY_UPSTREAM_SOURCE_VALUES,
    ROUTE_PROXY_ACCOUNT_POOL_STRATEGY_VALUES,
)

def build_library_tab_page(app: Any, parent: tk.Misc, *, library_profile_view_tabs: tuple[tuple[str, str], ...]) -> None:
    parent.columnconfigure(0, weight=1)
    parent.rowconfigure(0, weight=1)

    content = tk.Frame(parent, bg=PALETTE["panel_bg"])
    content.grid(row=0, column=0, sticky="nsew")
    content.columnconfigure(0, weight=5)
    content.columnconfigure(1, weight=6)
    content.rowconfigure(0, weight=1)

    left = app._make_card(content)
    left.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
    left.columnconfigure(0, weight=1)
    left.rowconfigure(2, weight=1)
    tk.Label(left, text="配置库", bg=PALETTE["card_bg"], fg=PALETTE["text"], font=app.hero_font).grid(row=0, column=0, sticky="w")
    tk.Label(left, textvariable=app.library_hint_var, bg=PALETTE["card_bg"], fg=PALETTE["muted"], font=app.small_font).grid(row=0, column=0, sticky="e")

    library_tabs = tk.Frame(left, bg=PALETTE["card_bg"])
    library_tabs.grid(row=1, column=0, sticky="ew", pady=(12, 0))
    for column, (profile_view, label) in enumerate(library_profile_view_tabs):
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
        tab.bind("<Button-1>", lambda _event, view=profile_view: app._set_library_profile_view(view))
        app.library_scope_tabs[profile_view] = tab
    library_tabs.columnconfigure(len(library_profile_view_tabs), weight=1)

    tree_wrap = tk.Frame(left, bg=PALETTE["card_bg"])
    tree_wrap.grid(row=2, column=0, sticky="nsew", pady=(10, 0))
    tree_wrap.columnconfigure(0, weight=1)
    tree_wrap.rowconfigure(0, weight=1)
    app.profile_tree = ttk.Treeview(tree_wrap, columns=("name", "vendor", "base_url", "model", "sign_in", "health"), show="headings")
    app.profile_tree.heading("name", text="配置名", anchor="w")
    app.profile_tree.heading("vendor", text="供应商", anchor="center")
    app.profile_tree.heading("base_url", text="API 地址", anchor="w")
    app.profile_tree.heading("model", text="默认模型", anchor="center")
    app.profile_tree.heading("sign_in", text="API签到状态", anchor="center")
    app.profile_tree.heading("health", text="状态", anchor="center")
    app.profile_tree.column("name", width=150, anchor="w")
    app.profile_tree.column("vendor", width=72, anchor="center", stretch=False)
    app.profile_tree.column("base_url", width=220, anchor="w")
    app.profile_tree.column("model", width=130, anchor="center")
    app.profile_tree.column("sign_in", width=110, anchor="center")
    app.profile_tree.column("health", width=90, anchor="center")
    app.profile_tree.grid(row=0, column=0, sticky="nsew")
    app.profile_tree.bind("<<TreeviewSelect>>", app._on_profile_selection_changed)

    profile_scroll = ttk.Scrollbar(tree_wrap, orient="vertical", command=app.profile_tree.yview)
    profile_scroll.grid(row=0, column=1, sticky="ns")
    app.profile_tree.configure(yscrollcommand=profile_scroll.set)

    actions = tk.Frame(left, bg=PALETTE["card_bg"])
    actions.grid(row=3, column=0, sticky="ew", pady=(14, 0))
    for column in range(4):
        actions.columnconfigure(column, weight=1)
    make_button(actions, text="新增", variant="primary", command=app.add_profile).grid(row=0, column=0, sticky="ew", padx=(0, 8), pady=(0, 8))
    make_button(actions, text="编辑", variant="secondary", command=app.edit_profile).grid(row=0, column=1, sticky="ew", padx=(0, 8), pady=(0, 8))
    make_button(actions, text="删除", variant="danger", command=app.delete_profile).grid(row=0, column=2, sticky="ew", padx=(0, 8), pady=(0, 8))
    make_button(actions, textvariable=app.hide_error_button_var, variant="secondary", command=app._on_profile_filter_changed).grid(row=0, column=3, sticky="ew", pady=(0, 8))
    make_button(actions, text="设为当前", variant="primary", command=app.apply_selected_profile).grid(row=1, column=0, sticky="ew", padx=(0, 8))
    make_button(actions, text="测试选中", variant="secondary", command=app.test_selected_profile).grid(row=1, column=1, sticky="ew", padx=(0, 8))
    make_button(actions, text="测试全部", variant="secondary", command=app.test_all_profiles).grid(row=1, column=2, sticky="ew", padx=(0, 8))
    make_button(actions, text="刷新", variant="secondary", command=app.refresh_all).grid(row=1, column=3, sticky="ew")

    right = app._make_card(content)
    right.grid(row=0, column=1, sticky="nsew")
    right.columnconfigure(0, weight=1)
    right.columnconfigure(1, weight=1)

    header = tk.Frame(right, bg=PALETTE["card_bg"])
    header.grid(row=0, column=0, columnspan=2, sticky="ew")
    header.columnconfigure(0, weight=1)
    tk.Label(header, textvariable=app.library_selected_name_var, bg=PALETTE["card_bg"], fg=PALETTE["text"], font=app.hero_font).grid(row=0, column=0, sticky="w")
    app.library_health_badge = make_status_badge(header, text="未检测")
    app.library_health_badge.grid(row=0, column=1, sticky="e")
    tk.Label(header, text="这里展示选中配置的连接信息、签到状态和最近检测返回模型。", bg=PALETTE["card_bg"], fg=PALETTE["muted"], font=app.small_font).grid(
        row=1,
        column=0,
        sticky="w",
        pady=(4, 0),
    )

    detail = tk.Frame(right, bg=PALETTE["card_bg"])
    detail.grid(row=1, column=0, columnspan=2, sticky="nsew", pady=(14, 0))
    detail.columnconfigure(1, weight=1)
    detail.columnconfigure(3, weight=1)
    app._create_dual_info_row(detail, 0, "供应商", app.library_selected_provider_var, "分类", app.library_selected_category_var)
    app._create_info_row(detail, 1, "模型", app.library_selected_model_var, wraplength=460)
    app.library_api_link_label = app._create_link_info_row(detail, 2, "API 地址", app.library_selected_api_var, app._open_selected_api_url, wraplength=460)
    app._create_dual_info_row(detail, 3, "活动 Key", app.library_selected_key_var, "Wire API", app.library_selected_wire_var)
    app._create_info_row(detail, 4, "签到状态", app.library_selected_sign_in_status_var, wraplength=460)
    app.library_sign_in_link_label = app._create_link_info_row(detail, 5, "签到地址", app.library_selected_sign_in_url_var, app._open_selected_sign_in_url, wraplength=460)
    app._create_info_row(detail, 6, "备注", app.library_selected_notes_var, wraplength=460)

    tk.Label(detail, text="返回模型", bg=PALETTE["card_bg"], fg=PALETTE["muted"], font=app.small_font).grid(row=7, column=0, sticky="nw", padx=(0, 14), pady=(12, 4))
    models_wrap = tk.Frame(detail, bg=PALETTE["card_bg"])
    models_wrap.grid(row=7, column=1, columnspan=3, sticky="nsew", pady=(12, 4))
    models_wrap.columnconfigure(0, weight=1)
    models_wrap.rowconfigure(1, weight=1)

    models_summary = tk.Frame(models_wrap, bg=PALETTE["card_bg"])
    models_summary.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 8))
    models_summary.columnconfigure(0, weight=1)
    tk.Label(
        models_summary,
        textvariable=app.library_models_summary_var,
        bg=PALETTE["card_bg"],
        fg=PALETTE["text"],
        font=app.small_font,
        justify="left",
        wraplength=520,
    ).grid(row=0, column=0, sticky="w")
    make_button(
        models_summary,
        textvariable=app.library_model_stats_button_var,
        variant="secondary",
        command=app._toggle_library_model_stats,
    ).grid(row=0, column=1, sticky="e", padx=(10, 0))

    app.library_models_canvas = tk.Canvas(
        models_wrap,
        height=176,
        bg="#FBFDFE",
        highlightbackground=PALETTE["card_border"],
        highlightthickness=1,
    )
    app.library_models_canvas.grid(row=1, column=0, sticky="nsew")
    library_models_scroll = ttk.Scrollbar(models_wrap, orient="vertical", command=app.library_models_canvas.yview)
    library_models_scroll.grid(row=1, column=1, sticky="ns")
    app.library_models_canvas.configure(yscrollcommand=library_models_scroll.set)
    app.library_model_tags_frame = tk.Frame(app.library_models_canvas, bg="#FBFDFE")
    app.library_model_tags_window = app.library_models_canvas.create_window((0, 0), window=app.library_model_tags_frame, anchor="nw")
    app.library_model_tags_frame.bind(
        "<Configure>",
        lambda _event: app.library_models_canvas.configure(scrollregion=app.library_models_canvas.bbox("all")),
    )
    app.library_models_canvas.bind("<Configure>", app._on_library_models_canvas_configure)

    app.library_model_stats_text = tk.Text(
        models_wrap,
        height=7,
        wrap="word",
        relief="solid",
        borderwidth=1,
        highlightthickness=0,
        font=app.small_font,
        bg="#FBFDFE",
        fg=PALETTE["text"],
        state="disabled",
    )
    app.library_model_stats_text.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(8, 0))
    app.library_model_stats_text.grid_remove()


def build_global_tab_page(app: Any, parent: tk.Misc) -> None:
    parent.columnconfigure(0, weight=1)
    parent.rowconfigure(1, weight=1)

    metrics = tk.Frame(parent, bg=PALETTE["panel_bg"])
    metrics.grid(row=0, column=0, sticky="ew", pady=(0, 8))
    for column in range(4):
        metrics.columnconfigure(column, weight=1)

    app._make_metric_card(metrics, "配置总数", app.global_total_var, PALETTE["accent"], PALETTE["selection_bg"]).grid(row=0, column=0, sticky="ew", padx=(0, 8))
    app._make_metric_card(metrics, "健康配置", app.global_healthy_var, PALETTE["success"], PALETTE["success_soft"], value_foreground="#16A34A").grid(row=0, column=1, sticky="ew", padx=(0, 8))
    app._make_metric_card(metrics, "受限配置", app.global_degraded_var, PALETTE["warning"], PALETTE["warning_soft"], value_foreground="#CA8A04").grid(row=0, column=2, sticky="ew", padx=(0, 8))
    app._make_metric_card(metrics, "异常配置", app.global_error_var, PALETTE["danger"], PALETTE["danger_soft"], value_foreground="#DC2626").grid(row=0, column=3, sticky="ew")

    content = tk.Frame(parent, bg=PALETTE["panel_bg"])
    content.grid(row=1, column=0, sticky="nsew")
    content.columnconfigure(0, weight=6)
    content.columnconfigure(1, weight=5)
    content.rowconfigure(0, weight=1)

    current = app._make_card(content)
    current.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
    current.columnconfigure(0, weight=1)
    current.columnconfigure(1, weight=1)

    left = tk.Frame(current, bg=PALETTE["card_bg"])
    left.grid(row=0, column=0, sticky="nsew", padx=(0, 18))
    left.columnconfigure(0, weight=1)
    tk.Label(left, text="Codex 当前生效配置", bg=PALETTE["card_bg"], fg=PALETTE["text"], font=app.section_font).grid(row=0, column=0, sticky="w")
    tk.Label(left, textvariable=app.codex_current_models_var, bg=PALETTE["card_bg"], fg=PALETTE["text"], font=app.body_font, justify="left", wraplength=420).grid(row=1, column=0, sticky="w", pady=(8, 4))
    tk.Label(left, textvariable=app.codex_current_api_var, bg=PALETTE["card_bg"], fg=PALETTE["muted"], font=app.body_font, justify="left", wraplength=420).grid(row=2, column=0, sticky="w")

    tk.Label(left, text="Claude 当前生成配置", bg=PALETTE["card_bg"], fg=PALETTE["text"], font=app.section_font).grid(row=3, column=0, sticky="w", pady=(22, 0))
    tk.Label(left, textvariable=app.claude_current_models_var, bg=PALETTE["card_bg"], fg=PALETTE["text"], font=app.body_font, justify="left", wraplength=420).grid(row=4, column=0, sticky="w", pady=(8, 4))
    tk.Label(left, textvariable=app.claude_current_api_var, bg=PALETTE["card_bg"], fg=PALETTE["muted"], font=app.body_font, justify="left", wraplength=420).grid(row=5, column=0, sticky="w")

    right = tk.Frame(current, bg=PALETTE["card_bg"])
    right.grid(row=0, column=1, sticky="nsew")
    right.columnconfigure(0, weight=1)
    tk.Label(right, text="配置文件位置", bg=PALETTE["card_bg"], fg=PALETTE["text"], font=app.section_font).grid(row=0, column=0, sticky="w")
    tk.Label(right, textvariable=app.current_path_var, bg=PALETTE["card_bg"], fg=PALETTE["muted"], font=app.small_font, justify="left", wraplength=360).grid(row=1, column=0, sticky="w", pady=(10, 12))

    tk.Label(right, text="全局 API 设置", bg=PALETTE["card_bg"], fg=PALETTE["text"], font=app.section_font).grid(row=2, column=0, sticky="w", pady=(18, 8))
    codex_profile_row = tk.Frame(right, bg=PALETTE["card_bg"])
    codex_profile_row.grid(row=3, column=0, sticky="ew")
    codex_profile_row.columnconfigure(0, weight=1)
    tk.Label(codex_profile_row, text="Codex", bg=PALETTE["card_bg"], fg=PALETTE["text"], font=app.small_font).grid(row=0, column=0, sticky="w")
    app.global_codex_profile_combo = ttk.Combobox(
        codex_profile_row,
        textvariable=app.global_codex_profile_choice_var,
        state="readonly",
        width=40,
    )
    app.global_codex_profile_combo.grid(row=1, column=0, sticky="ew", pady=(4, 0))
    app.global_codex_profile_combo.bind("<<ComboboxSelected>>", lambda event: app._on_global_profile_choice_changed(VENDOR_CODEX, event))
    claude_profile_row = tk.Frame(right, bg=PALETTE["card_bg"])
    claude_profile_row.grid(row=4, column=0, sticky="ew", pady=(10, 0))
    claude_profile_row.columnconfigure(0, weight=1)
    tk.Label(claude_profile_row, text="Claude", bg=PALETTE["card_bg"], fg=PALETTE["text"], font=app.small_font).grid(row=0, column=0, sticky="w")
    app.global_claude_profile_combo = ttk.Combobox(
        claude_profile_row,
        textvariable=app.global_claude_profile_choice_var,
        state="readonly",
        width=40,
    )
    app.global_claude_profile_combo.grid(row=1, column=0, sticky="ew", pady=(4, 0))
    app.global_claude_profile_combo.bind("<<ComboboxSelected>>", lambda event: app._on_global_profile_choice_changed(VENDOR_CLAUDE, event))
    global_api_actions = tk.Frame(right, bg=PALETTE["card_bg"])
    global_api_actions.grid(row=5, column=0, sticky="ew", pady=(14, 0))
    for column in range(3):
        global_api_actions.columnconfigure(column, weight=1)
    make_button(global_api_actions, text="写入全局配置", variant="primary", command=app.apply_global_profile).grid(row=0, column=0, sticky="ew", padx=(0, 8))
    make_button(global_api_actions, text="打开 Codex 配置", variant="secondary", command=app.open_global_codex_config).grid(row=0, column=1, sticky="ew", padx=(0, 8))
    make_button(global_api_actions, text="打开 Claude 配置", variant="secondary", command=app.open_global_claude_config).grid(row=0, column=2, sticky="ew")

    mcp_card = app._make_card(content)
    mcp_card.grid(row=0, column=1, sticky="nsew")
    mcp_card.columnconfigure(0, weight=1)
    tk.Label(mcp_card, text="全局 MCP 配置", bg=PALETTE["card_bg"], fg=PALETTE["text"], font=app.hero_font).grid(row=0, column=0, sticky="w")
    tk.Label(
        mcp_card,
        text="用于全局切换时自动注入托管的 MCP 服务器。清空后会显式退出默认注入。",
        bg=PALETTE["card_bg"],
        fg=PALETTE["muted"],
        font=app.small_font,
        justify="left",
        wraplength=360,
    ).grid(row=1, column=0, sticky="w", pady=(6, 12))
    tk.Label(mcp_card, textvariable=app.global_mcp_var, bg=PALETTE["card_bg"], fg=PALETTE["text"], font=app.body_font, justify="left", wraplength=360).grid(row=2, column=0, sticky="w")

    actions = tk.Frame(mcp_card, bg=PALETTE["card_bg"])
    actions.grid(row=3, column=0, sticky="ew", pady=(18, 0))
    for column in range(3):
        actions.columnconfigure(column, weight=1)
    make_button(actions, text="选择 MCP", variant="primary", command=app.select_global_mcp).grid(row=0, column=0, sticky="ew", padx=(0, 8))
    make_button(actions, text="禁用 MCP", variant="danger", command=app.clear_global_mcp).grid(row=0, column=1, sticky="ew", padx=(0, 8))
    make_button(actions, text="刷新", variant="secondary", command=app.refresh_all).grid(row=0, column=2, sticky="ew")


def build_mcp_tab_page(app: Any, parent: tk.Misc) -> None:
    parent.columnconfigure(0, weight=1)
    parent.rowconfigure(0, weight=1)

    content = tk.Frame(parent, bg=PALETTE["panel_bg"])
    content.grid(row=0, column=0, sticky="nsew")
    content.columnconfigure(0, weight=7)
    content.columnconfigure(1, weight=5)
    content.rowconfigure(0, weight=1)

    list_card = app._make_card(content)
    list_card.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
    list_card.columnconfigure(0, weight=1)
    list_card.rowconfigure(1, weight=1)

    tk.Label(list_card, text="MCP配置", bg=PALETTE["card_bg"], fg=PALETTE["text"], font=app.hero_font).grid(row=0, column=0, sticky="w")
    tk.Label(list_card, textvariable=app.mcp_hint_var, bg=PALETTE["card_bg"], fg=PALETTE["muted"], font=app.small_font).grid(row=0, column=0, sticky="e")

    tree_wrap = tk.Frame(list_card, bg=PALETTE["card_bg"])
    tree_wrap.grid(row=1, column=0, sticky="nsew", pady=(12, 0))
    tree_wrap.columnconfigure(0, weight=1)
    tree_wrap.rowconfigure(0, weight=1)

    app.mcp_tree = ttk.Treeview(
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
        app.mcp_tree.heading(column, text=title, anchor=anchor)
        app.mcp_tree.column(column, width=width, anchor=anchor)
    app.mcp_tree.grid(row=0, column=0, sticky="nsew")
    app.mcp_tree.bind("<<TreeviewSelect>>", app._on_mcp_server_selection_changed)

    y_scroll = ttk.Scrollbar(tree_wrap, orient="vertical", command=app.mcp_tree.yview)
    y_scroll.grid(row=0, column=1, sticky="ns")
    x_scroll = ttk.Scrollbar(tree_wrap, orient="horizontal", command=app.mcp_tree.xview)
    x_scroll.grid(row=1, column=0, sticky="ew")
    app.mcp_tree.configure(yscrollcommand=y_scroll.set, xscrollcommand=x_scroll.set)

    actions = tk.Frame(list_card, bg=PALETTE["card_bg"])
    actions.grid(row=2, column=0, sticky="ew", pady=(14, 0))
    for column in range(3):
        actions.columnconfigure(column, weight=1)
    make_button(actions, text="新增 MCP", variant="primary", command=app.add_mcp_server).grid(row=0, column=0, sticky="ew", padx=(0, 8), pady=(0, 8))
    make_button(actions, text="修改 MCP", variant="secondary", command=app.edit_mcp_server).grid(row=0, column=1, sticky="ew", padx=(0, 8), pady=(0, 8))
    make_button(actions, text="删除 MCP", variant="danger", command=app.delete_mcp_server).grid(row=0, column=2, sticky="ew", pady=(0, 8))
    make_button(actions, text="保存 MCP", variant="primary", command=app.save_mcp_servers).grid(row=1, column=0, sticky="ew", padx=(0, 8))
    make_button(actions, text="恢复默认", variant="secondary", command=app.restore_default_mcp_servers).grid(row=1, column=1, sticky="ew", padx=(0, 8))
    make_button(actions, text="清空禁用", variant="danger", command=app.disable_global_mcp_from_page).grid(row=1, column=2, sticky="ew")

    detail = app._make_card(content)
    detail.grid(row=0, column=1, sticky="nsew")
    detail.columnconfigure(0, weight=1)
    detail.rowconfigure(3, weight=1)
    tk.Label(detail, textvariable=app.mcp_selected_name_var, bg=PALETTE["card_bg"], fg=PALETTE["text"], font=app.hero_font).grid(row=0, column=0, sticky="w")
    tk.Label(
        detail,
        text=f"在 command、args、cwd、env 或高级字段里写 {PROJECT_ROOT_PLACEHOLDER}，生成项目配置时会替换为项目目录。",
        bg=PALETTE["card_bg"],
        fg=PALETTE["muted"],
        font=app.small_font,
        justify="left",
        wraplength=420,
    ).grid(row=1, column=0, sticky="w", pady=(6, 10))
    tk.Label(detail, textvariable=app.mcp_selected_summary_var, bg=PALETTE["card_bg"], fg=PALETTE["text"], font=app.body_font, justify="left", wraplength=420).grid(row=2, column=0, sticky="w")

    preview_wrap = tk.Frame(detail, bg=PALETTE["card_bg"])
    preview_wrap.grid(row=3, column=0, sticky="nsew", pady=(12, 0))
    preview_wrap.columnconfigure(0, weight=1)
    preview_wrap.rowconfigure(0, weight=1)
    app.mcp_preview_text = tk.Text(
        preview_wrap,
        wrap="none",
        relief="solid",
        borderwidth=1,
        highlightthickness=0,
        font=("Consolas", 10),
        bg="#FBFDFE",
        fg=PALETTE["text"],
    )
    app.mcp_preview_text.grid(row=0, column=0, sticky="nsew")
    preview_y = ttk.Scrollbar(preview_wrap, orient="vertical", command=app.mcp_preview_text.yview)
    preview_y.grid(row=0, column=1, sticky="ns")
    preview_x = ttk.Scrollbar(preview_wrap, orient="horizontal", command=app.mcp_preview_text.xview)
    preview_x.grid(row=1, column=0, sticky="ew")
    app.mcp_preview_text.configure(yscrollcommand=preview_y.set, xscrollcommand=preview_x.set, state="disabled")


def build_docs_tab_page(app: Any, parent: tk.Misc) -> None:
    parent.columnconfigure(0, weight=1)
    parent.rowconfigure(0, weight=1)

    card = app._make_card(parent)
    card.grid(row=0, column=0, sticky="nsew")
    card.columnconfigure(0, weight=1)
    card.rowconfigure(2, weight=1)

    header = tk.Frame(card, bg=PALETTE["card_bg"])
    header.grid(row=0, column=0, sticky="ew")
    header.columnconfigure(0, weight=1)
    tk.Label(header, text="文档配置", bg=PALETTE["card_bg"], fg=PALETTE["text"], font=app.hero_font).grid(row=0, column=0, sticky="w")
    tk.Label(header, textvariable=app.docs_hint_var, bg=PALETTE["card_bg"], fg=PALETTE["muted"], font=app.small_font).grid(row=1, column=0, sticky="w", pady=(4, 0))

    actions = tk.Frame(card, bg=PALETTE["card_bg"])
    actions.grid(row=1, column=0, sticky="e", pady=(0, 10))
    make_button(actions, text="保存文档", variant="primary", command=app.save_agents_doc).grid(row=0, column=0, padx=(0, 8))
    make_button(actions, text="恢复默认", variant="secondary", command=app.restore_default_agents_doc).grid(row=0, column=1)

    editor_wrap = tk.Frame(card, bg=PALETTE["card_bg"])
    editor_wrap.grid(row=2, column=0, sticky="nsew")
    editor_wrap.columnconfigure(0, weight=1)
    editor_wrap.rowconfigure(0, weight=1)
    app.agents_doc_editor = tk.Text(
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
    app.agents_doc_editor.grid(row=0, column=0, sticky="nsew")
    app.agents_doc_editor.insert("1.0", app.agents_doc_text)
    doc_scroll = ttk.Scrollbar(editor_wrap, orient="vertical", command=app.agents_doc_editor.yview)
    doc_scroll.grid(row=0, column=1, sticky="ns")
    app.agents_doc_editor.configure(yscrollcommand=doc_scroll.set)


def build_account_pool_tab_page(app: Any, parent: tk.Misc) -> None:
    parent.columnconfigure(0, weight=1)
    parent.rowconfigure(0, weight=1)

    content = tk.Frame(parent, bg=PALETTE["panel_bg"])
    content.grid(row=0, column=0, sticky="nsew")
    content.columnconfigure(0, weight=7)
    content.columnconfigure(1, weight=4)
    content.rowconfigure(0, weight=1)

    left = app._make_card(content)
    left.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
    left.columnconfigure(0, weight=1)
    left.rowconfigure(3, weight=1)
    header = tk.Frame(left, bg=PALETTE["card_bg"])
    header.grid(row=0, column=0, sticky="ew")
    header.columnconfigure(0, weight=1)
    tk.Label(header, text="号池", bg=PALETTE["card_bg"], fg=PALETTE["text"], font=app.hero_font).grid(row=0, column=0, sticky="w")
    ttk.Checkbutton(
        header,
        text="启用号池",
        variable=app.account_pool_enabled_var,
        command=app.save_account_pool_settings,
    ).grid(row=0, column=1, sticky="e")
    tk.Label(left, textvariable=app.account_pool_summary_var, bg=PALETTE["card_bg"], fg=PALETTE["muted"], font=app.small_font).grid(row=1, column=0, sticky="w", pady=(4, 12))

    group_bar = tk.Frame(left, bg=PALETTE["card_bg"])
    group_bar.grid(row=2, column=0, sticky="ew", pady=(0, 10))
    group_bar.columnconfigure(1, weight=1)
    group_bar.columnconfigure(3, weight=1)
    tk.Label(group_bar, text="号池组", bg=PALETTE["card_bg"], fg=PALETTE["muted"], font=app.small_font).grid(row=0, column=0, sticky="w", padx=(0, 8))
    app.account_pool_group_combo = ttk.Combobox(
        group_bar,
        textvariable=app.account_pool_group_var,
        state="readonly",
        width=24,
    )
    app.account_pool_group_combo.grid(row=0, column=1, sticky="ew", padx=(0, 8))
    app.account_pool_group_combo.bind("<<ComboboxSelected>>", app._on_account_pool_group_changed)
    ttk.Checkbutton(
        group_bar,
        text="启用组",
        variable=app.account_pool_group_enabled_var,
        command=app.save_account_pool_group_settings,
    ).grid(row=0, column=2, sticky="w", padx=(0, 8))
    make_button(group_bar, text="新建组", variant="secondary", command=app.add_account_pool_group).grid(row=0, column=3, padx=(0, 8))
    make_button(group_bar, text="删除组", variant="danger", command=app.delete_account_pool_group).grid(row=0, column=4, padx=(0, 8))
    app.account_pool_source_filter_combo = ttk.Combobox(
        group_bar,
        textvariable=app.account_pool_source_filter_var,
        values=(
            ACCOUNT_POOL_SOURCE_FILTER_ALL,
            ACCOUNT_POOL_SOURCE_FILTER_TEMPORARY,
            ACCOUNT_POOL_SOURCE_FILTER_PROFILE,
        ),
        state="readonly",
        width=12,
    )
    app.account_pool_source_filter_combo.grid(row=0, column=5, sticky="e")
    app.account_pool_source_filter_var.trace_add("write", lambda *_args: app.refresh_account_pool_tab())

    tk.Label(group_bar, text="类型", bg=PALETTE["card_bg"], fg=PALETTE["muted"], font=app.small_font).grid(row=1, column=0, sticky="w", padx=(0, 8), pady=(8, 0))
    ttk.Combobox(
        group_bar,
        textvariable=app.account_pool_group_type_var,
        values=tuple(ACCOUNT_POOL_GROUP_TYPE_LABELS.values()),
        state="readonly",
        width=14,
    ).grid(row=1, column=1, sticky="w", padx=(0, 8), pady=(8, 0))
    tk.Label(group_bar, text="Codex 默认模型", bg=PALETTE["card_bg"], fg=PALETTE["muted"], font=app.small_font).grid(row=1, column=2, sticky="w", padx=(0, 8), pady=(8, 0))
    ttk.Entry(group_bar, textvariable=app.account_pool_group_default_model_var, width=24).grid(row=1, column=3, columnspan=3, sticky="ew", pady=(8, 0))
    tk.Label(group_bar, text="Claude 默认模型", bg=PALETTE["card_bg"], fg=PALETTE["muted"], font=app.small_font).grid(row=2, column=0, sticky="w", padx=(0, 8), pady=(8, 0))
    ttk.Entry(group_bar, textvariable=app.account_pool_group_claude_model_var, width=24).grid(row=2, column=1, sticky="ew", padx=(0, 8), pady=(8, 0))
    tk.Label(group_bar, text="Claude 兜底模型", bg=PALETTE["card_bg"], fg=PALETTE["muted"], font=app.small_font).grid(row=2, column=2, sticky="w", padx=(0, 8), pady=(8, 0))
    ttk.Entry(group_bar, textvariable=app.account_pool_group_claude_fallback_model_var, width=24).grid(row=2, column=3, columnspan=3, sticky="ew", pady=(8, 0))
    make_button(group_bar, text="保存组设置", variant="primary", command=app.save_account_pool_group_settings).grid(row=3, column=3, columnspan=3, sticky="e", pady=(8, 0))

    tree_wrap = tk.Frame(left, bg=PALETTE["card_bg"])
    tree_wrap.grid(row=3, column=0, sticky="nsew")
    tree_wrap.columnconfigure(0, weight=1)
    tree_wrap.rowconfigure(0, weight=1)
    app.account_pool_tree = ttk.Treeview(
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
        app.account_pool_tree.heading(column, text=title)
        app.account_pool_tree.column(column, width=width, anchor="center")
    app.account_pool_tree.grid(row=0, column=0, sticky="nsew")
    app.account_pool_tree.bind("<<TreeviewSelect>>", app._on_account_pool_selection_changed)
    pool_scroll = ttk.Scrollbar(tree_wrap, orient="vertical", command=app.account_pool_tree.yview)
    pool_scroll.grid(row=0, column=1, sticky="ns")
    app.account_pool_tree.configure(yscrollcommand=pool_scroll.set)

    actions = tk.Frame(left, bg=PALETTE["card_bg"])
    actions.grid(row=4, column=0, sticky="ew", pady=(14, 0))
    for column in range(6):
        actions.columnconfigure(column, weight=1)
    make_button(actions, text="添加临时", variant="primary", command=app.add_account_pool_channel).grid(row=0, column=0, sticky="ew", padx=(0, 8))
    make_button(actions, text="加入配置库", variant="secondary", command=app.add_account_pool_profile_channel).grid(row=0, column=1, sticky="ew", padx=(0, 8))
    make_button(actions, text="编辑渠道", variant="secondary", command=app.edit_account_pool_channel).grid(row=0, column=2, sticky="ew", padx=(0, 8))
    make_button(actions, text="删除渠道", variant="danger", command=app.delete_account_pool_channel).grid(row=0, column=3, sticky="ew", padx=(0, 8))
    make_button(actions, text="重测异常", variant="secondary", command=app.retest_account_pool_channel).grid(row=0, column=4, sticky="ew", padx=(0, 8))
    make_button(actions, text="刷新", variant="secondary", command=app.refresh_account_pool_tab).grid(row=0, column=5, sticky="ew")

    right = app._make_card(content)
    right.grid(row=0, column=1, sticky="nsew")
    right.columnconfigure(1, weight=1)
    tk.Label(right, textvariable=app.account_pool_selected_name_var, bg=PALETTE["card_bg"], fg=PALETTE["text"], font=app.hero_font).grid(row=0, column=0, columnspan=2, sticky="w")
    app._create_info_row(right, 1, "渠道详情", app.account_pool_selected_detail_var, wraplength=360)


def build_proxy_tab_page(app: Any, parent: tk.Misc) -> None:
    parent.columnconfigure(0, weight=1)
    parent.rowconfigure(0, weight=1)

    content = tk.Frame(parent, bg=PALETTE["panel_bg"])
    content.grid(row=0, column=0, sticky="nsew")
    content.columnconfigure(0, weight=5)
    content.columnconfigure(1, weight=6)
    content.rowconfigure(0, weight=1)

    left = app._make_card(content)
    left.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
    left.columnconfigure(0, weight=1)
    left.rowconfigure(9, weight=1)
    tk.Label(left, text="路由代理", bg=PALETTE["card_bg"], fg=PALETTE["text"], font=app.hero_font).grid(row=0, column=0, sticky="w")
    tk.Label(left, textvariable=app.proxy_hint_var, bg=PALETTE["card_bg"], fg=PALETTE["muted"], font=app.small_font).grid(row=1, column=0, sticky="w", pady=(4, 12))

    settings = tk.Frame(left, bg=PALETTE["card_bg"])
    settings.grid(row=2, column=0, sticky="ew")
    settings.columnconfigure(1, weight=1)
    tk.Label(settings, text="监听地址", bg=PALETTE["card_bg"], fg=PALETTE["muted"], font=app.small_font).grid(row=0, column=0, sticky="w", padx=(0, 10), pady=4)
    ttk.Entry(settings, textvariable=app.proxy_host_var, width=18).grid(row=0, column=1, sticky="w", pady=4)
    tk.Label(settings, text="端口", bg=PALETTE["card_bg"], fg=PALETTE["muted"], font=app.small_font).grid(row=0, column=2, sticky="w", padx=(16, 10), pady=4)
    ttk.Entry(settings, textvariable=app.proxy_port_var, width=8).grid(row=0, column=3, sticky="w", pady=4)
    tk.Label(settings, text="号池策略", bg=PALETTE["card_bg"], fg=PALETTE["muted"], font=app.small_font).grid(row=1, column=0, sticky="w", padx=(0, 10), pady=4)
    ttk.Combobox(
        settings,
        textvariable=app.proxy_account_pool_strategy_var,
        values=tuple(ROUTE_PROXY_ACCOUNT_POOL_STRATEGY_VALUES.keys()),
        state="readonly",
        width=12,
    ).grid(row=1, column=1, sticky="w", pady=4)
    tk.Label(settings, text="节点超时(秒)", bg=PALETTE["card_bg"], fg=PALETTE["muted"], font=app.small_font).grid(row=1, column=2, sticky="w", padx=(16, 10), pady=4)
    ttk.Entry(settings, textvariable=app.proxy_upstream_timeout_var, width=8).grid(row=1, column=3, sticky="w", pady=4)
    tk.Label(settings, text="Codex 来源", bg=PALETTE["card_bg"], fg=PALETTE["muted"], font=app.small_font).grid(row=2, column=0, sticky="w", padx=(0, 10), pady=4)
    ttk.Combobox(
        settings,
        textvariable=app.proxy_codex_upstream_source_var,
        values=tuple(CODEX_ROUTE_PROXY_UPSTREAM_SOURCE_VALUES.keys()),
        state="readonly",
        width=28,
    ).grid(row=2, column=1, columnspan=3, sticky="w", pady=4)
    tk.Label(settings, text="Codex 号池组", bg=PALETTE["card_bg"], fg=PALETTE["muted"], font=app.small_font).grid(row=3, column=0, sticky="w", padx=(0, 10), pady=4)
    app.proxy_account_pool_group_combo = ttk.Combobox(
        settings,
        textvariable=app.proxy_account_pool_group_var,
        state="readonly",
        width=28,
    )
    app.proxy_account_pool_group_combo.grid(row=3, column=1, columnspan=3, sticky="w", pady=4)
    tk.Label(settings, text="Codex 协议", bg=PALETTE["card_bg"], fg=PALETTE["muted"], font=app.small_font).grid(row=4, column=0, sticky="w", padx=(0, 10), pady=4)
    ttk.Combobox(
        settings,
        textvariable=app.proxy_codex_protocol_var,
        values=CODEX_ROUTE_PROXY_PROTOCOLS,
        state="readonly",
        width=28,
    ).grid(row=4, column=1, columnspan=3, sticky="w", pady=4)
    tk.Label(settings, text="Compact 模型", bg=PALETTE["card_bg"], fg=PALETTE["muted"], font=app.small_font).grid(row=5, column=0, sticky="w", padx=(0, 10), pady=4)
    ttk.Entry(settings, textvariable=app.proxy_codex_compact_model_var, width=28).grid(row=5, column=1, columnspan=3, sticky="w", pady=4)
    tk.Label(settings, text="Claude 来源", bg=PALETTE["card_bg"], fg=PALETTE["muted"], font=app.small_font).grid(row=6, column=0, sticky="w", padx=(0, 10), pady=4)
    ttk.Combobox(
        settings,
        textvariable=app.proxy_claude_upstream_source_var,
        values=tuple(CODEX_ROUTE_PROXY_UPSTREAM_SOURCE_VALUES.keys()),
        state="readonly",
        width=28,
    ).grid(row=6, column=1, columnspan=3, sticky="w", pady=4)
    tk.Label(settings, text="Claude 号池组", bg=PALETTE["card_bg"], fg=PALETTE["muted"], font=app.small_font).grid(row=7, column=0, sticky="w", padx=(0, 10), pady=4)
    app.proxy_claude_account_pool_group_combo = ttk.Combobox(
        settings,
        textvariable=app.proxy_claude_account_pool_group_var,
        state="readonly",
        width=28,
    )
    app.proxy_claude_account_pool_group_combo.grid(row=7, column=1, columnspan=3, sticky="w", pady=4)
    tk.Label(settings, text="Claude 协议", bg=PALETTE["card_bg"], fg=PALETTE["muted"], font=app.small_font).grid(row=8, column=0, sticky="w", padx=(0, 10), pady=4)
    ttk.Combobox(
        settings,
        textvariable=app.proxy_claude_protocol_var,
        values=CLAUDE_ROUTE_PROXY_PROTOCOLS,
        state="readonly",
        width=28,
    ).grid(row=8, column=1, columnspan=3, sticky="w", pady=4)

    proxy_tree_wrap = tk.Frame(left, bg=PALETTE["card_bg"])
    proxy_tree_wrap.grid(row=9, column=0, sticky="nsew", pady=(12, 0))
    proxy_tree_wrap.columnconfigure(0, weight=1)
    proxy_tree_wrap.rowconfigure(0, weight=1)
    app.proxy_project_tree = ttk.Treeview(proxy_tree_wrap, columns=("name", "codex", "claude", "pool", "enabled"), show="headings")
    for column, title, width in (
        ("name", "项目", 160),
        ("codex", "Codex", 120),
        ("claude", "Claude", 120),
        ("pool", "号池", 80),
        ("enabled", "代理", 80),
    ):
        app.proxy_project_tree.heading(column, text=title)
        app.proxy_project_tree.column(column, width=width, anchor="center")
    app.proxy_project_tree.grid(row=0, column=0, sticky="nsew")
    app.proxy_project_tree.bind("<<TreeviewSelect>>", app._on_proxy_project_selection_changed)
    proxy_scroll = ttk.Scrollbar(proxy_tree_wrap, orient="vertical", command=app.proxy_project_tree.yview)
    proxy_scroll.grid(row=0, column=1, sticky="ns")
    app.proxy_project_tree.configure(yscrollcommand=proxy_scroll.set)

    actions = tk.Frame(left, bg=PALETTE["card_bg"])
    actions.grid(row=10, column=0, sticky="ew", pady=(14, 0))
    for column in range(4):
        actions.columnconfigure(column, weight=1)
    make_button(actions, text="保存设置", variant="secondary", command=app.save_route_proxy_settings).grid(row=0, column=0, sticky="ew", padx=(0, 8))
    make_button(actions, text="启动代理", variant="primary", command=app.start_route_proxy).grid(row=0, column=1, sticky="ew", padx=(0, 8))
    make_button(actions, text="停止代理", variant="danger", command=app.stop_route_proxy).grid(row=0, column=2, sticky="ew", padx=(0, 8))
    make_button(actions, text="刷新", variant="secondary", command=app.refresh_proxy_tab).grid(row=0, column=3, sticky="ew")
    make_button(actions, text="启用项目代理", variant="primary", command=app.enable_route_proxy_for_project).grid(row=1, column=0, columnspan=2, sticky="ew", padx=(0, 8), pady=(8, 0))
    make_button(actions, text="关闭项目代理", variant="secondary", command=app.disable_route_proxy_for_project).grid(row=1, column=2, columnspan=2, sticky="ew", pady=(8, 0))

    right = app._make_card(content)
    right.grid(row=0, column=1, sticky="nsew")
    right.columnconfigure(0, weight=1)
    right.rowconfigure(5, weight=1)
    tk.Label(right, textvariable=app.proxy_status_var, bg=PALETTE["card_bg"], fg=PALETTE["text"], font=app.hero_font).grid(row=0, column=0, sticky="w")
    app._create_info_row(right, 1, "选中项目", app.proxy_selected_project_var, wraplength=460)
    app._create_info_row(right, 2, "当前规则", app.proxy_selected_rules_var, wraplength=460)
    tk.Label(right, text="最近代理日志", bg=PALETTE["card_bg"], fg=PALETTE["text"], font=app.section_font).grid(row=3, column=0, sticky="w", pady=(16, 6))
    log_wrap = tk.Frame(right, bg=PALETTE["card_bg"])
    log_wrap.grid(row=5, column=0, sticky="nsew")
    log_wrap.columnconfigure(0, weight=1)
    log_wrap.rowconfigure(0, weight=1)
    app.proxy_log_text = tk.Text(
        log_wrap,
        height=18,
        wrap="word",
        relief="solid",
        borderwidth=1,
        highlightthickness=0,
        font=app.small_font,
        bg="#FBFDFE",
        fg=PALETTE["text"],
        state="disabled",
    )
    app.proxy_log_text.grid(row=0, column=0, sticky="nsew")
    proxy_log_scroll = ttk.Scrollbar(log_wrap, orient="vertical", command=app.proxy_log_text.yview)
    proxy_log_scroll.grid(row=0, column=1, sticky="ns")
    app.proxy_log_text.configure(yscrollcommand=proxy_log_scroll.set)


def build_stats_tab_page(app: Any, parent: tk.Misc) -> None:
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
    app._make_metric_card(metrics, "总 Token", app.stats_total_tokens_var, PALETTE["accent"], PALETTE["selection_bg"]).grid(row=0, column=0, sticky="ew", padx=(0, 8))
    app._make_metric_card(metrics, "今日 Token", app.stats_today_tokens_var, PALETTE["success"], PALETTE["success_soft"], value_foreground="#16A34A").grid(row=0, column=1, sticky="ew", padx=(0, 8))
    app._make_metric_card(metrics, "项目数", app.stats_project_count_var, PALETTE["warning"], PALETTE["warning_soft"], value_foreground="#CA8A04").grid(row=0, column=2, sticky="ew", padx=(0, 8))
    app._make_metric_card(metrics, "API 数", app.stats_api_count_var, PALETTE["danger"], PALETTE["danger_soft"], value_foreground="#DC2626").grid(row=0, column=3, sticky="ew")

    left = app._make_card(content)
    left.grid(row=1, column=0, sticky="nsew", padx=(0, 10))
    left.columnconfigure(0, weight=1)
    left.rowconfigure(1, weight=1)
    header = tk.Frame(left, bg=PALETTE["card_bg"])
    header.grid(row=0, column=0, sticky="ew")
    header.columnconfigure(0, weight=1)
    tk.Label(header, text="日消耗", bg=PALETTE["card_bg"], fg=PALETTE["text"], font=app.hero_font).grid(row=0, column=0, sticky="w")
    make_button(header, text="刷新", variant="secondary", command=app.refresh_stats_tab).grid(row=0, column=1, sticky="e")
    day_tree_wrap, app.stats_day_tree = app._build_usage_tree(left)
    day_tree_wrap.grid(row=1, column=0, sticky="nsew", pady=(12, 0))

    right = tk.Frame(content, bg=PALETTE["panel_bg"])
    right.grid(row=1, column=1, sticky="nsew")
    right.columnconfigure(0, weight=1)
    right.rowconfigure(0, weight=1)
    right.rowconfigure(1, weight=1)

    project_card = app._make_card(right)
    project_card.grid(row=0, column=0, sticky="nsew", pady=(0, 10))
    project_card.columnconfigure(0, weight=1)
    project_card.rowconfigure(1, weight=1)
    tk.Label(project_card, text="项目消耗", bg=PALETTE["card_bg"], fg=PALETTE["text"], font=app.hero_font).grid(row=0, column=0, sticky="w")
    project_tree_wrap, app.stats_project_tree = app._build_usage_tree(project_card)
    project_tree_wrap.grid(row=1, column=0, sticky="nsew", pady=(12, 0))

    api_card = app._make_card(right)
    api_card.grid(row=1, column=0, sticky="nsew")
    api_card.columnconfigure(0, weight=1)
    api_card.rowconfigure(1, weight=1)
    tk.Label(api_card, text="API 消耗", bg=PALETTE["card_bg"], fg=PALETTE["text"], font=app.hero_font).grid(row=0, column=0, sticky="w")
    api_tree_wrap, app.stats_api_tree = app._build_usage_tree(api_card)
    api_tree_wrap.grid(row=1, column=0, sticky="nsew", pady=(12, 0))


def build_test_tab_page(app: Any, parent: tk.Misc) -> None:
    parent.columnconfigure(0, weight=1)
    parent.rowconfigure(0, weight=1)

    content = tk.Frame(parent, bg=PALETTE["panel_bg"])
    content.grid(row=0, column=0, sticky="nsew")
    content.columnconfigure(0, weight=0)
    content.columnconfigure(1, weight=1)
    content.rowconfigure(0, weight=1)
    app.test_layout_content = content
    content.bind("<Configure>", app._sync_test_layout_widths)

    left = app._make_card(content)
    left.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
    left.grid_propagate(False)
    left.columnconfigure(0, weight=1)
    left.rowconfigure(1, weight=1)
    app.test_api_panel = left
    test_api_header = tk.Frame(left, bg=PALETTE["card_bg"])
    test_api_header.grid(row=0, column=0, sticky="ew")
    test_api_header.columnconfigure(0, weight=1)
    tk.Label(test_api_header, text="测试 API 选择", bg=PALETTE["card_bg"], fg=PALETTE["text"], font=app.hero_font).grid(row=0, column=0, sticky="w")
    make_button(test_api_header, textvariable=app.hide_error_button_var, variant="secondary", command=app._on_profile_filter_changed).grid(row=0, column=1, sticky="e")

    api_tree_wrap = tk.Frame(left, bg=PALETTE["card_bg"])
    api_tree_wrap.grid(row=1, column=0, sticky="nsew", pady=(12, 0))
    api_tree_wrap.columnconfigure(0, weight=1)
    api_tree_wrap.rowconfigure(0, weight=1)

    app.test_api_tree = ttk.Treeview(api_tree_wrap, columns=("name", "health"), show="headings")
    app.test_api_tree.heading("name", text="API")
    app.test_api_tree.heading("health", text="状态")
    app.test_api_tree.column("name", width=165, minwidth=120, anchor="w")
    app.test_api_tree.column("health", width=78, minwidth=64, anchor="center")
    app.test_api_tree.grid(row=0, column=0, sticky="nsew")
    app.test_api_tree.bind("<<TreeviewSelect>>", app._on_test_api_selection_changed)

    api_scroll = ttk.Scrollbar(api_tree_wrap, orient="vertical", command=app.test_api_tree.yview)
    api_scroll.grid(row=0, column=1, sticky="ns")
    app.test_api_tree.configure(yscrollcommand=api_scroll.set)

    right = tk.Frame(content, bg=PALETTE["panel_bg"])
    right.grid(row=0, column=1, sticky="nsew")
    right.columnconfigure(0, weight=1)
    right.rowconfigure(0, weight=0)
    right.rowconfigure(1, weight=1)

    detail = app._make_card(right)
    detail.grid(row=0, column=0, sticky="nsew", pady=(0, 10))
    detail.columnconfigure(1, weight=1)
    detail.columnconfigure(3, weight=1)

    header = tk.Frame(detail, bg=PALETTE["card_bg"])
    header.grid(row=0, column=0, columnspan=4, sticky="ew")
    header.columnconfigure(0, weight=1)
    tk.Label(header, text="健康检测", bg=PALETTE["card_bg"], fg=PALETTE["text"], font=app.hero_font).grid(row=0, column=0, sticky="w")
    app.test_detail_badge = make_status_badge(header, textvariable=app.test_detail_health_var)
    app.test_detail_badge.grid(row=0, column=1, sticky="e", padx=(10, 8))
    app.model_batch_button = make_button(header, text="测试选中 API 模型", variant="primary", command=app.test_selected_api_models)
    app.model_batch_button.grid(row=0, column=2, sticky="e")
    tk.Label(header, textvariable=app.test_selected_name_var, bg=PALETTE["card_bg"], fg=PALETTE["muted"], font=app.small_font).grid(row=1, column=0, columnspan=3, sticky="w", pady=(4, 0))

    tk.Label(detail, text="健康状态判定", bg=PALETTE["card_bg"], fg=PALETTE["muted"], font=app.small_font).grid(row=1, column=0, sticky="nw", padx=(0, 14), pady=(14, 4))
    override_row = tk.Frame(detail, bg=PALETTE["card_bg"])
    override_row.grid(row=1, column=1, sticky="ew", pady=(14, 4))
    app.health_override_combo = ttk.Combobox(override_row, textvariable=app.health_override_var, state="readonly", values=tuple(HEALTH_OVERRIDE_DISPLAY.values()), width=22)
    app.health_override_combo.grid(row=0, column=0, sticky="w")
    app.health_override_combo.bind("<<ComboboxSelected>>", app._on_health_override_changed)
    tk.Label(override_row, textvariable=app.health_override_note_var, bg=PALETTE["card_bg"], fg=PALETTE["muted"], font=app.small_font, justify="left", wraplength=320).grid(row=1, column=0, sticky="w", pady=(6, 0))

    app._create_dual_info_row(detail, 2, "提供方", app.test_detail_provider_var, "默认模型", app.test_detail_model_var)
    app._create_dual_info_row(detail, 3, "API Key", app.test_detail_key_var, "Wire API", app.test_detail_wire_var)
    app._create_dual_info_row(detail, 4, "最近检测", app.test_detail_checked_var, "最近 endpoint", app.test_detail_endpoint_var)
    app._create_info_row(detail, 5, "API 地址", app.test_detail_api_var, wraplength=520)
    app._create_info_row(detail, 6, "结果详情", app.test_detail_result_var, wraplength=520)
    app._create_success_models_row(detail, 7)
    app._create_info_row(detail, 8, "备注", app.test_detail_notes_var, wraplength=520)

    chat = app._make_card(right)
    chat.grid(row=1, column=0, sticky="nsew")
    chat.columnconfigure(0, weight=1)
    chat.rowconfigure(2, weight=1)

    chat_header = tk.Frame(chat, bg=PALETTE["card_bg"])
    chat_header.grid(row=0, column=0, sticky="ew")
    chat_header.columnconfigure(0, weight=1)
    tk.Label(chat_header, text="聊天测试", bg=PALETTE["card_bg"], fg=PALETTE["text"], font=app.hero_font).grid(row=0, column=0, sticky="w")
    tk.Label(chat_header, text="模型、接口标准和请求体在聊天设置里临时覆盖。", bg=PALETTE["card_bg"], fg=PALETTE["muted"], font=app.small_font).grid(row=1, column=0, sticky="w", pady=(4, 0))
    app.chat_settings_button = make_button(chat_header, text="聊天设置", variant="secondary", command=app.open_chat_settings)
    app.chat_settings_button.grid(row=0, column=1, rowspan=2, sticky="e")

    chat_meta = tk.Frame(chat, bg=PALETTE["card_bg"])
    chat_meta.grid(row=1, column=0, sticky="ew", pady=(12, 10))
    chat_meta.columnconfigure(1, weight=1)
    tk.Label(chat_meta, text="测试配置", bg=PALETTE["card_bg"], fg=PALETTE["muted"], font=app.small_font).grid(row=0, column=0, sticky="w", padx=(0, 12))
    tk.Label(chat_meta, textvariable=app.chat_target_var, bg=PALETTE["card_bg"], fg=PALETTE["text"], font=app.body_font).grid(row=0, column=1, sticky="w")
    tk.Label(chat_meta, text="当前设置", bg=PALETTE["card_bg"], fg=PALETTE["muted"], font=app.small_font).grid(row=1, column=0, sticky="w", padx=(0, 12), pady=(6, 0))
    tk.Label(chat_meta, textvariable=app.chat_settings_summary_var, bg=PALETTE["card_bg"], fg=PALETTE["text"], font=app.body_font, justify="left", wraplength=620).grid(row=1, column=1, sticky="w", pady=(6, 0))

    history_wrap = tk.Frame(chat, bg=PALETTE["card_bg"])
    history_wrap.grid(row=2, column=0, sticky="nsew")
    history_wrap.columnconfigure(0, weight=1)
    history_wrap.rowconfigure(0, weight=1)
    app.chat_history = tk.Text(history_wrap, wrap="word", relief="solid", borderwidth=1, highlightthickness=0, font=app.body_font, bg="#FBFDFE", fg=PALETTE["text"], state="disabled")
    app.chat_history.grid(row=0, column=0, sticky="nsew")
    chat_scroll = ttk.Scrollbar(history_wrap, orient="vertical", command=app.chat_history.yview)
    chat_scroll.grid(row=0, column=1, sticky="ns")
    app.chat_history.configure(yscrollcommand=chat_scroll.set)

    input_wrap = tk.Frame(chat, bg=PALETTE["card_bg"])
    input_wrap.grid(row=3, column=0, sticky="ew", pady=(12, 0))
    input_wrap.columnconfigure(0, weight=1)
    app.chat_input = tk.Text(input_wrap, height=4, wrap="word", relief="solid", borderwidth=1, highlightthickness=0, font=app.body_font, fg=PALETTE["text"])
    app.chat_input.grid(row=0, column=0, sticky="ew")
    buttons = tk.Frame(input_wrap, bg=PALETTE["card_bg"])
    buttons.grid(row=0, column=1, sticky="ns", padx=(10, 0))
    app.chat_send_button = make_button(buttons, text="发送测试", variant="primary", command=app.send_chat_message)
    app.chat_send_button.grid(row=0, column=0, sticky="ew", pady=(0, 8))
    make_button(buttons, text="清空记录", variant="secondary", command=app.clear_chat_history).grid(row=1, column=0, sticky="ew")
    content.after_idle(app._sync_test_layout_widths)


def build_settings_tab_page(app: Any, parent: tk.Misc) -> None:
    parent.columnconfigure(0, weight=1)
    parent.columnconfigure(1, weight=1)
    parent.rowconfigure(1, weight=1)

    settings_card = app._make_card(parent)
    settings_card.grid(row=0, column=0, sticky="nsew", padx=(0, 10), pady=(0, 10))
    settings_card.columnconfigure(1, weight=1)

    tk.Label(settings_card, text="设置", bg=PALETTE["card_bg"], fg=PALETTE["text"], font=app.hero_font).grid(row=0, column=0, columnspan=3, sticky="w")
    tk.Label(settings_card, textvariable=app.settings_hint_var, bg=PALETTE["card_bg"], fg=PALETTE["muted"], font=app.small_font).grid(
        row=1,
        column=0,
        columnspan=3,
        sticky="w",
        pady=(4, 12),
    )
    tk.Label(settings_card, text="模型批量测试同时请求数", bg=PALETTE["card_bg"], fg=PALETTE["muted"], font=app.small_font).grid(
        row=2,
        column=0,
        sticky="w",
        padx=(0, 14),
    )
    tk.Spinbox(
        settings_card,
        from_=MODEL_BATCH_CONCURRENCY_MIN,
        to=MODEL_BATCH_CONCURRENCY_MAX,
        textvariable=app.model_batch_concurrency_var,
        width=8,
        font=app.body_font,
        relief="solid",
        borderwidth=1,
    ).grid(row=2, column=1, sticky="w")
    tk.Label(settings_card, text="号池检测间隔（分钟）", bg=PALETTE["card_bg"], fg=PALETTE["muted"], font=app.small_font).grid(
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
        textvariable=app.account_pool_recovery_interval_var,
        width=8,
        font=app.body_font,
        relief="solid",
        borderwidth=1,
    ).grid(row=3, column=1, sticky="w", pady=(10, 0))
    tk.Label(settings_card, text="软件更新", bg=PALETTE["card_bg"], fg=PALETTE["muted"], font=app.small_font).grid(
        row=4,
        column=0,
        sticky="w",
        padx=(0, 14),
        pady=(10, 0),
    )
    tk.Label(settings_card, textvariable=app.software_update_status_var, bg=PALETTE["card_bg"], fg=PALETTE["muted"], font=app.small_font).grid(
        row=4,
        column=1,
        sticky="w",
        pady=(10, 0),
    )
    make_button(settings_card, text="检查软件更新", variant="secondary", command=app.check_software_update_now).grid(row=4, column=2, sticky="e", pady=(10, 0))
    ttk.Checkbutton(
        settings_card,
        text="启用仓库同步轮询",
        variable=app.hot_update_enabled_var,
    ).grid(row=5, column=0, sticky="w", pady=(10, 0))
    tk.Spinbox(
        settings_card,
        from_=5,
        to=1440,
        textvariable=app.hot_update_interval_var,
        width=8,
        font=app.body_font,
        relief="solid",
        borderwidth=1,
    ).grid(row=5, column=1, sticky="w", pady=(10, 0))
    make_button(settings_card, text="检查仓库同步", variant="secondary", command=app.check_hot_updates_now).grid(row=5, column=2, sticky="e", pady=(10, 0))
    tk.Label(settings_card, textvariable=app.hot_update_status_var, bg=PALETTE["card_bg"], fg=PALETTE["muted"], font=app.small_font).grid(
        row=6,
        column=0,
        columnspan=2,
        sticky="w",
        pady=(8, 0),
    )
    make_button(settings_card, text="保存设置", variant="primary", command=app.save_settings).grid(row=6, column=2, sticky="e", pady=(8, 0))

    info_card = app._make_card(parent)
    info_card.grid(row=0, column=1, sticky="nsew", pady=(0, 10))
    info_card.columnconfigure(1, weight=1)
    info_card.columnconfigure(3, weight=1)
    tk.Label(info_card, text="版本信息 / 系统信息", bg=PALETTE["card_bg"], fg=PALETTE["text"], font=app.hero_font).grid(row=0, column=0, columnspan=4, sticky="w")
    app._create_dual_info_row(info_card, 1, "应用版本", app.settings_version_var, "Python", app.settings_python_var)
    app._create_dual_info_row(info_card, 2, "Tk/Tcl", app.settings_tk_var, "ttkbootstrap", app.settings_ttkbootstrap_var)
    app._create_info_row(info_card, 3, "配置库", app.settings_storage_path_var, wraplength=560)
    app._create_info_row(info_card, 4, "Codex config", app.settings_codex_config_path_var, wraplength=560)
    app._create_info_row(info_card, 5, "Codex auth", app.settings_codex_auth_path_var, wraplength=560)
    app._create_info_row(info_card, 6, "当前工作目录", app.settings_project_root_var, wraplength=560)
    app._create_info_row(info_card, 7, "平台", app.settings_platform_var, wraplength=560)

    hot_update_log_card = app._make_card(parent)
    hot_update_log_card.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(0, 10))
    hot_update_log_card.columnconfigure(0, weight=1)
    tk.Label(hot_update_log_card, text="最近更新与同步记录", bg=PALETTE["card_bg"], fg=PALETTE["text"], font=app.section_font).grid(row=0, column=0, sticky="w")
    hot_update_log_wrap = tk.Frame(hot_update_log_card, bg=PALETTE["card_bg"])
    hot_update_log_wrap.grid(row=1, column=0, sticky="ew", pady=(8, 0))
    hot_update_log_wrap.columnconfigure(0, weight=1)
    app.hot_update_log_text = tk.Text(
        hot_update_log_wrap,
        height=6,
        wrap="word",
        relief="solid",
        borderwidth=1,
        highlightthickness=0,
        font=app.small_font,
        bg="#FBFDFE",
        fg=PALETTE["text"],
        state="disabled",
    )
    app.hot_update_log_text.grid(row=0, column=0, sticky="ew")
    hot_update_log_scroll = ttk.Scrollbar(hot_update_log_wrap, orient="vertical", command=app.hot_update_log_text.yview)
    hot_update_log_scroll.grid(row=0, column=1, sticky="ns")
    app.hot_update_log_text.configure(yscrollcommand=hot_update_log_scroll.set)


def build_skills_tab_page(app: Any, parent: tk.Misc) -> None:
    parent.columnconfigure(0, weight=1)
    parent.rowconfigure(0, weight=1)
    card = app._make_card(parent)
    card.grid(row=0, column=0, sticky="nsew")
    card.columnconfigure(0, weight=1)
    card.rowconfigure(1, weight=1)

    tk.Label(card, text="Skills 管理", bg=PALETTE["card_bg"], fg=PALETTE["text"], font=app.hero_font).grid(row=0, column=0, sticky="w")
    tk.Label(card, textvariable=app.skills_hint_var, bg=PALETTE["card_bg"], fg=PALETTE["muted"], font=app.small_font).grid(row=0, column=0, sticky="e")

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

    build_skill_repos_panel_page(app, market_tab)
    build_skill_repo_source_panel_page(app, repo_tab)
    build_local_skills_panel_page(app, local_tab)
    build_project_skills_panel_page(app, project_tab)


def build_skill_repos_panel_page(app: Any, parent: tk.Misc) -> None:
    parent.columnconfigure(0, weight=1)
    parent.rowconfigure(1, weight=1)
    repo_filter_bar = tk.Frame(parent, bg=PALETTE["card_bg"])
    repo_filter_bar.grid(row=0, column=0, sticky="ew", pady=(0, 8))
    repo_filter_bar.columnconfigure(1, weight=1)
    tk.Label(repo_filter_bar, text="筛选 Skill", bg=PALETTE["card_bg"], fg=PALETTE["muted"], font=app.small_font).grid(row=0, column=0, sticky="w", padx=(0, 8))
    app.skill_market_filter_entry = ttk.Entry(repo_filter_bar, textvariable=app.skill_market_filter_var)
    app.skill_market_filter_entry.grid(row=0, column=1, sticky="ew", padx=(0, 8))
    make_button(repo_filter_bar, text="清除", variant="secondary", command=app.clear_skill_market_filter).grid(row=0, column=2, sticky="e")
    app.skill_market_filter_var.trace_add("write", lambda *_args: app.apply_skill_market_filter())
    make_button(repo_filter_bar, text="刷新市场", variant="secondary", command=app.refresh_skill_market_now).grid(row=0, column=3, sticky="e", padx=(8, 0))
    tk.Label(parent, textvariable=app.skill_repo_preview_var, bg=PALETTE["card_bg"], fg=PALETTE["muted"], font=app.small_font).grid(row=2, column=0, sticky="w", pady=(8, 0))

    market_wrap = tk.Frame(parent, bg=PALETTE["card_bg"])
    market_wrap.grid(row=1, column=0, sticky="nsew")
    market_wrap.columnconfigure(0, weight=1)
    market_wrap.rowconfigure(0, weight=1)
    app.skill_market_canvas = tk.Canvas(market_wrap, bg=PALETTE["card_bg"], highlightthickness=0)
    app.skill_market_canvas.grid(row=0, column=0, sticky="nsew")
    market_scroll = ttk.Scrollbar(market_wrap, orient="vertical", command=app.skill_market_canvas.yview)
    market_scroll.grid(row=0, column=1, sticky="ns")
    app.skill_market_canvas.configure(yscrollcommand=market_scroll.set)
    app.skill_market_frame = tk.Frame(app.skill_market_canvas, bg=PALETTE["card_bg"])
    app.skill_market_window = app.skill_market_canvas.create_window((0, 0), window=app.skill_market_frame, anchor="nw")
    app.skill_market_frame.bind(
        "<Configure>",
        lambda _event: app.skill_market_canvas.configure(scrollregion=app.skill_market_canvas.bbox("all")),
    )
    app.skill_market_canvas.bind("<Configure>", app._layout_skill_market_cards)


def build_skill_repo_source_panel_page(app: Any, parent: tk.Misc) -> None:
    parent.columnconfigure(0, weight=1)
    parent.rowconfigure(2, weight=1)
    tk.Label(parent, text="仓库源管理", bg=PALETTE["card_bg"], fg=PALETTE["text"], font=app.section_font).grid(row=0, column=0, sticky="w")

    toolbar = tk.Frame(parent, bg=PALETTE["card_bg"])
    toolbar.grid(row=1, column=0, sticky="ew", pady=(8, 8))
    toolbar.columnconfigure(1, weight=1)
    tk.Label(toolbar, text="筛选仓库", bg=PALETTE["card_bg"], fg=PALETTE["muted"], font=app.small_font).grid(row=0, column=0, sticky="w", padx=(0, 8))
    app.skill_repo_filter_entry = ttk.Entry(toolbar, textvariable=app.skill_repo_filter_var)
    app.skill_repo_filter_entry.grid(row=0, column=1, sticky="ew", padx=(0, 8))
    make_button(toolbar, text="清除", variant="secondary", command=app.clear_skill_repo_filter).grid(row=0, column=2, sticky="e", padx=(0, 8))
    make_button(toolbar, text="新增仓库", variant="primary", command=app.add_skill_market_repo).grid(row=0, column=3, sticky="e", padx=(0, 8))
    make_button(toolbar, text="检查更新", variant="secondary", command=app.check_selected_skill_repo_update).grid(row=0, column=4, sticky="e")
    app.skill_repo_filter_var.trace_add("write", lambda *_args: app.apply_skill_repo_filter())

    repo_wrap = tk.Frame(parent, bg=PALETTE["card_bg"])
    repo_wrap.grid(row=2, column=0, sticky="nsew")
    repo_wrap.columnconfigure(0, weight=1)
    repo_wrap.rowconfigure(0, weight=1)
    app.skill_repo_tree = ttk.Treeview(repo_wrap, columns=("url", "branch", "commit", "auto"), show="headings")
    app.skill_repo_tree.heading("url", text="GitHub 仓库", anchor="w")
    app.skill_repo_tree.heading("branch", text="Ref", anchor="center")
    app.skill_repo_tree.heading("commit", text="最近提交", anchor="center")
    app.skill_repo_tree.heading("auto", text="自动更新", anchor="center")
    app.skill_repo_tree.column("url", width=300, anchor="w")
    app.skill_repo_tree.column("branch", width=90, anchor="center", stretch=False)
    app.skill_repo_tree.column("commit", width=110, anchor="center", stretch=False)
    app.skill_repo_tree.column("auto", width=80, anchor="center", stretch=False)
    app.skill_repo_tree.grid(row=0, column=0, sticky="nsew")
    app.skill_repo_tree.bind("<<TreeviewSelect>>", lambda _event: app._refresh_skill_repo_detail())
    repo_scroll = ttk.Scrollbar(repo_wrap, orient="vertical", command=app.skill_repo_tree.yview)
    repo_scroll.grid(row=0, column=1, sticky="ns")
    app.skill_repo_tree.configure(yscrollcommand=repo_scroll.set)

    repo_actions = tk.Frame(parent, bg=PALETTE["card_bg"])
    repo_actions.grid(row=3, column=0, sticky="ew", pady=(10, 0))
    repo_actions.columnconfigure(0, weight=1)
    tk.Label(repo_actions, textvariable=app.skill_repo_detail_var, bg=PALETTE["card_bg"], fg=PALETTE["muted"], font=app.small_font).grid(row=0, column=0, sticky="w", padx=(0, 8))
    make_button(repo_actions, text="编辑仓库", variant="secondary", command=app.edit_skill_market_repo).grid(row=0, column=1, sticky="e", padx=(0, 8))
    make_button(repo_actions, text="删除仓库", variant="danger", command=app.delete_skill_market_repo).grid(row=0, column=2, sticky="e", padx=(0, 8))
    make_button(repo_actions, text="安装到组", variant="secondary", command=app.install_selected_skill_repo_to_group).grid(row=0, column=3, sticky="e")


def build_local_skills_panel_page(app: Any, parent: tk.Misc) -> None:
    parent.columnconfigure(0, weight=1)
    parent.rowconfigure(0, weight=1)
    wrap = tk.Frame(parent, bg=PALETTE["card_bg"])
    wrap.grid(row=0, column=0, sticky="nsew")
    wrap.columnconfigure(0, weight=1)
    wrap.rowconfigure(0, weight=1)
    app.skill_group_tree = ttk.Treeview(wrap, columns=("name", "count", "description"), show="headings")
    app.skill_group_tree.heading("name", text="组名", anchor="w")
    app.skill_group_tree.heading("count", text="Skills", anchor="center")
    app.skill_group_tree.heading("description", text="描述", anchor="w")
    app.skill_group_tree.column("name", width=180, anchor="w")
    app.skill_group_tree.column("count", width=80, anchor="center", stretch=False)
    app.skill_group_tree.column("description", width=420, anchor="w")
    app.skill_group_tree.grid(row=0, column=0, sticky="nsew")
    app.skill_group_tree.bind("<<TreeviewSelect>>", lambda _event: app._refresh_skill_group_detail())
    group_scroll = ttk.Scrollbar(wrap, orient="vertical", command=app.skill_group_tree.yview)
    group_scroll.grid(row=0, column=1, sticky="ns")
    app.skill_group_tree.configure(yscrollcommand=group_scroll.set)

    actions = tk.Frame(parent, bg=PALETTE["card_bg"])
    actions.grid(row=1, column=0, sticky="ew", pady=(10, 0))
    for column in range(6):
        actions.columnconfigure(column, weight=1)
    make_button(actions, text="新增组", variant="primary", command=app.add_skill_group).grid(row=0, column=0, sticky="ew", padx=(0, 8))
    make_button(actions, text="编辑组", variant="secondary", command=app.edit_skill_group).grid(row=0, column=1, sticky="ew", padx=(0, 8))
    make_button(actions, text="删除组", variant="danger", command=app.delete_skill_group).grid(row=0, column=2, sticky="ew", padx=(0, 8))
    make_button(actions, text="刷新", variant="secondary", command=app.refresh_skills_tab).grid(row=0, column=3, sticky="ew", padx=(0, 8))
    tk.Label(actions, textvariable=app.skill_group_detail_var, bg=PALETTE["card_bg"], fg=PALETTE["muted"], font=app.small_font).grid(row=0, column=4, columnspan=2, sticky="w")


def build_project_skills_panel_page(app: Any, parent: tk.Misc) -> None:
    parent.columnconfigure(0, weight=1)
    parent.rowconfigure(0, weight=1)
    wrap = tk.Frame(parent, bg=PALETTE["card_bg"])
    wrap.grid(row=0, column=0, sticky="nsew")
    wrap.columnconfigure(0, weight=1)
    wrap.rowconfigure(0, weight=1)
    app.skill_project_tree = ttk.Treeview(wrap, columns=("name", "groups", "skills"), show="headings")
    app.skill_project_tree.heading("name", text="项目", anchor="w")
    app.skill_project_tree.heading("groups", text="关联组", anchor="w")
    app.skill_project_tree.heading("skills", text="展开 Skills", anchor="w")
    app.skill_project_tree.column("name", width=180, anchor="w")
    app.skill_project_tree.column("groups", width=260, anchor="w")
    app.skill_project_tree.column("skills", width=360, anchor="w")
    app.skill_project_tree.grid(row=0, column=0, sticky="nsew")
    app.skill_project_tree.bind("<<TreeviewSelect>>", lambda _event: app._refresh_skill_project_detail())
    project_scroll = ttk.Scrollbar(wrap, orient="vertical", command=app.skill_project_tree.yview)
    project_scroll.grid(row=0, column=1, sticky="ns")
    app.skill_project_tree.configure(yscrollcommand=project_scroll.set)

    actions = tk.Frame(parent, bg=PALETTE["card_bg"])
    actions.grid(row=1, column=0, sticky="ew", pady=(10, 0))
    actions.columnconfigure(0, weight=1)
    actions.columnconfigure(1, weight=1)
    actions.columnconfigure(2, weight=3)
    make_button(actions, text="编辑项目关联", variant="primary", command=app.edit_project).grid(row=0, column=0, sticky="ew", padx=(0, 8))
    make_button(actions, text="刷新", variant="secondary", command=app.refresh_skills_tab).grid(row=0, column=1, sticky="ew", padx=(0, 8))
    tk.Label(actions, textvariable=app.skill_project_detail_var, bg=PALETTE["card_bg"], fg=PALETTE["muted"], font=app.small_font).grid(row=0, column=2, sticky="w")
