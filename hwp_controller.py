"""
HWP COM API wrapper for reading/writing HWP documents.
Requires Hancom Office (HWP) installed on the system.
"""
import os
import re
import struct
import zlib
import tempfile
from pathlib import Path
from typing import Optional


def _parse_inline_md(text: str) -> list[tuple[str, bool, bool]]:
    """마크다운 인라인 서식을 (텍스트, bold, italic) 세그먼트 리스트로 분해합니다."""
    segments = []
    pattern = re.compile(r'(\*\*\*.*?\*\*\*|\*\*.*?\*\*|\*.*?\*|___.*?___|__.*?__|_.*?_|`.*?`)')
    pos = 0
    for m in pattern.finditer(text):
        if m.start() > pos:
            segments.append((text[pos:m.start()], False, False))
        raw = m.group(0)
        if raw.startswith('***') or raw.startswith('___'):
            segments.append((raw[3:-3], True, True))
        elif raw.startswith('**') or raw.startswith('__'):
            segments.append((raw[2:-2], True, False))
        elif raw.startswith('`'):
            segments.append((raw[1:-1], False, False))
        else:
            segments.append((raw[1:-1], False, True))
        pos = m.end()
    if pos < len(text):
        segments.append((text[pos:], False, False))
    return segments


def markdown_to_plain(text: str) -> str:
    """마크다운 기호를 제거하여 읽기 좋은 평문으로 변환합니다 (미리보기용)."""
    result = []
    in_code = False
    code_lang = ""

    for line in text.splitlines():
        # ── 코드 펜스 ──
        fence = re.match(r'^(`{3,}|~{3,})(.*)', line.strip())
        if fence:
            if in_code:
                in_code = False
            else:
                in_code = True
                code_lang = fence.group(2).strip()
                result.append(f'[코드{": " + code_lang if code_lang else ""}]')
            continue
        if in_code:
            result.append(line)
            continue

        # ── 제목 ──
        h = re.match(r'^(#{1,6})\s+(.*)', line)
        if h:
            result.append(h.group(2).strip())
            continue

        # ── 구분선 ──
        if re.match(r'^[-*_]{3,}\s*$', line.strip()):
            result.append('─' * 40)
            continue

        # ── 표 행 ──
        if line.strip().startswith('|'):
            cols = [c.strip() for c in line.strip().strip('|').split('|')]
            # 구분자 행(--- 만 있는 행) 건너뜀
            if all(re.match(r'^[-: ]+$', c) for c in cols if c):
                continue
            result.append('  '.join(cols))
            continue

        # ── 인라인 서식 제거 ──
        line = re.sub(r'\*\*\*(.*?)\*\*\*', r'\1', line)
        line = re.sub(r'\*\*(.*?)\*\*',     r'\1', line)
        line = re.sub(r'\*(.*?)\*',          r'\1', line)
        line = re.sub(r'___(.*?)___',        r'\1', line)
        line = re.sub(r'__(.*?)__',          r'\1', line)
        line = re.sub(r'_(.*?)_',            r'\1', line)
        line = re.sub(r'`([^`]+)`',          r'\1', line)
        line = re.sub(r'^[-*+]\s+',          '• ',  line)

        result.append(line)

    return '\n'.join(result)


# ── COM-based controller (HWP must be running) ──────────────────────────────

class HwpController:
    def __init__(self):
        self.hwp = None
        self._connected = False

    def connect(self) -> bool:
        try:
            import win32com.client
            self.hwp = win32com.client.Dispatch("HWPFrame.HwpObject")
            # SecurityModule: 파일 경로 제한 해제용. 실패해도 연결은 유지
            import hwp_security
            hwp_security.register(self.hwp)
            self._connected = True
            return True
        except Exception as e:
            self._connected = False
            raise RuntimeError(f"HWP COM 연결 실패: {e}\n한글 프로그램이 설치되어 있는지 확인하세요.")

    def is_connected(self) -> bool:
        return self._connected and self.hwp is not None

    def open_file(self, path: str) -> bool:
        if not self.is_connected():
            self.connect()
        path = str(Path(path).resolve())
        return bool(self.hwp.Open(path, "HWP", ""))

    def new_document(self):
        if not self.is_connected():
            self.connect()
        self.hwp.HAction.Run("FileNew")

    def read_text(self) -> str:
        """Extract all visible text from the open document."""
        if not self.is_connected():
            raise RuntimeError("HWP가 연결되지 않았습니다.")
        texts = []
        ctrl = self.hwp.HeadCtrl
        while ctrl is not None:
            try:
                if hasattr(ctrl, "Text") and ctrl.Text:
                    texts.append(ctrl.Text)
            except Exception:
                pass
            try:
                ctrl = ctrl.Next
            except Exception:
                break
        # Fallback: use clipboard
        if not texts:
            self.hwp.HAction.GetDefault("SelectAll", self.hwp.HParameterSet.HSelectionAll.HSet)
            self.hwp.HAction.Execute("SelectAll", self.hwp.HParameterSet.HSelectionAll.HSet)
            texts = [self._get_selected_text()]
        return "\n".join(t for t in texts if t)

    def _get_selected_text(self) -> str:
        try:
            import win32clipboard
            import win32con
            self.hwp.HAction.GetDefault("Copy", self.hwp.HParameterSet.HSelectionAll.HSet)
            self.hwp.HAction.Execute("Copy", self.hwp.HParameterSet.HSelectionAll.HSet)
            win32clipboard.OpenClipboard()
            data = win32clipboard.GetClipboardData(win32con.CF_UNICODETEXT)
            win32clipboard.CloseClipboard()
            return data
        except Exception:
            return ""

    def get_fields(self) -> list[str]:
        """Return all field names ({{field}}) in the document."""
        text = self._read_raw_text()
        return re.findall(r'\{\{(\w+)\}\}', text)

    def _read_raw_text(self) -> str:
        """Read text including template markers."""
        if not self.is_connected():
            return ""
        try:
            return self.hwp.GetTextFile("TEXT", "") or ""
        except Exception:
            return self.read_text()

    def fill_fields(self, fields: dict[str, str]):
        """Replace {{field}} markers with actual values using Find & Replace."""
        if not self.is_connected():
            raise RuntimeError("HWP가 연결되지 않았습니다.")
        for key, value in fields.items():
            param = self.hwp.HParameterSet.HFindReplace
            self.hwp.HAction.GetDefault("AllReplace", param.HSet)
            param.FindString = f"{{{{{key}}}}}"
            param.ReplaceString = value
            param.IgnoreMessage = 1
            param.FindType = 1
            self.hwp.HAction.Execute("AllReplace", param.HSet)

    def insert_text(self, text: str, position: str = "end"):
        """Insert text at given position (start/end/cursor).
        클립보드 경유 방식을 우선 사용 — 긴 한국어 텍스트에 더 안정적."""
        if not self.is_connected():
            raise RuntimeError("HWP가 연결되지 않았습니다.")
        if position == "end":
            self.hwp.MovePos(6)
        elif position == "start":
            self.hwp.MovePos(5)

        # 1차: 클립보드 경유 붙여넣기 (한국어·긴 텍스트에 신뢰성 높음)
        try:
            import win32clipboard
            import win32con
            win32clipboard.OpenClipboard()
            win32clipboard.EmptyClipboard()
            win32clipboard.SetClipboardData(win32con.CF_UNICODETEXT, text)
            win32clipboard.CloseClipboard()
            self.hwp.HAction.GetDefault("Paste", self.hwp.HParameterSet.HSelectionAll.HSet)
            self.hwp.HAction.Execute("Paste", self.hwp.HParameterSet.HSelectionAll.HSet)
            return
        except Exception:
            pass

        # 2차: InsertText 액션 (폴백)
        self.hwp.HAction.GetDefault("InsertText", self.hwp.HParameterSet.HInsertText.HSet)
        self.hwp.HParameterSet.HInsertText.Text = text
        self.hwp.HAction.Execute("InsertText", self.hwp.HParameterSet.HInsertText.HSet)

    def save_as(self, path: str, format: str = "HWP") -> bool:
        """Save document to path. format: 'HWP', 'HWPX', 'PDF', 'DOCX'."""
        path = str(Path(path).resolve())
        fmt_map = {"HWP": "HWP", "HWPX": "HWPX", "PDF": "PDF", "DOCX": "DOCX"}
        fmt = fmt_map.get(format.upper(), "HWP")

        # 1차: SaveAs 직접 메서드 (더 간단하고 안정적)
        try:
            return bool(self.hwp.SaveAs(path, fmt, ""))
        except Exception:
            pass

        # 2차: FileSaveAs 액션 (폴백)
        param = self.hwp.HParameterSet.HFileSaveAs
        self.hwp.HAction.GetDefault("FileSaveAs", param.HSet)
        param.filename = path
        param.Format = fmt
        param.version = "5.0.0.0"
        return bool(self.hwp.HAction.Execute("FileSaveAs", param.HSet))

    def write_markdown(self, text: str):
        """마크다운 텍스트를 파싱하여 HWP 서식으로 작성합니다."""
        if not self.is_connected():
            raise RuntimeError("HWP가 연결되지 않았습니다.")
        in_code = False
        code_buf: list[str] = []

        for line in text.splitlines():
            fence = re.match(r'^(`{3,}|~{3,})(.*)', line.strip())
            if fence:
                if in_code:
                    # 코드 블록 종료 → 모아서 삽입
                    in_code = False
                    self._md_insert_code_block('\n'.join(code_buf))
                    code_buf = []
                else:
                    in_code = True
                    lang = fence.group(2).strip()
                    if lang:
                        self._md_insert_inline(f'[{lang}]', indent=False)
                continue

            if in_code:
                code_buf.append(line)
                continue

            # 표 행
            if line.strip().startswith('|'):
                cols = [c.strip() for c in line.strip().strip('|').split('|')]
                if all(re.match(r'^[-: ]+$', c) for c in cols if c):
                    continue  # 구분자 행 건너뜀
                self._md_insert_inline('   '.join(cols))
                continue

            self._md_write_line(line)

        # 미닫힌 코드 블록 처리
        if in_code and code_buf:
            self._md_insert_code_block('\n'.join(code_buf))

    # ── 마크다운 헬퍼 ─────────────────────────────────────────────────

    def _md_write_line(self, line: str):
        h = re.match(r'^(#{1,6})\s+(.*)', line)
        if h:
            level = len(h.group(1))
            self._md_insert_heading(h.group(2).strip(), level)
            return
        if re.match(r'^[-*_]{3,}\s*$', line.strip()):
            self._md_insert_hr()
            return
        bullet = re.match(r'^(\s*)([-*+])\s+(.*)', line)
        if bullet:
            self._md_insert_inline(bullet.group(3), indent=True)
            return
        num = re.match(r'^(\s*)\d+\.\s+(.*)', line)
        if num:
            self._md_insert_inline(num.group(2), indent=True)
            return
        if line.strip() == '':
            self._hwp_break_para()
        else:
            self._md_insert_inline(line)

    def _md_insert_heading(self, text: str, level: int):
        sizes  = {1: 2200, 2: 1800, 3: 1600, 4: 1400, 5: 1200, 6: 1100}
        size = sizes.get(level, 1200)
        plain = re.sub(r'\*+|_+|`', '', text)
        self._hwp_set_charshape(bold=True, size=size)
        self._hwp_insert_text(plain)
        self._hwp_reset_charshape()
        self._hwp_break_para()

    def _md_insert_hr(self):
        self._hwp_insert_text('─' * 40)
        self._hwp_break_para()

    def _md_insert_code_block(self, code: str):
        self._hwp_set_charshape(bold=False, italic=False, size=900,
                                face="courier new")
        for line in code.splitlines():
            self._hwp_insert_text(line or ' ')
            self._hwp_break_para()
        self._hwp_reset_charshape()

    def _md_insert_inline(self, text: str, indent: bool = False):
        if indent:
            self._hwp_insert_text('  ')
        for content, bold, italic in _parse_inline_md(text):
            if content:
                self._hwp_set_charshape(bold=bold, italic=italic)
                self._hwp_insert_text(content)
        self._hwp_reset_charshape()
        self._hwp_break_para()

    def _hwp_insert_text(self, text: str):
        p = self.hwp.HParameterSet.HInsertText
        self.hwp.HAction.GetDefault("InsertText", p.HSet)
        p.Text = text
        self.hwp.HAction.Execute("InsertText", p.HSet)

    def _hwp_break_para(self):
        self.hwp.HAction.Run("BreakPara")

    def _hwp_set_charshape(self, bold: bool = False, italic: bool = False,
                           size: int = 0, face: str = ""):
        p = self.hwp.HParameterSet.HCharShape
        self.hwp.HAction.GetDefault("CharShape", p.HSet)
        p.Bold   = 1 if bold   else 0
        p.Italic = 1 if italic else 0
        if size:
            p.Height = size
        if face:
            try:
                p.FaceNameHangul  = face
                p.FaceNameLatin   = face
            except Exception:
                pass
        self.hwp.HAction.Execute("CharShape", p.HSet)

    def _hwp_reset_charshape(self):
        p = self.hwp.HParameterSet.HCharShape
        self.hwp.HAction.GetDefault("CharShape", p.HSet)
        p.Bold = 0
        p.Italic = 0
        p.Height = 1000  # 10pt 기본
        self.hwp.HAction.Execute("CharShape", p.HSet)

    def run_macro(self, code: str) -> tuple[bool, str]:
        """HWP JavaScript 매크로를 실행합니다. (성공, 오류메시지) 반환."""
        if not self.is_connected():
            self.connect()

        # Python exec 방식: JS 엔진 없이 COM API 직접 호출
        try:
            ns: dict = {}
            exec(code, {"__builtins__": __builtins__}, ns)  # def main(hwp) 정의
            if "main" not in ns:
                return False, "생성된 코드에 'def main(hwp):' 함수가 없습니다."
            ns["main"](self.hwp)
            return True, ""
        except Exception as e:
            return False, str(e)

    def close(self):
        if self.hwp:
            try:
                self.hwp.Quit()
            except Exception:
                pass
            self.hwp = None
            self._connected = False

    @staticmethod
    def create_hwpx(path: str, text: str) -> None:
        """HWP 설치 없이 HWPX 파일을 생성합니다. 한글 2010 이상에서 열 수 있습니다."""
        import zipfile

        def esc(s: str) -> str:
            return (s.replace("&", "&amp;").replace("<", "&lt;")
                     .replace(">", "&gt;").replace('"', "&quot;"))

        # 본문: 줄바꿈을 단락으로 변환
        paras = "\n".join(
            f'  <hp:p><hp:run><hc:t>{esc(ln)}</hc:t></hp:run></hp:p>'
            for ln in text.split("\n")
        )

        section_xml = (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
            '<hs:sec xmlns:hs="http://www.hancom.co.kr/hwpml/2012/section"'
            ' xmlns:hp="http://www.hancom.co.kr/hwpml/2012/paragraph"'
            ' xmlns:hc="http://www.hancom.co.kr/hwpml/2012/char">\n'
            f'{paras}\n'
            '</hs:sec>'
        )

        container_xml = (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
            '<container>\n'
            '  <rootfiles>\n'
            '    <rootfile full-path="Contents/content.hpf"/>\n'
            '  </rootfiles>\n'
            '</container>'
        )

        content_hpf = (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
            '<package xmlns="http://www.idpf.org/2007/opf">\n'
            '  <metadata/>\n'
            '  <manifest>\n'
            '    <item id="section0" href="section0.xml" media-type="application/xml"/>\n'
            '  </manifest>\n'
            '  <spine><itemref idref="section0"/></spine>\n'
            '</package>'
        )

        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
            # mimetype은 반드시 첫 번째, 비압축으로 저장
            info = zipfile.ZipInfo("mimetype")
            info.compress_type = zipfile.ZIP_STORED
            zf.writestr(info, "application/hwp+zip")
            zf.writestr("META-INF/container.xml", container_xml)
            zf.writestr("Contents/content.hpf", content_hpf)
            zf.writestr("Contents/section0.xml", section_xml)


# ── Standalone HWP reader (no HWP installation needed) ──────────────────────

class HwpFileReader:
    """
    Reads HWP 5.0 files directly (OLE + raw deflate).
    Use this when HWP COM is not available.
    """

    SECTOR = 512
    MINI_SECTOR = 64
    MINI_CUTOFF = 4096

    def __init__(self, path: str):
        with open(path, 'rb') as f:
            self.data = f.read()
        self._fat: list[int] = []
        self._mini_fat: list[int] = []
        self._directory: list[dict] = []
        self._mini_stream: bytes = b''
        self._parse_ole()

    def _u32(self, off: int) -> int:
        return struct.unpack_from('<I', self.data, off)[0]

    def _i32(self, off: int) -> int:
        return struct.unpack_from('<i', self.data, off)[0]

    def _parse_ole(self):
        S = self.SECTOR
        # FAT
        for i in range(109):
            fs = self._i32(0x4C + i * 4)
            if fs < 0:
                break
            off = S + fs * S
            for j in range(S // 4):
                self._fat.append(self._i32(off + j * 4))
        # Directory
        dir_start = self._u32(0x30)
        dir_raw = self._read_large(dir_start, 10 * 1024 * 1024)
        for i in range(len(dir_raw) // 128):
            b = i * 128
            nlen = struct.unpack_from('<H', dir_raw, b + 64)[0]
            name = dir_raw[b:b + max(nlen - 2, 0)].decode('utf-16-le', errors='replace') if nlen >= 2 else ''
            etype = dir_raw[b + 66]
            start = self._u32(b + 116) if b + 120 <= len(dir_raw) else 0
            size  = self._u32(b + 120) if b + 124 <= len(dir_raw) else 0
            if name or etype == 5:
                self._directory.append({'name': name, 'type': etype, 'start': start, 'size': size})
        # Mini FAT
        mfs = self._u32(0x3C)
        if mfs < 0xFFFFFFFE:
            for sec in self._sector_chain(mfs):
                off = S + sec * S
                for j in range(S // 4):
                    self._mini_fat.append(self._i32(off + j * 4))
        # Mini stream
        root = self._directory[0] if self._directory else {'start': 0, 'size': 0}
        self._mini_stream = self._read_large(root['start'], root['size'])

    def _sector_chain(self, start: int) -> list[int]:
        chain, cur, seen = [], start, set()
        while 0 <= cur < len(self._fat) and cur not in seen:
            seen.add(cur); chain.append(cur); cur = self._fat[cur]
        return chain

    def _mini_chain(self, start: int) -> list[int]:
        chain, cur, seen = [], start, set()
        while 0 <= cur < len(self._mini_fat) and cur not in seen:
            seen.add(cur); chain.append(cur); cur = self._mini_fat[cur]
        return chain

    def _read_large(self, start: int, size: int) -> bytes:
        S = self.SECTOR
        buf = bytearray()
        for sec in self._sector_chain(start):
            off = S + sec * S
            buf.extend(self.data[off:off + S])
        return bytes(buf[:size])

    def _read_mini(self, start: int, size: int) -> bytes:
        MS = self.MINI_SECTOR
        buf = bytearray()
        for ms in self._mini_chain(start):
            off = ms * MS
            buf.extend(self._mini_stream[off:off + MS])
        return bytes(buf[:size])

    def _get_stream(self, name: str) -> Optional[bytes]:
        for e in self._directory:
            if e['name'] == name and e['type'] == 2:
                if e['size'] < self.MINI_CUTOFF:
                    return self._read_mini(e['start'], e['size'])
                else:
                    return self._read_large(e['start'], e['size'])
        return None

    @staticmethod
    def _decompress(raw: bytes) -> bytes:
        return zlib.decompress(raw, wbits=-15)

    def _parse_records(self, raw: bytes) -> list[dict]:
        recs, pos = [], 0
        while pos + 4 <= len(raw):
            hdr = struct.unpack_from('<I', raw, pos)[0]
            tag = hdr & 0x3FF
            lv  = (hdr >> 10) & 0x3FF
            sz  = (hdr >> 20) & 0xFFF
            pos += 4
            if sz == 0xFFF and pos + 4 <= len(raw):
                sz = struct.unpack_from('<I', raw, pos)[0]; pos += 4
            recs.append({'tag': tag, 'lv': lv, 'sz': sz, 'data': raw[pos:pos + sz]})
            pos += sz
        return recs

    def read_preview_text(self) -> str:
        prv = self._get_stream('PrvText')
        if not prv:
            return ''
        return prv.decode('utf-16-le', errors='replace').rstrip('\x00')

    def read_body_text(self) -> str:
        texts = []
        i = 0
        while True:
            stream_name = f'Section{i}'
            raw = self._get_stream(stream_name)
            if raw is None:
                break
            try:
                dec = self._decompress(raw)
                for rec in self._parse_records(dec):
                    if rec['tag'] == 51 and rec['sz'] > 0:  # PARA_TEXT
                        chars = []
                        for j in range(0, rec['sz'] - 1, 2):
                            code = struct.unpack_from('<H', rec['data'], j)[0]
                            if code == 13: break
                            if code >= 32:
                                chars.append(chr(code))
                        t = ''.join(chars)
                        if t.strip():
                            texts.append(t)
            except Exception:
                pass
            i += 1
        return '\n'.join(texts)

    def read_all_text(self) -> str:
        body = self.read_body_text()
        if body:
            return body
        return self.read_preview_text()

    def get_fields(self) -> list[str]:
        text = self.read_all_text()
        return list(dict.fromkeys(re.findall(r'\{\{(\w+)\}\}', text)))

    def get_file_info(self) -> dict:
        fh = self._get_stream('FileHeader')
        if not fh or len(fh) < 40:
            return {}
        sig = fh[:32].rstrip(b'\x00').decode('ascii', errors='replace')
        ver = struct.unpack_from('<4B', fh, 32)
        flags = struct.unpack_from('<I', fh, 36)[0]
        return {
            'signature': sig,
            'version': f'{ver[3]}.{ver[2]}.{ver[1]}.{ver[0]}',
            'compressed': bool(flags & 1),
            'encrypted': bool(flags & 2),
        }
