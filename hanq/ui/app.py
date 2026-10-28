"""한큐(HanQ) 메인 창: 탭, 상태 표시줄, 작업 실행(스레드)·중단, 실시간 화면, 미리보기, 설정 저장."""
import datetime
import itertools
import shutil
import threading
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk

from .. import config as cfg
from ..ai import AIConfig, Cancelled
from ..ai.providers import find_cli
from ..config import ALL_PROVIDERS, BUILTIN_FORMS_DIR, CACHE_DIR, CLI_PROVIDERS, DEFAULT_MODELS
from ..hwp import HwpWorker
from ..services import Job, LiveView
from ..system import EN_FAMILY, FONT_PLUS, IS_WIN, font
from .theme import APP_NAME, APP_NAME_EN, BG, FONT, HEADER, apply_ttk_style, display_name

_tokens = itertools.count(1)


class Workspace:
    """지금 열려 있는 문서: 작업 파일(버전 목록), 저장한 위치, 제목."""

    def __init__(self):
        self.versions: list[str] = []
        self.saved_path: str | None = None
        self.title = "문서"

    @property
    def current(self) -> str | None:
        return self.versions[-1] if self.versions else None

    def start(self, path: str, title: str, saved_path: str | None = None):
        self.versions = [path]
        self.title = title
        self.saved_path = saved_path

    def next_path(self) -> str:
        base = Path(self.versions[0]).stem if self.versions else "문서"
        return str(CACHE_DIR / f"{base}_v{len(self.versions) + 1}.hwpx")


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.s = cfg.load()
        # API 키가 없으면, 설치된 Claude Code / Codex를 기본으로 고른다
        if self.s["provider"] not in CLI_PROVIDERS and not self.s["api_keys"].get(self.s["provider"]):
            for p in CLI_PROVIDERS:
                if find_cli(p):
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

        self.forms: list[dict] = []
        self.workspace = Workspace()
        self.busy = False
        self.job: Job | None = None
        self._save_job = None
        self._busy_listeners = []
        self._forms_listeners = []
        self.worker = self._new_worker()
        # rhwp(한글 없이 실제 모양으로 그리는 오픈소스 엔진)가 있으면 미리보기·HWP 변환에 쓴다
        from ..hwp.rhwp import get_rhwp
        self.rhwp = get_rhwp(self.s.get("rhwp_path", ""))
        self.live = LiveView(lambda result, token: self.after(0, self._on_live_frame, result, token),
                             dpi=int(self.s.get("preview_dpi", 96)), rhwp=self.rhwp, hangul=self.worker)
        self._panes = []

        apply_ttk_style(self)
        self._build()
        if IS_WIN:  # 조합 중 글자 크기 문제는 윈도우 입력기에만 있다
            from . import ime_font
            ime_font.install(self)
        self.reload_forms()
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        from .update import Updater
        self.updater = Updater(self)
        self.updater.check_on_start()
        if IS_WIN and self.s.get("auto_security_module", True):
            self._auto_security()

    def _auto_security(self):
        """'접근 허용' 창을 없애는 보안 모듈이 아직 없으면 바탕화면·다운로드에서 찾아 자동 등록한다."""
        from ..hwp import security

        def run():
            try:
                dll = security.auto_install()
            except OSError:
                dll = None
            if dll:
                self.after(0, self._security_installed, dll)
        threading.Thread(target=run, daemon=True).start()

    def _security_installed(self, dll):
        self.restart_worker()
        self.status(f"한글 보안 승인 모듈을 찾아 자동으로 등록했습니다 ({Path(dll).name})")
        if hasattr(self, "settings_tab"):
            self.settings_tab.refresh_security()

    # ── 화면 뼈대 ───────────────────────────────────────────────────────
    def _build(self):
        hdr = tk.Frame(self, bg=HEADER, height=52)
        hdr.pack(fill="x")
        tk.Label(hdr, text=APP_NAME, bg=HEADER, fg="#ffffff", font=font(16, "bold")).pack(side="left", padx=(20, 4), pady=10)
        tk.Label(hdr, text=APP_NAME_EN, bg=HEADER, fg="#ffffff",
                 font=(EN_FAMILY, 13 + FONT_PLUS, "bold")).pack(side="left", padx=(0, 12), pady=(12, 8))
        self._status = tk.StringVar(value="준비")
        tk.Label(hdr, textvariable=self._status, bg=HEADER, fg="#d6e4ff", font=FONT).pack(side="right", padx=20)
        self._header = hdr
        self._progress = ttk.Progressbar(self, mode="indeterminate", style="Horizontal.TProgressbar")

        from .forms_tab import FormsTab
        from .generate_tab import GenerateTab
        from .settings_tab import SettingsTab
        self.nb = ttk.Notebook(self)
        self.nb.pack(fill="both", expand=True)
        self.tab_gen = tk.Frame(self.nb, bg=BG)
        self.tab_tpl = tk.Frame(self.nb, bg=BG)
        self.tab_cfg = tk.Frame(self.nb, bg=BG)
        self.nb.add(self.tab_gen, text="문서 생성")
        self.nb.add(self.tab_tpl, text="템플릿")
        self.nb.add(self.tab_cfg, text="설정")
        self.gen = GenerateTab(self, self.tab_gen)
        self.forms_tab = FormsTab(self, self.tab_tpl)
        self.settings_tab = SettingsTab(self, self.tab_cfg)

    def status(self, msg: str):
        self._status.set(msg)

    def register_pane(self, pane):
        self._panes.append(pane)

    def unregister_pane(self, pane):
        if pane in self._panes:
            self._panes.remove(pane)

    def on_busy_change(self, fn):
        self._busy_listeners.append(fn)

    def on_forms_change(self, fn):
        self._forms_listeners.append(fn)

    # ── 양식 목록 ───────────────────────────────────────────────────────
    def reload_forms(self):
        forms = [{"path": str(p), "name": display_name(p), "builtin": True, "kind": "hwpx"}
                 for p in sorted(BUILTIN_FORMS_DIR.glob("*.hwpx"))]
        udir = Path(self.s["user_forms_dir"])
        if udir.exists():
            for p in sorted(list(udir.glob("*.hwpx")) + list(udir.glob("*.pdf"))):
                forms.append({"path": str(p), "name": display_name(p), "builtin": False, "kind": p.suffix.lower()[1:]})
        self.forms = forms
        for fn in self._forms_listeners:
            fn()

    def base_style_path(self) -> str:
        p = BUILTIN_FORMS_DIR / self.s.get("base_style_form", "")
        if p.exists():
            return str(p)
        return str(sorted(BUILTIN_FORMS_DIR.glob("*.hwpx"))[0])

    # ── AI 설정 ─────────────────────────────────────────────────────────
    def ai_config(self) -> AIConfig:
        p = self.s["provider"]
        if p in CLI_PROVIDERS:
            # CLI 방식은 api_key 자리에 실행 파일 경로를 넣는다
            key = self.s.get("cli_paths", {}).get(p, "").strip() or find_cli(p) or ""
            model = self.s["models"].get(p, "").strip()
        else:
            key = self.s["api_keys"].get(p, "").strip()
            model = self.s["models"].get(p) or DEFAULT_MODELS[p][0]
        return AIConfig(provider=p, api_key=key, model=model, max_tokens=int(self.s["max_tokens"]),
                        temperature=float(self.s["temperature"]), timeout=int(self.s["request_timeout"]),
                        ref_max_chars=int(self.s["ref_max_chars"]),
                        send_images=bool(self.s.get("ai_sees_screen", True)),
                        max_images=int(self.s.get("max_screen_pages", 6)))

    def check_ai(self, ai: AIConfig) -> bool:
        if ai.api_key:
            return True
        name = ALL_PROVIDERS[ai.provider]
        why = (f"{name}가 이 컴퓨터에 설치되어 있지 않습니다." if ai.is_cli
               else f"{name} API 키가 입력되어 있지 않습니다.")
        from .connect import ConnectDialog
        ConnectDialog(self, why)
        return False

    # ── 작업 실행 ───────────────────────────────────────────────────────
    def run_job(self, work, on_done, on_error, pane=None) -> Job | None:
        """work(job)를 작업 스레드에서 실행한다. pane이 있으면 실시간 화면을 그 미리보기에 보낸다.
        끝나면 on_done(결과), 실패하면 on_error(메시지, 중단 여부)를 화면 스레드에서 부른다."""
        if self.busy:
            return None
        self.flush_settings()
        token = ("job", next(_tokens))
        live = pane is not None and self.s.get("live_preview", True)
        job = Job(on_status=lambda m: self.after(0, self.status, m),
                  on_frame=(lambda data: self.live.submit(data, token)) if live else None)
        if pane is not None:
            pane.token = token
        self.job = job
        self._set_busy(True)

        def run():
            try:
                result = work(job)
            except Cancelled:
                self.after(0, self._finish, lambda: on_error("중단했습니다.", True))
                return
            except Exception as e:
                msg = str(e) or e.__class__.__name__
                self.after(0, self._finish, lambda: on_error(msg, False))
                return
            self.after(0, self._finish, lambda: on_done(result))
        threading.Thread(target=run, daemon=True).start()
        return job

    def stop_job(self):
        if self.job is not None:
            self.job.stop.set()
            self.status("중단하는 중…")

    def _finish(self, callback):
        self.job = None
        self._set_busy(False)
        callback()

    def _set_busy(self, busy: bool):
        self.busy = busy
        if busy:
            self._progress.pack(fill="x", after=self._header)
            self._progress.start(12)
        else:
            self._progress.stop()
            self._progress.pack_forget()
        for fn in self._busy_listeners:
            fn(busy)

    # ── 미리보기 ────────────────────────────────────────────────────────
    def _on_live_frame(self, result, token):
        for pane in self._panes:
            if pane.token == token:
                live_job = token[0] == "job"
                if live_job:
                    note = {"hangul": "실시간 미리보기 (한글)", "rhwp": "실시간 미리보기 (rhwp — 한글과 조금 다를 수 있음)"}.get(
                        self.live.engine, "실시간 미리보기 (간이 — 한글과 다를 수 있음)")
                else:
                    note = "" if self.rhwp else "빠른 미리보기 (실제 한글과 조금 다를 수 있음)"
                pane.show_pages(result.pages, note,
                                focus=(result.focus_page, result.focus_y) if live_job else None,
                                keep_scroll=token == pane.keep_token)
                pane.keep_token = token

    def preview_file(self, pane, path: str, note: str = "", original: bool = False):
        """문서 모양 미리보기 — 빠른 것부터 보여주고 더 정확한 것으로 바꾼다.
          1) rhwp(있으면, 실제 한글과 거의 같음) 또는 간이 렌더링을 바로
          2) 윈도우 한글이 있고 설정이 켜져 있으면 한글이 직접 그린 쪽 이미지로 교체 (가장 정확)"""
        token = ("file", next(_tokens))
        pane.token = token
        if path.lower().endswith(".pdf"):
            try:
                from ..readers.pdf import read_pdf
                pane.show_text(read_pdf(path)[:20000])
            except Exception as e:
                pane.show_message(f"PDF를 읽을 수 없습니다: {e}")
            return
        is_hwpx = path.lower().endswith(".hwpx")
        first = None
        if self.rhwp is not None:
            self.live.submit_file(path, token, original)
        elif is_hwpx:
            try:
                self.live.submit(Path(path).read_bytes(), token)
            except OSError as e:
                pane.show_message(f"파일을 읽을 수 없습니다: {e}")
                return
        else:
            # HWP: 파일 안에 한글이 넣어 둔 첫 쪽 그림을 먼저 보여준다 (한글 없이도 실제 모양)
            from ..readers.hwp import preview_image
            first = preview_image(path)
            if first is not None:
                pane.show_pages([first], "첫 쪽 미리보기 (한글이 저장해 둔 그림)")
            else:
                pane.show_message("한글로 쪽 이미지를 만드는 중…")
        if not (IS_WIN and self.s.get("auto_preview", True)):
            if not is_hwpx and first is None and self.rhwp is None:
                self._show_text_instead(pane, path, "HWP 문서 모양 미리보기는 윈도우용 한글이 있어야 합니다")
            return
        pane.set_note("한글로 정확한 미리보기 만드는 중…")

        def done(pages, err):
            def apply():
                if pane.token != token:
                    return   # 그 사이 다른 문서를 보고 있음
                if pages and not err:
                    pane.token = None
                    pane.show_pages(pages, note or "", keep_scroll=True)
                elif err:
                    self.status(err[:120])
                    if self.rhwp is not None:
                        pane.set_note("rhwp 미리보기 (한글과 조금 다를 수 있음)")
                    elif is_hwpx:
                        pane.set_note("빠른 미리보기 (실제 한글 화면과 조금 다를 수 있음)")
                    elif first is not None:
                        pane.set_note("첫 쪽만 표시 — 전체 내용은 [AI에 보낼 글]")
                    else:
                        self._show_text_instead(pane, path, err)
            self.after(0, apply)
        self.worker.render(path, int(self.s.get("preview_dpi", 96)), done)

    def _show_text_instead(self, pane, path: str, why: str):
        """한글로 쪽 모양을 못 그릴 때(HWP): 읽어 낸 글이라도 보여준다."""
        from ..readers import read_reference
        try:
            text = read_reference(path)
        except Exception as e:
            pane.show_message(f"{why}\n({e})")
            return
        pane.show_text(text[:30000], "글만 표시 — 한글 미리보기를 만들지 못함")

    # ── 한글 변환 ───────────────────────────────────────────────────────
    def convert_hwp(self, src: str, on_done, out_dir: Path | None = None):
        """HWP를 HWPX로 바꾼 뒤 on_done(hwpx 경로). rhwp가 있으면 한글 없이 바꾼다."""
        out_dir = out_dir or CACHE_DIR
        if self.rhwp is not None:
            out = str(out_dir / (Path(src).stem + ".hwpx"))
            self.status("HWP → HWPX 변환 중…")

            def run():
                try:
                    self.rhwp.to_hwpx(src, out)
                except Exception as e:
                    err = str(e)
                    self.after(0, lambda: (self.status("변환 실패"),
                                           messagebox.showerror("변환 실패", f"HWP 파일을 HWPX로 바꾸지 못했습니다.\n\n{err}")))
                    return
                self.after(0, lambda: (self.status("변환 완료"), on_done(out)))
            threading.Thread(target=run, daemon=True).start()
            return
        if not IS_WIN:
            messagebox.showerror("변환 불가", "HWP 파일을 HWPX로 바꾸는 기능은 윈도우용 한글이 있어야 합니다.\n"
                                          "맥용 한글에서 [다른 이름으로 저장 → HWPX]로 바꾼 뒤 사용해 주세요.")
            return
        out_dir = out_dir or CACHE_DIR
        out = str(out_dir / (Path(src).stem + ".hwpx"))
        self.status("HWP → HWPX 변환 중…")

        def done(path, err):
            def apply():
                if path and not err:
                    self.status("변환 완료")
                    on_done(path)
                else:
                    self.status("변환 실패")
                    messagebox.showerror("변환 실패", f"HWP 파일을 HWPX로 바꾸려면 한글 프로그램이 필요합니다.\n\n{err}")
            self.after(0, apply)
        self.worker.convert(src, out, "HWPX", done)

    def page_info(self, path: str):
        """AI에게 보여줄 (쪽 이미지 경로 목록, {"paras": 본문 줄별 시작 쪽, "pages": 쪽 수}). 작업 스레드에서 부른다.
        rhwp가 있으면 rhwp로, 없으면 한글로. 둘 다 안 되면 ([], None)."""
        dpi = int(self.s.get("preview_dpi", 96))
        if self.rhwp is None:
            return self.worker.page_info(path, dpi)
        try:
            from ..doc import HwpxDocument
            from ..doc.xml import P
            from ..hwp.worker import _key
            pages = self.rhwp.render_to_dir(path, CACHE_DIR / ("rhwp_" + _key(path, dpi)), dpi)
            layout = self.rhwp.layout(path)
            counts = [sum(1 for _ in root.iterchildren(P)) for root in HwpxDocument(path).ordered_sections()]
            return pages, {"paras": layout.para_pages(counts), "pages": layout.pages}
        except Exception:
            return [], None

    # ── 설정 ────────────────────────────────────────────────────────────
    def set(self, key, value):
        self.s[key] = value
        self._schedule_save()

    def set_nested(self, key, sub, value):
        self.s.setdefault(key, {})[sub] = value
        self._schedule_save()

    def _schedule_save(self):
        if self._save_job:
            self.after_cancel(self._save_job)
        self._save_job = self.after(400, self.flush_settings)

    def flush_settings(self):
        if self._save_job:
            self.after_cancel(self._save_job)
        self._save_job = None
        try:
            cfg.save(self.s)
            self.settings_tab.saved(datetime.datetime.now())
        except Exception as e:
            self.status("설정 저장 실패")
            messagebox.showerror("설정 저장 실패", f"{cfg.SETTINGS_FILE}\n\n{e}")

    def restart_worker(self):
        """보안 모듈을 새로 등록한 뒤: 이미 떠 있는 한글을 새로 띄워야 적용된다."""
        self.worker.shutdown()
        self.worker = self._new_worker()
        self.live.hangul = self.worker

    def _new_worker(self) -> HwpWorker:
        from ..hwp.worker import PROMPT_HINT
        w = HwpWorker()
        w.on_prompt = lambda: self.after(0, self.status, PROMPT_HINT)
        return w

    def clear_cache(self):
        shutil.rmtree(CACHE_DIR, ignore_errors=True)
        self.status("미리보기 캐시를 비웠습니다.")

    def _on_close(self):
        if self.job is not None:
            self.job.stop.set()
        self.s["window_geometry"] = self.geometry()
        self.flush_settings()
        self.worker.shutdown()
        self.live.close()
        self.destroy()
