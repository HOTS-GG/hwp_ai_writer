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
        self._tpl_btn = button(btns, "완성 문서를 양식으로…", self._templatize_selected)
        self._tpl_btn.pack(fill="x", pady=(6, 0))
        button(btns, "내 양식 폴더 열기", self._open_dir).pack(fill="x", pady=(6, 0))
        tk.Label(btns, text="HWPX·HWP·PDF 양식을 추가할 수 있습니다.\n○○○○ 같은 빈칸이 있으면 그 자리만 채웁니다.\n"
                            "작년 계획서 같은 완성 문서는 [완성 문서를 양식으로…]로\n바뀌는 부분만 빈칸으로 만들 수 있습니다.",
                 bg=BG, fg=MUTED, font=FONT_SM, justify="left").pack(anchor="w", pady=(8, 0))
        app.on_busy_change(lambda busy: self._tpl_btn.configure(state="disabled" if busy else "normal"))

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
        announced = getattr(self, "_announce", None)
        if announced:
            self._announce = None
            if summary.fill_lines == 0 and summary.tables == 0:
                messagebox.showinfo("채울 곳을 찾지 못했습니다",
                                    "이 양식에서 AI가 채울 빈칸을 찾지 못했습니다.\n\n"
                                    "한글에서 양식을 열어 내용이 들어갈 자리에 ○○○○를 적고 저장한 뒤 다시 추가하면,\n"
                                    "그 자리만 채우고 나머지 서식은 그대로 둡니다.")
            elif not summary.has_placeholders and messagebox.askyesno(
                    "완성 문서입니다",
                    "이 문서에는 ○○○○ 같은 빈칸이 없습니다.\n\n"
                    "AI가 날짜·장소·인원·내용처럼 해마다 바뀌는 부분만 빈칸으로 바꾼 '양식'으로 만들까요?\n"
                    "(서식과 제목·항목명은 그대로 둡니다. 저장하기 전에 결과를 보여 드립니다.)\n\n"
                    "[아니요]를 누르면 지금 문서를 그대로 양식으로 씁니다 (매번 모든 문장을 새로 씀)."):
                self.after_idle_templatize(announced)
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
        bad = [Path(p).name for p in paths if Path(p).suffix.lower() not in (".hwpx", ".hwp", ".pdf")]
        paths = [p for p in paths if Path(p).suffix.lower() in (".hwpx", ".hwp", ".pdf")]
        if bad:
            messagebox.showwarning(
                "양식으로 쓸 수 없는 파일",
                "양식은 한글 파일(HWPX·HWP)과 PDF만 쓸 수 있습니다. 아래 파일은 추가하지 않았습니다.\n\n"
                + "\n".join(f"• {n}" for n in bad[:10])
                + "\n\nWord·엑셀 문서는 한글에서 열어 [다른 이름으로 저장 → HWPX]로 바꾼 뒤 추가해 주세요.")
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

    # ── 완성 문서 → 빈칸 양식 ──
    def after_idle_templatize(self, path: str):
        self.app.after(100, lambda: self._templatize(path))

    def _templatize_selected(self):
        f = self._selected()
        if not f:
            messagebox.showinfo("양식 고르기", "왼쪽 목록에서 양식으로 만들 완성 문서를 고르세요.\n"
                                           "(목록에 없으면 먼저 [양식 추가…]로 넣으세요)")
            return
        if f["kind"] != "hwpx":
            messagebox.showinfo("HWPX만 가능", "PDF는 빈칸 양식으로 바꿀 수 없습니다. 한글 파일(HWPX·HWP)을 넣어 주세요.")
            return
        self._templatize(f["path"])

    def _templatize(self, path: str):
        ai = self.app.ai_config()
        if not self.app.check_ai(ai):
            return
        src = Path(path)
        udir = Path(self.app.s["user_forms_dir"])
        udir.mkdir(parents=True, exist_ok=True)
        stem = src.stem[:-3] if src.stem.endswith("_양식") else src.stem
        target = udir / f"{stem}_양식.hwpx"
        i = 2
        while target.exists():
            target = udir / f"{stem}_양식 ({i}).hwpx"
            i += 1
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        tmp = CACHE_DIR / f"templatize_{src.stem}.hwpx"
        tmp.unlink(missing_ok=True)
        self.preview.set_title(f"양식으로 만드는 중 — {src.name}")
        self._info.set(f"{src.name}\n\nAI가 해마다 바뀌는 부분을 찾아 ○○○○로 바꾸고 있습니다…")

        def work(job):
            from ..services import templatize
            return templatize(job, str(src), str(tmp), ai)

        def done(res):
            if not res.changed or not tmp.exists():
                self._info.set(f"{src.name}\n\n바꿀 부분을 찾지 못했습니다. {res.reply}")
                messagebox.showinfo("양식으로 만들지 못했습니다", "AI가 빈칸으로 바꿀 부분을 찾지 못했습니다.\n" + res.reply)
                return
            self._req += 1
            self._show_analysis_then_ask(src, tmp, target, res)

        def failed(msg, cancelled):
            self._info.set(f"{src.name}\n\n{'중단했습니다.' if cancelled else '실패: ' + msg[:200]}")
            if not cancelled:
                from .errors import show_ai_error
                show_ai_error(self.app, "양식으로 만들지 못했습니다", msg)

        self.app.run_job(work, done, failed, pane=self.preview)

    def _show_analysis_then_ask(self, src: Path, tmp: Path, target: Path, res):
        """만든 양식을 형광펜으로 보여 준 뒤, 저장할지 묻는다."""
        from ..doc.annotate import annotate
        try:
            data, summary = annotate(str(tmp))
            view = CACHE_DIR / f"highlight_{tmp.stem}.hwpx"
            view.write_bytes(data)
        except Exception:
            summary, view = None, tmp
        self.preview.set_title(f"새 양식 미리보기 — {target.name}")
        self.app.preview_file(self.preview, str(view), note="노랑 = 이번에 빈칸으로 바꾼 곳 (저장 전 확인)")
        desc = summary.describe() if summary else ""
        self._info.set(f"새 양식 (아직 저장 안 함)\n{res.reply}\n\n{desc}")
        self.app.after(1200, lambda: self._ask_save(tmp, target, summary))

    def _ask_save(self, tmp: Path, target: Path, summary):
        blanks = summary.fill_lines if summary else 0
        if messagebox.askyesno("양식 저장", f"빈칸 {blanks}곳이 있는 양식을 만들었습니다.\n"
                                           f"미리보기를 확인하고, '{target.name}'(으)로 내 양식에 저장할까요?"):
            shutil.copyfile(tmp, target)
            self.app.reload_forms()
            self.select_path(str(target))
            self.app.status(f"새 양식 저장: {target.name}")
        else:
            self.app.status("새 양식을 저장하지 않았습니다.")
            self._on_select()

    def _open_dir(self):
        d = Path(self.app.s["user_forms_dir"])
        d.mkdir(parents=True, exist_ok=True)
        open_path(str(d))
