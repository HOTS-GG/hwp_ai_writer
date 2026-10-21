"""템플릿(양식) 탭: 기본·내 양식 목록, 미리보기, 추가·삭제."""
import shutil
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox

from ..system import open_path
from .generate_tab import form_label
from .preview import PreviewPane
from .theme import ACCENT, BG, CARD, FONT, FONT_SM, MUTED, SOFT, TEXT, button, card


class FormsTab:
    def __init__(self, app, parent):
        self.app = app
        pw = tk.PanedWindow(parent, orient="horizontal", bg=BG, sashwidth=6, bd=0)
        pw.pack(fill="both", expand=True, padx=12, pady=12)
        left, right = tk.Frame(pw, bg=BG), tk.Frame(pw, bg=BG)
        pw.add(left, minsize=280, width=320, stretch="never")
        pw.add(right, minsize=480, stretch="always")

        c = card(left, "양식 목록")
        c.pack(fill="both", expand=True)
        self._list = tk.Listbox(c, bg=CARD, fg=TEXT, relief="flat", font=FONT, selectbackground=SOFT,
                                selectforeground=ACCENT, activestyle="none", highlightthickness=0, bd=0)
        self._list.pack(fill="both", expand=True, padx=8, pady=(0, 8))
        self._list.bind("<<ListboxSelect>>", lambda e: self._on_select())
        self._list.bind("<Double-Button-1>", lambda e: self._use())
        self._info = tk.StringVar(value="")
        tk.Label(c, textvariable=self._info, bg=CARD, fg=MUTED, font=FONT_SM, justify="left",
                 wraplength=280).pack(anchor="w", padx=14, pady=(0, 10))

        btns = tk.Frame(left, bg=BG)
        btns.pack(fill="x", pady=(10, 0))
        button(btns, "이 양식으로 작성", self._use, "primary").pack(fill="x")
        row = tk.Frame(btns, bg=BG)
        row.pack(fill="x", pady=(6, 0))
        button(row, "양식 추가…", self._add).pack(side="left", fill="x", expand=True)
        button(row, "삭제", self._delete, "danger").pack(side="left", padx=(6, 0))
        button(btns, "내 양식 폴더 열기", self._open_dir).pack(fill="x", pady=(6, 0))
        tk.Label(btns, text="HWPX·HWP·PDF 양식을 추가할 수 있습니다.\n○○○○ 같은 빈칸이 있으면 그 자리만 채웁니다.",
                 bg=BG, fg=MUTED, font=FONT_SM, justify="left").pack(anchor="w", pady=(8, 0))

        self.preview = PreviewPane(right, "미리보기", app.s.get("preview_zoom", 100))
        self.preview.pack(fill="both", expand=True)
        app.register_pane(self.preview)
        app.on_forms_change(self.refresh)

    def refresh(self):
        self._list.delete(0, "end")
        for f in self.app.forms:
            self._list.insert("end", "  " + form_label(f))

    def _selected(self):
        sel = self._list.curselection()
        return self.app.forms[sel[0]] if sel else None

    def _on_select(self):
        f = self._selected()
        if not f:
            return
        self.preview.set_title(f"미리보기 — {f['name']}")
        self._info.set("기본 제공 양식" if f["builtin"] else f"내 양식 · {Path(f['path']).name}")
        self.app.preview_file(self.preview, f["path"])

    def _use(self):
        f = self._selected()
        if not f:
            return
        self.app.gen.select_form(f)
        self.app.nb.select(self.app.tab_gen)

    def _add(self):
        paths = filedialog.askopenfilenames(title="양식 추가",
                                            filetypes=[("양식", "*.hwpx *.hwp *.pdf"), ("모든 파일", "*.*")])
        if not paths:
            return
        udir = Path(self.app.s["user_forms_dir"])
        udir.mkdir(parents=True, exist_ok=True)
        for p in paths:
            if p.lower().endswith(".hwp"):
                self.app.convert_hwp(p, lambda out: self.app.reload_forms(), udir)
            else:
                shutil.copy(p, udir / Path(p).name)
        self.app.reload_forms()
        self.app.status(f"양식 {len(paths)}개 추가됨")

    def _delete(self):
        f = self._selected()
        if not f:
            return
        if f["builtin"]:
            messagebox.showinfo("삭제 불가", "기본 제공 양식은 삭제할 수 없습니다.")
            return
        if messagebox.askyesno("양식 삭제", f"'{f['name']}' 양식을 내 양식 폴더에서 삭제할까요?"):
            Path(f["path"]).unlink(missing_ok=True)
            self.app.reload_forms()
            self.preview.show_message("미리볼 양식을 선택하세요.")

    def _open_dir(self):
        d = Path(self.app.s["user_forms_dir"])
        d.mkdir(parents=True, exist_ok=True)
        open_path(str(d))
