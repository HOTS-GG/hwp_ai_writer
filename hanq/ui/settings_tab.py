"""설정 탭. 바꾸면 바로 settings.json에 저장된다."""
import threading
import tkinter as tk
import webbrowser
from tkinter import filedialog, messagebox, ttk

from .. import config as cfg
from ..ai import providers
from ..config import BUILTIN_FORMS_DIR, CLI_PROVIDERS, DEFAULT_MODELS, PROVIDERS
from ..system import IS_MAC, IS_WIN, font, wheel_units
from .theme import (ACCENT, BG, BORDER, CARD, DANGER, FONT, FONT_SM, INPUT_BG, MUTED, OK, SOFT, TEXT, button,
                    card)

CLI_DESC = {
    "claude_code": "Claude Pro/Max 구독이 있으면 씁니다. Claude 데스크톱 앱이 있으면 이미 들어 있는 것을 씁니다.",
    "codex": "ChatGPT Plus/Pro 구독이 있으면 씁니다. Codex는 글을 다 쓴 뒤에 한 번에 보여 줍니다.",
}
CLI_INSTALL_NOTE = {
    "claude_code": "Anthropic 공식 설치 스크립트로 Claude Code를 설치합니다 (1~2분).",
    "codex": "OpenAI Codex를 설치합니다. Node.js가 없으면 먼저 Node.js를 설치합니다 (2~5분, 권한 확인 창이 뜨면 '예').",
}


class SettingsTab:
    def __init__(self, app, parent):
        self.app = app
        self.s = app.s
        outer = tk.Frame(parent, bg=BG)
        outer.pack(fill="both", expand=True)
        canvas = tk.Canvas(outer, bg=BG, highlightthickness=0)
        sb = ttk.Scrollbar(outer, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)
        inner = tk.Frame(canvas, bg=BG)
        self._canvas, self._inner = canvas, inner
        win = canvas.create_window((0, 0), window=inner, anchor="nw")
        inner.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda e: canvas.itemconfigure(win, width=min(e.width, 900)))
        canvas.bind("<Enter>", lambda e: canvas.bind_all(
            "<MouseWheel>", lambda ev: canvas.yview_scroll(wheel_units(ev), "units")))
        canvas.bind("<Leave>", lambda e: canvas.unbind_all("<MouseWheel>"))

        self._build_providers(inner)
        self._build_cli(inner)

        c = self._card(inner, "기본 정보 (문서에 자동 반영)")
        self._entry(c, "학교(기관)명", "school_name")
        self._entry(c, "작성 부서", "department", "예) 과학정보부")
        self._entry(c, "작성자", "author", "예) 교사 홍길동", last=True)

        c = self._card(inner, "저장")
        self._entry(c, "저장 폴더", "output_dir", browse="dir")
        self._entry(c, "파일 이름 규칙", "filename_pattern", "{title}=제목, {date}=날짜, {time}=시각")
        self._check(c, "생성하면 저장 폴더에 자동 저장", "auto_save")
        self._check(c, "저장 후 한글로 바로 열기", "open_after_save", last=True)

        c = self._card(inner, "양식")
        self._entry(c, "내 양식 폴더", "user_forms_dir", browse="dir", on_change=app.reload_forms)
        row = self._row(c, "기본 서식", "PDF 양식·자유 작성 문서에 쓰는 서식")
        styles = [p.name for p in sorted(BUILTIN_FORMS_DIR.glob("*.hwpx"))]
        v = tk.StringVar(value=self.s.get("base_style_form"))
        v.trace_add("write", lambda *a: (app.set("base_style_form", v.get()), app.gen.refresh_forms()))
        ttk.Combobox(row, textvariable=v, values=styles, state="readonly", font=FONT).pack(fill="x")
        tk.Frame(c, bg=CARD, height=8).pack()

        c = self._card(inner, "미리보기")
        if app.rhwp is not None:
            engine = f"✓ rhwp 사용 중 — 한글 없이 실제 모양으로 그립니다 ({app.rhwp.exe})"
        else:
            engine = "rhwp 없음 — 간이 미리보기를 쓰고, 한글이 있으면 한글로 다시 그립니다"
        tk.Label(c, text=engine, bg=CARD, fg=OK if app.rhwp else MUTED, font=FONT_SM, justify="left",
                 wraplength=760).pack(anchor="w", padx=14, pady=(0, 4))
        self._entry(c, "rhwp 실행 파일", "rhwp_path", "비워 두면 자동으로 찾음 (바꾸면 다시 시작해야 적용)")
        self._check(c, "AI가 쓰는 대로 실시간으로 보기", "live_preview")
        self._check(c, "rhwp가 없을 때: 다 쓴 뒤 한글로 정확한 쪽 이미지 다시 그리기 (윈도우 한글 필요)", "auto_preview")
        self._spin(c, "해상도 (DPI)", "preview_dpi", 72, 200, 12)
        self._spin(c, "기본 확대율 (%)", "preview_zoom", 30, 250, 10, last=True)

        if IS_WIN:
            self._build_security(inner)
        self._build_update(inner)

        c = self._card(inner, "AI 고급 옵션")
        self._spin(c, "최대 출력 토큰", "max_tokens", 2000, 128000, 1000)
        self._spin(c, "창의성 (temperature)", "temperature", 0.0, 1.0, 0.1, is_float=True)
        self._spin(c, "참고 자료 최대 글자 수", "ref_max_chars", 2000, 200000, 2000)
        self._spin(c, "응답 대기 시간 (초)", "request_timeout", 60, 1800, 30)
        self._check(c, "수정 요청 때 AI에게 한글 화면(쪽 이미지)과 쪽 나눔 보여주기", "ai_sees_screen")
        self._spin(c, "AI에게 보여줄 최대 쪽 수", "max_screen_pages", 1, 20, 1, last=True)

        bottom = tk.Frame(inner, bg=BG)
        bottom.pack(fill="x", padx=24, pady=18)
        self._saved_lbl = tk.StringVar(value="변경 사항은 자동으로 저장됩니다.")
        tk.Label(bottom, textvariable=self._saved_lbl, bg=BG, fg=MUTED, font=FONT_SM).pack(side="left")
        button(bottom, "미리보기 캐시 비우기", app.clear_cache).pack(side="right")
        tk.Label(bottom, text=f"한큐 HanQ  v{cfg.APP_VERSION}", bg=BG, fg=MUTED, font=FONT_SM).pack(side="right", padx=12)

    def saved(self, when):
        self._saved_lbl.set(f"저장됨 ({when:%H:%M:%S})")

    # ── AI 제공자 ──
    def _build_providers(self, inner):
        app = self.app
        c = self._card(inner, "AI 제공자", top=18)
        tk.Label(c, text="사용할 제공자를 고르세요. 키와 모델은 제공자마다 따로 저장됩니다.",
                 bg=CARD, fg=MUTED, font=FONT_SM).pack(anchor="w", padx=14)
        grid = tk.Frame(c, bg=CARD)
        grid.pack(fill="x", padx=14, pady=(8, 12))
        grid.columnconfigure(2, weight=1)
        grid.columnconfigure(4, weight=1)
        self._provider_var = tk.StringVar(value=self.s["provider"])
        self._provider_var.trace_add("write", lambda *a: app.set("provider", self._provider_var.get()))
        for col, head in enumerate(["사용", "제공자", "API 키", "", "모델", ""]):
            tk.Label(grid, text=head, bg=CARD, fg=MUTED, font=FONT_SM).grid(row=0, column=col, sticky="w", padx=4)
        self._model_combos = {}
        self._api_entries = {}
        for r, (pid, pname) in enumerate(PROVIDERS.items(), start=1):
            ttk.Radiobutton(grid, variable=self._provider_var, value=pid).grid(row=r, column=0, padx=4, pady=4)
            tk.Label(grid, text=pname, bg=CARD, fg=TEXT, font=FONT).grid(row=r, column=1, sticky="w", padx=4)
            kv = tk.StringVar(value=self.s["api_keys"].get(pid, ""))
            kv.trace_add("write", lambda *a, p=pid, v=kv: self._api_key_changed(p, v.get().strip()))
            ent = tk.Entry(grid, textvariable=kv, show="•", bg=INPUT_BG, fg=TEXT, relief="flat", font=FONT,
                           highlightthickness=1, highlightbackground=BORDER, highlightcolor=ACCENT)
            ent.grid(row=r, column=2, sticky="ew", padx=4, ipady=4)
            self._api_entries[pid] = ent
            tk.Button(grid, text="보기", bg=CARD, fg=MUTED, relief="flat", font=FONT_SM, cursor="hand2",
                      command=lambda e=ent: e.configure(show="" if e.cget("show") else "•")).grid(row=r, column=3, padx=2)
            mv = tk.StringVar(value=self.s["models"].get(pid) or DEFAULT_MODELS[pid][0])
            mv.trace_add("write", lambda *a, p=pid, v=mv: app.set_nested("models", p, v.get().strip()))
            cb = ttk.Combobox(grid, textvariable=mv, font=FONT,
                              values=self.s.get("model_lists", {}).get(pid) or DEFAULT_MODELS[pid])
            cb.grid(row=r, column=4, sticky="ew", padx=4)
            self._model_combos[pid] = cb
            button(grid, "목록 갱신", lambda p=pid: self._refresh_models(p)).grid(row=r, column=5, padx=4)

    def _api_key_changed(self, pid, key):
        self.app.set_nested("api_keys", pid, key)
        # 지금 고른 방식이 쓸 수 없는 상태면, 방금 키를 넣은 제공자를 바로 고른다
        if key and not self.app.ai_config().api_key:
            self._provider_var.set(pid)

    def focus_api_key(self):
        cur = self._provider_var.get()
        ent = self._api_entries.get(cur) or self._api_entries["claude"]
        self.scroll_to(ent)
        ent.focus_set()
        self.app.status("API 키를 붙여 넣으세요 (Ctrl+V). 넣으면 바로 저장되고 그 제공자가 선택됩니다.")

    def start_cli_setup(self, pid):
        box = self._cli[pid]
        self.scroll_to(box.go)
        box.setup()

    def scroll_to(self, widget):
        self._canvas.update_idletasks()
        y = widget.winfo_rooty() - self._inner.winfo_rooty()
        total = max(self._inner.winfo_height(), 1)
        self._canvas.yview_moveto(max(0.0, (y - 80) / total))

    def _refresh_models(self, pid):
        key = self.s["api_keys"].get(pid, "").strip()
        self.app.status(f"{PROVIDERS[pid]} 모델 목록 불러오는 중…")

        def run():
            try:
                models = providers.list_models(pid, key)
                self.app.after(0, lambda: self._models_loaded(pid, models))
            except Exception as e:
                err = str(e)
                self.app.after(0, lambda: (self.app.status("모델 목록 실패"), messagebox.showerror("모델 목록", err[:400])))
        threading.Thread(target=run, daemon=True).start()

    def _models_loaded(self, pid, models):
        self._model_combos[pid]["values"] = models
        self.app.set_nested("model_lists", pid, models)
        self.app.status(f"{PROVIDERS[pid]} 모델 {len(models)}개")

    # ── 구독 계정 (CLI) ──
    def _build_cli(self, inner):
        c = self._card(inner, "API 키 없이 쓰기 — 구독 계정 연결")
        tk.Label(c, text="Claude 또는 ChatGPT를 월 구독 중이면 API 키 없이 쓸 수 있습니다.\n"
                         "[한 번에 설정]을 누르면 설치·로그인·연결을 한큐가 알아서 합니다. (로그인할 때만 브라우저에서 한 번 확인)",
                 bg=CARD, fg=MUTED, font=FONT_SM, justify="left").pack(anchor="w", padx=14)
        self._cli = {}
        for pid, pname in CLI_PROVIDERS.items():
            self._cli[pid] = _CliBox(self, c, pid, pname)
        tk.Frame(c, bg=CARD, height=10).pack()
        self._provider_var.trace_add("write", lambda *a: [b.update_button() for b in self._cli.values()])

    def cli_selected(self, pid):
        """[한 번에 설정]이 끝난 제공자를 사용하도록 고른다."""
        self._provider_var.set(pid)

    # ── 한글 보안 모듈 ──
    def _build_security(self, inner):
        c = self._card(inner, "한글 '접근 허용' 경고 없애기")
        tk.Label(c, text="한컴의 '보안 승인 모듈'이 등록되어 있으면 미리보기·저장 때 '접근 허용' 창이 뜨지 않습니다.\n"
                         "한큐는 켤 때마다 바탕화면·다운로드·문서 폴더에서 모듈(DLL 또는 받은 zip)을 찾아 자동으로 등록합니다.\n"
                         "아직 없다면: 한컴 디벨로퍼 사이트 → 한글 오토메이션 → 보안 승인 모듈을 받아 다운로드 폴더에 두고 [자동으로 찾기].",
                 bg=CARD, fg=MUTED, font=FONT_SM, justify="left").pack(anchor="w", padx=14)
        row = tk.Frame(c, bg=CARD)
        row.pack(fill="x", padx=14, pady=(8, 4))
        self._sec_var = tk.StringVar()
        self._sec_lbl = tk.Label(row, textvariable=self._sec_var, bg=CARD, font=FONT)
        self._sec_lbl.pack(side="left")
        button(row, "DLL 직접 선택…", self._install_dll).pack(side="right")
        button(row, "자동으로 찾기", self._auto_find_dll, "primary").pack(side="right", padx=(0, 6))
        button(row, "받는 곳 열기", lambda: webbrowser.open("https://developer.hancom.com/")).pack(side="right", padx=(0, 6))
        self._check(c, "켤 때 자동으로 찾아 등록하기", "auto_security_module", last=True)
        self.refresh_security()

    def refresh_security(self):
        from ..hwp import security
        ok, msg = security.status()
        self._sec_var.set(("✓ " if ok else "✗ ") + msg)
        self._sec_lbl.configure(fg=OK if ok else DANGER)

    def _auto_find_dll(self):
        from ..hwp import security
        self._sec_var.set("찾는 중…")

        def run():
            try:
                dll = security.auto_install()
                err = None
            except OSError as e:
                dll, err = None, str(e)
            self.app.after(0, self._auto_found, dll, err)
        threading.Thread(target=run, daemon=True).start()

    def _auto_found(self, dll, err):
        from ..hwp import security
        self.refresh_security()
        if dll:
            self.app.restart_worker()
            messagebox.showinfo("등록 완료", f"보안 승인 모듈을 찾아 등록했습니다.\n{dll}\n\n"
                                         "다음 미리보기부터 '접근 허용' 창이 뜨지 않습니다.")
        elif security.status()[0]:
            messagebox.showinfo("이미 등록됨", "보안 승인 모듈이 이미 등록되어 있습니다.")
        else:
            messagebox.showinfo("찾지 못했습니다",
                                (err + "\n\n" if err else "") +
                                "바탕화면·다운로드·문서 폴더에서 보안 승인 모듈을 찾지 못했습니다.\n\n"
                                "1. [받는 곳 열기] → 한글 오토메이션 → 보안 승인 모듈을 내려받기\n"
                                "2. 받은 zip 파일을 그대로 다운로드 폴더에 두기\n"
                                "3. 다시 [자동으로 찾기]")

    def _install_dll(self):
        from ..hwp import security
        path = filedialog.askopenfilename(title="한글 보안 승인 모듈 DLL 선택", filetypes=[("DLL", "*.dll")])
        if not path:
            return
        try:
            security.install(path)
        except OSError as e:
            messagebox.showerror("등록 실패", str(e))
            return
        self.refresh_security()
        self.app.restart_worker()
        messagebox.showinfo("등록 완료", "보안 승인 모듈을 등록했습니다.\n다음 미리보기부터 '접근 허용' 창이 뜨지 않습니다.")

    # ── 업데이트 ──
    def _build_update(self, inner):
        c = self._card(inner, "업데이트")
        row = tk.Frame(c, bg=CARD)
        row.pack(fill="x", padx=14, pady=(0, 4))
        tk.Label(row, text=f"지금 버전: 한큐 {cfg.APP_VERSION}", bg=CARD, fg=TEXT, font=FONT).pack(side="left")
        self._upd_var = tk.StringVar(value=self._update_note())
        tk.Label(row, textvariable=self._upd_var, bg=CARD, fg=MUTED, font=FONT_SM).pack(side="left", padx=12)
        self._upd_btn = button(row, "지금 확인", self._check_update)
        self._upd_btn.pack(side="right")
        self._check(c, "프로그램을 켤 때 새 버전이 있는지 확인 (새 버전이 있을 때만 알림)", "auto_update_check", last=True)

    def _update_note(self) -> str:
        when = self.s.get("last_update_check")
        return f"마지막 확인: {when}" if when else ""

    def _check_update(self):
        self._upd_var.set("확인하는 중…")
        self.app.set("skip_version", "")   # 직접 확인할 때는 건너뛴 버전도 다시 알린다

        def result(rel, err):
            if err:
                self._upd_var.set("확인 실패 (인터넷 연결 확인)")
            elif rel is None:
                self._upd_var.set(f"최신 버전입니다 · {self._update_note()}")
            else:
                self._upd_var.set(f"새 버전 {rel.version} 있음")
        self.app.updater.check(silent=False, on_result=result)

    # ── 입력칸 도우미 ──
    def _card(self, inner, title, top=14):
        c = card(inner, title)
        c.pack(fill="x", padx=24, pady=(top, 0))
        return c

    def _row(self, parent, label, hint=None):
        row = tk.Frame(parent, bg=CARD)
        row.pack(fill="x", padx=14, pady=4)
        lab = tk.Frame(row, bg=CARD, width=200)
        lab.pack(side="left", fill="y")
        lab.pack_propagate(False)
        tk.Label(lab, text=label, bg=CARD, fg=TEXT, font=FONT).pack(anchor="w")
        if hint:
            tk.Label(lab, text=hint, bg=CARD, fg=MUTED, font=font(8), wraplength=190, justify="left").pack(anchor="w")
            lab.configure(height=40)
        else:
            lab.configure(height=28)
        body = tk.Frame(row, bg=CARD)
        body.pack(side="left", fill="x", expand=True)
        return body

    def _entry(self, parent, label, key, hint=None, browse=None, on_change=None, last=False):
        body = self._row(parent, label, hint)
        v = tk.StringVar(value=str(self.s.get(key, "")))

        def changed(*a):
            self.app.set(key, v.get())
            if on_change:
                self.app.after(300, on_change)
        v.trace_add("write", changed)
        tk.Entry(body, textvariable=v, bg=INPUT_BG, fg=TEXT, relief="flat", font=FONT, highlightthickness=1,
                 highlightbackground=BORDER, highlightcolor=ACCENT).pack(side="left", fill="x", expand=True, ipady=4)
        if browse == "dir":
            button(body, "찾기…", lambda: (lambda d: d and v.set(d))(
                filedialog.askdirectory(initialdir=v.get() or None))).pack(side="left", padx=(6, 0))
        if last:
            tk.Frame(parent, bg=CARD, height=8).pack()

    def _check(self, parent, label, key, last=False):
        v = tk.BooleanVar(value=bool(self.s.get(key, True)))
        v.trace_add("write", lambda *a: self.app.set(key, v.get()))
        ttk.Checkbutton(parent, text=label, variable=v).pack(anchor="w", padx=14, pady=4)
        if last:
            tk.Frame(parent, bg=CARD, height=8).pack()

    def _spin(self, parent, label, key, lo, hi, step, is_float=False, last=False):
        body = self._row(parent, label)
        v = tk.StringVar(value=str(self.s.get(key)))

        def changed(*a):
            try:
                val = float(v.get()) if is_float else int(float(v.get()))
            except ValueError:
                return
            self.app.set(key, max(lo, min(hi, val)))
        v.trace_add("write", changed)
        ttk.Spinbox(body, from_=lo, to=hi, increment=step, textvariable=v, width=10, font=FONT).pack(side="left")
        if last:
            tk.Frame(parent, bg=CARD, height=8).pack()


class _CliBox:
    """구독 방식 하나(Claude Code 또는 Codex)의 칸: 상태, [한 번에 설정], 명령어 복사, 고급(경로·모델)."""

    def __init__(self, tab, parent, pid, pname):
        self.tab, self.app, self.s, self.pid, self.name = tab, tab.app, tab.s, pid, pname
        self._stop = threading.Event()
        self._busy = False
        self.ready = False
        box = tk.Frame(parent, bg=CARD, highlightthickness=1, highlightbackground=SOFT)
        box.pack(fill="x", padx=14, pady=(8, 0))
        head = tk.Frame(box, bg=CARD)
        head.pack(fill="x", padx=10, pady=(8, 2))
        ttk.Radiobutton(head, text=pname, variable=tab._provider_var, value=pid).pack(side="left")
        self.state = tk.StringVar(value="확인하는 중…")
        self.state_lbl = tk.Label(head, textvariable=self.state, bg=CARD, fg=MUTED, font=FONT_SM)
        self.state_lbl.pack(side="left", padx=10)
        tk.Label(box, text=CLI_DESC[pid], bg=CARD, fg=TEXT, font=FONT_SM, justify="left", wraplength=760
                 ).pack(anchor="w", padx=12)

        row = tk.Frame(box, bg=CARD)
        row.pack(fill="x", padx=12, pady=(6, 2))
        self.go = button(row, "한 번에 설정", self.setup, "primary")
        self.go.pack(side="left")
        button(row, "명령어 복사", self.copy).pack(side="left", padx=(6, 0))
        self.adv_btn = button(row, "고급 ▾", self.toggle_adv)
        self.adv_btn.pack(side="left", padx=(6, 0))
        self.log = tk.StringVar(value="")
        tk.Label(box, textvariable=self.log, bg=CARD, fg=MUTED, font=FONT_SM, justify="left", wraplength=760
                 ).pack(anchor="w", padx=12, pady=(2, 8))

        self.adv = tk.Frame(box, bg=CARD)
        r = tk.Frame(self.adv, bg=CARD)
        r.pack(fill="x", padx=12, pady=(0, 4))
        tk.Label(r, text="실행 파일", bg=CARD, fg=TEXT, font=FONT_SM, width=8, anchor="w").pack(side="left")
        self.path_var = tk.StringVar(value=self.s.get("cli_paths", {}).get(pid, ""))
        self.path_var.trace_add("write", lambda *a: self.app.set_nested("cli_paths", pid, self.path_var.get().strip()))
        tk.Entry(r, textvariable=self.path_var, bg=INPUT_BG, fg=TEXT, relief="flat", font=FONT_SM, highlightthickness=1,
                 highlightbackground=BORDER, highlightcolor=ACCENT).pack(side="left", fill="x", expand=True, ipady=3)
        button(r, "찾기…", self.browse).pack(side="left", padx=(6, 0))
        tk.Label(r, text="모델", bg=CARD, fg=TEXT, font=FONT_SM).pack(side="left", padx=(12, 4))
        mv = tk.StringVar(value=self.s["models"].get(pid, ""))
        mv.trace_add("write", lambda *a: self.app.set_nested("models", pid, mv.get().strip()))
        ttk.Combobox(r, textvariable=mv, width=12, font=FONT_SM,
                     values=["", "sonnet", "opus", "haiku"] if pid == "claude_code" else ["", "gpt-5", "gpt-5-codex"]
                     ).pack(side="left")
        r2 = tk.Frame(self.adv, bg=CARD)
        r2.pack(fill="x", padx=12, pady=(0, 10))
        self.found = tk.StringVar(value="")
        tk.Label(r2, textvariable=self.found, bg=CARD, fg=MUTED, font=FONT_SM, justify="left", wraplength=600
                 ).pack(side="left")
        button(r2, "다른 계정으로 로그인", self.relogin).pack(side="right")
        self.refresh()

    # ── 상태 ──
    def exe(self) -> str:
        return self.s.get("cli_paths", {}).get(self.pid, "").strip() or providers.find_cli(self.pid) or ""

    def refresh(self):
        from ..ai import cli_setup

        def run():
            exe = self.exe()
            ok, detail = cli_setup.login_status(self.pid, exe) if exe else (False, "")
            self.app.after(0, self._show, exe, ok, detail)
        threading.Thread(target=run, daemon=True).start()

    def _show(self, exe, ok, detail):
        self.ready = bool(exe and ok)
        if not exe:
            self.state.set("✗ 설치 안 됨")
            self.state_lbl.configure(fg=DANGER)
            self.found.set("실행 파일을 찾지 못했습니다.")
        else:
            where = ("Claude 앱에 포함된 것" if "Claude-Data" in exe else "Codex 앱에 포함된 것" if "OpenAI" in exe
                     else "설치된 것")
            self.found.set(f"사용 중: {where}\n{exe}")
            self.state.set(f"✓ 설치됨 · {'✓ ' + detail if ok else '✗ 로그인 필요'}")
            self.state_lbl.configure(fg=OK if ok else DANGER)
        self.update_button()

    def update_button(self):
        if self._busy:
            return
        if not self.ready:
            self.go.configure(text="한 번에 설정")
        elif self.tab._provider_var.get() == self.pid:
            self.go.configure(text="✓ 사용 중")
        else:
            self.go.configure(text="이걸로 쓰기")

    # ── 한 번에 설정: 설치 → 로그인 → 선택 ──
    def setup(self):
        if self._busy:
            self._stop.set()
            return
        if self.ready:
            self.tab.cli_selected(self.pid)
            self.log.set(f"✓ 이제 문서를 만들 때 {self.name}을(를) 씁니다.")
            return
        exe = self.exe()
        if not exe and not messagebox.askyesno(
                "설치 확인", f"{CLI_INSTALL_NOTE[self.pid]}\n\n설치한 뒤 로그인 창이 뜨면 브라우저에서 로그인해 주세요.\n계속할까요?"):
            return
        self._busy = True
        self._stop.clear()
        self.go.configure(text="취소")
        say = lambda m: self.app.after(0, self.log.set, m)   # noqa: E731

        def run():
            from ..ai import cli_setup
            try:
                path = exe or cli_setup.install(self.pid, say, self._stop)
                ok, _ = cli_setup.login_status(self.pid, path)
                if not ok:
                    say("로그인 창을 열었습니다. 브라우저에서 로그인을 마치면 자동으로 이어집니다…")
                    proc = cli_setup.start_login(self.pid, path)
                    if not cli_setup.wait_login(self.pid, path, proc, self._stop):
                        raise cli_setup.SetupError("로그인이 끝나지 않았습니다. 다시 [한 번에 설정]을 눌러 주세요.")
            except cli_setup.SetupError as e:
                err = str(e)
                self.app.after(0, self._done, False, err)
                return
            self.app.after(0, self._done, True, "")
        threading.Thread(target=run, daemon=True).start()

    def _done(self, ok, err):
        self._busy = False
        if ok:
            self.tab.cli_selected(self.pid)
            self.log.set(f"✓ 준비 완료 — 이제 문서를 만들 때 {self.name}을(를) 씁니다.")
            self.app.status(f"{self.name} 연결 완료")
        else:
            self.log.set(f"✗ {err}")
            if "취소" not in err:
                messagebox.showwarning("설정하지 못했습니다", f"{err}\n\n직접 하려면 [명령어 복사]를 눌러 명령 프롬프트에 붙여 넣으세요.")
        self.refresh()

    def relogin(self):
        from ..ai import cli_setup
        exe = self.exe()
        if not exe:
            messagebox.showinfo("설치 필요", "먼저 [한 번에 설정]으로 설치해 주세요.")
            return
        proc = cli_setup.start_login(self.pid, exe)
        self.log.set("로그인 창을 열었습니다. 브라우저에서 로그인을 마치면 자동으로 확인합니다…")

        def run():
            cli_setup.wait_login(self.pid, exe, proc)
            self.app.after(0, self.refresh)
        threading.Thread(target=run, daemon=True).start()

    # ── 그 밖 ──
    def copy(self):
        from ..ai.cli_setup import COPY_COMMANDS
        self.app.clipboard_clear()
        self.app.clipboard_append(COPY_COMMANDS[self.pid])
        where = "터미널" if IS_MAC else "명령 프롬프트(cmd)"
        self.log.set(f"명령어를 복사했습니다. {where}에 붙여 넣고(Ctrl+V) 한 줄씩 Enter를 누르세요:\n"
                     + COPY_COMMANDS[self.pid])

    def toggle_adv(self):
        if self.adv.winfo_ismapped():
            self.adv.pack_forget()
            self.adv_btn.configure(text="고급 ▾")
        else:
            self.adv.pack(fill="x")
            self.adv_btn.configure(text="고급 ▴")

    def browse(self):
        f = filedialog.askopenfilename(
            title="실행 파일 선택",
            filetypes=[("실행 파일", "*.exe *.cmd"), ("모든 파일", "*.*")] if IS_WIN else [("모든 파일", "*")])
        if f:
            self.path_var.set(f)
            self.refresh()
