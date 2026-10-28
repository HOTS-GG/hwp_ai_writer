"""새 버전 알림 창: 확인 → 내려받기(진행률) → 설치 후 다시 시작."""
import threading
import tkinter as tk
import webbrowser
from tkinter import messagebox, ttk

from .. import config as cfg
from .. import updater
from ..system import IS_MAC
from .theme import BG, CARD, FONT_H, FONT_SM, MUTED, TEXT, button


class Updater:
    """앱 시작 때 조용히 확인하고, 설정 탭의 [지금 확인]에서도 쓴다."""

    def __init__(self, app):
        self.app = app
        self._checking = False

    def check_on_start(self):
        if self.app.s.get("auto_update_check", True):
            self.app.after(4000, lambda: self.check(silent=True))

    def check(self, silent: bool = False, on_result=None):
        """silent=True면 새 버전이 있을 때만 창을 띄운다."""
        if self._checking:
            return
        self._checking = True

        def run():
            try:
                rel = updater.check()
                err = None
            except updater.UpdateError as e:
                rel, err = None, str(e)
            self.app.after(0, self._checked, rel, err, silent, on_result)
        threading.Thread(target=run, daemon=True).start()

    def _checked(self, rel, err, silent, on_result):
        self._checking = False
        import datetime
        self.app.set("last_update_check", f"{datetime.datetime.now():%Y-%m-%d %H:%M}")
        if on_result:
            on_result(rel, err)
        if err:
            if not silent:
                messagebox.showwarning("업데이트 확인", err)
            return
        if rel is None:
            if not silent:
                messagebox.showinfo("업데이트 확인", f"지금 쓰는 한큐 {cfg.APP_VERSION}이(가) 최신 버전입니다.")
            return
        if silent and self.app.s.get("skip_version") == rel.version:
            return
        UpdateDialog(self.app, rel)


class UpdateDialog(tk.Toplevel):
    def __init__(self, app, rel: updater.Release):
        super().__init__(app)
        self.app, self.rel = app, rel
        self.title("새 버전이 있습니다")
        self.configure(bg=BG)
        self.resizable(False, False)
        self.transient(app)
        self._stop = threading.Event()
        self.protocol("WM_DELETE_WINDOW", self._close)

        box = tk.Frame(self, bg=CARD, highlightthickness=1, highlightbackground="#d0d7e2")
        box.pack(fill="both", expand=True, padx=16, pady=16)
        tk.Label(box, text=f"한큐 {rel.version}이(가) 나왔습니다", bg=CARD, fg=TEXT, font=FONT_H
                 ).pack(anchor="w", padx=18, pady=(16, 2))
        tk.Label(box, text=f"지금 쓰는 버전: {cfg.APP_VERSION}", bg=CARD, fg=MUTED, font=FONT_SM
                 ).pack(anchor="w", padx=18)
        if rel.notes:
            notes = tk.Text(box, height=min(10, max(3, rel.notes.count("\n") + 2)), width=58, bg=CARD, fg=TEXT,
                            relief="flat", font=FONT_SM, wrap="word", highlightthickness=0)
            notes.insert("1.0", rel.notes)
            notes.configure(state="disabled")
            notes.pack(fill="x", padx=18, pady=(10, 0))

        self._how = tk.StringVar(value=self._how_text())
        tk.Label(box, textvariable=self._how, bg=CARD, fg=MUTED, font=FONT_SM, justify="left", wraplength=470
                 ).pack(anchor="w", padx=18, pady=(10, 0))
        self._bar = ttk.Progressbar(box, mode="determinate", length=470, style="Horizontal.TProgressbar")
        self._bar_lbl = tk.StringVar(value="")
        self._bar_lbl_w = tk.Label(box, textvariable=self._bar_lbl, bg=CARD, fg=MUTED, font=FONT_SM)
        self._bar_lbl_w.pack(anchor="w", padx=18)

        row = tk.Frame(box, bg=CARD)
        row.pack(fill="x", padx=18, pady=(12, 16))
        self._go = button(row, "지금 업데이트", self._start, "primary")
        self._go.pack(side="right")
        self._later = button(row, "다음에", self._close)
        self._later.pack(side="right", padx=(0, 6))
        self._skip = button(row, "이 버전 건너뛰기", self._skip_version)
        self._skip.pack(side="left")

        self.update_idletasks()
        x = app.winfo_rootx() + (app.winfo_width() - self.winfo_width()) // 2
        y = app.winfo_rooty() + (app.winfo_height() - self.winfo_height()) // 3
        self.geometry(f"+{max(x, 0)}+{max(y, 0)}")
        self.grab_set()
        self.focus_set()

    def _how_text(self) -> str:
        if not updater.is_installed_app():
            return "소스 코드로 실행 중이라 자동 설치는 할 수 없습니다. [지금 업데이트]를 누르면 내려받기 페이지를 엽니다."
        if not self.rel.asset_url:
            return "이 컴퓨터용 설치 파일이 아직 올라오지 않았습니다. [지금 업데이트]를 누르면 내려받기 페이지를 엽니다."
        if IS_MAC:
            return "[지금 업데이트]를 누르면 새 버전을 받아 엽니다. 열린 창에서 HanQ를 Applications로 끌어다 놓으세요."
        return ("[지금 업데이트]를 누르면 새 버전을 받아 설치하고, 한큐가 잠깐 닫혔다가 새 버전으로 다시 열립니다.\n"
                "설정·API 키·내 양식은 그대로 남습니다.")

    def _start(self):
        if not updater.is_installed_app() or not self.rel.asset_url:
            webbrowser.open(self.rel.page_url)
            self.destroy()
            return
        if self.app.busy:
            messagebox.showinfo("업데이트", "지금 문서를 만들거나 고치는 중입니다. 끝난 뒤에 다시 눌러 주세요.", parent=self)
            return
        for b in (self._go, self._skip):
            b.configure(state="disabled")
        self._bar.pack(anchor="w", padx=18, pady=(8, 0), before=self._bar_lbl_w)
        self._bar_lbl.set("내려받는 중…")

        def progress(done, total):
            self.after(0, self._show_progress, done, total)

        def run():
            try:
                path = updater.download(self.rel, progress, self._stop)
            except updater.UpdateError as e:
                err = str(e)
                self.after(0, self._failed, err)
                return
            self.after(0, self._install, path)
        threading.Thread(target=run, daemon=True).start()

    def _show_progress(self, done, total):
        if not self.winfo_exists():
            return
        mb = done / 1024 / 1024
        if total:
            self._bar["value"] = done * 100 / total
            self._bar_lbl.set(f"내려받는 중… {mb:.0f} / {total / 1024 / 1024:.0f}MB")
        else:
            self._bar_lbl.set(f"내려받는 중… {mb:.0f}MB")

    def _failed(self, err):
        if not self.winfo_exists():
            return
        for b in (self._go, self._skip):
            b.configure(state="normal")
        self._bar_lbl.set("")
        messagebox.showerror("업데이트 실패", f"{err}\n\n직접 받으려면 릴리스 페이지를 여세요:\n{self.rel.page_url}",
                             parent=self)

    def _install(self, path):
        self._bar_lbl.set("설치를 시작합니다…")
        try:
            updater.launch_installer(path)
        except Exception as e:
            self._failed(str(e))
            return
        if IS_MAC:
            self.destroy()
            return
        # 설치 프로그램이 한큐 폴더를 덮어써야 하므로 닫는다 (설치가 끝나면 새 한큐가 다시 열린다)
        self.app.after(300, self.app._on_close)

    def _skip_version(self):
        self.app.set("skip_version", self.rel.version)
        self.destroy()

    def _close(self):
        self._stop.set()
        self.destroy()
