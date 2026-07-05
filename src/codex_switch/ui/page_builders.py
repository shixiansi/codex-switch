from __future__ import annotations

import tkinter as tk
from typing import Any

from codex_switch.codex_config import PROJECT_ROOT_PLACEHOLDER
from codex_switch.models import ACCOUNT_POOL_GROUP_TYPE_LABELS
from codex_switch.ui.account_pool_logic import (
    ACCOUNT_POOL_SOURCE_FILTER_ALL,
    ACCOUNT_POOL_SOURCE_FILTER_PROFILE,
    ACCOUNT_POOL_SOURCE_FILTER_TEMPORARY,
)
from codex_switch.ui.styles import HEALTH_OVERRIDE_DISPLAY, PALETTE, make_button, make_status_badge, ttk


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
