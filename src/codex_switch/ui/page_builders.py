from __future__ import annotations

import tkinter as tk
from typing import Any

from codex_switch.codex_config import PROJECT_ROOT_PLACEHOLDER
from codex_switch.ui.styles import PALETTE, make_button, ttk


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
