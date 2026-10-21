"""HWP 5.0 바이너리 파일을 한글 없이 읽는다 (참고 자료용).

파일은 OLE 복합 문서이고, 본문은 BodyText/SectionN 스트림에 레코드로 들어 있다(대개 deflate 압축).
레코드 머리 4바이트: tag(10비트) | level(10비트) | size(12비트, 0xFFF면 뒤 4바이트가 크기).
문단은 PARA_HEADER(66) 아래 level+1에 PARA_TEXT(67)가 오고, 표는 CTRL_HEADER(71, 'tbl ') 아래
TABLE(77)과 칸마다 LIST_HEADER(72, 칸 위치) + 그 칸의 문단들이 이어진다.
"""
import struct
import zlib

OLE_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
FREE, END_OF_CHAIN = 0xFFFFFFFF, 0xFFFFFFFE

TAG_PARA_HEADER, TAG_PARA_TEXT, TAG_CTRL_HEADER, TAG_LIST_HEADER, TAG_TABLE = 66, 67, 71, 72, 77
# 머리말·꼬리말·쪽 번호 등은 참고 자료에 필요 없는 반복 글이라 뺀다
SKIP_CTRLS = {b"head", b"foot", b"pgnp", b"pghd", b"atno", b"nwno", b"bokm", b"idxm", b"tcmt", b"tdut"}


class HwpReadError(Exception):
    pass


class OleFile:
    """OLE(Compound File Binary) 스트림 읽기."""

    def __init__(self, data: bytes):
        if data[:8] != OLE_MAGIC:
            raise HwpReadError("HWP(OLE) 파일이 아닙니다.")
        self.data = data
        self.sector = 1 << struct.unpack_from("<H", data, 30)[0]
        self.mini_sector = 1 << struct.unpack_from("<H", data, 32)[0]
        self.mini_cutoff = struct.unpack_from("<I", data, 56)[0]
        self.fat = self._read_fat()
        self.entries = self._read_directory(struct.unpack_from("<I", data, 48)[0])
        root = self.entries[0] if self.entries else {"start": END_OF_CHAIN, "size": 0}
        self.mini_stream = self._read_chain(root["start"], root["size"])
        mini_fat_start = struct.unpack_from("<I", data, 60)[0]
        mf = self._read_chain(mini_fat_start, None) if mini_fat_start < END_OF_CHAIN else b""
        self.mini_fat = list(struct.unpack_from(f"<{len(mf) // 4}I", mf)) if mf else []

    def _sector_bytes(self, sid: int) -> bytes:
        off = (sid + 1) * self.sector
        return self.data[off:off + self.sector]

    def _read_fat(self) -> list[int]:
        # 머리의 DIFAT 109개 + DIFAT 섹터 체인
        difat = list(struct.unpack_from("<109I", self.data, 76))
        nxt = struct.unpack_from("<I", self.data, 68)[0]
        seen = set()
        per = self.sector // 4 - 1
        while nxt < END_OF_CHAIN and nxt not in seen:
            seen.add(nxt)
            vals = struct.unpack_from(f"<{per + 1}I", self._sector_bytes(nxt))
            difat.extend(vals[:per])
            nxt = vals[per]
        fat = []
        for sid in difat:
            if sid >= END_OF_CHAIN:
                continue
            b = self._sector_bytes(sid)
            fat.extend(struct.unpack_from(f"<{len(b) // 4}I", b))
        return fat

    def _chain(self, start: int, table: list[int]) -> list[int]:
        out, cur, seen = [], start, set()
        while cur < len(table) and cur not in seen and cur < END_OF_CHAIN:
            seen.add(cur)
            out.append(cur)
            cur = table[cur]
        return out

    def _read_chain(self, start: int, size: int | None) -> bytes:
        buf = b"".join(self._sector_bytes(s) for s in self._chain(start, self.fat))
        return buf if size is None else buf[:size]

    def _read_mini(self, start: int, size: int) -> bytes:
        ms = self.mini_sector
        buf = b"".join(self.mini_stream[s * ms:(s + 1) * ms] for s in self._chain(start, self.mini_fat))
        return buf[:size]

    def _read_directory(self, start: int) -> list[dict]:
        raw = self._read_chain(start, None)
        entries = []
        for b in range(0, len(raw) - 127, 128):
            nlen = struct.unpack_from("<H", raw, b + 64)[0]
            etype = raw[b + 66]
            if etype == 0:
                continue
            name = raw[b:b + max(nlen - 2, 0)].decode("utf-16-le", errors="replace")
            entries.append({"name": name, "type": etype,
                            "start": struct.unpack_from("<I", raw, b + 116)[0],
                            "size": struct.unpack_from("<I", raw, b + 120)[0]})
        return entries

    def stream(self, name: str) -> bytes | None:
        for e in self.entries:
            if e["type"] == 2 and e["name"] == name:
                if e["size"] < self.mini_cutoff:
                    return self._read_mini(e["start"], e["size"])
                return self._read_chain(e["start"], e["size"])
        return None

    def names(self) -> list[str]:
        return [e["name"] for e in self.entries if e["type"] == 2]


def parse_records(raw: bytes) -> list[tuple[int, int, bytes]]:
    """(tag, level, data) 목록."""
    recs, pos, n = [], 0, len(raw)
    while pos + 4 <= n:
        hdr = struct.unpack_from("<I", raw, pos)[0]
        tag, lv, sz = hdr & 0x3FF, (hdr >> 10) & 0x3FF, (hdr >> 20) & 0xFFF
        pos += 4
        if sz == 0xFFF and pos + 4 <= n:
            sz = struct.unpack_from("<I", raw, pos)[0]
            pos += 4
        recs.append((tag, lv, raw[pos:pos + sz]))
        pos += sz
    return recs


def decode_para_text(data: bytes) -> str:
    """PARA_TEXT(UTF-16LE) → 글자. 제어문자 1~9, 11~12, 14~23은 인라인/확장 컨트롤로
    8글자(16바이트)를 차지하므로 건너뛴다. 9(탭)는 탭으로, 10·13은 줄바꿈으로."""
    out, k = [], 0
    n = len(data) // 2
    while k < n:
        code = struct.unpack_from("<H", data, k * 2)[0]
        if code >= 32:
            out.append(chr(code))
            k += 1
            continue
        if code == 9:
            out.append("\t")
        elif code in (10, 13):
            out.append("\n")
        k += 8 if code not in (0, 10, 13) and code < 24 else 1
    # 서로게이트 쌍(확장 한자 등)을 정상 글자로 합친다
    text = "".join(out).encode("utf-16-le", "surrogatepass").decode("utf-16-le", "replace")
    return text.rstrip("\n")


class _BodyParser:
    """레코드 목록을 줄(본문)과 '| 칸 | 칸 |' 줄(표)로 바꾼다."""

    def __init__(self, recs):
        self.recs = recs
        self.i = 0

    def paragraphs(self, level: int) -> list[str]:
        """level의 PARA_HEADER들을 읽는다. 같은 level의 다른 레코드(다음 칸의 LIST_HEADER 등)나
        더 얕은 level을 만나면 멈춘다."""
        out = []
        recs = self.recs
        while self.i < len(recs):
            tag, lv, _ = recs[self.i]
            if lv < level or (lv == level and tag != TAG_PARA_HEADER):
                break
            if lv > level:      # 예상 밖 레코드: 건너뜀
                self.i += 1
                continue
            self.i += 1
            text, extra = "", []
            while self.i < len(recs) and recs[self.i][1] > level:
                tag, lv, data = recs[self.i]
                if tag == TAG_PARA_TEXT and lv == level + 1:
                    text = decode_para_text(data)
                    self.i += 1
                elif tag == TAG_CTRL_HEADER and lv == level + 1:
                    extra += self._control(lv)
                else:
                    self.i += 1
            if text.strip():
                out.append(text)
            out += extra
        return out

    def _control(self, level: int) -> list[str]:
        ctrl = self.recs[self.i][2][:4][::-1]
        self.i += 1
        if ctrl == b"tbl ":
            return self._table(level)
        lines = []
        # 글상자·각주 등: 안에 든 문단 글만 꺼낸다
        while self.i < len(self.recs) and self.recs[self.i][1] > level:
            tag, lv, _ = self.recs[self.i]
            if tag == TAG_LIST_HEADER and ctrl not in SKIP_CTRLS:
                self.i += 1
                lines += self.paragraphs(lv)
            else:
                self.i += 1
        return [ln for ln in lines if ln.strip()]

    def _table(self, level: int) -> list[str]:
        cells, nested = {}, []
        while self.i < len(self.recs) and self.recs[self.i][1] > level:
            tag, lv, data = self.recs[self.i]
            if tag == TAG_LIST_HEADER and lv == level + 1 and len(data) >= 12:
                col, row = struct.unpack_from("<HH", data, 8)
                self.i += 1
                lines = self.paragraphs(lv)
                plain = [ln for ln in lines if not ln.startswith("| ")]
                nested += [ln for ln in lines if ln.startswith("| ")]
                cells[(row, col)] = " ".join(s.strip().replace("\n", " ") for s in plain).strip()
            else:
                self.i += 1
        rows: dict[int, list] = {}
        for (r, c), text in sorted(cells.items()):
            rows.setdefault(r, []).append(text)
        out = ["| " + " | ".join(v) + " |" for _, v in sorted(rows.items()) if any(x for x in v)]
        return out + nested


class HwpReader:
    def __init__(self, path: str):
        with open(path, "rb") as f:
            self.ole = OleFile(f.read())
        fh = self.ole.stream("FileHeader") or b""
        flags = struct.unpack_from("<I", fh, 36)[0] if len(fh) >= 40 else 1
        self.compressed = bool(flags & 1)
        self.encrypted = bool(flags & 2)
        self.distribution = bool(flags & 4)

    def _section_records(self, i: int):
        raw = self.ole.stream(f"Section{i}")
        if raw is None:
            return None
        if self.compressed:
            try:
                raw = zlib.decompress(raw, -15)
            except zlib.error:
                return []
        return parse_records(raw)

    def body_text(self) -> str:
        lines = []
        i = 0
        while True:
            recs = self._section_records(i)
            if recs is None:
                break
            parser = _BodyParser(recs)
            while parser.i < len(recs):
                before = parser.i
                lines += parser.paragraphs(0)
                if parser.i == before:   # 문단이 아닌 레코드: 건너뛰고 계속
                    parser.i += 1
            i += 1
        return "\n".join(lines)

    def preview_text(self) -> str:
        prv = self.ole.stream("PrvText")
        return prv.decode("utf-16-le", errors="replace").rstrip("\x00") if prv else ""

    def text(self) -> str:
        """본문 글. 암호·배포용 문서처럼 본문을 못 읽으면 미리보기 글(앞부분)이라도 돌려준다."""
        if not (self.encrypted or self.distribution):
            body = self.body_text()
            if body.strip():
                return body
        return self.preview_text()


def read_hwp(path: str) -> str:
    return HwpReader(path).text()


def preview_image(path: str):
    """한글이 저장할 때 파일 안에 넣어 둔 첫 쪽 그림(PrvImage, 보통 PNG). 한글 없이 실제 모양을 보여줄 때 쓴다.
    없거나 못 읽으면 None."""
    import io
    try:
        with open(path, "rb") as f:
            data = OleFile(f.read()).stream("PrvImage")
        if not data:
            return None
        from PIL import Image
        im = Image.open(io.BytesIO(data))
        im.load()
        return im.convert("RGB")
    except Exception:
        return None
