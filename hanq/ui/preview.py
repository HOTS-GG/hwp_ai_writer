"""PreviewPane: 쪽 이미지를 세로로 이어 보여주는 큰 미리보기.

쪽 이미지는 파일 경로(한글 미리보기)나 메모리 이미지(실시간 간이 렌더링) 둘 다 받는다.
실시간 화면에서는 '방금 쓴 곳'이 화면 밖이면 그 위치로 스크롤한다.
"""
import tkinter as tk
from tkinter import ttk

from ..system import font, wheel_units, zoom_modifier
from .theme import BG, BORDER, FONT_H, FONT_SM, MUTED, PREVIEW_BG, TEXT, button

GAP = 16


class PreviewPane(tk.Frame):
    def __init__(self, parent, title: str, zoom: int = 100):
        super().__init__(parent, bg=BG)
        self._pages: list = []          # 경로(str) 또는 PIL 이미지
        self._photos = []
        self._zoom = zoom
        self._text = None
        self._message = None
        self._focus = None              # (쪽, y px)
        self.token = None               # 지금 보여줄 그리기 요청 번호
        self.keep_token = None          # 마지막으로 그린 요청 (같은 요청이면 스크롤 유지)

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
        tk.Label(zoom_box, textvariable=self._zoom_var, bg=BG, fg=MUTED, font=FONT_SM, width=5).pack(side="left")
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

    # ── 바깥에서 부르는 것 ──────────────────────────────────────────────
    @property
    def has_pages(self) -> bool:
        return bool(self._pages)

    def set_title(self, s):
        self._title_var.set(s)

    def set_note(self, s):
        self._info_var.set(s)

    def set_zoom(self, z):
        self._zoom = max(30, min(250, z))
        self._zoom_var.set(f"{self._zoom}%")
        self._layout()

    def show_message(self, msg: str):
        self._pages, self._text, self._message, self._focus = [], None, msg, None
        self._info_var.set("")
        self._layout()

    def show_text(self, text: str, note: str = "텍스트 미리보기"):
        self._pages, self._text, self._message, self._focus = [], text, None, None
        self._info_var.set(note)
        self.canvas.yview_moveto(0)
        self._layout()

    def show_pages(self, pages: list, note: str = "", focus: tuple | None = None, keep_scroll: bool = False):
        """pages: png 경로 또는 PIL 이미지 목록. focus=(쪽, y px)면 그곳이 보이게 스크롤한다."""
        top = self.canvas.yview()[0]
        self._pages, self._text, self._focus = pages, None, focus
        self._message = None if pages else "미리보기 이미지가 없습니다."
        self._info_var.set(f"{len(pages)}쪽 {note}".strip() if pages else note)
        self._layout()
        if focus is not None:
            self._follow(focus)
        elif keep_scroll:
            self.canvas.yview_moveto(top)
        else:
            self.canvas.yview_moveto(0)

    # ── 내부 ────────────────────────────────────────────────────────────
    def _wheel(self, e):
        if zoom_modifier(e):
            self.set_zoom(self._zoom + (10 if e.delta > 0 else -10))
        else:
            self.canvas.yview_scroll(wheel_units(e), "units")

    def _follow(self, focus):
        """강조 위치가 화면 밖이면 그 위치가 화면 위쪽 1/3에 오게 옮긴다."""
        page, y = focus
        if page is None or not self._offsets or page >= len(self._offsets):
            return
        target = self._offsets[page] + int((y or 0) * self._zoom / 100)
        total = self._total_h or 1
        view_h = max(self.canvas.winfo_height(), 1)
        top = self.canvas.yview()[0] * total
        if top + 40 <= target <= top + view_h - 80:
            return
        self.canvas.yview_moveto(max(target - view_h / 3, 0) / total)

    def _layout(self):
        from PIL import Image, ImageTk
        c = self.canvas
        c.delete("all")
        self._photos = []
        self._offsets = []
        self._total_h = 0
        cw = max(c.winfo_width(), 200)
        if self._pages:
            y = GAP
            for src in self._pages:
                try:
                    im = Image.open(src) if isinstance(src, str) else src
                except OSError:
                    continue
                w = int(im.width * self._zoom / 100)
                h = int(im.height * self._zoom / 100)
                im = im.resize((max(w, 1), max(h, 1)), Image.LANCZOS if self._zoom < 100 else Image.BILINEAR)
                ph = ImageTk.PhotoImage(im)
                self._photos.append(ph)
                self._offsets.append(y)
                x = max((cw - w) // 2, 8)
                c.create_rectangle(x + 3, y + 3, x + w + 3, y + h + 3, fill="#5b6475", outline="")
                c.create_image(x, y, image=ph, anchor="nw")
                y += h + GAP
            self._total_h = y
            c.configure(scrollregion=(0, 0, cw, y))
        elif self._text:
            w = min(cw - 40, 820)
            x = (cw - w) // 2
            item = c.create_text(x + 30, 46, text=self._text, anchor="nw", width=w - 60, font=font(10), fill=TEXT)
            bbox = c.bbox(item)
            c.create_rectangle(x, 16, x + w, bbox[3] + 30, fill="#ffffff", outline="")
            c.tag_raise(item)
            self._total_h = bbox[3] + 50
            c.configure(scrollregion=(0, 0, cw, self._total_h))
        else:
            c.create_text(cw // 2, 120, text=self._message or "", fill="#ffffff", font=FONT_H)
            self._total_h = 240
            c.configure(scrollregion=(0, 0, cw, 240))
