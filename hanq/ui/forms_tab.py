"""템플릿(양식) 탭: 기본·내 양식 목록, 미리보기(AI가 채울 곳 형광펜 표시), 추가·삭제."""
import shutil
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox

from ..config import CACHE_DIR
from ..doc.annotate import COLORS
from ..system import open_path
from .generate_tab import form_label
from .preview import PreviewPane
from .theme import ACCENT, BG, CARD, FONT, FONT_SM, MUTED, SOFT, TEXT, button, card

LEGEND = (("fill", "AI가 채울 빈칸"), ("example", "AI가 주제에 맞게 고칠 수 있는 예시 문장"),
          ("table", "AI가 행 수까지 맞춰 채우는 표"), (None, "색 없음: 그대로 남는 부분"))


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
        self._info = tk.StringVar(value="양식을 고르면 AI가 어디를 채우는지 색으로 보여 줍니다.")
        tk.Label(c, textvariable=self._info, bg=CARD, fg=TEXT, font=FONT_SM, justify="left",
                 wraplength=280).pack(anchor="w", padx=14, pady=(0, 6))
        self._legend = tk.Frame(c, bg=CARD)
        for key, text in LEGEND:
            r = tk.Frame(self._legend, bg=CARD)
            r.pack(anchor="w", pady=1)
            tk.Label(r, text="  ", bg=COLORS[key] if key else CARD, width=2,
                     highlightthickness=1, highlightbackground="#d0d7e2").pack(side="left")
            tk.Label(r, text=text, bg=CARD, fg=MUTED, font=FONT_SM).pack(side="left", padx=6)
        self._legend.pack(anchor="w", padx=14, pady=(0, 10))

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
        self._hl_btn = button(self.preview.actions, "", self._toggle_highlight)
        self._hl_btn.pack(side="left")
        self._update_hl_button()
        app.register_pane(self.preview)
        app.on_forms_change(self.refresh)
        self._req = 0

    def refresh(self):
        self._list.delete(0, "end")
        for f in self.app.forms:
            self._list.insert("end", "  " + form_label(f))

    def _selected(self):
        sel = self._list.curselection()
        return self.app.forms[sel[0]] if sel else None

    # ── AI가 채울 곳 표시 ──
    def _highlight_on(self) -> bool:
        return bool(self.app.s.get("form_highlight", True))

    def _update_hl_button(self):
        self._hl_btn.configure(text="🖍 AI가 채울 곳 보기: 켜짐" if self._highlight_on() else "🖍 AI가 채울 곳 보기: 꺼짐")

    def _toggle_highlight(self):
        self.app.set("form_highlight", not self._highlight_on())
        self._update_hl_button()
        self._on_select()

    def _on_select(self):
        f = self._selected()
        if not f:
            return
        self.preview.set_title(f"미리보기 — {f['name']}")
        where = "기본 제공 양식" if f["builtin"] else f"내 양식 · {Path(f['path']).name}"
        if f["kind"] == "pdf":
            self._info.set(f"{where}\n\nPDF 양식은 글자만 읽어, 장·항목 순서를 그대로 따라 "
                           "학교 기본 서식으로 새 문서를 만듭니다. (색 표시는 HWPX 양식만)")
            self.app.preview_file(self.preview, f["path"], original=True)
            return
        self._info.set(f"{where}\n\n분석하는 중…")
        self._req += 1
        req, hl = self._req, self._highlight_on()
        if not hl:
            self.app.preview_file(self.preview, f["path"], original=True)

        def run():
            from ..doc.annotate import annotate
            try:
                data, summary = annotate(f["path"])
            except Exception as e:
                msg = f"양식을 분석하지 못했습니다: {e}"
                self.app.after(0, lambda: req == self._req and self._info.set(f"{where}\n\n{msg}"))
                return
            out = None
            if hl:
                CACHE_DIR.mkdir(parents=True, exist_ok=True)
                out = CACHE_DIR / f"highlight_{Path(f['path']).stem}.hwpx"
                out.write_bytes(data)
            self.app.after(0, self._show_analysis, req, where, summary, out)
        threading.Thread(target=run, daemon=True).start()

    def _show_analysis(self, req, where, summary, out):
        if req != self._req:
            return   # 그 사이 다른 양식을 골랐다
        self._info.set(f"{where}\n\n{summary.describe()}")
        if getattr(self, "_announce", None):
            self._announce = None
            if summary.fill_lines == 0 and summary.tables == 0:
                messagebox.showinfo("채울 곳을 찾지 못했습니다",
                                    "이 양식에서 AI가 채울 빈칸을 찾지 못했습니다.\n\n"
                                    "한글에서 양식을 열어 내용이 들어갈 자리에 ○○○○를 적고 저장한 뒤 다시 추가하면,\n"
                                    "그 자리만 채우고 나머지 서식은 그대로 둡니다.")
        if out is not None:
            self.app.preview_file(self.preview, str(out), note="AI가 채울 곳을 색으로 표시함 (실제 문서에는 색이 없음)")

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
        last = None
        for p in paths:
            if p.lower().endswith(".hwp"):
                self.app.convert_hwp(p, lambda out: (self.app.reload_forms(), self.select_path(out, announce=True)),
                                     udir)
            else:
                last = udir / Path(p).name
                shutil.copy(p, last)
        self.app.reload_forms()
        self.app.status(f"양식 {len(paths)}개 추가됨")
        if last is not None:
            self.select_path(str(last), announce=True)

    def select_path(self, path: str, announce: bool = False):
        """목록에서 그 양식을 골라 분석·미리보기를 띄운다. announce면 채울 곳이 없을 때 안내한다."""
        for i, f in enumerate(self.app.forms):
            if Path(f["path"]) == Path(path):
                self._list.selection_clear(0, "end")
                self._list.selection_set(i)
                self._list.see(i)
                self._announce = path if announce else None
                self._on_select()
                return

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
