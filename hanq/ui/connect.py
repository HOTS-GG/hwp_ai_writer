"""AI가 연결되지 않았을 때: 경고 대신 '무엇을 가지고 있는지'만 고르면 나머지를 한큐가 해 준다."""
import tkinter as tk

from .theme import BG, CARD, FONT_H, FONT_SM, MUTED, TEXT, button


class ConnectDialog(tk.Toplevel):
    def __init__(self, app, why: str = ""):
        super().__init__(app)
        self.app = app
        self.title("AI 연결하기")
        self.configure(bg=BG)
        self.resizable(False, False)
        self.transient(app)

        box = tk.Frame(self, bg=CARD, highlightthickness=1, highlightbackground="#d0d7e2")
        box.pack(fill="both", expand=True, padx=16, pady=16)
        tk.Label(box, text="AI를 연결해 주세요", bg=CARD, fg=TEXT, font=FONT_H).pack(anchor="w", padx=18, pady=(16, 2))
        tk.Label(box, text=(why + "\n" if why else "") + "가지고 있는 것을 고르면 나머지는 한큐가 설정합니다.",
                 bg=CARD, fg=MUTED, font=FONT_SM, justify="left").pack(anchor="w", padx=18)

        for title, desc, action in (
                ("Claude 구독이 있어요", "Claude Pro·Max — 설치와 로그인을 자동으로 합니다",
                 lambda: self._cli("claude_code")),
                ("ChatGPT 구독이 있어요", "ChatGPT Plus·Pro — 설치와 로그인을 자동으로 합니다",
                 lambda: self._cli("codex")),
                ("API 키가 있어요", "Claude·GPT·Gemini·OpenRouter 키를 붙여 넣습니다", self._api)):
            row = tk.Frame(box, bg=CARD)
            row.pack(fill="x", padx=18, pady=(10, 0))
            button(row, title, action, "primary", width=18).pack(side="left")
            tk.Label(row, text=desc, bg=CARD, fg=MUTED, font=FONT_SM).pack(side="left", padx=10)
        tk.Frame(box, bg=CARD, height=6).pack()
        button(box, "나중에", self.destroy).pack(anchor="e", padx=18, pady=(4, 16))

        self.update_idletasks()
        x = app.winfo_rootx() + (app.winfo_width() - self.winfo_width()) // 2
        y = app.winfo_rooty() + (app.winfo_height() - self.winfo_height()) // 3
        self.geometry(f"+{max(x, 0)}+{max(y, 0)}")
        self.grab_set()

    def _cli(self, pid):
        self.destroy()
        self.app.nb.select(self.app.tab_cfg)
        self.app.settings_tab.start_cli_setup(pid)

    def _api(self):
        self.destroy()
        self.app.nb.select(self.app.tab_cfg)
        self.app.settings_tab.focus_api_key()
