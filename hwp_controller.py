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
            try:
                self.hwp.RegisterModule("FilePathCheckDLL", "SecurityModule")
            except Exception:
                pass
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
        self.hwp.HAction.GetDefault("FileNew", self.hwp.HParameterSet.HFileNew.HSet)
        self.hwp.HAction.Execute("FileNew", self.hwp.HParameterSet.HFileNew.HSet)

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
