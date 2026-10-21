"""AI 수정 대화: 열린 문서를 말로 고친다. 고칠 때마다 버전이 쌓이고 되돌릴 수 있다."""
import datetime
import shutil
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox

from ..config import CACHE_DIR
from ..readers import FILE_TYPES as REF_TYPES
from .theme import ACCENT, BORDER, CARD, FONT, FONT_B, FONT_SM, INPUT_BG, MUTED, TEXT, button, card, restyle

WELCOME = ("문서를 생성하거나 [파일 열기]로 HWPX·HWP 문서를 불러오면\n여기서 고칠 내용을 말로 요청할 수 있습니다.\n\n"
           "예) '운영 개요의 장소를 시청각실로 바꿔줘'\n"
           "    '추진 목적을 3개로 늘려줘'\n"
           "    '예산 표에 간식비 5만 원 추가하고 합계 고쳐줘'\n"
           "    [자료 첨부]로 공문을 붙이고 '이 공문 내용을 반영해줘'")


class ChatPanel:
    def __init__(self, app, parent, gen_tab):
        self.app = app
        self.gen = gen_tab
        self.history: list[tuple[str, str]] = []
        self.attached: list[str] = []

        c = card(parent)
        c.pack(fill="both", expand=True)
        tk.Label(c, text="AI에게 수정 요청", bg=CARD, fg=TEXT, font=FONT_B).pack(anchor="w", padx=12, pady=(10, 4))
        top = tk.Frame(c, bg=CARD)
        top.pack(fill="x", padx=12, pady=(0, 6))
        button(top, "파일 열기…", self._open_for_edit).pack(side="left")
        self._undo_btn = button(top, "되돌리기", self._undo)
        self._undo_btn.pack(side="left", padx=(6, 0))
        self._undo_btn.configure(state="disabled")

        # 입력부를 먼저 아래에 고정해야 대화창이 늘어나도 가려지지 않는다
        row = tk.Frame(c, bg=CARD)
        row.pack(side="bottom", fill="x", padx=12, pady=(0, 12))
        button(row, "자료 첨부…", self._attach).pack(side="left")
        tk.Label(row, text="Enter 보내기", bg=CARD, fg=MUTED, font=FONT_SM).pack(side="left", padx=6)
        self._send_btn = button(row, "보내기", self._send, "primary")
        self._send_btn.pack(side="right")
        self._attach_var = tk.StringVar(value="")
        tk.Label(c, textvariable=self._attach_var, bg=CARD, fg=ACCENT, font=FONT_SM, justify="left",
                 wraplength=290).pack(side="bottom", anchor="w", padx=12)
        self._input = tk.Text(c, height=3, bg=CARD, fg=TEXT, relief="flat", font=FONT, wrap="word",
                              insertbackground=TEXT, highlightthickness=1, highlightbackground=BORDER,
                              highlightcolor=ACCENT, padx=8, pady=6)
        self._input.pack(side="bottom", fill="x", padx=12, pady=(8, 4))
        self._input.bind("<Return>", self._on_enter)

        self._log = tk.Text(c, bg=INPUT_BG, fg=TEXT, relief="flat", font=FONT, wrap="word",
                            highlightthickness=1, highlightbackground=BORDER, padx=10, pady=8,
                            cursor="arrow", spacing1=2, spacing3=6)
        self._log.pack(fill="both", expand=True, padx=12)
        self._log.tag_configure("me", background="#e3edff", lmargin1=40, lmargin2=40, rmargin=4, spacing1=6)
        self._log.tag_configure("ai", background="#f1f3f6", lmargin1=4, lmargin2=4, rmargin=40, spacing1=6)
        self._log.tag_configure("who", foreground=MUTED, font=FONT_SM)
        self._log.tag_configure("sys", foreground=MUTED, font=FONT_SM, justify="center", spacing1=6)
        self._log.configure(state="disabled")
        self.reset(WELCOME)
        app.on_busy_change(self._on_busy)

    # ── 대화창 ──────────────────────────────────────────────────────────
    def add(self, who: str, text: str):
        log = self._log
        log.configure(state="normal")
        if who == "sys":
            log.insert("end", text + "\n", "sys")
        else:
            log.insert("end", ("나" if who == "me" else "AI") + "\n", ("who", who))
            log.insert("end", text.strip() + "\n", who)
        log.configure(state="disabled")
        log.see("end")

    def reset(self, msg: str):
        self._log.configure(state="normal")
        self._log.delete("1.0", "end")
        self._log.configure(state="disabled")
        self.history = []
        self._update_undo()
        self.add("sys", msg)

    def _on_enter(self, e):
        if e.state & 0x1:   # Shift+Enter는 줄바꿈
            return None
        self._send()
        return "break"

    def _on_busy(self, busy: bool):
        if busy:
            self._send_btn.configure(text="■ 중단", command=self.app.stop_job)
            restyle(self._send_btn, "stop")
        else:
            self._send_btn.configure(text="보내기", command=self._send)
            restyle(self._send_btn, "primary")
        self._update_undo()

    def _update_undo(self):
        n = len(self.app.workspace.versions)
        self._undo_btn.configure(state="normal" if n > 1 and not self.app.busy else "disabled")

    # ── 문서 열기 / 자료 첨부 ───────────────────────────────────────────
    def _open_for_edit(self):
        if self.app.busy:
            return
        path = filedialog.askopenfilename(title="수정할 문서",
                                          filetypes=[("한글 문서", "*.hwpx *.hwp"), ("모든 파일", "*.*")])
        if not path:
            return
        if path.lower().endswith(".hwp"):
            self.app.convert_hwp(path, lambda out: self._start_edit(out, Path(path).name))
            return
        self._start_edit(path, Path(path).name)

    def _start_edit(self, path: str, shown_name: str):
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        work = CACHE_DIR / f"edit_{datetime.datetime.now():%Y%m%d_%H%M%S}.hwpx"
        shutil.copyfile(path, work)
        self.app.workspace.start(str(work), Path(shown_name).stem)
        self.gen.set_doc_buttons(True)
        self.gen.preview.set_title(f"편집 중 — {shown_name}")
        self.reset(f"'{shown_name}'을(를) 불러왔습니다.\n"
                   "원본은 그대로 두고, 고친 결과는 [다른 이름으로 저장]으로 저장하세요.")
        self.app.preview_file(self.gen.preview, str(work))

    def _attach(self):
        for p in filedialog.askopenfilenames(title="반영할 자료 첨부", filetypes=REF_TYPES):
            if p not in self.attached:
                self.attached.append(p)
        self._attach_var.set("📎 " + ", ".join(Path(p).name for p in self.attached) if self.attached else "")

    # ── 보내기 ──────────────────────────────────────────────────────────
    def _send(self):
        app = self.app
        text = self._input.get("1.0", "end").strip()
        if not text or app.busy:
            return
        ws = app.workspace
        if not ws.current:
            messagebox.showinfo("수정할 문서 없음", "먼저 문서를 생성하거나 [파일 열기]로 문서를 불러오세요.")
            return
        ai = app.ai_config()
        if not app.check_ai(ai):
            return
        refs = list(self.attached)
        self.attached = []
        self._attach_var.set("")
        self._input.delete("1.0", "end")
        self.add("me", text + ("".join(f"\n📎 {Path(p).name}" for p in refs)))
        src = ws.current
        out = ws.next_path()
        history = list(self.history)
        self.history.append(("user", text))
        sees = bool(app.s.get("ai_sees_screen", True))

        def work(job):
            from ..services import edit_document
            page_info = None
            if sees:
                job.status("한글 화면 읽는 중…")
                page_info = app.page_info(src)
            res = edit_document(job, src, out, text, history, ai, page_info=page_info, refs=refs)
            # 결과 확인: 고친 문서를 한글로 다시 열어 쪽 수를 센다
            if page_info and page_info[1] and res.changed:
                job.status("결과 확인 중…")
                _, after = app.page_info(out)
                if after:
                    res.pages = (page_info[1].get("pages"), after.get("pages"))
            return res

        def failed(msg, cancelled):
            app.status("수정 중단" if cancelled else "수정 실패")
            self.add("sys", "중단했습니다." if cancelled else f"오류: {msg[:300]}")
            if self.history and self.history[-1][0] == "user":
                self.history.pop()
            app.preview_file(self.gen.preview, src)   # 받는 중에 보이던 화면을 원래대로

        app.run_job(work, lambda r: self._on_edited(out, src, r), failed, pane=self.gen.preview)

    def _on_edited(self, out: str, src: str, res):
        app = self.app
        reply = res.reply or ("수정했습니다." if res.changed else "바꿀 부분을 찾지 못했습니다.")
        self.history.append(("ai", reply))
        self.add("ai", reply)
        if res.warning:
            self.add("sys", "⚠ " + res.warning)
            self.history.append(("ai", "(프로그램 알림) " + res.warning))
        if not res.changed:
            app.status("변경 없음")
            app.preview_file(self.gen.preview, src)
            return
        app.workspace.versions.append(out)
        self._apply_version(out)
        msg = f"{res.changed}곳 수정 · 버전 {len(app.workspace.versions)}"
        if res.pages:
            before, after = res.pages
            msg += f" · 쪽 수 {before} → {after}"
            self.history.append(("ai", f"(프로그램 알림) 수정 결과 문서는 {before}쪽에서 {after}쪽이 되었음"))
        self.add("sys", msg)

    def _apply_version(self, path: str):
        ws = self.app.workspace
        self._update_undo()
        if ws.saved_path:
            try:
                shutil.copyfile(path, ws.saved_path)
                self.app.status(f"저장됨: {ws.saved_path}")
            except OSError as e:
                self.app.status(f"저장 실패 (한글에서 파일을 열어두었나요?): {e}")
        self.app.preview_file(self.gen.preview, path)

    def _undo(self):
        ws = self.app.workspace
        if len(ws.versions) <= 1 or self.app.busy:
            return
        ws.versions.pop()
        self._apply_version(ws.current)
        self.add("sys", f"되돌림 · 버전 {len(ws.versions)}")
