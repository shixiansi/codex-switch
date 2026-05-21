from __future__ import annotations

import json
from pathlib import Path
import textwrap
import tkinter as tk
import tomllib
from tkinter import filedialog, messagebox

from codex_switch.codex_config import dumps_toml, parse_mcp_servers_toml, render_mcp_servers_toml
from codex_switch.models import Profile, ProjectRecord
from codex_switch.ui.styles import PALETTE, make_button, ttk
from codex_switch.ui.utils import compact_text, is_http_url


class ChatSettingsDialog(tk.Toplevel):
    def __init__(
        self,
        master: tk.Misc,
        *,
        model_values: list[str],
        selected_model: str,
        wire_values: tuple[str, ...],
        selected_wire: str,
        payload_text: str,
        payload_templates: dict[str, str],
    ) -> None:
        super().__init__(master)
        self.title("聊天设置")
        self.geometry("760x620")
        self.minsize(680, 520)
        self.configure(bg=PALETTE["app_bg"])
        self.result: dict | None = None
        self.payload_templates = payload_templates

        values = model_values or ["-"]
        selected_model = selected_model.strip()
        self.model_var = tk.StringVar(value=selected_model if selected_model and selected_model != "-" else values[0])
        self.wire_var = tk.StringVar(value=selected_wire if selected_wire in wire_values else wire_values[0])

        card = tk.Frame(
            self,
            bg=PALETTE["card_bg"],
            highlightbackground=PALETTE["card_border"],
            highlightthickness=1,
            padx=20,
            pady=18,
        )
        card.pack(fill="both", expand=True, padx=18, pady=18)
        card.columnconfigure(1, weight=1)
        card.rowconfigure(4, weight=1)

        tk.Label(card, text="聊天设置", bg=PALETTE["card_bg"], fg=PALETTE["text"], font=("Microsoft YaHei UI", 14, "bold")).grid(
            row=0,
            column=0,
            columnspan=2,
            sticky="w",
        )
        tk.Label(
            card,
            text="这里的模型、接口标准和请求体只影响当前聊天测试与模型批量测试；模型可从列表选择，也可以直接输入。",
            bg=PALETTE["card_bg"],
            fg=PALETTE["muted"],
            font=("Microsoft YaHei UI", 9),
        ).grid(row=1, column=0, columnspan=2, sticky="w", pady=(4, 14))

        tk.Label(card, text="聊天模型", bg=PALETTE["card_bg"], fg=PALETTE["text"], font=("Microsoft YaHei UI", 10, "bold")).grid(row=2, column=0, sticky="w", pady=6)
        self.model_combo = ttk.Combobox(card, textvariable=self.model_var, values=tuple(values), state="normal", width=42)
        self.model_combo.grid(row=2, column=1, sticky="ew", pady=6)

        tk.Label(card, text="接口标准", bg=PALETTE["card_bg"], fg=PALETTE["text"], font=("Microsoft YaHei UI", 10, "bold")).grid(row=3, column=0, sticky="w", pady=6)
        wire_row = tk.Frame(card, bg=PALETTE["card_bg"])
        wire_row.grid(row=3, column=1, sticky="ew", pady=6)
        wire_row.columnconfigure(0, weight=1)
        self.wire_combo = ttk.Combobox(wire_row, textvariable=self.wire_var, values=wire_values, state="readonly", width=24)
        self.wire_combo.grid(row=0, column=0, sticky="w")
        make_button(wire_row, text="重置请求体", variant="secondary", command=self._reset_payload).grid(row=0, column=1, sticky="e")

        tk.Label(card, text="请求体 JSON", bg=PALETTE["card_bg"], fg=PALETTE["text"], font=("Microsoft YaHei UI", 10, "bold")).grid(row=4, column=0, sticky="nw", pady=(10, 0))
        editor_wrap = tk.Frame(card, bg=PALETTE["card_bg"])
        editor_wrap.grid(row=4, column=1, sticky="nsew", pady=(10, 0))
        editor_wrap.columnconfigure(0, weight=1)
        editor_wrap.rowconfigure(0, weight=1)
        self.payload_text = tk.Text(
            editor_wrap,
            wrap="word",
            relief="solid",
            borderwidth=1,
            highlightthickness=0,
            font=("Consolas", 10),
            bg="#FBFDFE",
            fg=PALETTE["text"],
        )
        self.payload_text.grid(row=0, column=0, sticky="nsew")
        self.payload_text.insert("1.0", payload_text)
        payload_scroll = ttk.Scrollbar(editor_wrap, orient="vertical", command=self.payload_text.yview)
        payload_scroll.grid(row=0, column=1, sticky="ns")
        self.payload_text.configure(yscrollcommand=payload_scroll.set)

        buttons = ttk.Frame(card)
        buttons.grid(row=5, column=0, columnspan=2, sticky="e", pady=(14, 0))
        make_button(buttons, text="取消", variant="secondary", command=self.destroy).grid(row=0, column=0, padx=(0, 8))
        make_button(buttons, text="保存设置", variant="primary", command=self._on_submit).grid(row=0, column=1)

        self.transient(master)
        self.grab_set()

    def _reset_payload(self) -> None:
        template = self.payload_templates.get(self.wire_var.get().strip(), "")
        self.payload_text.delete("1.0", "end")
        self.payload_text.insert("1.0", template)

    def _on_submit(self) -> None:
        payload = self.payload_text.get("1.0", "end").strip()
        if payload:
            try:
                parsed = json.loads(payload)
            except json.JSONDecodeError as exc:
                messagebox.showerror("校验失败", f"请求体 JSON 无效：第 {exc.lineno} 行第 {exc.colno} 列。", parent=self)
                return
            if not isinstance(parsed, dict):
                messagebox.showerror("校验失败", "请求体 JSON 必须是 object。", parent=self)
                return
        self.result = {
            "model": self.model_var.get().strip(),
            "wire_api": self.wire_var.get().strip(),
            "payload_text": payload,
        }
        self.destroy()


class ModelBatchTestDialog(tk.Toplevel):
    STATUS_TEXT = {
        "pending": "等待",
        "running": "测试中",
        "success": "成功",
        "error": "失败",
    }
    BLOCK_WIDTH = 300
    BLOCK_HEIGHT = 128
    GRID_GAP = 10
    DEFAULT_GRID_COLUMNS = 3
    MAX_GRID_COLUMNS = 5
    MODEL_NAME_CHARS = 18
    DETAIL_PREVIEW_LINES = 3
    DETAIL_PREVIEW_WIDTH = 42
    DETAIL_WRAP_LENGTH = 260
    SLOW_DURATION_MS = 10_000

    def __init__(self, master: tk.Misc, *, profile_name: str, models: list[str], retest_command) -> None:
        super().__init__(master)
        self.title("模型批量测试")
        self.geometry("1040x640")
        self.minsize(760, 480)
        self.configure(bg=PALETTE["app_bg"])
        self.status_labels: dict[str, tk.Label] = {}
        self.duration_labels: dict[str, tk.Label] = {}
        self.detail_labels: dict[str, tk.Label] = {}
        self.result_blocks: dict[str, tk.Frame] = {}
        self.rendered_models: list[str] = []
        self.grid_columns = self.DEFAULT_GRID_COLUMNS
        self.summary_var = tk.StringVar(value=f"待测试 {len(models)} 个模型")

        card = tk.Frame(
            self,
            bg=PALETTE["card_bg"],
            highlightbackground=PALETTE["card_border"],
            highlightthickness=1,
            padx=20,
            pady=18,
        )
        card.pack(fill="both", expand=True, padx=18, pady=18)
        card.columnconfigure(0, weight=1)
        card.rowconfigure(2, weight=1)

        header = tk.Frame(card, bg=PALETTE["card_bg"])
        header.grid(row=0, column=0, sticky="ew")
        header.columnconfigure(0, weight=1)
        tk.Label(header, text="模型批量测试", bg=PALETTE["card_bg"], fg=PALETTE["text"], font=("Microsoft YaHei UI", 14, "bold")).grid(row=0, column=0, sticky="w")
        self.retest_button = make_button(header, text="重新测试", variant="primary", command=retest_command)
        self.retest_button.grid(row=0, column=1, sticky="e", padx=(0, 8))
        make_button(header, text="关闭", variant="secondary", command=self.destroy).grid(row=0, column=2, sticky="e")
        tk.Label(
            header,
            text=f"当前 API：{profile_name}",
            bg=PALETTE["card_bg"],
            fg=PALETTE["muted"],
            font=("Microsoft YaHei UI", 9),
        ).grid(row=1, column=0, columnspan=3, sticky="w", pady=(4, 0))

        tk.Label(card, textvariable=self.summary_var, bg=PALETTE["card_bg"], fg=PALETTE["muted"], font=("Microsoft YaHei UI", 9)).grid(row=1, column=0, sticky="w", pady=(12, 8))

        list_wrap = tk.Frame(card, bg=PALETTE["card_bg"])
        list_wrap.grid(row=2, column=0, sticky="nsew")
        list_wrap.columnconfigure(0, weight=1)
        list_wrap.rowconfigure(0, weight=1)

        self.canvas = tk.Canvas(list_wrap, bg=PALETTE["card_bg"], highlightthickness=0)
        self.canvas.grid(row=0, column=0, sticky="nsew")
        scrollbar = ttk.Scrollbar(list_wrap, orient="vertical", command=self.canvas.yview)
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.canvas.configure(yscrollcommand=scrollbar.set)

        self.rows = tk.Frame(self.canvas, bg=PALETTE["card_bg"])
        self.rows_id = self.canvas.create_window((0, 0), window=self.rows, anchor="nw")

        def sync_scroll_region(_event: tk.Event) -> None:
            self.canvas.configure(scrollregion=self.canvas.bbox("all"))

        def sync_row_width(event: tk.Event) -> None:
            self.canvas.itemconfigure(self.rows_id, width=event.width)
            self._layout_result_blocks(event.width)

        self.rows.bind("<Configure>", sync_scroll_region)
        self.canvas.bind("<Configure>", sync_row_width)
        self.render_models(models)
        self.transient(master)

    def render_models(self, models: list[str]) -> None:
        for child in self.rows.winfo_children():
            child.destroy()
        self.status_labels = {}
        self.duration_labels = {}
        self.detail_labels = {}
        self.result_blocks = {}
        self.rendered_models = list(models)
        for model in models:
            block = tk.Frame(
                self.rows,
                bg=PALETTE["status_bg"],
                highlightbackground=PALETTE["card_border"],
                highlightthickness=1,
                width=self.BLOCK_WIDTH,
                height=self.BLOCK_HEIGHT,
            )
            block.grid_propagate(False)

            content = tk.Frame(block, bg=PALETTE["status_bg"])
            content.pack(fill="both", expand=True, padx=12, pady=10)
            content.rowconfigure(1, weight=1)
            content.columnconfigure(0, weight=1)

            top = tk.Frame(content, bg=PALETTE["status_bg"])
            top.grid(row=0, column=0, sticky="ew")
            top.columnconfigure(0, weight=1)
            tk.Label(
                top,
                text=compact_text(model, self.MODEL_NAME_CHARS),
                bg=PALETTE["status_bg"],
                fg=PALETTE["text"],
                font=("Microsoft YaHei UI", 10, "bold"),
                anchor="w",
                width=self.MODEL_NAME_CHARS,
            ).grid(row=0, column=0, sticky="w")

            meta = tk.Frame(top, bg=PALETTE["status_bg"])
            meta.grid(row=0, column=1, sticky="e", padx=(12, 0))
            duration = tk.Label(
                meta,
                text="待测",
                bg=PALETTE["neutral_soft"],
                fg=PALETTE["neutral_text"],
                font=("Microsoft YaHei UI", 9, "bold"),
                padx=8,
                pady=3,
                width=8,
            )
            duration.grid(row=0, column=0, sticky="e", padx=(0, 6))
            status = tk.Label(
                meta,
                text="等待",
                bg=PALETTE["neutral_soft"],
                fg=PALETTE["neutral_text"],
                font=("Microsoft YaHei UI", 9, "bold"),
                padx=8,
                pady=3,
                width=5,
            )
            status.grid(row=0, column=1, sticky="e")

            detail = tk.Label(
                content,
                text="等待测试",
                bg=PALETTE["status_bg"],
                fg=PALETTE["muted"],
                font=("Microsoft YaHei UI", 9),
                anchor="nw",
                justify="left",
                wraplength=self.DETAIL_WRAP_LENGTH,
                height=self.DETAIL_PREVIEW_LINES,
            )
            detail.grid(row=1, column=0, sticky="nsew", pady=(8, 0))
            self.detail_labels[model] = detail
            self.duration_labels[model] = duration
            self.status_labels[model] = status
            self.result_blocks[model] = block
        self._layout_result_blocks(self.canvas.winfo_width())

    def _grid_columns_for_width(self, width: int) -> int:
        if width <= 1:
            return self.DEFAULT_GRID_COLUMNS
        columns = max(1, (width + self.GRID_GAP) // (self.BLOCK_WIDTH + self.GRID_GAP))
        return min(self.MAX_GRID_COLUMNS, columns)

    def _layout_result_blocks(self, width: int) -> None:
        columns = self._grid_columns_for_width(width)
        if columns == self.grid_columns and all(block.winfo_manager() for block in self.result_blocks.values()):
            return
        self.grid_columns = columns
        for column in range(self.MAX_GRID_COLUMNS):
            self.rows.columnconfigure(column, weight=0, minsize=0)
        for index, model in enumerate(self.rendered_models):
            block = self.result_blocks.get(model)
            if block is None:
                continue
            column = index % columns
            padx = (0, self.GRID_GAP if column < columns - 1 else 0)
            block.grid(row=index // columns, column=column, sticky="nw", padx=padx, pady=(0, self.GRID_GAP))

    def set_retest_enabled(self, enabled: bool) -> None:
        if enabled:
            self.retest_button.state(["!disabled"])
        else:
            self.retest_button.state(["disabled"])

    def set_status(self, model: str, status: str, detail: str = "", duration_ms: int | None = None) -> None:
        label = self.status_labels.get(model)
        duration_label = self.duration_labels.get(model)
        detail_label = self.detail_labels.get(model)
        if label is None or duration_label is None or detail_label is None:
            return
        bg, fg = self._result_colors(status, duration_ms)
        label.configure(text=self.STATUS_TEXT.get(status, status), bg=bg, fg=fg)
        duration_label.configure(text=self._duration_text(status, duration_ms), bg=bg, fg=fg)
        if detail:
            detail_label.configure(
                text=self._detail_preview(detail),
                fg=PALETTE["text"] if status == "success" else PALETTE["danger"],
            )
        elif status == "running":
            detail_label.configure(text="正在发送 ping 请求...", fg=PALETTE["muted"])
        elif status == "success":
            detail_label.configure(text="无返回内容", fg=PALETTE["muted"])
        else:
            detail_label.configure(text="等待测试", fg=PALETTE["muted"])

    def set_summary(self, *, total: int, success_count: int, error_count: int, running: bool) -> None:
        finished = success_count + error_count
        if running:
            self.summary_var.set(f"正在测试：已完成 {finished}/{total}，成功 {success_count}，失败 {error_count}")
        else:
            self.summary_var.set(f"测试完成：成功 {success_count}，失败 {error_count}，共 {total} 个模型")

    def _detail_preview(self, detail: str) -> str:
        lines = detail.strip().splitlines() or ["等待测试"]
        preview: list[str] = []
        overflow = False
        for line_index, raw_line in enumerate(lines):
            wrapped = textwrap.wrap(raw_line.strip(), width=self.DETAIL_PREVIEW_WIDTH) or [""]
            for part in wrapped:
                if len(preview) >= self.DETAIL_PREVIEW_LINES:
                    overflow = True
                    break
                preview.append(part)
            if overflow:
                break
            if line_index < len(lines) - 1 and len(preview) >= self.DETAIL_PREVIEW_LINES:
                overflow = True
                break
        if overflow and preview:
            preview[-1] = f"{preview[-1][: self.DETAIL_PREVIEW_WIDTH - 3]}..."
        return "\n".join(preview)

    def _duration_text(self, status: str, duration_ms: int | None) -> str:
        if duration_ms is None:
            return "请求中" if status == "running" else "待测"
        if duration_ms < 1000:
            return f"{duration_ms} ms"
        return f"{duration_ms / 1000:.1f} 秒"

    def _result_colors(self, status: str, duration_ms: int | None) -> tuple[str, str]:
        if status == "error":
            return PALETTE["danger_soft"], PALETTE["danger"]
        if status == "success":
            if duration_ms is not None and duration_ms >= self.SLOW_DURATION_MS:
                return PALETTE["warning_soft"], PALETTE["warning"]
            return PALETTE["success_soft"], PALETTE["success"]
        if status == "running":
            return PALETTE["warning_soft"], PALETTE["warning"]
        return PALETTE["neutral_soft"], PALETTE["neutral_text"]


class SuccessfulModelsDialog(tk.Toplevel):
    def __init__(self, master: tk.Misc, *, profile_name: str, models: list[str], copy_command) -> None:
        super().__init__(master)
        self.title("成功模型")
        self.geometry("640x460")
        self.minsize(520, 360)
        self.configure(bg=PALETTE["app_bg"])
        self.copy_command = copy_command
        self.hint_var = tk.StringVar(value="点击模型便签即可复制名称。")

        card = tk.Frame(
            self,
            bg=PALETTE["card_bg"],
            highlightbackground=PALETTE["card_border"],
            highlightthickness=1,
            padx=20,
            pady=18,
        )
        card.pack(fill="both", expand=True, padx=18, pady=18)
        card.columnconfigure(0, weight=1)
        card.rowconfigure(2, weight=1)

        header = tk.Frame(card, bg=PALETTE["card_bg"])
        header.grid(row=0, column=0, sticky="ew")
        header.columnconfigure(0, weight=1)
        tk.Label(header, text="成功模型", bg=PALETTE["card_bg"], fg=PALETTE["text"], font=("Microsoft YaHei UI", 14, "bold")).grid(row=0, column=0, sticky="w")
        make_button(header, text="关闭", variant="secondary", command=self.destroy).grid(row=0, column=1, sticky="e")
        tk.Label(
            header,
            text=f"当前 API：{profile_name}",
            bg=PALETTE["card_bg"],
            fg=PALETTE["muted"],
            font=("Microsoft YaHei UI", 9),
        ).grid(row=1, column=0, columnspan=2, sticky="w", pady=(4, 0))

        tk.Label(card, textvariable=self.hint_var, bg=PALETTE["card_bg"], fg=PALETTE["muted"], font=("Microsoft YaHei UI", 9)).grid(row=1, column=0, sticky="w", pady=(12, 8))

        list_wrap = tk.Frame(card, bg=PALETTE["card_bg"])
        list_wrap.grid(row=2, column=0, sticky="nsew")
        list_wrap.columnconfigure(0, weight=1)
        list_wrap.rowconfigure(0, weight=1)

        self.canvas = tk.Canvas(list_wrap, bg=PALETTE["card_bg"], highlightthickness=0)
        self.canvas.grid(row=0, column=0, sticky="nsew")
        scrollbar = ttk.Scrollbar(list_wrap, orient="vertical", command=self.canvas.yview)
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.canvas.configure(yscrollcommand=scrollbar.set)

        self.tags = tk.Frame(self.canvas, bg=PALETTE["card_bg"])
        self.tags_id = self.canvas.create_window((0, 0), window=self.tags, anchor="nw")

        def sync_scroll_region(_event: tk.Event) -> None:
            self.canvas.configure(scrollregion=self.canvas.bbox("all"))

        def sync_tag_width(event: tk.Event) -> None:
            self.canvas.itemconfigure(self.tags_id, width=event.width)

        self.tags.bind("<Configure>", sync_scroll_region)
        self.canvas.bind("<Configure>", sync_tag_width)
        self._render_tags(models)
        self.transient(master)

    def _render_tags(self, models: list[str]) -> None:
        if not models:
            tk.Label(
                self.tags,
                text="暂无成功模型。",
                bg=PALETTE["card_bg"],
                fg=PALETTE["muted"],
                font=("Microsoft YaHei UI", 10),
            ).grid(row=0, column=0, sticky="w", pady=6)
            return

        column_count = 3
        for column in range(column_count):
            self.tags.columnconfigure(column, weight=1)
        for index, model in enumerate(models):
            tag = tk.Canvas(
                self.tags,
                width=244,
                height=38,
                bg=PALETTE["card_bg"],
                highlightthickness=0,
                cursor="hand2",
            )
            tag.create_rectangle(1, 1, 243, 37, fill=PALETTE["success_soft"], outline="#A7F3D0")
            tag.create_text(
                13,
                19,
                text=compact_text(model, 28),
                fill=PALETTE["success"],
                font=("Microsoft YaHei UI", 10, "bold"),
                anchor="w",
            )
            tag.grid(row=index // column_count, column=index % column_count, sticky="w", padx=6, pady=6)
            tag.bind("<Button-1>", lambda _event, name=model: self._copy_model(name))

    def _copy_model(self, model: str) -> None:
        self.copy_command(model)
        self.hint_var.set(f"已复制：{model}")


class ProfileDialog(tk.Toplevel):
    def __init__(self, master: tk.Misc, profile: Profile | None = None) -> None:
        super().__init__(master)
        self.title("配置编辑")
        self.resizable(False, False)
        self.configure(bg=PALETTE["app_bg"])
        self.result: dict | None = None

        defaults = profile or Profile.create(name="", base_url="", api_key="")
        self.last_signed_date = defaults.last_signed_date
        self.name_var = tk.StringVar(value=defaults.name)
        self.base_url_var = tk.StringVar(value=defaults.base_url)
        self.api_key_var = tk.StringVar(value=defaults.api_key)
        self.model_var = tk.StringVar(value=defaults.model)
        self.provider_name_var = tk.StringVar(value=defaults.provider_name)
        self.wire_api_var = tk.StringVar(value=defaults.wire_api)
        self.requires_sign_in_var = tk.BooleanVar(value=defaults.requires_sign_in)
        self.sign_in_url_var = tk.StringVar(value=defaults.sign_in_url)
        self.show_key_var = tk.BooleanVar(value=False)

        card = tk.Frame(
            self,
            bg=PALETTE["card_bg"],
            highlightbackground=PALETTE["card_border"],
            highlightthickness=1,
            padx=20,
            pady=18,
        )
        card.grid(padx=18, pady=18, sticky="nsew")
        tk.Label(
            card,
            text="新增或编辑配置",
            bg=PALETTE["card_bg"],
            fg=PALETTE["text"],
            font=("Microsoft YaHei UI", 14, "bold"),
        ).grid(row=0, column=0, columnspan=3, sticky="w")
        tk.Label(
            card,
            text="默认模型用于全局切换和聊天测试；如需签到，可在这里补充签到地址。",
            bg=PALETTE["card_bg"],
            fg=PALETTE["muted"],
            font=("Microsoft YaHei UI", 9),
        ).grid(row=1, column=0, columnspan=3, sticky="w", pady=(4, 14))

        fields = [
            ("名称", self.name_var),
            ("API 地址", self.base_url_var),
            ("API Key", self.api_key_var),
            ("默认模型", self.model_var),
            ("提供方名称", self.provider_name_var),
            ("Wire API", self.wire_api_var),
        ]
        self.entries: dict[str, ttk.Entry] = {}
        for index, (label, variable) in enumerate(fields, start=2):
            tk.Label(
                card,
                text=label,
                bg=PALETTE["card_bg"],
                fg=PALETTE["text"],
                font=("Microsoft YaHei UI", 10, "bold"),
            ).grid(row=index, column=0, sticky="w", pady=6)
            show = "*" if label == "API Key" and not self.show_key_var.get() else ""
            entry = ttk.Entry(card, textvariable=variable, width=48, show=show)
            entry.grid(row=index, column=1, sticky="ew", pady=6)
            self.entries[label] = entry

        ttk.Checkbutton(card, text="显示 Key", variable=self.show_key_var, command=self._toggle_key_visibility).grid(
            row=4,
            column=2,
            padx=(8, 0),
            sticky="w",
        )
        ttk.Checkbutton(card, text="需要签到", variable=self.requires_sign_in_var, command=self._toggle_sign_in_fields).grid(
            row=8,
            column=0,
            sticky="w",
            pady=(6, 0),
        )
        tk.Label(
            card,
            text="签到地址",
            bg=PALETTE["card_bg"],
            fg=PALETTE["text"],
            font=("Microsoft YaHei UI", 10, "bold"),
        ).grid(row=9, column=0, sticky="w", pady=6)
        self.sign_in_url_entry = ttk.Entry(card, textvariable=self.sign_in_url_var, width=48)
        self.sign_in_url_entry.grid(row=9, column=1, columnspan=2, sticky="ew", pady=6)

        tk.Label(
            card,
            text="备注",
            bg=PALETTE["card_bg"],
            fg=PALETTE["text"],
            font=("Microsoft YaHei UI", 10, "bold"),
        ).grid(row=10, column=0, sticky="nw", pady=6)
        self.notes_text = tk.Text(
            card,
            width=48,
            height=4,
            wrap="word",
            relief="solid",
            borderwidth=1,
            highlightthickness=0,
            font=("Microsoft YaHei UI", 10),
            fg=PALETTE["text"],
        )
        self.notes_text.grid(row=10, column=1, columnspan=2, sticky="ew", pady=6)
        if defaults.notes:
            self.notes_text.insert("1.0", defaults.notes)

        buttons = ttk.Frame(card)
        buttons.grid(row=11, column=0, columnspan=3, sticky="e", pady=(14, 0))
        make_button(buttons, text="取消", variant="secondary", command=self.destroy).grid(row=0, column=0, padx=(0, 8))
        make_button(buttons, text="保存配置", variant="primary", command=self._on_submit).grid(row=0, column=1)

        card.columnconfigure(1, weight=1)
        self._toggle_sign_in_fields()
        self.transient(master)
        self.grab_set()
        self.entries["名称"].focus_set()

    def _toggle_key_visibility(self) -> None:
        self.entries["API Key"].configure(show="" if self.show_key_var.get() else "*")

    def _toggle_sign_in_fields(self) -> None:
        state = "normal" if self.requires_sign_in_var.get() else "disabled"
        self.sign_in_url_entry.configure(state=state)

    def _on_submit(self) -> None:
        name = self.name_var.get().strip()
        base_url = self.base_url_var.get().strip()
        api_key = self.api_key_var.get().strip()
        model = self.model_var.get().strip()
        requires_sign_in = self.requires_sign_in_var.get()
        sign_in_url = self.sign_in_url_var.get().strip()

        if not name:
            messagebox.showerror("校验失败", "请输入配置名称。", parent=self)
            return
        if not is_http_url(base_url):
            messagebox.showerror("校验失败", "API 地址必须以 http:// 或 https:// 开头。", parent=self)
            return
        if not api_key:
            messagebox.showerror("校验失败", "请输入 API Key。", parent=self)
            return
        if not model:
            messagebox.showerror("校验失败", "请至少填写一个默认模型。", parent=self)
            return
        if requires_sign_in and sign_in_url and not is_http_url(sign_in_url):
            messagebox.showerror("校验失败", "签到地址必须以 http:// 或 https:// 开头。", parent=self)
            return

        self.result = {
            "name": name,
            "base_url": base_url.rstrip("/"),
            "api_key": api_key,
            "model": model,
            "provider_name": self.provider_name_var.get().strip() or "OpenAI",
            "wire_api": self.wire_api_var.get().strip() or "responses",
            "requires_sign_in": requires_sign_in,
            "sign_in_url": sign_in_url if requires_sign_in else "",
            "last_signed_date": self.last_signed_date if requires_sign_in else None,
            "notes": self.notes_text.get("1.0", "end").strip(),
        }
        self.destroy()


class ProjectDialog(tk.Toplevel):
    def __init__(
        self,
        master: tk.Misc,
        profiles: list[Profile],
        project: ProjectRecord | None = None,
        initial_project_dir: str = "",
    ) -> None:
        super().__init__(master)
        self.title("项目配置")
        self.resizable(False, False)
        self.configure(bg=PALETTE["app_bg"])
        self.result: dict | None = None
        self.profile_values: dict[str, str] = {}

        if project is None:
            default_name = ""
            default_project_dir = initial_project_dir.strip()
            default_profile_id = profiles[0].id if profiles else ""
            default_run_command = ""
        else:
            default_name = project.name
            default_project_dir = project.project_dir
            default_profile_id = project.profile_id
            default_run_command = project.run_command
        self.name_var = tk.StringVar(value=default_name)
        self.project_dir_var = tk.StringVar(value=default_project_dir)
        self.profile_var = tk.StringVar()
        self.run_command_var = tk.StringVar(value=default_run_command)

        card = tk.Frame(
            self,
            bg=PALETTE["card_bg"],
            highlightbackground=PALETTE["card_border"],
            highlightthickness=1,
            padx=20,
            pady=18,
        )
        card.grid(padx=18, pady=18, sticky="nsew")
        tk.Label(
            card,
            text="新增或编辑项目",
            bg=PALETTE["card_bg"],
            fg=PALETTE["text"],
            font=("Microsoft YaHei UI", 14, "bold"),
        ).grid(row=0, column=0, columnspan=3, sticky="w")
        tk.Label(
            card,
            text="项目模板会根据绑定的配置生成 .codex 目录、启动脚本和项目级 MCP 配置。",
            bg=PALETTE["card_bg"],
            fg=PALETTE["muted"],
            font=("Microsoft YaHei UI", 9),
        ).grid(row=1, column=0, columnspan=3, sticky="w", pady=(4, 14))

        tk.Label(card, text="项目名", bg=PALETTE["card_bg"], fg=PALETTE["text"], font=("Microsoft YaHei UI", 10, "bold")).grid(row=2, column=0, sticky="w", pady=6)
        ttk.Entry(card, textvariable=self.name_var, width=52).grid(row=2, column=1, columnspan=2, sticky="ew", pady=6)

        tk.Label(card, text="项目目录", bg=PALETTE["card_bg"], fg=PALETTE["text"], font=("Microsoft YaHei UI", 10, "bold")).grid(row=3, column=0, sticky="w", pady=6)
        ttk.Entry(card, textvariable=self.project_dir_var, width=52, state="readonly").grid(row=3, column=1, sticky="ew", pady=6)
        browse_button = make_button(card, text="浏览", variant="secondary", command=self._pick_dir)
        browse_button.grid(row=3, column=2, sticky="ew", padx=(8, 0), pady=6)

        tk.Label(card, text="绑定配置", bg=PALETTE["card_bg"], fg=PALETTE["text"], font=("Microsoft YaHei UI", 10, "bold")).grid(row=4, column=0, sticky="w", pady=6)
        profile_choices: list[str] = []
        for profile in profiles:
            label = f"{profile.name} | {profile.provider_name} | {profile.model or '-'}"
            if label in self.profile_values:
                label = f"{label} [{profile.id[:8]}]"
            self.profile_values[label] = profile.id
            profile_choices.append(label)
            if profile.id == default_profile_id:
                self.profile_var.set(label)
        if not self.profile_var.get() and profile_choices:
            self.profile_var.set(profile_choices[0])
        ttk.Combobox(card, textvariable=self.profile_var, values=profile_choices, state="readonly", width=50).grid(
            row=4,
            column=1,
            columnspan=2,
            sticky="ew",
            pady=6,
        )

        tk.Label(card, text="运行命令", bg=PALETTE["card_bg"], fg=PALETTE["text"], font=("Microsoft YaHei UI", 10, "bold")).grid(row=5, column=0, sticky="w", pady=6)
        ttk.Entry(card, textvariable=self.run_command_var, width=52).grid(row=5, column=1, columnspan=2, sticky="ew", pady=6)
        tk.Label(
            card,
            text="例如 npm run dev、pnpm dev、python main.py。点击“运行项目”时会在新开的 cmd 窗口执行。",
            bg=PALETTE["card_bg"],
            fg=PALETTE["muted"],
            font=("Microsoft YaHei UI", 9),
            justify="left",
            wraplength=420,
        ).grid(row=6, column=1, columnspan=2, sticky="w", pady=(0, 6))

        buttons = ttk.Frame(card)
        buttons.grid(row=7, column=0, columnspan=3, sticky="e", pady=(14, 0))
        make_button(buttons, text="取消", variant="secondary", command=self.destroy).grid(row=0, column=0, padx=(0, 8))
        make_button(buttons, text="保存项目", variant="primary", command=self._on_submit).grid(row=0, column=1)

        card.columnconfigure(1, weight=1)
        self.transient(master)
        self.grab_set()

    def _pick_dir(self) -> None:
        current = self.project_dir_var.get().strip() or str(Path.cwd())
        selected = filedialog.askdirectory(parent=self, initialdir=current)
        if selected:
            self.project_dir_var.set(selected)

    def _on_submit(self) -> None:
        project_dir_raw = self.project_dir_var.get().strip()
        if not project_dir_raw:
            messagebox.showerror("校验失败", "请选择项目目录。", parent=self)
            return

        project_root = Path(project_dir_raw).expanduser().resolve(strict=False)
        if not project_root.exists() or not project_root.is_dir():
            messagebox.showerror("校验失败", "项目目录不存在，或不是一个目录。", parent=self)
            return

        selected_profile = self.profile_values.get(self.profile_var.get())
        if not selected_profile:
            messagebox.showerror("校验失败", "请选择要绑定的配置。", parent=self)
            return

        project_name = self.name_var.get().strip() or project_root.name or "未命名项目"
        self.result = {
            "name": project_name,
            "project_dir": str(project_root),
            "profile_id": selected_profile,
            "run_command": self.run_command_var.get().strip(),
        }
        self.destroy()


class McpConfigDialog(tk.Toplevel):
    def __init__(self, master: tk.Misc, title: str, subtitle: str, initial_text: str = "") -> None:
        super().__init__(master)
        self.title(title)
        self.geometry("760x620")
        self.minsize(680, 520)
        self.configure(bg=PALETTE["app_bg"])
        self.result: str | None = None

        card = tk.Frame(
            self,
            bg=PALETTE["card_bg"],
            highlightbackground=PALETTE["card_border"],
            highlightthickness=1,
            padx=20,
            pady=18,
        )
        card.pack(fill="both", expand=True, padx=18, pady=18)
        card.columnconfigure(0, weight=1)
        card.rowconfigure(1, weight=1)

        tk.Label(card, text=title, bg=PALETTE["card_bg"], fg=PALETTE["text"], font=("Microsoft YaHei UI", 14, "bold")).grid(row=0, column=0, sticky="w")
        tk.Label(card, text=subtitle, bg=PALETTE["card_bg"], fg=PALETTE["muted"], font=("Microsoft YaHei UI", 9), justify="left", wraplength=680).grid(
            row=0,
            column=0,
            sticky="e",
        )

        editor_wrap = tk.Frame(card, bg=PALETTE["card_bg"])
        editor_wrap.grid(row=1, column=0, sticky="nsew", pady=(14, 0))
        editor_wrap.columnconfigure(0, weight=1)
        editor_wrap.rowconfigure(0, weight=1)
        self.text = tk.Text(
            editor_wrap,
            wrap="none",
            relief="solid",
            borderwidth=1,
            highlightthickness=0,
            font=("Consolas", 10),
            bg="#FBFDFE",
            fg=PALETTE["text"],
        )
        self.text.grid(row=0, column=0, sticky="nsew")
        self.text.insert("1.0", initial_text)

        y_scroll = ttk.Scrollbar(editor_wrap, orient="vertical", command=self.text.yview)
        y_scroll.grid(row=0, column=1, sticky="ns")
        x_scroll = ttk.Scrollbar(editor_wrap, orient="horizontal", command=self.text.xview)
        x_scroll.grid(row=1, column=0, sticky="ew")
        self.text.configure(yscrollcommand=y_scroll.set, xscrollcommand=x_scroll.set)

        buttons = ttk.Frame(card)
        buttons.grid(row=2, column=0, sticky="e", pady=(14, 0))
        make_button(buttons, text="取消", variant="secondary", command=self.destroy).grid(row=0, column=0, padx=(0, 8))
        make_button(buttons, text="保存配置", variant="primary", command=self._on_submit).grid(row=0, column=1)

        self.transient(master)
        self.grab_set()

    def _on_submit(self) -> None:
        content = self.text.get("1.0", "end").strip()
        if content:
            try:
                parse_mcp_servers_toml(content)
            except ValueError as exc:
                messagebox.showerror("校验失败", str(exc), parent=self)
                return
        self.result = content
        self.destroy()


class McpServerDialog(tk.Toplevel):
    STANDARD_FIELDS = {"type", "command", "args", "cwd", "env"}

    def __init__(self, master: tk.Misc, server_name: str = "", server_config: dict | None = None) -> None:
        super().__init__(master)
        is_edit = bool(server_name)
        self.title("编辑 MCP 工具" if is_edit else "新增 MCP 工具")
        self.geometry("760x720")
        self.minsize(700, 620)
        self.configure(bg=PALETTE["app_bg"])
        self.result: dict | None = None

        config = dict(server_config or {})
        self.name_var = tk.StringVar(value=server_name)
        self.type_var = tk.StringVar(value=str(config.get("type", "stdio" if not is_edit else "")))
        self.command_var = tk.StringVar(value=str(config.get("command", "")))
        self.cwd_var = tk.StringVar(value=str(config.get("cwd", "")))

        card = tk.Frame(
            self,
            bg=PALETTE["card_bg"],
            highlightbackground=PALETTE["card_border"],
            highlightthickness=1,
            padx=20,
            pady=18,
        )
        card.pack(fill="both", expand=True, padx=18, pady=18)
        card.columnconfigure(1, weight=1)
        card.rowconfigure(4, weight=1)
        card.rowconfigure(6, weight=1)
        card.rowconfigure(7, weight=1)

        tk.Label(card, text=self.title(), bg=PALETTE["card_bg"], fg=PALETTE["text"], font=("Microsoft YaHei UI", 14, "bold")).grid(
            row=0,
            column=0,
            columnspan=2,
            sticky="w",
            pady=(0, 12),
        )
        self._entry_row(card, 1, "名称", self.name_var)
        self._entry_row(card, 2, "type", self.type_var)
        self._entry_row(card, 3, "command", self.command_var)
        self._text_row(card, 4, "args\n每行一个参数", self._format_args(config.get("args")))
        self._entry_row(card, 5, "cwd", self.cwd_var)
        self._text_row(card, 6, "env\nKEY=VALUE", self._format_env(config.get("env")))
        self._text_row(card, 7, "高级字段 TOML", self._format_advanced(config), height=6)

        buttons = ttk.Frame(card)
        buttons.grid(row=8, column=0, columnspan=2, sticky="e", pady=(14, 0))
        make_button(buttons, text="取消", variant="secondary", command=self.destroy).grid(row=0, column=0, padx=(0, 8))
        make_button(buttons, text="保存工具", variant="primary", command=self._on_submit).grid(row=0, column=1)

        self.transient(master)
        self.grab_set()

    def _entry_row(self, parent: tk.Misc, row: int, label: str, variable: tk.StringVar) -> None:
        tk.Label(parent, text=label, bg=PALETTE["card_bg"], fg=PALETTE["muted"], font=("Microsoft YaHei UI", 9)).grid(
            row=row,
            column=0,
            sticky="nw",
            padx=(0, 14),
            pady=6,
        )
        ttk.Entry(parent, textvariable=variable).grid(row=row, column=1, sticky="ew", pady=6)

    def _text_row(self, parent: tk.Misc, row: int, label: str, value: str, height: int = 5) -> None:
        tk.Label(parent, text=label, bg=PALETTE["card_bg"], fg=PALETTE["muted"], font=("Microsoft YaHei UI", 9), justify="left").grid(
            row=row,
            column=0,
            sticky="nw",
            padx=(0, 14),
            pady=6,
        )
        wrap = tk.Frame(parent, bg=PALETTE["card_bg"])
        wrap.grid(row=row, column=1, sticky="nsew", pady=6)
        wrap.columnconfigure(0, weight=1)
        wrap.rowconfigure(0, weight=1)
        text = tk.Text(
            wrap,
            height=height,
            wrap="none",
            relief="solid",
            borderwidth=1,
            highlightthickness=0,
            font=("Consolas", 10),
            bg="#FBFDFE",
            fg=PALETTE["text"],
        )
        text.grid(row=0, column=0, sticky="nsew")
        text.insert("1.0", value)
        scrollbar = ttk.Scrollbar(wrap, orient="vertical", command=text.yview)
        scrollbar.grid(row=0, column=1, sticky="ns")
        text.configure(yscrollcommand=scrollbar.set)
        if row == 4:
            self.args_text = text
        elif row == 6:
            self.env_text = text
        else:
            self.advanced_text = text

    def _format_env(self, env_value) -> str:
        if not isinstance(env_value, dict):
            return ""
        return "\n".join(f"{key}={value}" for key, value in env_value.items())

    def _format_args(self, args_value) -> str:
        if isinstance(args_value, list):
            return "\n".join(str(item) for item in args_value if str(item).strip())
        if isinstance(args_value, str) and args_value.strip():
            return args_value.strip()
        return ""

    def _format_advanced(self, config: dict) -> str:
        advanced = {
            key: value
            for key, value in config.items()
            if key not in self.STANDARD_FIELDS
        }
        try:
            return dumps_toml(advanced).strip() if advanced else ""
        except TypeError:
            return ""

    def _parse_env(self) -> dict[str, str]:
        env: dict[str, str] = {}
        for line in self.env_text.get("1.0", "end").splitlines():
            item = line.strip()
            if not item:
                continue
            if "=" not in item:
                raise ValueError("env 每行必须使用 KEY=VALUE 格式。")
            key, value = item.split("=", 1)
            key = key.strip()
            if not key:
                raise ValueError("env 的 KEY 不能为空。")
            env[key] = value.strip()
        return env

    def _on_submit(self) -> None:
        name = self.name_var.get().strip()
        if not name:
            messagebox.showerror("校验失败", "MCP 名称不能为空。", parent=self)
            return

        advanced_raw = self.advanced_text.get("1.0", "end").strip()
        try:
            server_config = tomllib.loads(advanced_raw) if advanced_raw else {}
            if not isinstance(server_config, dict):
                raise ValueError("高级字段 TOML 必须解析为对象。")
            env = self._parse_env()
        except (tomllib.TOMLDecodeError, ValueError) as exc:
            messagebox.showerror("校验失败", str(exc), parent=self)
            return

        type_value = self.type_var.get().strip()
        command_value = self.command_var.get().strip()
        cwd_value = self.cwd_var.get().strip()
        args = [line.strip() for line in self.args_text.get("1.0", "end").splitlines() if line.strip()]

        for field in self.STANDARD_FIELDS:
            server_config.pop(field, None)
        if type_value:
            server_config["type"] = type_value
        if command_value:
            server_config["command"] = command_value
        if args:
            server_config["args"] = args
        if cwd_value:
            server_config["cwd"] = cwd_value
        if env:
            server_config["env"] = env

        try:
            parse_mcp_servers_toml(render_mcp_servers_toml({name: server_config}))
        except ValueError as exc:
            messagebox.showerror("校验失败", str(exc), parent=self)
            return

        self.result = {"name": name, "config": server_config}
        self.destroy()
