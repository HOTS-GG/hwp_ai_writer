"""설정 탭. 바꾸면 바로 settings.json에 저장된다."""
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from .. import config as cfg
from ..ai import providers
from ..config import BUILTIN_FORMS_DIR, CLI_PROVIDERS, DEFAULT_MODELS, PROVIDERS
from ..system import FONT_PLUS, IS_MAC, IS_WIN, MONO_FAMILY, font, wheel_units
from .theme import (ACCENT, BG, BORDER, CARD, DANGER, FONT, FONT_SM, INPUT_BG, MUTED, OK, SOFT, TEXT, button,
                    card)

CLI_GUIDE = {
    "claude_code": ("Claude Pro/Max 구독이 있으면 사용할 수 있습니다.",
                    "설치: PowerShell에서  irm https://claude.ai/install.ps1 | iex\n"
                    "로그인: 설치 후 명령 프롬프트에서  claude  를 한 번 실행해 로그인"),
    "codex": ("ChatGPT Plus/Pro 구독이 있으면 사용할 수 있습니다. (Node.js 필요)",
              "설치: 명령 프롬프트에서  npm install -g @openai/codex\n"
              "로그인: 설치 후  codex  를 한 번 실행해 'ChatGPT로 로그인' 선택"),
}
if IS_MAC:
    CLI_GUIDE = {
        "claude_code": ("Claude Pro/Max 구독이 있으면 사용할 수 있습니다.",
                        "설치: 터미널에서  curl -fsSL https://claude.ai/install.sh | bash\n"
                        "로그인: 설치 후 터미널에서  claude  를 한 번 실행해 로그인"),
        "codex": ("ChatGPT Plus/Pro 구독이 있으면 사용할 수 있습니다.",
                  "설치: 터미널에서  brew install codex  (또는 npm install -g @openai/codex)\n"
                  "로그인: 설치 후  codex  를 한 번 실행해 'ChatGPT로 로그인' 선택"),
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
        for r, (pid, pname) in enumerate(PROVIDERS.items(), start=1):
            ttk.Radiobutton(grid, variable=self._provider_var, value=pid).grid(row=r, column=0, padx=4, pady=4)
            tk.Label(grid, text=pname, bg=CARD, fg=TEXT, font=FONT).grid(row=r, column=1, sticky="w", padx=4)
            kv = tk.StringVar(value=self.s["api_keys"].get(pid, ""))
            kv.trace_add("write", lambda *a, p=pid, v=kv: app.set_nested("api_keys", p, v.get().strip()))
            ent = tk.Entry(grid, textvariable=kv, show="•", bg=INPUT_BG, fg=TEXT, relief="flat", font=FONT,
                           highlightthickness=1, highlightbackground=BORDER, highlightcolor=ACCENT)
            ent.grid(row=r, column=2, sticky="ew", padx=4, ipady=4)
            tk.Button(grid, text="보기", bg=CARD, fg=MUTED, relief="flat", font=FONT_SM, cursor="hand2",
                      command=lambda e=ent: e.configure(show="" if e.cget("show") else "•")).grid(row=r, column=3, padx=2)
            mv = tk.StringVar(value=self.s["models"].get(pid) or DEFAULT_MODELS[pid][0])
            mv.trace_add("write", lambda *a, p=pid, v=mv: app.set_nested("models", p, v.get().strip()))
            cb = ttk.Combobox(grid, textvariable=mv, font=FONT,
                              values=self.s.get("model_lists", {}).get(pid) or DEFAULT_MODELS[pid])
            cb.grid(row=r, column=4, sticky="ew", padx=4)
            self._model_combos[pid] = cb
            button(grid, "목록 갱신", lambda p=pid: self._refresh_models(p)).grid(row=r, column=5, padx=4)

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
        app = self.app
        c = self._card(inner, "API 키 없이 쓰기 — 구독 계정 연결")
        tk.Label(c, text="API 키가 없어도, 컴퓨터에 Claude Code나 Codex를 설치하고 로그인해 두면 그 구독으로 한큐를 쓸 수 있습니다.\n"
                         "위의 API 방식보다 느릴 수 있습니다(한 번에 30초~2분). Codex는 다 쓴 뒤에 한 번에 보여 줍니다.",
                 bg=CARD, fg=MUTED, font=FONT_SM, justify="left").pack(anchor="w", padx=14)
        self._cli_status = {}
        for pid, pname in CLI_PROVIDERS.items():
            box = tk.Frame(c, bg=CARD, highlightthickness=1, highlightbackground=SOFT)
            box.pack(fill="x", padx=14, pady=(8, 0))
            head = tk.Frame(box, bg=CARD)
            head.pack(fill="x", padx=10, pady=(8, 2))
            ttk.Radiobutton(head, text=pname, variable=self._provider_var, value=pid).pack(side="left")
            st_var = tk.StringVar()
            st_lbl = tk.Label(head, textvariable=st_var, bg=CARD, font=FONT_SM)
            st_lbl.pack(side="left", padx=10)
            self._cli_status[pid] = (st_var, st_lbl)
            button(head, "연결 확인", lambda p=pid: self._check_cli(p, verbose=True)).pack(side="right")

            desc, how = CLI_GUIDE[pid]
            tk.Label(box, text=desc, bg=CARD, fg=TEXT, font=FONT_SM).pack(anchor="w", padx=12)
            tk.Label(box, text=how, bg=CARD, fg=MUTED, font=(MONO_FAMILY, 9 + FONT_PLUS), justify="left"
                     ).pack(anchor="w", padx=12, pady=(2, 4))

            row = tk.Frame(box, bg=CARD)
            row.pack(fill="x", padx=12, pady=(0, 10))
            tk.Label(row, text="실행 파일", bg=CARD, fg=TEXT, font=FONT_SM, width=8, anchor="w").pack(side="left")
            pv = tk.StringVar(value=self.s.get("cli_paths", {}).get(pid, ""))
            pv.trace_add("write", lambda *a, p=pid, v=pv: app.set_nested("cli_paths", p, v.get().strip()))
            tk.Entry(row, textvariable=pv, bg=INPUT_BG, fg=TEXT, relief="flat", font=FONT_SM, highlightthickness=1,
                     highlightbackground=BORDER, highlightcolor=ACCENT).pack(side="left", fill="x", expand=True, ipady=3)
            button(row, "찾기…", lambda v=pv: (lambda f: f and v.set(f))(filedialog.askopenfilename(
                title="실행 파일 선택",
                filetypes=[("실행 파일", "*.exe *.cmd"), ("모든 파일", "*.*")] if IS_WIN else [("모든 파일", "*")]))
                   ).pack(side="left", padx=(6, 0))
            tk.Label(row, text="모델", bg=CARD, fg=TEXT, font=FONT_SM).pack(side="left", padx=(12, 4))
            mv = tk.StringVar(value=self.s["models"].get(pid, ""))
            mv.trace_add("write", lambda *a, p=pid, v=mv: app.set_nested("models", p, v.get().strip()))
            ttk.Combobox(row, textvariable=mv, width=12, font=FONT_SM,
                         values=["", "sonnet", "opus", "haiku"] if pid == "claude_code" else ["", "gpt-5", "gpt-5-codex"]
                         ).pack(side="left")
            self._check_cli(pid, verbose=False)
        tk.Label(c, text="실행 파일 칸을 비워 두면 자동으로 찾습니다. 모델 칸을 비워 두면 그 프로그램의 기본 모델을 씁니다.",
                 bg=CARD, fg=MUTED, font=FONT_SM).pack(anchor="w", padx=14, pady=(0, 10))

    def _check_cli(self, pid, verbose: bool):
        st_var, st_lbl = self._cli_status[pid]
        path = self.s.get("cli_paths", {}).get(pid, "").strip() or providers.find_cli(pid)
        if not path:
            st_var.set("✗ 설치되지 않음")
            st_lbl.configure(fg=DANGER)
            if verbose:
                messagebox.showinfo("찾을 수 없음", f"{CLI_PROVIDERS[pid]}가 설치되어 있지 않습니다.\n"
                                                 "아래 안내대로 설치한 뒤 다시 [연결 확인]을 눌러 주세요.")
            return
        if not verbose:
            where = ("Claude 앱에 포함됨" if "Claude-Data" in path else "Codex 앱에 포함됨" if "OpenAI" in path else "설치됨")
            st_var.set(f"● 자동으로 찾음 ({where})")
            st_lbl.configure(fg=OK)
            return

        def run():
            try:
                ver = providers.cli_version(pid, path)
                self.app.after(0, lambda: (st_var.set(f"✓ 연결됨 {ver[:40]}"), st_lbl.configure(fg=OK),
                                           messagebox.showinfo("연결 확인", f"{CLI_PROVIDERS[pid]} 사용 가능\n{path}\n{ver}\n\n"
                                                                        "로그인이 안 되어 있으면 첫 생성 때 오류가 납니다.")))
            except Exception as e:
                err = str(e)
                self.app.after(0, lambda: (st_var.set("✗ 실행 실패"), st_lbl.configure(fg=DANGER),
                                           messagebox.showerror("연결 확인", err[:400])))
        threading.Thread(target=run, daemon=True).start()

    # ── 한글 보안 모듈 ──
    def _build_security(self, inner):
        from ..hwp import security
        c = self._card(inner, "한글 '접근 허용' 경고 없애기")
        tk.Label(c, text="한컴 디벨로퍼 사이트(한글 오토메이션 → 보안 승인 모듈)에서 받은 DLL 파일을 선택하면\n"
                         "등록되어, 미리보기·저장 때 뜨던 '접근 허용' 창이 더 이상 나오지 않습니다.\n"
                         "등록하지 않으면 한글 미리보기가 멈출 수 있습니다(그동안은 빠른 미리보기로 보여 줍니다).",
                 bg=CARD, fg=MUTED, font=FONT_SM, justify="left").pack(anchor="w", padx=14)
        row = tk.Frame(c, bg=CARD)
        row.pack(fill="x", padx=14, pady=(8, 12))
        ok, msg = security.status()
        self._sec_var = tk.StringVar(value=("✓ " if ok else "✗ ") + msg)
        self._sec_lbl = tk.Label(row, textvariable=self._sec_var, bg=CARD, font=FONT, fg=OK if ok else DANGER)
        self._sec_lbl.pack(side="left")
        button(row, "DLL 선택…", self._install_dll).pack(side="right")

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
        ok, msg = security.status()
        self._sec_var.set(("✓ " if ok else "✗ ") + msg)
        self._sec_lbl.configure(fg=OK if ok else DANGER)
        self.app.restart_worker()
        messagebox.showinfo("등록 완료", "보안 승인 모듈을 등록했습니다.\n다음 미리보기부터 '접근 허용' 창이 뜨지 않습니다.")

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
