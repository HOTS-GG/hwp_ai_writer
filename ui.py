"""한큐(HanQ) — tkinter UI."""
import datetime
import os
import re
import shutil
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, scrolledtext, ttk

import settings as cfg
from platform_util import (EN_FAMILY, FONT_PLUS, IS_MAC, IS_WIN, MONO_FAMILY, font, open_path,
                           wheel_units, zoom_modifier)
from settings import (ALL_PROVIDERS, BUILTIN_FORMS_DIR, CACHE_DIR, CLI_PROVIDERS,
                      DEFAULT_MODELS, PROVIDERS)

# ── 색상 / 글꼴 ──────────────────────────────────────────────────────────
BG = "#f4f6fa"
CARD = "#ffffff"
HEADER = "#1f4e96"
ACCENT = "#1f6feb"
ACCENT_DARK = "#1957bd"
TEXT = "#1d2939"
MUTED = "#667085"
BORDER = "#d0d7e2"
SOFT = "#e8eef8"
DANGER = "#d92d20"
PREVIEW_BG = "#8a94a6"
FONT = font(10)
FONT_B = font(10, "bold")
FONT_SM = font(9)
FONT_H = font(12, "bold")

APP_NAME = "한큐"
APP_NAME_EN = "HanQ"
FREE_FORM = "자유 작성 (기본 서식)"


class _FlatButton(tk.Label):
    """맥의 tk.Button은 배경색을 무시하고 회색 기본 버튼으로 그려지므로, Label로 같은 모양을 만든다."""

    def __init__(self, parent, command, **kw):
        super().__init__(parent, **kw)
        self._command = command
        self._bg, self._hover = kw["bg"], kw["activebackground"]
        self.bind("<ButtonRelease-1>", self._click)
        self.bind("<Enter>", lambda e: self._enabled() and super(_FlatButton, self).configure(bg=self._hover))
        self.bind("<Leave>", lambda e: super(_FlatButton, self).configure(bg=self._bg))

    def _enabled(self) -> bool:
        return str(self.cget("state")) != "disabled"

    def _click(self, e):
        inside = 0 <= e.x < self.winfo_width() and 0 <= e.y < self.winfo_height()
        if inside and self._enabled():
            self._command()

    def configure(self, cnf=None, **kw):
        if kw.get("state") == "disabled":
            kw.setdefault("bg", self._bg)
        return super().configure(cnf, **kw)

    config = configure


def button(parent, text, command, kind="normal", **kw):
    colors = {
        "primary": (ACCENT, "#ffffff", ACCENT_DARK),
        "danger": (CARD, DANGER, "#fdecea"),
        "normal": (SOFT, TEXT, "#d8e3f5"),
    }[kind]
    return (_FlatButton if IS_MAC else tk.Button)(parent, text=text, command=command, bg=colors[0], fg=colors[1],
                     activebackground=colors[2], activeforeground=colors[1],
                     relief="flat", bd=0, padx=12, pady=6, cursor="hand2",
                     font=FONT_B if kind == "primary" else FONT, **kw)


def display_name(path: Path) -> str:
    return re.sub(r"^\d+_", "", path.stem)


def safe_filename(s: str) -> str:
    s = re.sub(r'[\\/:*?"<>|\r\n]+', " ", s).strip()
    return re.sub(r"\s+", " ", s)[:80] or "문서"


# ── 미리보기 패널 ─────────────────────────────────────────────────────────

class PreviewPane(tk.Frame):
    """쪽 이미지를 세로로 이어 보여주는 큰 미리보기."""

    def __init__(self, parent, title: str, zoom: int = 100):
        super().__init__(parent, bg=BG)
        self._pages: list[str] = []
        self._photos = []
        self._zoom = zoom

        bar = tk.Frame(self, bg=BG)
        bar.pack(fill="x", pady=(0, 6))
        self._title_var = tk.StringVar(value=title)
        tk.Label(bar, textvariable=self._title_var, bg=BG, fg=TEXT, font=FONT_H).pack(side="left")
        self.actions = tk.Frame(bar, bg=BG)
        self.actions.pack(side="right")
        zoom_box = tk.Frame(bar, bg=BG)
        zoom_box.pack(side="right", padx=(0, 12))
        button(zoom_box, "－", lambda: self.set_zoom(self._zoom - 10)).pack(side="left")
        self._zoom_var = tk.StringVar(value=f"{zoom}%")
        tk.Label(zoom_box, textvariable=self._zoom_var, bg=BG, fg=MUTED, font=FONT_SM,
                 width=5).pack(side="left")
        button(zoom_box, "＋", lambda: self.set_zoom(self._zoom + 10)).pack(side="left")
        self._info_var = tk.StringVar(value="")
        tk.Label(bar, textvariable=self._info_var, bg=BG, fg=MUTED, font=FONT_SM).pack(side="right", padx=8)

        body = tk.Frame(self, bg=PREVIEW_BG, highlightthickness=1, highlightbackground=BORDER)
        body.pack(fill="both", expand=True)
        self.canvas = tk.Canvas(body, bg=PREVIEW_BG, highlightthickness=0)
        sb = ttk.Scrollbar(body, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)
        self.canvas.bind("<Configure>", lambda e: self._layout())
        self.canvas.bind("<Enter>", lambda e: self.canvas.bind_all("<MouseWheel>", self._wheel))
        self.canvas.bind("<Leave>", lambda e: self.canvas.unbind_all("<MouseWheel>"))
        self.show_message("미리볼 문서가 없습니다.")

    def _wheel(self, e):
        if zoom_modifier(e):
            self.set_zoom(self._zoom + (10 if e.delta > 0 else -10))
        else:
            self.canvas.yview_scroll(wheel_units(e), "units")

    def set_title(self, s):
        self._title_var.set(s)

    def set_zoom(self, z):
        self._zoom = max(30, min(250, z))
        self._zoom_var.set(f"{self._zoom}%")
        self._layout()

    def show_message(self, msg: str):
        self._pages = []
        self._text = None
        self._message = msg
        self._info_var.set("")
        self._layout()

    def show_text(self, text: str):
        self._pages = []
        self._text = text
        self._message = None
        self._info_var.set("텍스트 미리보기")
        self._layout()

    def show_pages(self, pages: list[str], note: str = ""):
        self._pages = pages
        self._text = None
        self._message = None if pages else "미리보기 이미지가 없습니다."
        self._info_var.set(f"{len(pages)}쪽 {note}".strip() if pages else note)
        self.canvas.yview_moveto(0)
        self._layout()

    def _layout(self):
        from PIL import Image, ImageTk
        c = self.canvas
        c.delete("all")
        self._photos = []
        cw = max(c.winfo_width(), 200)
        if self._pages:
            y = 16
            for path in self._pages:
                try:
                    im = Image.open(path)
                except OSError:
                    continue
                w = int(im.width * self._zoom / 100)
                h = int(im.height * self._zoom / 100)
                im = im.resize((max(w, 1), max(h, 1)), Image.LANCZOS)
                ph = ImageTk.PhotoImage(im)
                self._photos.append(ph)
                x = max((cw - w) // 2, 8)
                c.create_rectangle(x + 3, y + 3, x + w + 3, y + h + 3, fill="#5b6475", outline="")
                c.create_image(x, y, image=ph, anchor="nw")
                y += h + 16
            c.configure(scrollregion=(0, 0, cw, y))
        elif getattr(self, "_text", None):
            w = min(cw - 40, 820)
            x = (cw - w) // 2
            item = c.create_text(x + 30, 46, text=self._text, anchor="nw", width=w - 60,
                                 font=font(10), fill=TEXT)
            bbox = c.bbox(item)
            c.create_rectangle(x, 16, x + w, bbox[3] + 30, fill="#ffffff", outline="")
            c.tag_raise(item)
            c.configure(scrollregion=(0, 0, cw, bbox[3] + 50))
        else:
            c.create_text(cw // 2, 120, text=getattr(self, "_message", "") or "",
                          fill="#ffffff", font=FONT_H)
            c.configure(scrollregion=(0, 0, cw, 240))


# ── 메인 앱 ───────────────────────────────────────────────────────────────

class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.s = cfg.load()
        # API 키가 없으면, 설치된 Claude Code / Codex를 기본으로 고른다
        if self.s["provider"] not in CLI_PROVIDERS and not self.s["api_keys"].get(self.s["provider"]):
            import llm
            for p in CLI_PROVIDERS:
                if llm.find_cli(p):
                    self.s["provider"] = p
                    break
        self.title(f"{APP_NAME} {APP_NAME_EN}")
        icon = cfg.resource_dir() / "assets" / "icon.ico"
        if icon.exists():
            try:
                self.iconbitmap(default=str(icon))
            except tk.TclError:
                pass
        self.geometry(self.s.get("window_geometry", "1280x820"))
        self.minsize(1000, 720)
        self.configure(bg=BG)

        self._forms: list[dict] = []
        self._extra_forms: list[dict] = []
        self._refs: list[str] = []
        self._result_path: str | None = None
        self._saved_path: str | None = None
        self._busy = False
        self._save_job = None

        from preview import Renderer
        self.renderer = Renderer()

        self._style()
        self._build()
        if IS_WIN:  # 조합 중 글자 크기 문제는 윈도우 입력기에만 있다
            import ime_font
            ime_font.install(self)
        self.reload_forms()
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # ── 공통 ──
    def _style(self):
        # 한글 조합 중 글자는 Tk 기본 글꼴로 그려지므로, 기본 글꼴을 모두 같은 글꼴·크기로 맞춰
        # 입력할 때 글씨가 커졌다 작아졌다 하지 않게 한다
        import tkinter.font as tkfont
        for name in ("TkDefaultFont", "TkTextFont", "TkFixedFont", "TkMenuFont",
                     "TkHeadingFont", "TkCaptionFont", "TkSmallCaptionFont", "TkIconFont", "TkTooltipFont"):
            try:
                tkfont.nametofont(name).configure(family=FONT[0], size=FONT[1])
            except tk.TclError:
                pass
        st = ttk.Style(self)
        st.theme_use("clam")
        # 탭의 점선 포커스 테두리 제거 (Notebook.focus 요소를 뺀 레이아웃)
        st.layout("TNotebook.Tab", [
            ("Notebook.tab", {"sticky": "nswe", "children": [
                ("Notebook.padding", {"side": "top", "sticky": "nswe", "children": [
                    ("Notebook.label", {"side": "top", "sticky": ""})]})]})])
        st.configure(".", background=BG, foreground=TEXT, font=FONT)
        st.configure("TNotebook", background=BG, borderwidth=0, tabmargins=(12, 8, 12, 0))
        st.configure("TNotebook.Tab", background=SOFT, foreground=MUTED, padding=(18, 6),
                     font=FONT, borderwidth=0)
        # clam 테마는 선택 탭의 여백을 줄이므로, 반대로 선택 탭을 키운다
        st.map("TNotebook.Tab",
               background=[("selected", CARD)],
               foreground=[("selected", ACCENT)],
               padding=[("selected", (26, 10))],
               font=[("selected", font(11, "bold"))],
               expand=[("selected", (2, 4, 2, 0))])
        st.configure("TCombobox", fieldbackground=CARD, background=CARD, bordercolor=BORDER,
                     arrowcolor=TEXT, padding=4)
        st.map("TCombobox", fieldbackground=[("readonly", CARD)])
        st.configure("TCheckbutton", background=CARD)
        st.configure("TRadiobutton", background=CARD)
        # 라디오 버튼·체크 상자의 점선 포커스 테두리 제거
        for kind in ("Radiobutton", "Checkbutton"):
            st.layout(f"T{kind}", [
                (f"{kind}.padding", {"sticky": "nswe", "children": [
                    (f"{kind}.indicator", {"side": "left", "sticky": ""}),
                    (f"{kind}.label", {"side": "left", "sticky": "nswe"})]})])
        st.configure("TSpinbox", fieldbackground=CARD, bordercolor=BORDER, padding=3)
        st.configure("Horizontal.TProgressbar", background=ACCENT, troughcolor=SOFT, borderwidth=0)
        self.option_add("*TCombobox*Listbox.font", FONT)

    def _build(self):
        hdr = tk.Frame(self, bg=HEADER, height=52)
        hdr.pack(fill="x")
        tk.Label(hdr, text=APP_NAME, bg=HEADER, fg="#ffffff",
                 font=font(16, "bold")).pack(side="left", padx=(20, 4), pady=10)
        tk.Label(hdr, text=APP_NAME_EN, bg=HEADER, fg="#ffffff",
                 font=(EN_FAMILY, 13 + FONT_PLUS, "bold")).pack(side="left", padx=(0, 12), pady=(12, 8))
        self._status = tk.StringVar(value="준비")
        tk.Label(hdr, textvariable=self._status, bg=HEADER, fg="#d6e4ff", font=FONT).pack(side="right", padx=20)
        self._progress = ttk.Progressbar(self, mode="indeterminate", style="Horizontal.TProgressbar")

        self.nb = ttk.Notebook(self)
        self.nb.pack(fill="both", expand=True)
        self.tab_gen = tk.Frame(self.nb, bg=BG)
        self.tab_tpl = tk.Frame(self.nb, bg=BG)
        self.tab_cfg = tk.Frame(self.nb, bg=BG)
        self.nb.add(self.tab_gen, text="문서 생성")
        self.nb.add(self.tab_tpl, text="템플릿")
        self.nb.add(self.tab_cfg, text="설정")
        self._build_gen()
        self._build_tpl()
        self._build_cfg()

    def status(self, msg):
        self._status.set(msg)

    def card(self, parent, title=None):
        f = tk.Frame(parent, bg=CARD, highlightthickness=1, highlightbackground=BORDER)
        if title:
            tk.Label(f, text=title, bg=CARD, fg=TEXT, font=FONT_B).pack(anchor="w", padx=14, pady=(10, 4))
        return f

    # ── 양식 목록 ──
    def reload_forms(self):
        forms = []
        for p in sorted(BUILTIN_FORMS_DIR.glob("*.hwpx")):
            forms.append({"path": str(p), "name": display_name(p), "builtin": True, "kind": "hwpx"})
        udir = Path(self.s["user_forms_dir"])
        if udir.exists():
            for p in sorted(list(udir.glob("*.hwpx")) + list(udir.glob("*.pdf"))):
                forms.append({"path": str(p), "name": display_name(p), "builtin": False,
                              "kind": p.suffix.lower()[1:]})
        self._forms = forms
        self._refresh_form_combo()
        self._refresh_tpl_list()

    def _all_gen_forms(self):
        return self._forms + self._extra_forms

    @staticmethod
    def _form_label(f):
        tag = "기본" if f["builtin"] else ("PDF" if f["kind"] == "pdf" else "내 양식")
        return f"[{tag}] {f['name']}"

    def _refresh_form_combo(self):
        labels = [FREE_FORM] + [self._form_label(f) for f in self._all_gen_forms()]
        cur = self._form_var.get()
        self._form_combo["values"] = labels
        self._form_var.set(cur if cur in labels else (labels[1] if len(labels) > 1 else FREE_FORM))
        self._on_form_change()

    def _selected_form(self):
        label = self._form_var.get()
        for f in self._all_gen_forms():
            if self._form_label(f) == label:
                return f
        return None

    def base_style_path(self) -> str:
        p = BUILTIN_FORMS_DIR / self.s.get("base_style_form", "")
        if p.exists():
            return str(p)
        return str(sorted(BUILTIN_FORMS_DIR.glob("*.hwpx"))[0])

    # ══ 문서 생성 탭 ═══════════════════════════════════════════════════════
    def _build_gen(self):
        pw = tk.PanedWindow(self.tab_gen, orient="horizontal", bg=BG, sashwidth=6, bd=0)
        pw.pack(fill="both", expand=True, padx=12, pady=12)
        left = tk.Frame(pw, bg=BG)
        right = tk.Frame(pw, bg=BG)
        chat = tk.Frame(pw, bg=BG)
        # 창을 키우면 미리보기만 넓어지고 양옆 패널은 그대로 둔다
        pw.add(left, minsize=320, width=360, stretch="never")
        pw.add(right, minsize=420, stretch="always")
        pw.add(chat, minsize=280, width=330, stretch="never")
        self._build_chat(chat)

        # 양식
        c1 = self.card(left, "1. 양식")
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
                 justify="left", wraplength=360).pack(anchor="w", padx=14, pady=(4, 10))

        # 버튼과 참고 자료를 아래에 먼저 고정해야, 창이 작아질 때 요청 입력칸만 줄어든다
        self._gen_btn = button(left, "문서 생성", self._on_generate, "primary")
        self._gen_btn.configure(pady=10, font=font(11, "bold"))
        self._gen_btn.pack(side="bottom", fill="x", pady=(12, 0))
        c3 = self.card(left, "3. 참고 자료 (선택)")
        c3.pack(side="bottom", fill="x", pady=(10, 0))

        # 요청
        c2 = self.card(left, "2. 작성 요청")
        c2.pack(fill="both", expand=True, pady=(10, 0))
        tk.Label(c2, text="무엇을 쓸지 자유롭게 적어주세요. 날짜·장소·인원·예산 등 사실 정보가 많을수록 정확합니다.",
                 bg=CARD, fg=MUTED, font=FONT_SM, wraplength=360, justify="left").pack(anchor="w", padx=14)
        self._request = scrolledtext.ScrolledText(
            c2, height=3, bg="#fbfcfe", fg=TEXT, insertbackground=TEXT, relief="flat",
            font=FONT, wrap="word", highlightthickness=1, highlightbackground=BORDER,
            highlightcolor=ACCENT, padx=8, pady=6)
        self._request.pack(fill="both", expand=True, padx=14, pady=(6, 12))
        self._request.insert("1.0", "예) 2025. 5. 23.(금) 본교 체육관에서 1학년 120명 대상 과학 탐구 축전을 운영함. "
                                    "부스 6개, 예산 80만 원(재료비), 담당 과학정보부.")

        # 참고 자료 (카드는 위에서 아래쪽에 고정해 둠)
        tk.Label(c3, text="공문, 지난 계획서, 안내문 등 (PDF·HWPX·HWP·TXT)",
                 bg=CARD, fg=MUTED, font=FONT_SM).pack(anchor="w", padx=14)
        self._ref_list = tk.Listbox(c3, height=3, bg="#fbfcfe", fg=TEXT, relief="flat", font=FONT_SM,
                                    highlightthickness=1, highlightbackground=BORDER,
                                    selectbackground=SOFT, selectforeground=TEXT, activestyle="none")
        self._ref_list.pack(fill="x", padx=14, pady=(6, 6))
        rrow = tk.Frame(c3, bg=CARD)
        rrow.pack(fill="x", padx=14, pady=(0, 12))
        button(rrow, "추가…", self._add_ref).pack(side="left")
        button(rrow, "선택 제거", self._remove_ref).pack(side="left", padx=6)

        # 미리보기
        self.gen_preview = PreviewPane(right, "생성 결과", self.s.get("preview_zoom", 100))
        self.gen_preview.pack(fill="both", expand=True)
        a = self.gen_preview.actions
        self._btn_save = button(a, "다른 이름으로 저장…", self._save_as)
        self._btn_open = button(a, "한글로 열기", self._open_result, "primary")
        self._btn_folder = button(a, "폴더 열기", self._open_result_folder)
        for b in (self._btn_folder, self._btn_save, self._btn_open):
            b.pack(side="left", padx=(6, 0))
            b.configure(state="disabled")
        self.gen_preview.show_message("왼쪽에서 양식을 고르고 [문서 생성]을 누르세요.")

    def _on_form_change(self):
        f = self._selected_form()
        if f is None:
            self._form_info.set("양식 없이 요청 내용으로 문서를 구성합니다.\n"
                                f"서식은 설정의 기본 서식({display_name(Path(self.base_style_path()))})을 사용합니다.")
            return
        if f["kind"] == "pdf":
            self._form_info.set("PDF 양식: 항목 구성을 읽어 같은 순서로 내용을 쓰고, 학교 기본 서식으로 .hwpx를 만듭니다.")
            return
        self._form_info.set("양식 분석 중…")

        def run():
            try:
                from hwpx_form import HwpxDoc
                d = HwpxDoc(f["path"])
                d.analyze()
                n_s = sum(1 for k in d.slots if k.startswith("S"))
                msg = (f"빈칸 {n_s}개 · 반복 표 {len(d.tables)}개를 채웁니다. 서식은 원본 그대로 유지됩니다."
                       if d.has_placeholders else
                       f"○ 빈칸이 없는 완성 문서입니다. 문장 {n_s}개를 요청 주제에 맞게 다시 씁니다.")
            except Exception as e:
                msg = f"양식을 읽을 수 없습니다: {e}"
            self.after(0, lambda: self._form_info.set(msg))
        threading.Thread(target=run, daemon=True).start()

    def _open_form_file(self):
        path = filedialog.askopenfilename(title="양식 파일 선택",
                                          filetypes=[("양식", "*.hwpx *.pdf *.hwp"), ("모든 파일", "*.*")])
        if not path:
            return
        if path.lower().endswith(".hwp"):
            self._convert_hwp(path, lambda p: self._use_extra_form(p))
            return
        self._use_extra_form(path)

    def _use_extra_form(self, path):
        p = Path(path)
        f = {"path": str(p), "name": p.stem, "builtin": False, "kind": p.suffix.lower()[1:]}
        self._extra_forms = [x for x in self._extra_forms if x["path"] != f["path"]] + [f]
        self._form_var.set(self._form_label(f))
        self._refresh_form_combo()

    def _add_ref(self):
        paths = filedialog.askopenfilenames(
            title="참고 자료 선택",
            filetypes=[("문서", "*.pdf *.hwpx *.hwp *.txt *.md"), ("모든 파일", "*.*")])
        for p in paths:
            if p not in self._refs:
                self._refs.append(p)
                self._ref_list.insert("end", Path(p).name)

    def _remove_ref(self):
        for i in reversed(self._ref_list.curselection()):
            self._ref_list.delete(i)
            del self._refs[i]

    def _ai_params(self):
        p = self.s["provider"]
        if p in CLI_PROVIDERS:
            import llm
            # CLI 방식은 api_key 자리에 실행 파일 경로를 넣는다
            key = self.s.get("cli_paths", {}).get(p, "").strip() or llm.find_cli(p) or ""
            model = self.s["models"].get(p, "").strip()
        else:
            key = self.s["api_keys"].get(p, "").strip()
            model = self.s["models"].get(p) or DEFAULT_MODELS[p][0]
        return {
            "provider": p,
            "api_key": key,
            "model": model,
            "max_tokens": int(self.s["max_tokens"]),
            "temperature": float(self.s["temperature"]),
            "ref_max_chars": int(self.s["ref_max_chars"]),
            "timeout": int(self.s["request_timeout"]),
            "send_images": bool(self.s.get("ai_sees_screen", True)),
            "max_images": int(self.s.get("max_screen_pages", 6)),
        }

    def _check_ai(self, ai) -> bool:
        if ai["api_key"]:
            return True
        name = ALL_PROVIDERS[ai["provider"]]
        if ai["provider"] in CLI_PROVIDERS:
            messagebox.showwarning("프로그램 없음", f"{name}를 찾을 수 없습니다.\n"
                                                  "설정 탭의 안내대로 설치하거나 실행 파일 위치를 지정해 주세요.")
        else:
            messagebox.showwarning("API 키 필요", f"설정 탭에서 {name} API 키를 입력해주세요.")
        self.nb.select(self.tab_cfg)
        return False

    def _set_busy(self, busy: bool):
        self._busy = busy
        self._gen_btn.configure(state="disabled" if busy else "normal",
                                text="작성 중…" if busy else "문서 생성")
        if busy:
            self._progress.pack(fill="x", after=self.nb.master.winfo_children()[0])
            self._progress.start(12)
        else:
            self._progress.stop()
            self._progress.pack_forget()

    def _on_generate(self):
        if self._busy:
            return
        if self._save_job:
            self.after_cancel(self._save_job)
        self._save_settings()
        ai = self._ai_params()
        if not self._check_ai(ai):
            return
        form = self._selected_form()
        request = self._request.get("1.0", "end").strip()
        refs = list(self._refs)
        info = {k: self.s.get(k, "") for k in ("school_name", "department", "author")}
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        out = str(CACHE_DIR / f"result_{datetime.datetime.now():%Y%m%d_%H%M%S}.hwpx")
        base = self.base_style_path()
        self._set_busy(True)
        self.gen_preview.show_message("AI가 문서를 작성하고 있습니다…")

        def st(m):
            self.after(0, lambda: self.status(m))

        def run():
            import generator
            try:
                if form is None:
                    meta = generator.build_document(base, out, request, refs, info, ai, on_status=st)
                elif form["kind"] == "pdf":
                    meta = generator.build_document(base, out, request, refs, info, ai,
                                                    pdf_form=form["path"], on_status=st)
                else:
                    meta = generator.fill_form(form["path"], out, request, refs, info, ai, on_status=st)
                self.after(0, lambda: self._on_generated(out, meta, form))
            except Exception as e:
                err = str(e)
                self.after(0, lambda msg=err: self._on_gen_error(msg))
        threading.Thread(target=run, daemon=True).start()

    def _on_gen_error(self, msg):
        self._set_busy(False)
        self.status("생성 실패")
        self.gen_preview.show_message("생성에 실패했습니다.")
        messagebox.showerror("생성 오류", msg[:800])

    def _on_generated(self, out, meta, form):
        self._set_busy(False)
        self._result_path = out
        self._saved_path = None
        title = meta.get("title") or (form["name"] if form else "문서")
        title = re.sub(r"^\s*[-\d.]*\s*", "", title)
        self._result_title = title
        for b in (self._btn_save, self._btn_open, self._btn_folder):
            b.configure(state="normal")
        if self.s.get("auto_save", True):
            try:
                self._saved_path = self._save_to(self._default_save_path(title))
                self.status(f"저장됨: {self._saved_path}")
            except OSError as e:
                self.status(f"자동 저장 실패: {e}")
        else:
            self.status("생성 완료 — [다른 이름으로 저장]으로 저장하세요")
        self.gen_preview.set_title(f"생성 결과 — {title}")
        self._start_editing(out, "문서가 완성되었습니다. 고칠 부분이 있으면 말씀해주세요."
                                 + ("\n수정하면 저장된 파일에도 바로 반영됩니다." if self._saved_path else ""))
        if self.s.get("open_after_save") and self._saved_path:
            open_path(self._saved_path)
        self.preview_file(self.gen_preview, self._saved_path or out)

    def _default_save_path(self, title):
        pattern = self.s.get("filename_pattern") or "{title}_{date}"
        name = pattern.format(title=title, date=f"{datetime.date.today():%Y%m%d}",
                              time=f"{datetime.datetime.now():%H%M}")
        folder = Path(self.s.get("output_dir") or Path.home())
        folder.mkdir(parents=True, exist_ok=True)
        p = folder / f"{safe_filename(name)}.hwpx"
        i = 2
        while p.exists():
            p = folder / f"{safe_filename(name)} ({i}).hwpx"
            i += 1
        return p

    def _save_to(self, path) -> str:
        shutil.copyfile(self._result_path, path)
        return str(path)

    def _save_as(self):
        if not self._result_path:
            return
        default = self._default_save_path(getattr(self, "_result_title", "문서"))
        path = filedialog.asksaveasfilename(
            initialdir=str(default.parent), initialfile=default.name, defaultextension=".hwpx",
            filetypes=[("HWPX 문서", "*.hwpx")])
        if path:
            self._saved_path = self._save_to(path)
            self.status(f"저장됨: {self._saved_path}")
            if self.s.get("open_after_save"):
                open_path(self._saved_path)

    def _open_result(self):
        target = self._saved_path or self._result_path
        if target:
            open_path(target)

    def _open_result_folder(self):
        target = self._saved_path or self._result_path
        if target:
            open_path(str(Path(target).parent))

    # ── AI 수정 대화 ──
    def _build_chat(self, parent):
        c = self.card(parent)
        c.pack(fill="both", expand=True)
        tk.Label(c, text="AI에게 수정 요청", bg=CARD, fg=TEXT, font=FONT_B).pack(anchor="w", padx=12, pady=(10, 4))
        top = tk.Frame(c, bg=CARD)
        top.pack(fill="x", padx=12, pady=(0, 6))
        button(top, "파일 열기…", self._open_for_edit).pack(side="left")
        self._undo_btn = button(top, "되돌리기", self._undo_edit)
        self._undo_btn.pack(side="left", padx=(6, 0))
        self._undo_btn.configure(state="disabled")

        # 입력부를 먼저 아래에 고정해야 대화창이 늘어나도 가려지지 않는다
        row = tk.Frame(c, bg=CARD)
        row.pack(side="bottom", fill="x", padx=12, pady=(0, 12))
        tk.Label(row, text="Enter 보내기 · Shift+Enter 줄바꿈", bg=CARD, fg=MUTED, font=FONT_SM).pack(side="left")
        self._send_btn = button(row, "보내기", self._send_chat, "primary")
        self._send_btn.pack(side="right")
        self._chat_in = tk.Text(c, height=3, bg=CARD, fg=TEXT, relief="flat", font=FONT, wrap="word",
                                insertbackground=TEXT, highlightthickness=1, highlightbackground=BORDER,
                                highlightcolor=ACCENT, padx=8, pady=6)
        self._chat_in.pack(side="bottom", fill="x", padx=12, pady=(8, 4))
        self._chat_in.bind("<Return>", self._on_chat_enter)

        self._chat_log = tk.Text(c, bg="#fbfcfe", fg=TEXT, relief="flat", font=FONT, wrap="word",
                                 highlightthickness=1, highlightbackground=BORDER, padx=10, pady=8,
                                 cursor="arrow", spacing1=2, spacing3=6)
        self._chat_log.pack(fill="both", expand=True, padx=12)
        self._chat_log.tag_configure("me", background="#e3edff", lmargin1=40, lmargin2=40,
                                     rmargin=4, spacing1=6)
        self._chat_log.tag_configure("ai", background="#f1f3f6", lmargin1=4, lmargin2=4,
                                     rmargin=40, spacing1=6)
        self._chat_log.tag_configure("who", foreground=MUTED, font=FONT_SM)
        self._chat_log.tag_configure("sys", foreground=MUTED, font=FONT_SM, justify="center", spacing1=6)
        self._chat_log.configure(state="disabled")

        self._versions: list[str] = []
        self._history: list[tuple[str, str]] = []
        self._chat_reset("문서를 생성하거나 [파일 열기]로 HWPX를 불러오면\n여기서 고칠 내용을 말로 요청할 수 있습니다.\n\n"
                         "예) '운영 개요의 장소를 시청각실로 바꿔줘'\n"
                         "    '추진 목적을 3개로 늘려줘'\n"
                         "    '예산 표에 간식비 5만 원 추가하고 합계 고쳐줘'")

    def _chat_add(self, who: str, text: str):
        log = self._chat_log
        log.configure(state="normal")
        if who == "sys":
            log.insert("end", text + "\n", "sys")
        else:
            log.insert("end", ("나" if who == "me" else "AI") + "\n", ("who", who))
            log.insert("end", text.strip() + "\n", who)
        log.configure(state="disabled")
        log.see("end")

    def _chat_reset(self, msg: str):
        self._chat_log.configure(state="normal")
        self._chat_log.delete("1.0", "end")
        self._chat_log.configure(state="disabled")
        self._history = []
        self._chat_add("sys", msg)

    def _on_chat_enter(self, e):
        if e.state & 0x1:
            return None
        self._send_chat()
        return "break"

    def _start_editing(self, path: str, intro: str):
        self._versions = [path]
        self._undo_btn.configure(state="disabled")
        self._chat_reset(intro)

    def _open_for_edit(self):
        path = filedialog.askopenfilename(title="수정할 문서", filetypes=[("HWPX 문서", "*.hwpx")])
        if not path:
            return
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        work = CACHE_DIR / f"edit_{datetime.datetime.now():%Y%m%d_%H%M%S}.hwpx"
        shutil.copyfile(path, work)
        self._result_path = str(work)
        self._saved_path = None
        self._result_title = Path(path).stem
        for b in (self._btn_save, self._btn_open, self._btn_folder):
            b.configure(state="normal")
        self.gen_preview.set_title(f"편집 중 — {Path(path).name}")
        self._start_editing(str(work), f"'{Path(path).name}'을(를) 불러왔습니다.\n"
                                       "원본은 그대로 두고, 고친 결과는 [다른 이름으로 저장]으로 저장하세요.")
        self.preview_file(self.gen_preview, str(work))

    def _send_chat(self):
        text = self._chat_in.get("1.0", "end").strip()
        if not text or self._busy:
            return
        if not self._versions:
            messagebox.showinfo("수정할 문서 없음", "먼저 문서를 생성하거나 [파일 열기]로 HWPX를 불러오세요.")
            return
        ai = self._ai_params()
        if not self._check_ai(ai):
            return
        self._chat_in.delete("1.0", "end")
        self._chat_add("me", text)
        src = self._versions[-1]
        out = str(CACHE_DIR / f"{Path(self._versions[0]).stem}_v{len(self._versions) + 1}.hwpx")
        history = list(self._history)
        self._history.append(("user", text))
        self._set_busy(True)
        self._send_btn.configure(state="disabled")

        def st(m):
            self.after(0, lambda: self.status(m))

        def run():
            import generator
            try:
                page_info = None
                if self.s.get("ai_sees_screen", True):
                    st("한글 화면 읽는 중…")
                    page_info = self.renderer.page_info(src, int(self.s.get("preview_dpi", 96)))
                res = generator.edit_document(src, out, text, history, ai, on_status=st,
                                              page_info=page_info)
                # 결과 확인: 고친 문서를 한글로 다시 열어 쪽 수를 센다
                if page_info and page_info[1] and res.get("changed"):
                    st("결과 확인 중…")
                    _, after = self.renderer.page_info(out, int(self.s.get("preview_dpi", 96)))
                    if after:
                        res["pages"] = (page_info[1].get("pages"), after.get("pages"))
                self.after(0, lambda: self._on_edited(out, res))
            except Exception as e:
                err = str(e)
                self.after(0, lambda msg=err: self._on_edit_error(msg))
        threading.Thread(target=run, daemon=True).start()

    def _on_edit_error(self, msg):
        self._set_busy(False)
        self._send_btn.configure(state="normal")
        self.status("수정 실패")
        self._chat_add("sys", f"오류: {msg[:300]}")

    def _on_edited(self, out, res):
        self._set_busy(False)
        self._send_btn.configure(state="normal")
        reply = res.get("reply") or ("수정했습니다." if res["changed"] else "바꿀 부분을 찾지 못했습니다.")
        self._history.append(("ai", reply))
        self._chat_add("ai", reply)
        if res.get("warning"):
            self._chat_add("sys", "⚠ " + res["warning"])
            self._history.append(("ai", "(프로그램 알림) " + res["warning"]))
        if not res["changed"]:
            self.status("변경 없음")
            return
        self._versions.append(out)
        self._apply_version(out)
        msg = f"{res['changed']}곳 수정 · 버전 {len(self._versions)}"
        if res.get("pages"):
            before, after = res["pages"]
            msg += f" · 쪽 수 {before} → {after}"
            self._history.append(("ai", f"(프로그램 알림) 수정 결과 문서는 {before}쪽에서 {after}쪽이 되었음"))
        self._chat_add("sys", msg)

    def _apply_version(self, path):
        self._result_path = path
        self._undo_btn.configure(state="normal" if len(self._versions) > 1 else "disabled")
        if self._saved_path:
            try:
                shutil.copyfile(path, self._saved_path)
                self.status(f"저장됨: {self._saved_path}")
            except OSError as e:
                self.status(f"저장 실패 (한글에서 파일을 열어두었나요?): {e}")
        self.preview_file(self.gen_preview, path)

    def _undo_edit(self):
        if len(self._versions) <= 1 or self._busy:
            return
        self._versions.pop()
        self._apply_version(self._versions[-1])
        self._chat_add("sys", f"되돌림 · 버전 {len(self._versions)}")

    # ── 미리보기 공통 ──
    def preview_file(self, pane: PreviewPane, path: str):
        if path.lower().endswith(".pdf"):
            try:
                from pdf_reader import extract_pdf_text
                pane.show_text(extract_pdf_text(path)[:20000])
            except Exception as e:
                pane.show_message(f"PDF를 읽을 수 없습니다: {e}")
            return
        if not self.s.get("auto_preview", True):
            pane.show_message("자동 미리보기가 꺼져 있습니다 (설정).")
            return
        pane.show_message("한글로 쪽 이미지를 만드는 중…" if IS_WIN else "미리보기를 여는 중…")
        pane._pending = path

        def done(pages, err):
            def apply():
                if getattr(pane, "_pending", None) != path:
                    return
                if pages:
                    pane.show_pages(pages, "(간이 미리보기 — 실제 한글 화면과 조금 다를 수 있음)" if err else "")
                else:
                    pane.show_message(err or "미리보기를 만들 수 없습니다.")
            self.after(0, apply)
        self.renderer.render(path, int(self.s.get("preview_dpi", 96)), done)

    # ══ 템플릿 탭 ══════════════════════════════════════════════════════════
    def _build_tpl(self):
        pw = tk.PanedWindow(self.tab_tpl, orient="horizontal", bg=BG, sashwidth=6, bd=0)
        pw.pack(fill="both", expand=True, padx=12, pady=12)
        left = tk.Frame(pw, bg=BG)
        right = tk.Frame(pw, bg=BG)
        pw.add(left, minsize=280, width=320, stretch="never")
        pw.add(right, minsize=480, stretch="always")

        c = self.card(left, "양식 목록")
        c.pack(fill="both", expand=True)
        self._tpl_list = tk.Listbox(c, bg=CARD, fg=TEXT, relief="flat", font=FONT,
                                    selectbackground=SOFT, selectforeground=ACCENT,
                                    activestyle="none", highlightthickness=0, bd=0)
        self._tpl_list.pack(fill="both", expand=True, padx=8, pady=(0, 8))
        self._tpl_list.bind("<<ListboxSelect>>", lambda e: self._on_tpl_select())
        self._tpl_list.bind("<Double-Button-1>", lambda e: self._use_tpl())
        self._tpl_info = tk.StringVar(value="")
        tk.Label(c, textvariable=self._tpl_info, bg=CARD, fg=MUTED, font=FONT_SM,
                 justify="left", wraplength=280).pack(anchor="w", padx=14, pady=(0, 10))

        btns = tk.Frame(left, bg=BG)
        btns.pack(fill="x", pady=(10, 0))
        button(btns, "이 양식으로 작성", self._use_tpl, "primary").pack(fill="x")
        row = tk.Frame(btns, bg=BG)
        row.pack(fill="x", pady=(6, 0))
        button(row, "양식 추가…", self._add_tpl).pack(side="left", fill="x", expand=True)
        button(row, "삭제", self._del_tpl, "danger").pack(side="left", padx=(6, 0))
        button(btns, "내 양식 폴더 열기", self._open_forms_dir).pack(fill="x", pady=(6, 0))
        tk.Label(btns, text="HWPX·HWP·PDF 양식을 추가할 수 있습니다.\n○○○○ 같은 빈칸이 있으면 그 자리만 채웁니다.",
                 bg=BG, fg=MUTED, font=FONT_SM, justify="left").pack(anchor="w", pady=(8, 0))

        self.tpl_preview = PreviewPane(right, "미리보기", self.s.get("preview_zoom", 100))
        self.tpl_preview.pack(fill="both", expand=True)

    def _refresh_tpl_list(self):
        if not hasattr(self, "_tpl_list"):
            return
        self._tpl_list.delete(0, "end")
        for f in self._forms:
            self._tpl_list.insert("end", "  " + self._form_label(f))

    def _sel_tpl(self):
        sel = self._tpl_list.curselection()
        return self._forms[sel[0]] if sel else None

    def _on_tpl_select(self):
        f = self._sel_tpl()
        if not f:
            return
        self.tpl_preview.set_title(f"미리보기 — {f['name']}")
        info = "기본 제공 양식" if f["builtin"] else f"내 양식 · {Path(f['path']).name}"
        self._tpl_info.set(info)
        self.preview_file(self.tpl_preview, f["path"])

    def _use_tpl(self):
        f = self._sel_tpl()
        if not f:
            return
        self._form_var.set(self._form_label(f))
        self._on_form_change()
        self.nb.select(self.tab_gen)

    def _add_tpl(self):
        paths = filedialog.askopenfilenames(title="양식 추가",
                                            filetypes=[("양식", "*.hwpx *.hwp *.pdf"), ("모든 파일", "*.*")])
        if not paths:
            return
        udir = Path(self.s["user_forms_dir"])
        udir.mkdir(parents=True, exist_ok=True)
        for p in paths:
            if p.lower().endswith(".hwp"):
                self._convert_hwp(p, lambda out: self.reload_forms(), udir)
            else:
                shutil.copy(p, udir / Path(p).name)
        self.reload_forms()
        self.status(f"양식 {len(paths)}개 추가됨")

    def _convert_hwp(self, src, on_done, out_dir: Path | None = None):
        if not IS_WIN:
            messagebox.showerror("변환 불가", "HWP 파일을 HWPX로 바꾸는 기능은 윈도우용 한글이 있어야 합니다.\n"
                                          "맥용 한글에서 [다른 이름으로 저장 → HWPX]로 바꾼 뒤 추가해 주세요.")
            return
        out_dir = out_dir or CACHE_DIR
        out_dir.mkdir(parents=True, exist_ok=True)
        out = str(out_dir / (Path(src).stem + ".hwpx"))
        self.status("HWP → HWPX 변환 중…")

        def run():
            import pythoncom
            pythoncom.CoInitialize()
            try:
                import win32com.client
                hwp = win32com.client.DispatchEx("HWPFrame.HwpObject")
                import hwp_security
                hwp_security.register(hwp)
                try:
                    hwp.XHwpWindows.Item(0).Visible = False
                except Exception:
                    pass
                hwp.Open(os.path.abspath(src), "HWP", "forceopen:true")
                hwp.SaveAs(out, "HWPX", "")
                hwp.Clear(1)
                hwp.Quit()
                self.after(0, lambda: (self.status("변환 완료"), on_done(out)))
            except Exception as e:
                err = str(e)
                self.after(0, lambda: messagebox.showerror(
                    "변환 실패", f"HWP 파일을 HWPX로 바꾸려면 한글 프로그램이 필요합니다.\n\n{err}"))
            finally:
                pythoncom.CoUninitialize()
        threading.Thread(target=run, daemon=True).start()

    def _del_tpl(self):
        f = self._sel_tpl()
        if not f:
            return
        if f["builtin"]:
            messagebox.showinfo("삭제 불가", "기본 제공 양식은 삭제할 수 없습니다.")
            return
        if messagebox.askyesno("양식 삭제", f"'{f['name']}' 양식을 내 양식 폴더에서 삭제할까요?"):
            Path(f["path"]).unlink(missing_ok=True)
            self.reload_forms()
            self.tpl_preview.show_message("미리볼 양식을 선택하세요.")

    def _open_forms_dir(self):
        d = Path(self.s["user_forms_dir"])
        d.mkdir(parents=True, exist_ok=True)
        open_path(str(d))

    # ══ 설정 탭 ════════════════════════════════════════════════════════════
    def _build_cfg(self):
        outer = tk.Frame(self.tab_cfg, bg=BG)
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
        self._vars: dict[str, tk.Variable] = {}

        # AI
        c = self.card(inner, "AI 제공자")
        c.pack(fill="x", padx=24, pady=(18, 0))
        tk.Label(c, text="사용할 제공자를 고르세요. 키와 모델은 제공자마다 따로 저장됩니다.",
                 bg=CARD, fg=MUTED, font=FONT_SM).pack(anchor="w", padx=14)
        grid = tk.Frame(c, bg=CARD)
        grid.pack(fill="x", padx=14, pady=(8, 12))
        grid.columnconfigure(2, weight=1)
        grid.columnconfigure(4, weight=1)
        self._provider_var = tk.StringVar(value=self.s["provider"])
        self._provider_var.trace_add("write", lambda *a: self._set("provider", self._provider_var.get()))
        for col, head in enumerate(["사용", "제공자", "API 키", "", "모델", ""]):
            tk.Label(grid, text=head, bg=CARD, fg=MUTED, font=FONT_SM).grid(row=0, column=col, sticky="w", padx=4)
        self._model_combos = {}
        for r, (pid, pname) in enumerate(PROVIDERS.items(), start=1):
            ttk.Radiobutton(grid, variable=self._provider_var, value=pid).grid(row=r, column=0, padx=4, pady=4)
            tk.Label(grid, text=pname, bg=CARD, fg=TEXT, font=FONT).grid(row=r, column=1, sticky="w", padx=4)
            kv = tk.StringVar(value=self.s["api_keys"].get(pid, ""))
            kv.trace_add("write", lambda *a, p=pid, v=kv: self._set_nested("api_keys", p, v.get().strip()))
            ent = tk.Entry(grid, textvariable=kv, show="•", bg="#fbfcfe", fg=TEXT, relief="flat", font=FONT,
                           highlightthickness=1, highlightbackground=BORDER, highlightcolor=ACCENT)
            ent.grid(row=r, column=2, sticky="ew", padx=4, ipady=4)
            tk.Button(grid, text="보기", bg=CARD, fg=MUTED, relief="flat", font=FONT_SM, cursor="hand2",
                      command=lambda e=ent: e.configure(show="" if e.cget("show") else "•")
                      ).grid(row=r, column=3, padx=2)
            mv = tk.StringVar(value=self.s["models"].get(pid) or DEFAULT_MODELS[pid][0])
            mv.trace_add("write", lambda *a, p=pid, v=mv: self._set_nested("models", p, v.get().strip()))
            cb = ttk.Combobox(grid, textvariable=mv, font=FONT,
                              values=self.s.get("model_lists", {}).get(pid) or DEFAULT_MODELS[pid])
            cb.grid(row=r, column=4, sticky="ew", padx=4)
            self._model_combos[pid] = cb
            button(grid, "목록 갱신", lambda p=pid: self._refresh_models(p)).grid(row=r, column=5, padx=4)

        # API 키 없이: Claude Code / Codex
        self._build_cli_card(inner)

        # 기본 정보
        c = self.card(inner, "기본 정보 (문서에 자동 반영)")
        c.pack(fill="x", padx=24, pady=(14, 0))
        self._entry(c, "학교(기관)명", "school_name")
        self._entry(c, "작성 부서", "department", "예) 과학정보부")
        self._entry(c, "작성자", "author", "예) 교사 홍길동", last=True)

        # 저장
        c = self.card(inner, "저장")
        c.pack(fill="x", padx=24, pady=(14, 0))
        self._entry(c, "저장 폴더", "output_dir", browse="dir")
        self._entry(c, "파일 이름 규칙", "filename_pattern", "{title}=제목, {date}=날짜, {time}=시각")
        self._check(c, "생성하면 저장 폴더에 자동 저장", "auto_save")
        self._check(c, "저장 후 한글로 바로 열기", "open_after_save", last=True)

        # 양식
        c = self.card(inner, "양식")
        c.pack(fill="x", padx=24, pady=(14, 0))
        self._entry(c, "내 양식 폴더", "user_forms_dir", browse="dir", on_change=self.reload_forms)
        row = self._row(c, "기본 서식", "PDF 양식·자유 작성 문서에 쓰는 서식")
        styles = [p.name for p in sorted(BUILTIN_FORMS_DIR.glob("*.hwpx"))]
        v = tk.StringVar(value=self.s.get("base_style_form"))
        v.trace_add("write", lambda *a: (self._set("base_style_form", v.get()), self._on_form_change()))
        ttk.Combobox(row, textvariable=v, values=styles, state="readonly", font=FONT).pack(fill="x")
        tk.Frame(c, bg=CARD, height=8).pack()

        # 미리보기
        c = self.card(inner, "미리보기")
        c.pack(fill="x", padx=24, pady=(14, 0))
        self._check(c, "한글로 쪽 이미지 미리보기 (한글 설치 필요)", "auto_preview")
        self._spin(c, "해상도 (DPI)", "preview_dpi", 72, 200, 12)
        self._spin(c, "기본 확대율 (%)", "preview_zoom", 30, 250, 10, last=True)

        # 한글 보안 모듈 (윈도우용 한글 COM 전용)
        if IS_WIN:
            import hwp_security
            c = self.card(inner, "한글 '접근 허용' 경고 없애기")
            c.pack(fill="x", padx=24, pady=(14, 0))
            tk.Label(c, text="한컴 디벨로퍼 사이트(한글 오토메이션 → 보안 승인 모듈)에서 받은 DLL 파일을 선택하면\n"
                             "등록되어, 미리보기·저장 때 뜨던 '접근 허용' 창이 더 이상 나오지 않습니다.",
                     bg=CARD, fg=MUTED, font=FONT_SM, justify="left").pack(anchor="w", padx=14)
            row = tk.Frame(c, bg=CARD)
            row.pack(fill="x", padx=14, pady=(8, 12))
            ok, msg = hwp_security.status()
            self._sec_var = tk.StringVar(value=("✓ " if ok else "✗ ") + msg)
            self._sec_lbl = tk.Label(row, textvariable=self._sec_var, bg=CARD, font=FONT,
                                     fg="#067647" if ok else DANGER)
            self._sec_lbl.pack(side="left")
            button(row, "DLL 선택…", self._install_security_dll).pack(side="right")

        # 고급
        c = self.card(inner, "AI 고급 옵션")
        c.pack(fill="x", padx=24, pady=(14, 0))
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
        button(bottom, "미리보기 캐시 비우기", self._clear_cache).pack(side="right")
        tk.Label(bottom, text=f"한큐 HanQ  v{cfg.APP_VERSION}", bg=BG, fg=MUTED, font=FONT_SM
                 ).pack(side="right", padx=12)

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

    def _build_cli_card(self, inner):
        import llm
        c = self.card(inner, "API 키 없이 쓰기 — 구독 계정 연결")
        c.pack(fill="x", padx=24, pady=(14, 0))
        tk.Label(c, text="API 키가 없어도, 컴퓨터에 Claude Code나 Codex를 설치하고 로그인해 두면 그 구독으로 한큐를 쓸 수 있습니다.\n"
                         "위의 API 방식보다 느릴 수 있습니다(한 번에 30초~2분).",
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

            desc, how = self.CLI_GUIDE[pid]
            tk.Label(box, text=desc, bg=CARD, fg=TEXT, font=FONT_SM).pack(anchor="w", padx=12)
            tk.Label(box, text=how, bg=CARD, fg=MUTED, font=(MONO_FAMILY, 9 + FONT_PLUS), justify="left"
                     ).pack(anchor="w", padx=12, pady=(2, 4))

            row = tk.Frame(box, bg=CARD)
            row.pack(fill="x", padx=12, pady=(0, 10))
            tk.Label(row, text="실행 파일", bg=CARD, fg=TEXT, font=FONT_SM, width=8, anchor="w").pack(side="left")
            pv = tk.StringVar(value=self.s.get("cli_paths", {}).get(pid, ""))
            pv.trace_add("write", lambda *a, p=pid, v=pv: self._set_nested("cli_paths", p, v.get().strip()))
            tk.Entry(row, textvariable=pv, bg="#fbfcfe", fg=TEXT, relief="flat", font=FONT_SM,
                     highlightthickness=1, highlightbackground=BORDER, highlightcolor=ACCENT
                     ).pack(side="left", fill="x", expand=True, ipady=3)
            button(row, "찾기…", lambda v=pv: (lambda f: f and v.set(f))(filedialog.askopenfilename(
                title="실행 파일 선택",
                filetypes=[("실행 파일", "*.exe *.cmd"), ("모든 파일", "*.*")] if IS_WIN else [("모든 파일", "*")]))
                   ).pack(side="left", padx=(6, 0))
            tk.Label(row, text="모델", bg=CARD, fg=TEXT, font=FONT_SM).pack(side="left", padx=(12, 4))
            mv = tk.StringVar(value=self.s["models"].get(pid, ""))
            mv.trace_add("write", lambda *a, p=pid, v=mv: self._set_nested("models", p, v.get().strip()))
            ttk.Combobox(row, textvariable=mv, width=12, font=FONT_SM,
                         values=["", "sonnet", "opus", "haiku"] if pid == "claude_code" else ["", "gpt-5", "gpt-5-codex"]
                         ).pack(side="left")
            self._check_cli(pid, verbose=False)
        tk.Label(c, text="실행 파일 칸을 비워 두면 자동으로 찾습니다. 모델 칸을 비워 두면 그 프로그램의 기본 모델을 씁니다.",
                 bg=CARD, fg=MUTED, font=FONT_SM).pack(anchor="w", padx=14, pady=(0, 10))

    def _check_cli(self, pid, verbose: bool):
        import llm
        st_var, st_lbl = self._cli_status[pid]
        path = self.s.get("cli_paths", {}).get(pid, "").strip() or llm.find_cli(pid)
        if not path:
            st_var.set("✗ 설치되지 않음")
            st_lbl.configure(fg=DANGER)
            if verbose:
                messagebox.showinfo("찾을 수 없음", f"{CLI_PROVIDERS[pid]}가 설치되어 있지 않습니다.\n"
                                                 "아래 안내대로 설치한 뒤 다시 [연결 확인]을 눌러 주세요.")
            return
        if not verbose:
            where = ("Claude 앱에 포함됨" if "Claude-Data" in path else
                     "Codex 앱에 포함됨" if "OpenAI" in path else "설치됨")
            st_var.set(f"● 자동으로 찾음 ({where})")
            st_lbl.configure(fg="#067647")
            return

        def run():
            try:
                ver = llm.cli_version(pid, path)
                self.after(0, lambda: (st_var.set(f"✓ 연결됨 {ver[:40]}"), st_lbl.configure(fg="#067647"),
                                       messagebox.showinfo("연결 확인", f"{CLI_PROVIDERS[pid]} 사용 가능\n{path}\n{ver}\n\n"
                                                                    "로그인이 안 되어 있으면 첫 생성 때 오류가 납니다.")))
            except Exception as e:
                err = str(e)
                self.after(0, lambda: (st_var.set("✗ 실행 실패"), st_lbl.configure(fg=DANGER),
                                       messagebox.showerror("연결 확인", err[:400])))
        threading.Thread(target=run, daemon=True).start()

    def _row(self, parent, label, hint=None):
        row = tk.Frame(parent, bg=CARD)
        row.pack(fill="x", padx=14, pady=4)
        lab = tk.Frame(row, bg=CARD, width=200)
        lab.pack(side="left", fill="y")
        lab.pack_propagate(False)
        tk.Label(lab, text=label, bg=CARD, fg=TEXT, font=FONT).pack(anchor="w")
        if hint:
            tk.Label(lab, text=hint, bg=CARD, fg=MUTED, font=font(8),
                     wraplength=190, justify="left").pack(anchor="w")
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
            self._set(key, v.get())
            if on_change:
                self.after(300, on_change)
        v.trace_add("write", changed)
        tk.Entry(body, textvariable=v, bg="#fbfcfe", fg=TEXT, relief="flat", font=FONT,
                 highlightthickness=1, highlightbackground=BORDER, highlightcolor=ACCENT
                 ).pack(side="left", fill="x", expand=True, ipady=4)
        if browse == "dir":
            button(body, "찾기…", lambda: (lambda d: d and v.set(d))(
                filedialog.askdirectory(initialdir=v.get() or None))).pack(side="left", padx=(6, 0))
        if last:
            tk.Frame(parent, bg=CARD, height=8).pack()

    def _check(self, parent, label, key, last=False):
        v = tk.BooleanVar(value=bool(self.s.get(key, True)))
        v.trace_add("write", lambda *a: self._set(key, v.get()))
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
            self._set(key, max(lo, min(hi, val)))
        v.trace_add("write", changed)
        ttk.Spinbox(body, from_=lo, to=hi, increment=step, textvariable=v, width=10,
                    font=FONT).pack(side="left")
        if last:
            tk.Frame(parent, bg=CARD, height=8).pack()

    def _set(self, key, value):
        self.s[key] = value
        self._schedule_save()

    def _set_nested(self, key, sub, value):
        self.s.setdefault(key, {})[sub] = value
        self._schedule_save()

    def _schedule_save(self):
        if self._save_job:
            self.after_cancel(self._save_job)
        self._save_job = self.after(400, self._save_settings)

    def _save_settings(self):
        self._save_job = None
        try:
            cfg.save(self.s)
            if hasattr(self, "_saved_lbl"):
                self._saved_lbl.set(f"저장됨 ({datetime.datetime.now():%H:%M:%S})")
        except Exception as e:
            self.status("설정 저장 실패")
            messagebox.showerror("설정 저장 실패", f"{cfg.SETTINGS_FILE}\n\n{e}")

    def _refresh_models(self, pid):
        key = self.s["api_keys"].get(pid, "").strip()
        self.status(f"{PROVIDERS[pid]} 모델 목록 불러오는 중…")

        def run():
            import llm
            try:
                models = llm.list_models(pid, key)
                self.after(0, lambda: self._models_loaded(pid, models))
            except Exception as e:
                err = str(e)
                self.after(0, lambda: (self.status("모델 목록 실패"),
                                       messagebox.showerror("모델 목록", err[:400])))
        threading.Thread(target=run, daemon=True).start()

    def _models_loaded(self, pid, models):
        self._model_combos[pid]["values"] = models
        self.s.setdefault("model_lists", {})[pid] = models
        self._schedule_save()
        self.status(f"{PROVIDERS[pid]} 모델 {len(models)}개")

    def _install_security_dll(self):
        import hwp_security
        path = filedialog.askopenfilename(title="한글 보안 승인 모듈 DLL 선택",
                                          filetypes=[("DLL", "*.dll")])
        if not path:
            return
        try:
            hwp_security.install(path)
        except OSError as e:
            messagebox.showerror("등록 실패", str(e))
            return
        ok, msg = hwp_security.status()
        self._sec_var.set(("✓ " if ok else "✗ ") + msg)
        self._sec_lbl.configure(fg="#067647" if ok else DANGER)
        # 이미 떠 있는 미리보기용 한글을 새로 띄워야 모듈이 적용된다
        self.renderer.shutdown()
        from preview import Renderer
        self.renderer = Renderer()
        messagebox.showinfo("등록 완료", "보안 승인 모듈을 등록했습니다.\n다음 미리보기부터 '접근 허용' 창이 뜨지 않습니다.")

    def _clear_cache(self):
        shutil.rmtree(CACHE_DIR, ignore_errors=True)
        self.status("미리보기 캐시를 비웠습니다.")

    def _on_close(self):
        self.s["window_geometry"] = self.geometry()
        self._save_settings()
        self.renderer.shutdown()
        self.destroy()
