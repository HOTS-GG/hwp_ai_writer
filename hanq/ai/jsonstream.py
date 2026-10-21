"""스트리밍으로 받는 중인(아직 덜 끝난) JSON에서 지금까지 완성된 항목을 꺼낸다.

예) '{"slots": {"S1": "2025년 계획", "S2": "1. 목적을 달'  까지 받았으면
    entries = {"slots": {"S1": "2025년 계획"}}, typing = ("slots", "S2", "1. 목적을 달")

받을 때마다 처음부터 다시 훑는다 (응답은 수십 KB 이하라 충분히 빠르다).
문법이 어긋난 곳(따옴표 실수 등)을 만나면 거기서 멈추고, 마지막에는 jsonutil.parse_json이 고쳐서 읽는다.
"""
import json
from dataclasses import dataclass, field

# strict=False: 문자열 안의 날 줄바꿈·탭(AI가 자주 하는 실수)도 받아들인다
_DEC = json.JSONDecoder(strict=False)
_WS = " \t\r\n"
_ESC = {'"': '"', "\\": "\\", "/": "/", "b": "\b", "f": "\f", "n": "\n", "r": "\r", "t": "\t"}


@dataclass
class Partial:
    entries: dict = field(default_factory=dict)    # 지켜보는 객체 → {키: 값} (완성된 것만)
    items: dict = field(default_factory=dict)      # 지켜보는 배열 → [값, …] (완성된 것만)
    scalars: dict = field(default_factory=dict)    # 맨 바깥의 완성된 값 (title 등)
    typing: tuple | None = None                    # (객체 이름, 키, 지금까지 받은 글자) — 쓰는 중인 글자 값


def _skip(s: str, i: int) -> int:
    while i < len(s) and s[i] in _WS:
        i += 1
    return i


def _partial_string(s: str, i: int) -> str:
    """s[i]가 여는 따옴표 다음 글자. 끝나지 않은 문자열을 지금까지 받은 만큼 풀어 돌려준다."""
    out = []
    n = len(s)
    while i < n:
        ch = s[i]
        if ch == '"':
            break
        if ch == "\\":
            if i + 1 >= n:
                break
            nx = s[i + 1]
            if nx == "u":
                if i + 6 > n:
                    break
                try:
                    out.append(chr(int(s[i + 2:i + 6], 16)))
                except ValueError:
                    pass
                i += 6
                continue
            out.append(_ESC.get(nx, nx))
            i += 2
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def _closed(s: str, i: int, closers: str) -> bool:
    """값 바로 뒤에 쉼표나 닫는 괄호가 왔는지. 아직 안 왔으면(끝까지 받지 못함) 완성으로 보지 않는다.
    문장 속 따옴표 실수로 값이 일찍 끝난 것처럼 보이는 경우를 거른다."""
    j = _skip(s, i)
    return j < len(s) and s[j] in closers


def _key(s: str, i: int):
    """i에서 문자열 키를 읽는다. (키, 다음 위치) 또는 None(덜 받음/문법 오류)."""
    if i >= len(s) or s[i] != '"':
        return None
    try:
        k, j = _DEC.raw_decode(s, i)
    except ValueError:
        return None
    return (k, j) if isinstance(k, str) else None


def scan(text: str, objects=("slots", "tables"), arrays=("blocks",)) -> Partial:
    res = Partial()
    s = text
    i = s.find("{")
    if i < 0:
        return res
    i += 1
    while True:
        i = _skip(s, i)
        if i >= len(s) or s[i] == "}":
            return res
        if s[i] == ",":
            i += 1
            continue
        kv = _key(s, i)
        if kv is None:
            return res
        key, i = kv
        i = _skip(s, i)
        if i >= len(s) or s[i] != ":":
            return res
        i = _skip(s, i + 1)
        if i >= len(s):
            return res
        if key in objects and s[i] == "{":
            got = res.entries.setdefault(key, {})
            i += 1
            while True:
                i = _skip(s, i)
                if i >= len(s):
                    return res
                if s[i] == "}":
                    i += 1
                    break
                if s[i] == ",":
                    i += 1
                    continue
                kv = _key(s, i)
                if kv is None:
                    return res
                k2, i = kv
                i = _skip(s, i)
                if i >= len(s) or s[i] != ":":
                    return res
                i = _skip(s, i + 1)
                start = i
                try:
                    val, i = _DEC.raw_decode(s, i)
                    ok = _closed(s, i, ",}")
                except ValueError:
                    ok = False
                if not ok:
                    if start < len(s) and s[start] == '"':
                        res.typing = (key, k2, _partial_string(s, start + 1))
                    return res
                got[k2] = val
        elif key in arrays and s[i] == "[":
            got = res.items.setdefault(key, [])
            i += 1
            while True:
                i = _skip(s, i)
                if i >= len(s):
                    return res
                if s[i] == "]":
                    i += 1
                    break
                if s[i] == ",":
                    i += 1
                    continue
                try:
                    val, i = _DEC.raw_decode(s, i)
                except ValueError:
                    return res
                if not _closed(s, i, ",]"):
                    return res
                got.append(val)
        else:
            try:
                val, i = _DEC.raw_decode(s, i)
            except ValueError:
                return res
            if not _closed(s, i, ",}"):
                return res
            res.scalars[key] = val
