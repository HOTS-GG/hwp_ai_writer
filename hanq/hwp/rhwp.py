"""rhwp 명령줄 도구 연결 — 한글 없이 HWP/HWPX를 쪽 이미지로 그리고, HWP를 HWPX로 바꾼다.

rhwp: 오픈소스 HWP/HWPX 뷰어·편집기 엔진 (Rust, MIT 라이선스)
      https://github.com/edwardkim/rhwp — Copyright (c) Edward Kim and contributors
한큐는 배포 실행 파일(rhwp.exe)을 별도 프로그램으로 실행만 한다 (코드를 섞지 않음).

찾는 순서: 설정의 경로 → 설치 폴더 tools/rhwp → 개발용 _local/rhwp → PATH.
"""
import json
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from ..config import resource_dir

RHWP_VERSION = "0.8.7"
EXE = "rhwp.exe" if os.name == "nt" else "rhwp"


class RhwpError(Exception):
    pass


def find_rhwp(custom: str = "") -> str | None:
    candidates = [custom] if custom else []
    root = resource_dir()
    candidates += [str(root / "tools" / "rhwp" / EXE), str(root / "_local" / "rhwp" / "rhwp" / EXE)]
    for c in candidates:
        if c and os.path.isfile(c):
            return c
    return shutil.which("rhwp")


@dataclass
class PageLayout:
    """dump-pages 결과: 본문 문단마다 몇 쪽 어디에 놓였는지."""
    pages: int = 0
    # (구역 번호, 문단 번호) → (쪽 번호 0부터, 쪽 안의 y px @96dpi)
    pos: dict = field(default_factory=dict)

    def para_pages(self, counts: list[int]) -> list[int]:
        """구역별 문단 수(counts)에 맞춰, 본문 문단 순서대로 시작 쪽(1부터) 목록. AI에게 주는 쪽 정보용."""
        out, last = [], 1
        for sec, n in enumerate(counts):
            for pi in range(n):
                if (sec, pi) in self.pos:
                    last = self.pos[(sec, pi)][0] + 1
                out.append(last)
        return out


class Rhwp:
    def __init__(self, exe: str):
        self.exe = exe

    def _run(self, args: list[str], timeout: int = 60, ok=(0,)) -> subprocess.CompletedProcess:
        try:
            r = subprocess.run([self.exe, *args], capture_output=True, timeout=timeout,
                               creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except (OSError, subprocess.TimeoutExpired) as e:
            raise RhwpError(f"rhwp 실행 실패: {e}")
        if r.returncode not in ok:
            msg = (r.stderr or r.stdout).decode("utf-8", errors="replace").strip()
            raise RhwpError(f"rhwp {args[0]} 실패 (코드 {r.returncode}): {msg[:300]}")
        return r

    def version(self) -> str:
        return self._run(["--version"], 15).stdout.decode("utf-8", errors="replace").strip()

    # ── 쪽 이미지 ───────────────────────────────────────────────────────
    def render_to_dir(self, src: str, out_dir: Path, dpi: int = 96) -> list[str]:
        """src(hwp/hwpx)의 쪽 이미지를 out_dir에 저장하고, 쪽 순서대로 경로 목록을 돌려준다."""
        out_dir.mkdir(parents=True, exist_ok=True)
        for old in out_dir.glob("*.png"):
            old.unlink(missing_ok=True)
        self._run(["export-png", str(src), "-o", str(out_dir), "--dpi", str(int(dpi))])
        return sorted(str(p) for p in out_dir.glob("*.png"))

    def render_bytes(self, data: bytes, dpi: int = 96, with_layout: bool = False):
        """메모리의 hwpx를 그려 (PIL 이미지 목록, PageLayout 또는 None)."""
        from PIL import Image
        with tempfile.TemporaryDirectory(prefix="hanq_rhwp_") as d:
            src = Path(d) / "frame.hwpx"
            src.write_bytes(data)
            paths = self.render_to_dir(str(src), Path(d) / "png", dpi)
            images = []
            for p in paths:
                with Image.open(p) as im:
                    images.append(im.convert("RGB"))
            layout = self.layout(str(src)) if with_layout else None
        return images, layout

    def layout(self, src: str) -> PageLayout:
        r = self._run(["dump-pages", str(src), "--json"])
        try:
            data = json.loads(r.stdout.decode("utf-8", errors="replace"))
        except ValueError as e:
            raise RhwpError(f"rhwp 쪽 정보 해석 실패: {e}")
        lay = PageLayout(pages=int(data.get("pageCount") or len(data.get("pages", []))))
        for page in data.get("pages", []):
            sec, idx = int(page.get("section", 0)), int(page.get("pageIndex", 0))
            y = float((page.get("bodyArea") or {}).get("y", 0))
            for col in page.get("columns", []):
                for it in col.get("items", []):
                    pi = it.get("paraIndex")
                    if pi is None:
                        continue
                    lay.pos.setdefault((sec, int(pi)), (idx, int(y)))
                    y += float((it.get("height") or {}).get("total") or 0)
        return lay

    # ── 변환 ────────────────────────────────────────────────────────────
    def to_hwpx(self, src: str, out: str) -> str:
        """HWP → HWPX. 검증(--verify)에서 차이가 보고돼도(코드 3·4) 파일이 만들어졌으면 쓴다."""
        Path(out).parent.mkdir(parents=True, exist_ok=True)
        self._run(["export-hwpx", str(src), str(out), "--verify"], timeout=120, ok=(0, 3, 4))
        if not Path(out).is_file():
            raise RhwpError("rhwp가 HWPX 파일을 만들지 못했습니다.")
        return out


_cached: tuple[str, Rhwp | None] | None = None


def get_rhwp(custom: str = "") -> Rhwp | None:
    """찾은 rhwp (없으면 None). 같은 설정이면 다시 찾지 않는다."""
    global _cached
    if _cached is None or _cached[0] != custom:
        exe = find_rhwp(custom)
        _cached = (custom, Rhwp(exe) if exe else None)
    return _cached[1]
