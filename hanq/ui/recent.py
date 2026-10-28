"""최근 작업: 지난 작업 기록을 골라 다시 열거나 지운다."""
import tkinter as tk
from tkinter import messagebox

from .theme import ACCENT, BG, BORDER, CARD, FONT, FONT_H, FONT_SM, MUTED, SOFT, TEXT, button


class RecentDialog(tk.Toplevel):
    def __init__(self, app):
        super().__init__(app)
        self.app = app
        self.title("최근 작업")
        self.configure(bg=BG)
        self.geometry("620x460")
        self.transient(app)

        box = tk.Frame(self, bg=CARD, highlightthickness=1, highlightbackground=BORDER)
        box.pack(fill="both", expand=True, padx=14, pady=14)
        tk.Label(box, text="최근 작업", bg=CARD, fg=TEXT, font=FONT_H).pack(anchor="w", padx=16, pady=(14, 2))
        keep = int(app.s.get("session_keep_days", 7))
        tk.Label(box, text=f"만든 문서와 수정 대화가 {keep}일 동안 보관됩니다. 골라서 [열기]를 누르면 이어서 고칠 수 있습니다.",
                 bg=CARD, fg=MUTED, font=FONT_SM).pack(anchor="w", padx=16)

        row = tk.Frame(box, bg=CARD)
        row.pack(side="bottom", fill="x", padx=16, pady=(8, 14))
        button(row, "열기", self._open, "primary").pack(side="right")
        button(row, "닫기", self.destroy).pack(side="right", padx=(0, 6))
        button(row, "삭제", self._delete, "danger").pack(side="left")

        self._list = tk.Listbox(box, bg=CARD, fg=TEXT, relief="flat", font=FONT, selectbackground=SOFT,
                                selectforeground=ACCENT, activestyle="none", highlightthickness=1,
                                highlightbackground=BORDER)
        self._list.pack(fill="both", expand=True, padx=16, pady=(10, 0))
        self._list.bind("<Double-Button-1>", lambda e: self._open())
        self._load()

        self.update_idletasks()
        x = app.winfo_rootx() + (app.winfo_width() - self.winfo_width()) // 2
        y = app.winfo_rooty() + (app.winfo_height() - self.winfo_height()) // 3
        self.geometry(f"+{max(x, 0)}+{max(y, 0)}")
        self.grab_set()

    def _load(self):
        self._items = self.app.sessions.list()
        self._list.delete(0, "end")
        for s in self._items:
            mark = "  ● " if self.app.session is not None and s.id == self.app.session.id else "    "
            self._list.insert("end", mark + s.describe())
        if self._items:
            self._list.selection_set(0)
        else:
            self._list.insert("end", "    아직 작업 기록이 없습니다.")

    def _selected(self):
        sel = self._list.curselection()
        return self._items[sel[0]] if sel and sel[0] < len(self._items) else None

    def _open(self):
        s = self._selected()
        if s is None:
            return
        self.destroy()
        self.app.open_session(s)

    def _delete(self):
        s = self._selected()
        if s is None:
            return
        if self.app.session is not None and s.id == self.app.session.id:
            messagebox.showinfo("지금 열린 작업", "지금 열려 있는 작업은 지울 수 없습니다.", parent=self)
            return
        if messagebox.askyesno("작업 기록 삭제", f"'{s.title}' 작업 기록을 지울까요?\n"
                                              "(저장 폴더에 따로 저장한 문서는 지워지지 않습니다)", parent=self):
            self.app.sessions.delete(s.id)
            self._load()
