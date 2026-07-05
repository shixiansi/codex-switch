from __future__ import annotations

from dataclasses import dataclass
import tkinter as tk
from typing import Any

from codex_switch.models import SkillGroup
from codex_switch.ui.styles import PALETTE, make_button, ttk
from codex_switch.ui.windowing import install_windows_drag_redraw_guard


@dataclass(frozen=True)
class ChoiceDialogShell:
    dialog: tk.Toplevel
    selected_var: tk.StringVar
    combo: ttk.Combobox
    actions: tk.Frame


@dataclass(frozen=True)
class SkillGroupDialogShell:
    dialog: tk.Toplevel
    name_var: tk.StringVar
    description_var: tk.StringVar
    cards_frame: tk.Frame
    footer: tk.Frame


def build_choice_dialog_shell(
    app: Any,
    *,
    title: str,
    heading: str,
    labels: list[str],
    width: int,
) -> ChoiceDialogShell:
    dialog = tk.Toplevel(app.root)
    install_windows_drag_redraw_guard(dialog)
    dialog.title(title)
    dialog.transient(app.root)
    dialog.grab_set()
    dialog.configure(bg=PALETTE["card_bg"])
    dialog.resizable(False, False)
    dialog.columnconfigure(0, weight=1)
    tk.Label(
        dialog,
        text=heading,
        bg=PALETTE["card_bg"],
        fg=PALETTE["text"],
        font=app.section_font,
    ).grid(row=0, column=0, sticky="w", padx=16, pady=(14, 8))
    selected_var = tk.StringVar(value=labels[0])
    combo = ttk.Combobox(dialog, textvariable=selected_var, values=labels, state="readonly", width=width)
    combo.grid(row=1, column=0, sticky="ew", padx=16)
    actions = tk.Frame(dialog, bg=PALETTE["card_bg"])
    actions.grid(row=2, column=0, sticky="e", padx=16, pady=16)
    return ChoiceDialogShell(
        dialog=dialog,
        selected_var=selected_var,
        combo=combo,
        actions=actions,
    )


def build_skill_group_dialog_shell(app: Any, group: SkillGroup) -> SkillGroupDialogShell:
    dialog = tk.Toplevel(app.root)
    install_windows_drag_redraw_guard(dialog)
    dialog.title(f"编辑 Skills 组 - {group.name}")
    dialog.transient(app.root)
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
    tk.Label(form, text="组名", bg=PALETTE["card_bg"], fg=PALETTE["muted"], font=app.small_font).grid(row=0, column=0, sticky="w", padx=(0, 8))
    ttk.Entry(form, textvariable=name_var).grid(row=0, column=1, sticky="ew")
    tk.Label(form, text="描述", bg=PALETTE["card_bg"], fg=PALETTE["muted"], font=app.small_font).grid(row=1, column=0, sticky="w", padx=(0, 8), pady=(8, 0))
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
    canvas.bind("<Configure>", lambda event: app._layout_skill_group_dialog_cards(cards_frame, event.width, window_id, canvas))
    app._render_skill_group_dialog_cards(group, cards_frame)

    actions = tk.Frame(dialog, bg=PALETTE["card_bg"])
    actions.grid(row=1, column=0, sticky="ew", padx=16, pady=(0, 8))
    for column in range(5):
        actions.columnconfigure(column, weight=1)
    make_button(actions, text="新增 Skill", variant="primary", command=lambda: (app.add_skill_to_group(group), app._render_skill_group_dialog_cards(group, cards_frame))).grid(row=0, column=0, sticky="ew", padx=(0, 8))
    make_button(actions, text="安装 GitHub Skills", variant="secondary", command=lambda: (app.install_skill_repo_to_specific_group(group), app._render_skill_group_dialog_cards(group, cards_frame))).grid(row=0, column=1, sticky="ew", padx=(0, 8))
    make_button(actions, text="导入本地文件", variant="secondary", command=lambda: (app.import_local_skill_file_to_group(group), app._render_skill_group_dialog_cards(group, cards_frame))).grid(row=0, column=2, sticky="ew", padx=(0, 8))
    make_button(actions, text="导入扫描Skills", variant="secondary", command=lambda: (app.import_scanned_skills_to_group(group), app._render_skill_group_dialog_cards(group, cards_frame))).grid(row=0, column=3, sticky="ew", padx=(0, 8))
    make_button(actions, text="刷新", variant="secondary", command=lambda: app._render_skill_group_dialog_cards(group, cards_frame)).grid(row=0, column=4, sticky="ew")

    footer = tk.Frame(dialog, bg=PALETTE["card_bg"])
    footer.grid(row=3, column=0, sticky="e", padx=16, pady=16)
    return SkillGroupDialogShell(
        dialog=dialog,
        name_var=name_var,
        description_var=description_var,
        cards_frame=cards_frame,
        footer=footer,
    )
