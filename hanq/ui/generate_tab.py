"""문서 생성 탭: 왼쪽(양식·요청·참고 자료·생성), 가운데(미리보기), 오른쪽(AI 수정 대화)."""
import datetime
import re
import shutil
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, scrolledtext, ttk

from ..config import CACHE_DIR
from ..readers import FILE_TYPES as REF_TYPES
from ..system import font, open_path
from .chat import ChatPanel
from .preview import PreviewPane
from .theme import (BG, BORDER, CARD, FONT, FONT_SM, INPUT_BG, MUTED, SOFT, TEXT, ACCENT, button, card,
                    display_name, restyle, safe_filename)

FREE_FORM = "자유 작성 (기본 서식)"
EXAMPLE_REQUEST = ("예) 2025. 5. 23.(금) 본교 체육관에서 1학년 120명 대상 과학 탐구 축전을 운영함. "
                   "부스 6개, 예산 80만 원(재료비), 담당 과학정보부.")


def form_label(f: dict) -> str:
    tag = "기본" if f["builtin"] else ("PDF" if f["kind"] == "pdf" else "내 양식")
    return f"[{tag}] {f['name']}"


class GenerateTab:
    def __init__(self, app, parent):
        self.app = app
        self.refs: list[str] = []
        self.extra_forms: list[dict] = []

        pw = tk.PanedWindow(parent, orient="horizontal", bg=BG, sashwidth=6, bd=0)
        pw.pack(fill="both", expand=True, padx=12, pady=12)
        left, mid, right = tk.Frame(pw, bg=BG), tk.Frame(pw, bg=BG), tk.Frame(pw, bg=BG)
        # 창을 키우면 미리보기만 넓어지고 양옆 패널은 그대로 둔다
        pw.add(left, minsize=320, width=360, stretch="never")
        pw.add(mid, minsize=420, stretch="always")
        pw.add(right, minsize=280, width=330, stretch="never")

        self._build_left(left)
        self.preview = PreviewPane(mid, "생성 결과", app.s.get("preview_zoom", 100))
        self.preview.pack(fill="both", expand=True)
        app.register_pane(self.preview)
        a = self.preview.actions
        self._btn_save = button(a, "다른 이름으로 저장…", self._save_as)
        self._btn_open = button(a, "한글로 열기", self._open_result, "primary")
        self._btn_folder = button(a, "폴더 열기", self._open_folder)
        for b in (self._btn_folder, self._btn_save, self._btn_open):
            b.pack(side="left", padx=(6, 0))
            b.configure(state="disabled")
        self.preview.show_message("왼쪽에서 양식을 고르고 [문서 생성]을 누르세요.")
        self.chat = ChatPanel(app, right, self)

        app.on_busy_change(self._on_busy)
        app.on_forms_change(self.refresh_forms)

    # ── 왼쪽 ────────────────────────────────────────────────────────────
    def _build_left(self, left):
        c1 = card(left, "1. 양식")
        c1.pack(fill="x")
        row = tk.Frame(c1, bg=CARD)
        row.pack(fill="x", padx=14)
        self._form_var = tk.StringVar()
        self._form_combo = ttk.Combobox(row, textvariable=self._form_var, state="readonly", font=FONT)
        self._form_combo.pack(side="left", fill="x", expand=True)
        self._form_combo.bind("<<ComboboxSelected>>", lambda e: self._on_form_change())
        button(row, "파일 열기…", self._open_form_file).pack(side="left", padx=(6, 0))
        self._form_info = tk.StringVar(value="")
        tk.Label(c1, textvariable=self._form_info, bg=CARD, fg=MUTED, font=FONT_SM,
                 justify="left", wraplength=330).pack(anchor="w", padx=14, pady=(4, 10))

        # 버튼과 참고 자료를 아래에 먼저 고정해야, 창이 작아질 때 요청 입력칸만 줄어든다
        self._gen_btn = button(left, "문서 생성", self._on_generate, "primary")
        self._gen_btn.configure(pady=10, font=font(11, "bold"))
        self._gen_btn.pack(side="bottom", fill="x", pady=(12, 0))
        c3 = card(left, "3. 참고 자료 (선택)")
        c3.pack(side="bottom", fill="x", pady=(10, 0))

        c2 = card(left, "2. 작성 요청")
        c2.pack(fill="both", expand=True, pady=(10, 0))
        tk.Label(c2, text="무엇을 쓸지 자유롭게 적어주세요. 날짜·장소·인원·예산 등 사실 정보가 많을수록 정확합니다.",
                 bg=CARD, fg=MUTED, font=FONT_SM, wraplength=330, justify="left").pack(anchor="w", padx=14)
        self._request = scrolledtext.ScrolledText(
            c2, height=3, bg=INPUT_BG, fg=TEXT, insertbackground=TEXT, relief="flat", font=FONT, wrap="word",
            highlightthickness=1, highlightbackground=BORDER, highlightcolor=ACCENT, padx=8, pady=6)
        self._request.pack(fill="both", expand=True, padx=14, pady=(6, 12))
        self._request.insert("1.0", EXAMPLE_REQUEST)

        tk.Label(c3, text="공문, 지난 계획서, 안내문 등 (HWP·HWPX·PDF·DOCX·TXT)\n[보기]·두 번 누르기: 문서 모양 / [보낼 글]: AI에게 보내는 글",
                 bg=CARD, fg=MUTED, font=FONT_SM, justify="left").pack(anchor="w", padx=14)
        self._ref_list = tk.Listbox(c3, height=3, bg=INPUT_BG, fg=TEXT, relief="flat", font=FONT_SM,
                                    highlightthickness=1, highlightbackground=BORDER,
                                    selectbackground=SOFT, selectforeground=TEXT, activestyle="none")
        self._ref_list.pack(fill="x", padx=14, pady=(6, 6))
        self._ref_list.bind("<Double-Button-1>", lambda e: self._show_ref_doc())
        rrow = tk.Frame(c3, bg=CARD)
        rrow.pack(fill="x", padx=14, pady=(0, 12))
        # 좁은 창에서도 다 보이게 짧은 이름으로 (자세한 뜻은 위 안내 글에)
        for text, cmd in (("추가…", self._add_ref), ("보기", self._show_ref_doc),
                          ("보낼 글", self._show_ref), ("제거", self._remove_ref)):
            button(rrow, text, cmd, padx=8).pack(side="left", padx=(0, 4))

    # ── 양식 ────────────────────────────────────────────────────────────
    def _all_forms(self):
        return self.app.forms + self.extra_forms

    def refresh_forms(self):
        labels = [FREE_FORM] + [form_label(f) for f in self._all_forms()]
        cur = self._form_var.get()
        self._form_combo["values"] = labels
        self._form_var.set(cur if cur in labels else (labels[1] if len(labels) > 1 else FREE_FORM))
        self._on_form_change()

    def select_form(self, f: dict):
        self._form_var.set(form_label(f))
        self._on_form_change()

    def selected_form(self):
        label = self._form_var.get()
        return next((f for f in self._all_forms() if form_label(f) == label), None)

    def _on_form_change(self):
        f = self.selected_form()
        if f is None:
            self._form_info.set("양식 없이 요청 내용으로 문서를 구성합니다.\n"
                                f"서식은 설정의 기본 서식({display_name(Path(self.app.base_style_path()))})을 사용합니다.")
            return
        if f["kind"] == "pdf":
            self._form_info.set("PDF 양식: 항목 구성을 읽어 같은 순서로 내용을 쓰고, 학교 기본 서식으로 .hwpx를 만듭니다.")
            return
        self._form_info.set("양식 분석 중…")

        def run():
            try:
                from ..services import describe_form
                msg = describe_form(f["path"])
            except Exception as e:
                msg = f"양식을 읽을 수 없습니다: {e}"
            self.app.after(0, lambda: self._form_info.set(msg))
        threading.Thread(target=run, daemon=True).start()

    def _open_form_file(self):
        path = filedialog.askopenfilename(title="양식 파일 선택",
                                          filetypes=[("양식", "*.hwpx *.pdf *.hwp"), ("모든 파일", "*.*")])
        if not path:
            return
        if path.lower().endswith(".hwp"):
            self.app.convert_hwp(path, self._use_extra_form)
            return
        self._use_extra_form(path)

    def _use_extra_form(self, path):
        p = Path(path)
        f = {"path": str(p), "name": p.stem, "builtin": False, "kind": p.suffix.lower()[1:]}
        self.extra_forms = [x for x in self.extra_forms if x["path"] != f["path"]] + [f]
        self.refresh_forms()
        self.select_form(f)

    # ── 참고 자료 ───────────────────────────────────────────────────────
    def _add_ref(self):
        for p in filedialog.askopenfilenames(title="참고 자료 선택", filetypes=REF_TYPES):
            if p not in self.refs:
                self.refs.append(p)
                self._ref_list.insert("end", Path(p).name)

    def _remove_ref(self):
        for i in reversed(self._ref_list.curselection()):
            self._ref_list.delete(i)
            del self.refs[i]

    def _show_ref_doc(self):
        """참고 자료를 문서 모양 그대로 미리 본다 (HWPX는 바로, HWP는 한글로, 그 밖은 글로)."""
        sel = self._ref_list.curselection()
        if not sel:
            return
        path = self.refs[sel[0]]
        if not path.lower().endswith((".hwpx", ".hwp", ".pdf")):
            self._show_ref()
            return
        self.preview.set_title(f"참고 자료 — {Path(path).name}")
        self.app.preview_file(self.preview, path)

    def _show_ref(self):
        """AI에게 실제로 보내는 글(표는 '| 칸 |' 줄)을 보여준다."""
        sel = self._ref_list.curselection()
        if not sel:
            return
        path = self.refs[sel[0]]
        self.preview.token = None
        self.preview.set_title(f"참고 자료 — {Path(path).name}")
        self.preview.show_message("읽는 중…")

        def run():
            from ..readers import read_reference
            try:
                text = read_reference(path).strip() or "(글자가 없습니다)"
                note = f"AI에게 보내는 내용 · {len(text):,}자"
            except Exception as e:
                text, note = f"읽을 수 없습니다: {e}", ""
            self.app.after(0, lambda: self.preview.show_text(text[:30000], note))
        threading.Thread(target=run, daemon=True).start()

    # ── 생성 ────────────────────────────────────────────────────────────
    def _on_busy(self, busy: bool):
        if busy:
            self._gen_btn.configure(text="■ 중단", command=self.app.stop_job)
            restyle(self._gen_btn, "stop")
        else:
            self._gen_btn.configure(text="문서 생성", command=self._on_generate)
            restyle(self._gen_btn, "primary")

    def _on_generate(self):
        app = self.app
        if app.busy:
            return
        ai = app.ai_config()
        if not app.check_ai(ai):
            return
        form = self.selected_form()
        request = self._request.get("1.0", "end").strip()
        if request == EXAMPLE_REQUEST:
            request = ""
        refs = list(self.refs)
        info = {k: app.s.get(k, "") for k in ("school_name", "department", "author")}
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        out = str(CACHE_DIR / f"result_{datetime.datetime.now():%Y%m%d_%H%M%S}.hwpx")
        base = app.base_style_path()
        self.preview.set_title("생성 중…")
        self.preview.show_message("AI가 문서를 작성하고 있습니다…")

        def work(job):
            from ..services import build_document, fill_form
            if form is None:
                return build_document(job, base, out, request, refs, info, ai)
            if form["kind"] == "pdf":
                return build_document(job, base, out, request, refs, info, ai, pdf_form=form["path"])
            return fill_form(job, form["path"], out, request, refs, info, ai)

        def failed(msg, cancelled):
            app.status("생성 중단" if cancelled else "생성 실패")
            self.preview.set_title("생성 결과")
            self.preview.token = None
            if not cancelled:
                self.preview.show_message("생성에 실패했습니다.")
                messagebox.showerror("생성 오류", msg[:800])
            elif self.preview.has_pages:
                self.preview.set_note("중단됨 (저장되지 않음)")
            else:
                self.preview.show_message("중단했습니다.")

        app.run_job(work, lambda r: self._on_generated(r, form), failed, pane=self.preview)

    def _on_generated(self, result, form):
        app = self.app
        title = result.title or (form["name"] if form else "문서")
        title = re.sub(r"^\s*[-\d.]*\s*", "", title) or "문서"
        saved = None
        if app.s.get("auto_save", True):
            try:
                saved = str(self.default_save_path(title))
                shutil.copyfile(result.path, saved)
                app.status(f"저장됨: {saved}")
            except OSError as e:
                saved = None
                app.status(f"자동 저장 실패: {e}")
        else:
            app.status("생성 완료 — [다른 이름으로 저장]으로 저장하세요")
        app.workspace.start(result.path, title, saved)
        self.set_doc_buttons(True)
        self.preview.set_title(f"생성 결과 — {title}")
        intro = "문서가 완성되었습니다. 고칠 부분이 있으면 말씀해주세요."
        if saved:
            intro += "\n수정하면 저장된 파일에도 바로 반영됩니다."
        if result.report.missed:
            intro += "\n⚠ " + ", ".join(result.report.missed)
        self.chat.reset(intro)
        if app.s.get("open_after_save") and saved:
            open_path(saved)
        app.preview_file(self.preview, saved or result.path)

    # ── 결과 파일 ───────────────────────────────────────────────────────
    def set_doc_buttons(self, on: bool):
        for b in (self._btn_save, self._btn_open, self._btn_folder):
            b.configure(state="normal" if on else "disabled")

    def default_save_path(self, title) -> Path:
        s = self.app.s
        pattern = s.get("filename_pattern") or "{title}_{date}"
        try:
            name = pattern.format(title=title, date=f"{datetime.date.today():%Y%m%d}",
                                  time=f"{datetime.datetime.now():%H%M}")
        except (KeyError, ValueError, IndexError):
            name = f"{title}_{datetime.date.today():%Y%m%d}"
        folder = Path(s.get("output_dir") or Path.home())
        folder.mkdir(parents=True, exist_ok=True)
        p = folder / f"{safe_filename(name)}.hwpx"
        i = 2
        while p.exists():
            p = folder / f"{safe_filename(name)} ({i}).hwpx"
            i += 1
        return p

    def _save_as(self):
        ws = self.app.workspace
        if not ws.current:
            return
        default = self.default_save_path(ws.title)
        path = filedialog.asksaveasfilename(initialdir=str(default.parent), initialfile=default.name,
                                            defaultextension=".hwpx", filetypes=[("HWPX 문서", "*.hwpx")])
        if path:
            shutil.copyfile(ws.current, path)
            ws.saved_path = path
            self.app.status(f"저장됨: {path}")
            if self.app.s.get("open_after_save"):
                open_path(path)

    def _open_result(self):
        ws = self.app.workspace
        target = ws.saved_path or ws.current
        if target:
            open_path(target)

    def _open_folder(self):
        ws = self.app.workspace
        target = ws.saved_path or ws.current
        if target:
            open_path(str(Path(target).parent))
