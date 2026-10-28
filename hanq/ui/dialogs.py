"""버튼 이름을 정할 수 있는 확인 창 ([예]/[아니요] 대신 '저장하고 닫기'처럼 하는 일을 그대로 쓴다)."""
import tkinter as tk

from .theme import BG, CARD, FONT, FONT_H, MUTED, TEXT, button


def ask_choice(parent, title: str, message: str, options: list[tuple[str, str, str]], detail: str = "") -> str | None:
    """options = [(돌려줄 값, 버튼 글, 'primary'|'normal'|'danger'), …]. 창을 닫으면 None."""
    win = tk.Toplevel(parent)
    win.title(title)
    win.configure(bg=BG)
    win.resizable(False, False)
    win.transient(parent)
    result = {"value": None}

    box = tk.Frame(win, bg=CARD, highlightthickness=1, highlightbackground="#d0d7e2")
    box.pack(fill="both", expand=True, padx=14, pady=14)
    tk.Label(box, text=message, bg=CARD, fg=TEXT, font=FONT_H, justify="left", wraplength=440
             ).pack(anchor="w", padx=18, pady=(16, 4))
    if detail:
        tk.Label(box, text=detail, bg=CARD, fg=MUTED, font=FONT, justify="left", wraplength=440
                 ).pack(anchor="w", padx=18)
    row = tk.Frame(box, bg=CARD)
    row.pack(fill="x", padx=18, pady=(16, 16))

    def pick(v):
        result["value"] = v
        win.destroy()

    for value, text, kind in reversed(options):
        button(row, text, lambda v=value: pick(v), kind).pack(side="right", padx=(6, 0))

    win.update_idletasks()
    x = parent.winfo_rootx() + (parent.winfo_width() - win.winfo_width()) // 2
    y = parent.winfo_rooty() + (parent.winfo_height() - win.winfo_height()) // 3
    win.geometry(f"+{max(x, 0)}+{max(y, 0)}")
    win.bind("<Escape>", lambda e: win.destroy())
    win.grab_set()
    win.focus_set()
    parent.wait_window(win)
    return result["value"]
