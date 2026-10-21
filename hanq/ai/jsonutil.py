"""AI 응답에서 JSON 객체를 꺼내고, 흔한 실수(문장 속 따옴표, 날 줄바꿈, 끝 쉼표)를 고친다."""
import json
import re


class JSONError(ValueError):
    pass


def extract(text: str) -> str:
    """코드 블록(```json)이나 앞뒤 설명을 걷어내고 가장 바깥 { … }만 남긴다."""
    s = text.strip()
    if s.startswith("```"):
        s = s.split("\n", 1)[1] if "\n" in s else s
        s = s.rsplit("```", 1)[0]
    start, end = s.find("{"), s.rfind("}")
    if start < 0 or end < 0:
        raise JSONError("AI 응답에서 JSON을 찾지 못했습니다.")
    return s[start:end + 1]


def repair(s: str) -> str:
    """문자열 안에서 만난 '"' 다음(공백 제외)에 , : } ] 가 오지 않으면 문장 속 따옴표로 보고 이스케이프한다.
    문자열 안의 날 줄바꿈·탭도 이스케이프하고, 끝 쉼표(,} ,])를 지운다."""
    out = []
    in_str = False
    i, n = 0, len(s)
    while i < n:
        ch = s[i]
        if not in_str:
            out.append(ch)
            if ch == '"':
                in_str = True
        elif ch == "\\" and i + 1 < n:
            out.append(s[i:i + 2])
            i += 1
        elif ch == '"':
            j = i + 1
            while j < n and s[j] in " \t\r\n":
                j += 1
            if j >= n or s[j] in ",:}]":
                out.append(ch)
                in_str = False
            else:
                out.append('\\"')
        elif ch == "\n":
            out.append("\\n")
        elif ch == "\r":
            pass
        elif ch == "\t":
            out.append("\\t")
        else:
            out.append(ch)
        i += 1
    return re.sub(r",(\s*[}\]])", r"\1", "".join(out))


def parse_json(text: str) -> dict:
    s = extract(text)
    try:
        data = json.loads(s)
    except ValueError:
        try:
            data = json.loads(repair(s))
        except ValueError as e:
            raise JSONError(f"AI 응답 JSON 해석 실패: {e}")
    if not isinstance(data, dict):
        raise JSONError("AI 응답이 JSON 객체가 아닙니다.")
    return data
