"""
tkinter UI for HWP AI Document Generator.
"""
import os
import sys
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext, ttk
from pathlib import Path


# ── Colour palette ─────────────────────────────────────────────────────────
BG_DARK   = "#1e1e2e"
BG_PANEL  = "#2a2a3e"
BG_INPUT  = "#313145"
FG_WHITE  = "#cdd6f4"
FG_MUTED  = "#6c7086"
ACCENT    = "#89b4fa"
ACCENT2   = "#a6e3a1"
WARN      = "#f38ba8"
BORDER    = "#45475a"
BTN_BG    = "#313145"
BTN_ACT   = "#45475a"
FONT_UI   = ("Malgun Gothic", 10)
FONT_MONO = ("Consolas", 10)
FONT_BIG  = ("Malgun Gothic", 12, "bold")
FONT_SM   = ("Malgun Gothic", 9)


def styled_button(parent, text, command, width=None, accent=False, danger=False):
    bg = ACCENT if accent else (WARN if danger else BTN_BG)
    fg = BG_DARK if (accent or danger) else FG_WHITE
    kwargs = dict(text=text, command=command, bg=bg, fg=fg,
                  activebackground=ACCENT2 if accent else BTN_ACT,
                  activeforeground=BG_DARK if accent else FG_WHITE,
                  relief="flat", bd=0, padx=10, pady=6, cursor="hand2",
                  font=FONT_UI)
    if width:
        kwargs["width"] = width
    return tk.Button(parent, **kwargs)


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("HWP AI 문서 생성기")
        self.geometry("1100x750")
        self.minsize(900, 600)
        self.configure(bg=BG_DARK)
        self.resizable(True, True)

        # Lazy-loaded modules
        self._gen = None
        self._tmgr = None
        self._templates: list[dict] = []
        self._provider = "claude"  # 'claude' | 'gemini'

        self._build_ui()
        self._load_templates()

    # ── Lazy loaders ──────────────────────────────────────────────────────

    @property
    def gen(self):
        if self._gen is None:
            self._gen = self._make_generator()
        return self._gen

    def _make_generator(self):
        from ai_generator import create_generator
        model = self._model_var.get()
        if self._provider == "gemini":
            key = self._gemini_key_var.get().strip() or os.environ.get("GEMINI_API_KEY", "")
            return create_generator("gemini", key, model)
        elif self._provider == "openrouter":
            key = self._openrouter_key_var.get().strip() or os.environ.get("OPENROUTER_API_KEY", "")
            return create_generator("openrouter", key, model)
        else:
            key = self._apikey_var.get().strip() or os.environ.get("ANTHROPIC_API_KEY", "")
            return create_generator("claude", key, model)

    @property
    def tmgr(self):
        if self._tmgr is None:
            from template_manager import TemplateManager
            self._tmgr = TemplateManager()
        return self._tmgr

    # ── UI Construction ────────────────────────────────────────────────────

    def _build_ui(self):
        # ── Header ──────────────────────────────────────────────────────
        hdr = tk.Frame(self, bg=BG_PANEL, pady=12)
        hdr.pack(fill="x")
        tk.Label(hdr, text="✦  HWP AI 문서 생성기", bg=BG_PANEL, fg=ACCENT,
                 font=("Malgun Gothic", 16, "bold")).pack(side="left", padx=20)
        self._status_var = tk.StringVar(value="준비")
        tk.Label(hdr, textvariable=self._status_var, bg=BG_PANEL,
                 fg=FG_MUTED, font=FONT_SM).pack(side="right", padx=20)

        # ── Main paned layout ──────────────────────────────────────────
        pw = tk.PanedWindow(self, orient="horizontal", bg=BG_DARK,
                            sashwidth=4, sashrelief="flat")
        pw.pack(fill="both", expand=True, padx=8, pady=8)

        left = tk.Frame(pw, bg=BG_DARK)
        right = tk.Frame(pw, bg=BG_DARK)
        pw.add(left, minsize=380, width=420)
        pw.add(right, minsize=400)

        self._build_left(left)
        self._build_right(right)

    def _build_left(self, parent):
        nb = ttk.Notebook(parent)
        nb.pack(fill="both", expand=True)
        self._style_notebook(nb)

        gen_frame = tk.Frame(nb, bg=BG_DARK)
        tpl_frame = tk.Frame(nb, bg=BG_DARK)
        cfg_frame = tk.Frame(nb, bg=BG_DARK)
        nb.add(gen_frame, text="  생성  ")
        nb.add(tpl_frame, text="  템플릿  ")
        nb.add(cfg_frame, text="  설정  ")

        self._build_gen_tab(gen_frame)
        self._build_template_tab(tpl_frame)
        self._build_config_tab(cfg_frame)

    def _style_notebook(self, nb):
        style = ttk.Style()
        style.theme_use("default")
        style.configure("TNotebook", background=BG_DARK, borderwidth=0)
        style.configure("TNotebook.Tab", background=BG_PANEL, foreground=FG_MUTED,
                        padding=[12, 6], font=FONT_UI)
        style.map("TNotebook.Tab",
                  background=[("selected", BG_INPUT)],
                  foreground=[("selected", ACCENT)])

    def _label(self, parent, text, small=False):
        return tk.Label(parent, text=text, bg=BG_DARK,
                        fg=FG_MUTED if small else FG_WHITE,
                        font=FONT_SM if small else FONT_UI, anchor="w")

    def _entry_row(self, parent, label_text, var, pady=4):
        row = tk.Frame(parent, bg=BG_DARK)
        row.pack(fill="x", pady=(pady, 0))
        self._label(row, label_text).pack(anchor="w")
        e = tk.Entry(row, textvariable=var, bg=BG_INPUT, fg=FG_WHITE,
                     insertbackground=FG_WHITE, relief="flat", font=FONT_UI,
                     highlightthickness=1, highlightbackground=BORDER,
                     highlightcolor=ACCENT)
        e.pack(fill="x", ipady=4)
        return e

    # ── Generation Tab ──────────────────────────────────────────────────

    def _build_gen_tab(self, parent):
        pad = dict(padx=12, pady=6)

        scroll = tk.Frame(parent, bg=BG_DARK)
        scroll.pack(fill="both", expand=True)
        inner = tk.Frame(scroll, bg=BG_DARK)
        inner.pack(fill="both", expand=True, **pad)

        # Template selector
        self._label(inner, "템플릿 선택").pack(anchor="w", pady=(0, 2))
        self._tpl_var = tk.StringVar()
        self._tpl_combo = ttk.Combobox(inner, textvariable=self._tpl_var,
                                       state="readonly", font=FONT_UI)
        self._tpl_combo.pack(fill="x")
        self._tpl_combo.bind("<<ComboboxSelected>>", self._on_template_selected)

        # Document type
        self._label(inner, "문서 유형").pack(anchor="w", pady=(8, 2))
        self._dtype_var = tk.StringVar(value="보고서")
        from ai_generator import DOC_TYPE_PROMPTS
        doc_types = list(DOC_TYPE_PROMPTS.keys())
        self._dtype_combo = ttk.Combobox(inner, textvariable=self._dtype_var,
                                         values=doc_types, state="readonly", font=FONT_UI)
        self._dtype_combo.pack(fill="x")

        # Input type
        self._label(inner, "입력 방식").pack(anchor="w", pady=(8, 2))
        self._itype_var = tk.StringVar(value="keywords")
        itype_frame = tk.Frame(inner, bg=BG_DARK)
        itype_frame.pack(fill="x")
        for val, lbl in [("keywords", "키워드"), ("data", "데이터/정보"), ("text", "기존 텍스트")]:
            rb = tk.Radiobutton(itype_frame, text=lbl, variable=self._itype_var,
                                value=val, bg=BG_DARK, fg=FG_WHITE,
                                selectcolor=BG_INPUT, activebackground=BG_DARK,
                                activeforeground=ACCENT, font=FONT_UI)
            rb.pack(side="left", padx=(0, 10))

        # Input area
        self._label(inner, "입력 내용").pack(anchor="w", pady=(8, 2))
        self._input_text = scrolledtext.ScrolledText(
            inner, height=7, bg=BG_INPUT, fg=FG_WHITE,
            insertbackground=FG_WHITE, relief="flat", font=FONT_MONO,
            wrap="word", highlightthickness=1,
            highlightbackground=BORDER, highlightcolor=ACCENT)
        self._input_text.pack(fill="both", expand=True)
        self._input_text.insert("1.0", "예) 2024년 하반기 매출 분석, 전년 대비 15% 증가, 온라인 채널 확대")

        # Extra instructions
        self._label(inner, "추가 지시사항 (선택)").pack(anchor="w", pady=(6, 2))
        self._extra_var = tk.StringVar()
        tk.Entry(inner, textvariable=self._extra_var, bg=BG_INPUT, fg=FG_WHITE,
                 insertbackground=FG_WHITE, relief="flat", font=FONT_UI,
                 highlightthickness=1, highlightbackground=BORDER,
                 highlightcolor=ACCENT).pack(fill="x", ipady=4)

        # Buttons
        btn_row = tk.Frame(inner, bg=BG_DARK)
        btn_row.pack(fill="x", pady=(10, 0))
        self._gen_btn = styled_button(btn_row, "✦ AI 생성", self._on_generate, accent=True)
        self._gen_btn.pack(side="left", fill="x", expand=True, padx=(0, 4))
        styled_button(btn_row, "지우기", self._clear_output, width=8).pack(side="left")

        # Field values panel (shown when template has fields)
        self._fields_frame = tk.LabelFrame(inner, text=" 템플릿 필드값 ",
                                           bg=BG_DARK, fg=ACCENT, font=FONT_SM,
                                           bd=1, relief="solid")
        self._field_entries: dict[str, tk.StringVar] = {}

    # ── Template Tab ───────────────────────────────────────────────────

    def _build_template_tab(self, parent):
        pad = dict(padx=12, pady=6)
        inner = tk.Frame(parent, bg=BG_DARK)
        inner.pack(fill="both", expand=True, **pad)

        self._label(inner, "템플릿 목록").pack(anchor="w")
        list_frame = tk.Frame(inner, bg=BG_DARK)
        list_frame.pack(fill="both", expand=True, pady=(4, 0))

        scrollbar = tk.Scrollbar(list_frame)
        scrollbar.pack(side="right", fill="y")
        self._tpl_listbox = tk.Listbox(list_frame, bg=BG_INPUT, fg=FG_WHITE,
                                        selectbackground=ACCENT, selectforeground=BG_DARK,
                                        font=FONT_UI, relief="flat", activestyle="none",
                                        yscrollcommand=scrollbar.set)
        self._tpl_listbox.pack(side="left", fill="both", expand=True)
        scrollbar.config(command=self._tpl_listbox.yview)
        self._tpl_listbox.bind("<<ListboxSelect>>", self._on_tpl_list_select)

        # Preview
        self._label(inner, "미리보기").pack(anchor="w", pady=(8, 2))
        self._tpl_preview = scrolledtext.ScrolledText(
            inner, height=8, bg=BG_PANEL, fg=FG_WHITE, relief="flat",
            font=FONT_MONO, wrap="word", state="disabled")
        self._tpl_preview.pack(fill="both", expand=True)

        # Buttons
        btn_row = tk.Frame(inner, bg=BG_DARK)
        btn_row.pack(fill="x", pady=(8, 0))
        styled_button(btn_row, "새 템플릿", self._new_template, accent=True).pack(side="left", padx=(0, 4))
        styled_button(btn_row, "HWP 가져오기", self._import_hwp).pack(side="left", padx=(0, 4))
        styled_button(btn_row, "삭제", self._delete_template, danger=True).pack(side="right")

    # ── Config Tab ─────────────────────────────────────────────────────

    def _build_config_tab(self, parent):
        from ai_generator import CLAUDE_MODELS, GEMINI_MODELS
        inner = tk.Frame(parent, bg=BG_DARK)
        inner.pack(fill="both", expand=True, padx=12, pady=12)

        # ── Provider selector ──
        self._label(inner, "AI 제공자").pack(anchor="w")
        self._provider_var = tk.StringVar(value="claude")
        prov_row = tk.Frame(inner, bg=BG_DARK)
        prov_row.pack(fill="x", pady=(2, 8))
        for val, lbl in [("claude", "Claude"), ("gemini", "Gemini"), ("openrouter", "OpenRouter")]:
            rb = tk.Radiobutton(prov_row, text=lbl, variable=self._provider_var,
                                value=val, bg=BG_DARK, fg=FG_WHITE,
                                selectcolor=BG_INPUT, activebackground=BG_DARK,
                                activeforeground=ACCENT, font=FONT_UI,
                                command=self._on_provider_change)
            rb.pack(side="left", padx=(0, 12))

        # ── Claude section ──
        self._claude_frame = tk.Frame(inner, bg=BG_DARK)
        self._claude_frame.pack(fill="x")

        self._label(self._claude_frame, "Anthropic API Key").pack(anchor="w")
        self._apikey_var = tk.StringVar(value=os.environ.get("ANTHROPIC_API_KEY", ""))
        tk.Entry(self._claude_frame, textvariable=self._apikey_var, bg=BG_INPUT, fg=FG_WHITE,
                 insertbackground=FG_WHITE, relief="flat", font=FONT_MONO, show="*",
                 highlightthickness=1, highlightbackground=BORDER,
                 highlightcolor=ACCENT).pack(fill="x", ipady=4, pady=(2, 6))

        # ── Gemini section ──
        self._gemini_frame = tk.Frame(inner, bg=BG_DARK)
        # (shown when Gemini selected)

        self._label(self._gemini_frame, "Google Gemini API Key").pack(anchor="w")
        self._gemini_key_var = tk.StringVar(value=os.environ.get("GEMINI_API_KEY", ""))
        tk.Entry(self._gemini_frame, textvariable=self._gemini_key_var, bg=BG_INPUT, fg=FG_WHITE,
                 insertbackground=FG_WHITE, relief="flat", font=FONT_MONO, show="*",
                 highlightthickness=1, highlightbackground=BORDER,
                 highlightcolor=ACCENT).pack(fill="x", ipady=4, pady=(2, 6))

        # ── OpenRouter section ──
        self._openrouter_frame = tk.Frame(inner, bg=BG_DARK)
        # (shown when OpenRouter selected)

        self._label(self._openrouter_frame, "OpenRouter API Key").pack(anchor="w")
        self._openrouter_key_var = tk.StringVar(value=os.environ.get("OPENROUTER_API_KEY", ""))
        tk.Entry(self._openrouter_frame, textvariable=self._openrouter_key_var, bg=BG_INPUT, fg=FG_WHITE,
                 insertbackground=FG_WHITE, relief="flat", font=FONT_MONO, show="*",
                 highlightthickness=1, highlightbackground=BORDER,
                 highlightcolor=ACCENT).pack(fill="x", ipady=4, pady=(2, 2))
        tk.Label(self._openrouter_frame, text="openrouter.ai 에서 키 발급",
                 bg=BG_DARK, fg=FG_MUTED, font=FONT_SM).pack(anchor="w", pady=(0, 6))

        # ── Model selector (shared, values change by provider) ──
        self._label(inner, "모델").pack(anchor="w", pady=(6, 2))
        self._model_var = tk.StringVar(value=CLAUDE_MODELS[0][0])
        self._model_combo = ttk.Combobox(inner, textvariable=self._model_var,
                                         state="readonly", font=FONT_UI)
        self._model_combo.pack(fill="x")
        self._update_model_list()  # populate with claude models initially

        styled_button(inner, "설정 저장", self._save_api_key, accent=True).pack(anchor="w", pady=(10, 0))

        sep = tk.Frame(inner, bg=BORDER, height=1)
        sep.pack(fill="x", pady=12)

        # ── HWP section ──
        self._label(inner, "HWP COM 연결 (한글 프로그램 필요)").pack(anchor="w")
        self._hwp_status_var = tk.StringVar(value="미연결")
        tk.Label(inner, textvariable=self._hwp_status_var, bg=BG_DARK,
                 fg=WARN, font=FONT_SM).pack(anchor="w", pady=2)
        styled_button(inner, "HWP 연결 테스트", self._test_hwp_connection).pack(anchor="w", pady=4)

        info = (
            "HWP COM 없이도 텍스트 기반 생성이 가능합니다.\n"
            "HWP COM 연결 시 원본 서식을 유지한 문서 편집이 가능합니다."
        )
        tk.Label(inner, text=info, bg=BG_DARK, fg=FG_MUTED, font=FONT_SM,
                 justify="left", wraplength=320).pack(anchor="w")

    def _on_provider_change(self):
        self._provider = self._provider_var.get()
        self._gen = None
        self._update_model_list()
        self._claude_frame.pack_forget()
        self._gemini_frame.pack_forget()
        self._openrouter_frame.pack_forget()
        if self._provider == "gemini":
            self._gemini_frame.pack(fill="x")
        elif self._provider == "openrouter":
            self._openrouter_frame.pack(fill="x")
        else:
            self._claude_frame.pack(fill="x")

    def _update_model_list(self):
        from ai_generator import CLAUDE_MODELS, GEMINI_MODELS, OPENROUTER_MODELS
        provider = self._provider_var.get()
        if provider == "gemini":
            models = GEMINI_MODELS
        elif provider == "openrouter":
            models = OPENROUTER_MODELS
        else:
            models = CLAUDE_MODELS
        values = [m[0] for m in models]
        labels = [m[1] for m in models]
        self._model_combo["values"] = labels
        self._model_combo.current(0)
        self._model_var.set(values[0])
        self._model_values = values
        self._model_combo.bind("<<ComboboxSelected>>", self._on_model_select)

    def _on_model_select(self, _event=None):
        idx = self._model_combo.current()
        if 0 <= idx < len(self._model_values):
            self._model_var.set(self._model_values[idx])
            self._gen = None

    # ── Right panel (output) ─────────────────────────────────────────

    def _build_right(self, parent):
        top = tk.Frame(parent, bg=BG_DARK)
        top.pack(fill="x", padx=8, pady=(4, 0))
        tk.Label(top, text="생성 결과", bg=BG_DARK, fg=ACCENT,
                 font=FONT_BIG).pack(side="left")

        btn_row = tk.Frame(top, bg=BG_DARK)
        btn_row.pack(side="right")
        styled_button(btn_row, "텍스트 저장", self._save_txt).pack(side="left", padx=(0, 4))
        styled_button(btn_row, "HWP로 저장", self._save_hwp, accent=True).pack(side="left", padx=(0, 4))
        styled_button(btn_row, "클립보드 복사", self._copy_clipboard).pack(side="left")

        self._output_text = scrolledtext.ScrolledText(
            parent, bg=BG_PANEL, fg=FG_WHITE, insertbackground=FG_WHITE,
            relief="flat", font=FONT_MONO, wrap="word",
            highlightthickness=1, highlightbackground=BORDER, highlightcolor=ACCENT)
        self._output_text.pack(fill="both", expand=True, padx=8, pady=8)

        # Progress bar
        self._progress = ttk.Progressbar(parent, mode="indeterminate")
        self._progress.pack(fill="x", padx=8, pady=(0, 4))

    # ── Template management ─────────────────────────────────────────

    def _load_templates(self):
        self._templates = self.tmgr.list_templates()
        names = [f"{'[내장] ' if t['builtin'] else ''}{t['name']} ({t['doc_type']})"
                 for t in self._templates]
        self._tpl_combo["values"] = ["(템플릿 없이 생성)"] + names
        self._tpl_combo.current(0)

        self._tpl_listbox.delete(0, "end")
        for t in self._templates:
            prefix = "📌 " if t["builtin"] else "📄 "
            self._tpl_listbox.insert("end", f"{prefix}{t['name']}  [{t['doc_type']}]")

    def _on_template_selected(self, _event=None):
        idx = self._tpl_combo.current() - 1  # -1 for "(없이 생성)"
        if idx < 0:
            self._hide_fields()
            return
        tpl = self._templates[idx]
        try:
            full = self.tmgr.get_template(tpl["id"])
            self._dtype_var.set(full["doc_type"])
            if full.get("fields"):
                self._show_fields(full["fields"])
            else:
                self._hide_fields()
        except Exception as e:
            messagebox.showerror("오류", str(e))

    def _on_tpl_list_select(self, _event=None):
        sel = self._tpl_listbox.curselection()
        if not sel:
            return
        tpl = self._templates[sel[0]]
        try:
            full = self.tmgr.get_template(tpl["id"])
            content = full.get("content", "")
            self._tpl_preview.config(state="normal")
            self._tpl_preview.delete("1.0", "end")
            self._tpl_preview.insert("1.0", content)
            self._tpl_preview.config(state="disabled")
        except Exception:
            pass

    def _show_fields(self, fields: list[str]):
        self._fields_frame.pack(fill="x", padx=12, pady=(6, 0))
        # Clear old widgets
        for w in self._fields_frame.winfo_children():
            w.destroy()
        self._field_entries.clear()
        for f in fields:
            row = tk.Frame(self._fields_frame, bg=BG_DARK)
            row.pack(fill="x", padx=6, pady=2)
            tk.Label(row, text=f"{{{{{f}}}}}", bg=BG_DARK, fg=ACCENT,
                     font=FONT_SM, width=14, anchor="w").pack(side="left")
            var = tk.StringVar()
            tk.Entry(row, textvariable=var, bg=BG_INPUT, fg=FG_WHITE,
                     insertbackground=FG_WHITE, relief="flat", font=FONT_UI,
                     highlightthickness=1, highlightbackground=BORDER).pack(
                         side="left", fill="x", expand=True, ipady=3)
            self._field_entries[f] = var

    def _hide_fields(self):
        self._fields_frame.pack_forget()
        self._field_entries.clear()

    def _new_template(self):
        NewTemplateDialog(self, self.tmgr, self._load_templates)

    def _import_hwp(self):
        path = filedialog.askopenfilename(
            title="HWP 파일 선택",
            filetypes=[("HWP 파일", "*.hwp"), ("모든 파일", "*.*")])
        if not path:
            return
        name = Path(path).stem
        try:
            self.tmgr.import_hwp_template(path)
            self._load_templates()
            messagebox.showinfo("완료", f"'{name}' 템플릿을 가져왔습니다.")
        except Exception as e:
            messagebox.showerror("가져오기 실패", str(e))

    def _delete_template(self):
        sel = self._tpl_listbox.curselection()
        if not sel:
            messagebox.showwarning("선택 없음", "삭제할 템플릿을 선택하세요.")
            return
        tpl = self._templates[sel[0]]
        if tpl["builtin"]:
            messagebox.showinfo("삭제 불가", "내장 템플릿은 삭제할 수 없습니다.")
            return
        if messagebox.askyesno("확인", f"'{tpl['name']}' 템플릿을 삭제하시겠습니까?"):
            self.tmgr.delete_template(tpl["id"])
            self._load_templates()

    # ── Generation ─────────────────────────────────────────────────

    def _on_generate(self):
        input_data = self._input_text.get("1.0", "end").strip()
        if not input_data:
            messagebox.showwarning("입력 필요", "생성할 내용을 입력해주세요.")
            return

        # Check API key
        if self._provider == "gemini":
            if not os.environ.get("GEMINI_API_KEY") and not self._gemini_key_var.get().strip():
                messagebox.showerror("API Key 필요", "설정 탭에서 Gemini API Key를 입력해주세요.")
                return
        elif self._provider == "openrouter":
            if not os.environ.get("OPENROUTER_API_KEY") and not self._openrouter_key_var.get().strip():
                messagebox.showerror("API Key 필요", "설정 탭에서 OpenRouter API Key를 입력해주세요.")
                return
        else:
            if not os.environ.get("ANTHROPIC_API_KEY") and not self._apikey_var.get().strip():
                messagebox.showerror("API Key 필요", "설정 탭에서 Anthropic API Key를 입력해주세요.")
                return

        self._gen_btn.config(state="disabled")
        self._progress.start(10)
        self._set_status("AI 생성 중...")
        self._output_text.delete("1.0", "end")

        # Gather params
        idx = self._tpl_combo.current() - 1
        tpl = self._templates[idx] if idx >= 0 else None
        doc_type = self._dtype_var.get()
        input_type = self._itype_var.get()
        extra = self._extra_var.get()
        field_vals = {k: v.get() for k, v in self._field_entries.items()}

        def run():
            try:
                template_text = ""
                if tpl:
                    full = self.tmgr.get_template(tpl["id"])
                    template_content = full.get("content", "")
                    # If fields exist, fill them
                    if full.get("fields") and any(field_vals.values()):
                        template_text = self.tmgr.apply_fields(template_content, field_vals)
                    else:
                        template_text = template_content

                def on_chunk(text):
                    self.after(0, self._append_output, text)

                result = self.gen.generate_streaming(
                    doc_type=doc_type,
                    input_type=input_type,
                    input_data=input_data,
                    template_text=template_text,
                    extra_instructions=extra,
                    on_chunk=on_chunk,
                )
                self.after(0, self._on_gen_done, result)
            except Exception as e:
                self.after(0, self._on_gen_error, self._friendly_error(str(e)))

        threading.Thread(target=run, daemon=True).start()

    def _append_output(self, text: str):
        self._output_text.insert("end", text)
        self._output_text.see("end")

    def _on_gen_done(self, result: str):
        self._progress.stop()
        self._gen_btn.config(state="normal")
        labels = {"gemini": "Gemini", "openrouter": "OpenRouter"}
        provider_lbl = labels.get(self._provider, "Claude")
        self._set_status(f"[{provider_lbl}] 생성 완료 ({len(result)}자)")

    @staticmethod
    def _friendly_error(raw: str) -> str:
        """Convert raw API error strings into readable Korean messages."""
        r = raw.lower()
        # Gemini quota
        if "resource_exhausted" in r or "quota exceeded" in r:
            return (
                "Gemini API 할당량 초과 (429)\n\n"
                "무료 티어 한도에 도달했습니다.\n\n"
                "해결 방법:\n"
                "  1. 잠시 후 다시 시도 (약 1분 대기)\n"
                "  2. 설정에서 Claude로 전환\n"
                "  3. Google AI Studio에서 결제 설정 후 유료 티어 사용\n"
                "     → https://aistudio.google.com"
            )
        # Gemini auth
        if "api_key_invalid" in r or "api key not valid" in r:
            return "Gemini API Key가 유효하지 않습니다.\n설정 탭에서 올바른 키를 입력해주세요."
        # Anthropic auth
        if "authentication_error" in r or "invalid x-api-key" in r:
            return "Claude API Key가 유효하지 않습니다.\n설정 탭에서 올바른 키를 입력해주세요."
        # Anthropic overload
        if "overloaded" in r:
            return "Claude 서버가 일시적으로 과부하 상태입니다.\n잠시 후 다시 시도해주세요."
        # Generic rate limit
        if "rate limit" in r or "too many requests" in r or "429" in r:
            return "요청 한도 초과 (429)\n잠시 후 다시 시도해주세요."
        # Connection error
        if "connection" in r or "timeout" in r:
            return "네트워크 연결 오류\n인터넷 연결을 확인하고 다시 시도해주세요."
        # OpenRouter insufficient credits
        if "credit balance" in r or "insufficient credits" in r or "402" in r:
            return (
                "OpenRouter 크레딧이 부족합니다.\n\n"
                "해결 방법:\n"
                "  1. openrouter.ai 에서 크레딧 충전\n"
                "  2. 무료 모델(예: Llama)로 변경"
            )
        # Generic auth error (covers OpenRouter 401)
        if "no auth" in r or "unauthorized" in r:
            return "API Key가 유효하지 않습니다.\n설정 탭에서 올바른 키를 입력해주세요."
        # Fallback: show first 300 chars only
        return raw[:300] + ("..." if len(raw) > 300 else "")

    def _on_gen_error(self, error: str):
        self._progress.stop()
        self._gen_btn.config(state="normal")
        self._set_status("오류 발생")
        messagebox.showerror("생성 오류", error)

    def _clear_output(self):
        self._output_text.delete("1.0", "end")
        self._set_status("준비")

    # ── Save / Export ──────────────────────────────────────────────

    def _get_output(self) -> str:
        return self._output_text.get("1.0", "end").strip()

    def _save_txt(self):
        text = self._get_output()
        if not text:
            messagebox.showwarning("내용 없음", "저장할 내용이 없습니다.")
            return
        path = filedialog.asksaveasfilename(
            defaultextension=".txt",
            filetypes=[("텍스트 파일", "*.txt"), ("모든 파일", "*.*")])
        if path:
            Path(path).write_text(text, encoding="utf-8")
            self._set_status(f"저장됨: {Path(path).name}")

    def _save_hwp(self):
        text = self._get_output()
        if not text:
            messagebox.showwarning("내용 없음", "저장할 내용이 없습니다.")
            return
        path = filedialog.asksaveasfilename(
            defaultextension=".hwp",
            filetypes=[("HWP 파일", "*.hwp"), ("모든 파일", "*.*")])
        if not path:
            return

        def run():
            try:
                from hwp_controller import HwpController
                hwp = HwpController()
                hwp.connect()
                hwp.new_document()
                hwp.insert_text(text)
                hwp.save_as(path, "HWP")
                self.after(0, lambda: self._set_status(f"HWP 저장됨: {Path(path).name}"))
                self.after(0, lambda: messagebox.showinfo("저장 완료",
                    f"HWP 파일로 저장되었습니다:\n{path}"))
            except Exception as e:
                err_msg = str(e)  # Python 3: except 블록 종료 시 e가 삭제되므로 미리 캡처
                # 폴백 1: HWP COM 없이 HWPX 생성 (한글에서 열 수 있음)
                hwpx_path = (path[:-4] if path.lower().endswith(".hwp") else path) + ".hwpx"
                try:
                    from hwp_controller import HwpController
                    HwpController.create_hwpx(hwpx_path, text)
                    saved_name = Path(hwpx_path).name
                    self.after(0, lambda: messagebox.showwarning(
                        "HWPX로 저장",
                        f"HWP COM을 사용할 수 없어 HWPX 형식으로 저장했습니다.\n"
                        f"한글에서 열 수 있습니다.\n\n저장 위치: {hwpx_path}\n\n"
                        f"원인: {err_msg}"
                    ))
                    self.after(0, lambda: self._set_status(f"HWPX 저장됨: {saved_name}"))
                except Exception as e2:
                    # 폴백 2: 최후 수단으로 텍스트 저장
                    txt_path = (path[:-4] if path.lower().endswith(".hwp") else path) + "_내용.txt"
                    Path(txt_path).write_text(text, encoding="utf-8")
                    err2_msg = str(e2)
                    self.after(0, lambda: messagebox.showerror(
                        "저장 실패",
                        f"HWP/HWPX 저장 모두 실패하여 텍스트로 저장했습니다.\n"
                        f"저장 위치: {txt_path}\n\n원인: {err_msg}"
                    ))
                    self.after(0, lambda: self._set_status("텍스트로 저장됨"))

        threading.Thread(target=run, daemon=True).start()

    def _copy_clipboard(self):
        text = self._get_output()
        if text:
            self.clipboard_clear()
            self.clipboard_append(text)
            self._set_status("클립보드에 복사됨")

    # ── Config actions ─────────────────────────────────────────────

    def _save_api_key(self):
        claude_key = self._apikey_var.get().strip()
        gemini_key = self._gemini_key_var.get().strip()
        openrouter_key = self._openrouter_key_var.get().strip()
        if claude_key:
            os.environ["ANTHROPIC_API_KEY"] = claude_key
        if gemini_key:
            os.environ["GEMINI_API_KEY"] = gemini_key
        if openrouter_key:
            os.environ["OPENROUTER_API_KEY"] = openrouter_key
        self._gen = None
        self._set_status("설정 저장됨")
        messagebox.showinfo("저장", "설정이 이 세션에 적용되었습니다.")

    def _test_hwp_connection(self):
        def run():
            try:
                from hwp_controller import HwpController
                hwp = HwpController()
                hwp.connect()
                self.after(0, lambda: self._hwp_status_var.set("연결됨 ✓"))
                self.after(0, lambda: messagebox.showinfo("연결 성공", "HWP COM 연결 성공!"))
            except Exception as e:
                err_msg = str(e)
                self.after(0, lambda: self._hwp_status_var.set("연결 실패 ✗"))
                self.after(0, lambda: messagebox.showerror("연결 실패", err_msg))
        threading.Thread(target=run, daemon=True).start()

    def _set_status(self, msg: str):
        self._status_var.set(msg)


# ── New Template Dialog ────────────────────────────────────────────────────

class NewTemplateDialog(tk.Toplevel):
    def __init__(self, parent, tmgr, on_save):
        super().__init__(parent)
        self.title("새 템플릿 만들기")
        self.geometry("640x520")
        self.configure(bg=BG_DARK)
        self.resizable(True, True)
        self.grab_set()
        self._tmgr = tmgr
        self._on_save = on_save

        from ai_generator import DOC_TYPE_PROMPTS
        doc_types = list(DOC_TYPE_PROMPTS.keys())

        pad = dict(padx=16, pady=6)

        tk.Label(self, text="템플릿 이름", bg=BG_DARK, fg=FG_WHITE, font=FONT_UI).pack(anchor="w", **pad)
        self._name_var = tk.StringVar()
        tk.Entry(self, textvariable=self._name_var, bg=BG_INPUT, fg=FG_WHITE,
                 insertbackground=FG_WHITE, relief="flat", font=FONT_UI,
                 highlightthickness=1, highlightbackground=BORDER).pack(
                     fill="x", padx=16, ipady=4)

        tk.Label(self, text="문서 유형", bg=BG_DARK, fg=FG_WHITE, font=FONT_UI).pack(anchor="w", **pad)
        self._dtype_var = tk.StringVar(value="보고서")
        ttk.Combobox(self, textvariable=self._dtype_var, values=doc_types,
                     state="readonly", font=FONT_UI).pack(fill="x", padx=16)

        tk.Label(self, text="설명 (선택)", bg=BG_DARK, fg=FG_WHITE, font=FONT_UI).pack(anchor="w", **pad)
        self._desc_var = tk.StringVar()
        tk.Entry(self, textvariable=self._desc_var, bg=BG_INPUT, fg=FG_WHITE,
                 insertbackground=FG_WHITE, relief="flat", font=FONT_UI,
                 highlightthickness=1, highlightbackground=BORDER).pack(
                     fill="x", padx=16, ipady=4)

        hint = "힌트: {{필드명}} 형식으로 채울 영역을 표시하세요. 예) {{제목}}, {{내용}}"
        tk.Label(self, text=hint, bg=BG_DARK, fg=FG_MUTED, font=FONT_SM).pack(anchor="w", padx=16)

        tk.Label(self, text="템플릿 내용", bg=BG_DARK, fg=FG_WHITE, font=FONT_UI).pack(anchor="w", **pad)
        self._content_text = scrolledtext.ScrolledText(
            self, bg=BG_INPUT, fg=FG_WHITE, insertbackground=FG_WHITE,
            relief="flat", font=FONT_MONO, wrap="word",
            highlightthickness=1, highlightbackground=BORDER)
        self._content_text.pack(fill="both", expand=True, padx=16)
        self._content_text.insert("1.0",
            "{{제목}}\n\n1. 개요\n{{개요}}\n\n2. 내용\n{{내용}}\n\n3. 결론\n{{결론}}\n")

        btn_row = tk.Frame(self, bg=BG_DARK)
        btn_row.pack(fill="x", padx=16, pady=10)
        styled_button(btn_row, "저장", self._save, accent=True).pack(side="left", padx=(0, 8))
        styled_button(btn_row, "취소", self.destroy).pack(side="left")

    def _save(self):
        name = self._name_var.get().strip()
        if not name:
            messagebox.showwarning("이름 필요", "템플릿 이름을 입력해주세요.", parent=self)
            return
        content = self._content_text.get("1.0", "end").strip()
        if not content:
            messagebox.showwarning("내용 필요", "템플릿 내용을 입력해주세요.", parent=self)
            return
        self._tmgr.save_template(name, self._dtype_var.get(), content, self._desc_var.get())
        self._on_save()
        messagebox.showinfo("저장 완료", f"'{name}' 템플릿이 저장되었습니다.", parent=self)
        self.destroy()
