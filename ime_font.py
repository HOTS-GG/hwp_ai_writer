"""한글 조합 중인 글자를 입력칸 글꼴과 같은 크기로 보이게 한다.

조합 중인 글자는 윈도우 입력기(IME)가 그리는데, Tk는 입력기에 글꼴을 알려주지 않아
입력기 기본 글꼴(더 큰 크기)로 그려진다. 입력칸에 포커스가 갈 때 그 칸의 글꼴을
ImmSetCompositionFontW로 입력기에 넘겨준다.
"""
import ctypes
import tkinter as tk
import tkinter.font as tkfont
from ctypes import wintypes

HANGEUL_CHARSET = 129


class LOGFONTW(ctypes.Structure):
    _fields_ = [
        ("lfHeight", wintypes.LONG), ("lfWidth", wintypes.LONG),
        ("lfEscapement", wintypes.LONG), ("lfOrientation", wintypes.LONG),
        ("lfWeight", wintypes.LONG), ("lfItalic", wintypes.BYTE),
        ("lfUnderline", wintypes.BYTE), ("lfStrikeOut", wintypes.BYTE),
        ("lfCharSet", wintypes.BYTE), ("lfOutPrecision", wintypes.BYTE),
        ("lfClipPrecision", wintypes.BYTE), ("lfQuality", wintypes.BYTE),
        ("lfPitchAndFamily", wintypes.BYTE), ("lfFaceName", wintypes.WCHAR * 32),
    ]


try:
    _imm = ctypes.windll.imm32
    _imm.ImmGetContext.argtypes = [wintypes.HWND]
    _imm.ImmGetContext.restype = ctypes.c_void_p
    _imm.ImmReleaseContext.argtypes = [wintypes.HWND, ctypes.c_void_p]
    _imm.ImmSetCompositionFontW.argtypes = [ctypes.c_void_p, ctypes.POINTER(LOGFONTW)]
    _imm.ImmGetCompositionFontW.argtypes = [ctypes.c_void_p, ctypes.POINTER(LOGFONTW)]
except (AttributeError, OSError):
    _imm = None


def _logfont_for(widget) -> LOGFONTW:
    f = tkfont.Font(root=widget, font=widget.cget("font")).actual()
    size = f["size"]
    # 양수 = 포인트, 음수 = 픽셀
    px = round(size * widget.winfo_fpixels("1i") / 72) if size > 0 else -size
    lf = LOGFONTW()
    lf.lfHeight = -px
    lf.lfWeight = 700 if f.get("weight") == "bold" else 400
    lf.lfCharSet = HANGEUL_CHARSET
    lf.lfFaceName = f["family"][:31]
    return lf


def apply(widget) -> bool:
    if _imm is None:
        return False
    hwnd = widget.winfo_id()
    himc = _imm.ImmGetContext(hwnd)
    if not himc:
        return False
    try:
        lf = _logfont_for(widget)
        return bool(_imm.ImmSetCompositionFontW(himc, ctypes.byref(lf)))
    finally:
        _imm.ImmReleaseContext(hwnd, himc)


def current(widget) -> LOGFONTW | None:
    if _imm is None:
        return None
    hwnd = widget.winfo_id()
    himc = _imm.ImmGetContext(hwnd)
    if not himc:
        return None
    try:
        lf = LOGFONTW()
        return lf if _imm.ImmGetCompositionFontW(himc, ctypes.byref(lf)) else None
    finally:
        _imm.ImmReleaseContext(hwnd, himc)


def install(root: tk.Misc):
    """모든 입력칸(Entry, Text, Combobox, Spinbox)에 포커스가 갈 때 글꼴을 맞춘다."""
    def on_focus(e):
        w = e.widget
        if isinstance(w, str):
            return
        if w.winfo_class() in ("Entry", "Text", "TEntry", "TCombobox", "TSpinbox"):
            try:
                apply(w)
            except (tk.TclError, OSError, ValueError):
                pass
    root.bind_all("<FocusIn>", on_focus, add="+")
