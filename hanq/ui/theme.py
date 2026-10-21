"""색·글꼴·버튼·카드 — 화면 전체가 같은 모양을 쓰도록 한곳에 둔다."""
import re
import tkinter as tk
from pathlib import Path
from tkinter import ttk

from ..system import IS_MAC, font

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
OK = "#067647"
INPUT_BG = "#fbfcfe"
PREVIEW_BG = "#8a94a6"
FONT = font(10)
FONT_B = font(10, "bold")
FONT_SM = font(9)
FONT_H = font(12, "bold")

APP_NAME = "한큐"
APP_NAME_EN = "HanQ"


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
        if "command" in kw:
            self._command = kw.pop("command")
        return super().configure(cnf, **kw)

    config = configure


BUTTON_COLORS = {
    "primary": (ACCENT, "#ffffff", ACCENT_DARK),
    "danger": (CARD, DANGER, "#fdecea"),
    "stop": (DANGER, "#ffffff", "#b42318"),
    "normal": (SOFT, TEXT, "#d8e3f5"),
}


def button(parent, text, command, kind="normal", **kw):
    bg, fg, active = BUTTON_COLORS[kind]
    opts = {"relief": "flat", "bd": 0, "padx": 12, "pady": 6, "cursor": "hand2",
            "font": FONT_B if kind != "normal" else FONT, **kw}   # kw로 기본값을 바꿀 수 있다
    return (_FlatButton if IS_MAC else tk.Button)(
        parent, text=text, command=command, bg=bg, fg=fg, activebackground=active, activeforeground=fg, **opts)


def restyle(btn, kind: str):
    """버튼 색을 바꾼다 (예: 생성 ↔ 중단)."""
    bg, fg, active = BUTTON_COLORS[kind]
    btn.configure(bg=bg, fg=fg, activebackground=active, activeforeground=fg)
    if isinstance(btn, _FlatButton):
        btn._bg, btn._hover = bg, active


def card(parent, title=None):
    f = tk.Frame(parent, bg=CARD, highlightthickness=1, highlightbackground=BORDER)
    if title:
        tk.Label(f, text=title, bg=CARD, fg=TEXT, font=FONT_B).pack(anchor="w", padx=14, pady=(10, 4))
    return f


def text_input(parent, **kw):
    return tk.Text(parent, bg=INPUT_BG, fg=TEXT, insertbackground=TEXT, relief="flat", font=FONT, wrap="word",
                   highlightthickness=1, highlightbackground=BORDER, highlightcolor=ACCENT, padx=8, pady=6, **kw)


def display_name(path: Path) -> str:
    return re.sub(r"^\d+_", "", Path(path).stem)


def safe_filename(s: str) -> str:
    s = re.sub(r'[\\/:*?"<>|\r\n]+', " ", s).strip()
    return re.sub(r"\s+", " ", s)[:80] or "문서"


def apply_ttk_style(root: tk.Tk):
    # 한글 조합 중 글자는 Tk 기본 글꼴로 그려지므로, 기본 글꼴을 모두 같은 글꼴·크기로 맞춰
    # 입력할 때 글씨가 커졌다 작아졌다 하지 않게 한다
    import tkinter.font as tkfont
    for name in ("TkDefaultFont", "TkTextFont", "TkFixedFont", "TkMenuFont",
                 "TkHeadingFont", "TkCaptionFont", "TkSmallCaptionFont", "TkIconFont", "TkTooltipFont"):
        try:
            tkfont.nametofont(name).configure(family=FONT[0], size=FONT[1])
        except tk.TclError:
            pass
    st = ttk.Style(root)
    st.theme_use("clam")
    # 탭의 점선 포커스 테두리 제거 (Notebook.focus 요소를 뺀 레이아웃)
    st.layout("TNotebook.Tab", [
        ("Notebook.tab", {"sticky": "nswe", "children": [
            ("Notebook.padding", {"side": "top", "sticky": "nswe", "children": [
                ("Notebook.label", {"side": "top", "sticky": ""})]})]})])
    st.configure(".", background=BG, foreground=TEXT, font=FONT)
    st.configure("TNotebook", background=BG, borderwidth=0, tabmargins=(12, 8, 12, 0))
    st.configure("TNotebook.Tab", background=SOFT, foreground=MUTED, padding=(18, 6), font=FONT, borderwidth=0)
    # clam 테마는 선택 탭의 여백을 줄이므로, 반대로 선택 탭을 키운다
    st.map("TNotebook.Tab", background=[("selected", CARD)], foreground=[("selected", ACCENT)],
           padding=[("selected", (26, 10))], font=[("selected", font(11, "bold"))],
           expand=[("selected", (2, 4, 2, 0))])
    st.configure("TCombobox", fieldbackground=CARD, background=CARD, bordercolor=BORDER, arrowcolor=TEXT, padding=4)
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
    root.option_add("*TCombobox*Listbox.font", FONT)
