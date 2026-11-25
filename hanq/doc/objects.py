"""문서에 새로 넣는 개체의 XML: 그림, 수식, 글상자, 각주, 머리말·꼬리말, 쪽 번호.

모양은 한글이 저장한 HWPX를 그대로 따랐다 (크기 단위는 HWPUNIT, 1mm ≈ 283.5).
"""
import random
from xml.sax.saxutils import escape

from lxml import etree

from .xml import HC, HP, HWPUNIT_PER_MM, new_id

_NS = f'xmlns:hp="{HP}" xmlns:hc="{HC}"'
_POS = ('<hp:pos treatAsChar="1" affectLSpacing="0" flowWithText="1" allowOverlap="0" holdAnchorAndSO="0" '
        'vertRelTo="PARA" horzRelTo="COLUMN" vertAlign="TOP" horzAlign="LEFT" vertOffset="0" horzOffset="0"/>')
_MATRIX = ('<hp:renderingInfo><hc:transMatrix e1="1" e2="0" e3="0" e4="0" e5="1" e6="0"/>'
           '<hc:scaMatrix e1="1" e2="0" e3="0" e4="0" e5="1" e6="0"/>'
           '<hc:rotMatrix e1="1" e2="0" e3="0" e4="0" e5="1" e6="0"/></hp:renderingInfo>')
_SUBLIST = ('<hp:subList id="" textDirection="HORIZONTAL" lineWrap="BREAK" vertAlign="{va}" linkListIDRef="0" '
            'linkListNextIDRef="0" textWidth="{tw}" textHeight="{th}" hasTextRef="0" hasNumRef="0">')

IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".gif", ".bmp")   # 문서에 넣을 수 있는 그림 파일

PAGE_NUM_POS = {"top_left": "TOP_LEFT", "top_center": "TOP_CENTER", "top_right": "TOP_RIGHT",
                "bottom_left": "BOTTOM_LEFT", "bottom_center": "BOTTOM_CENTER", "bottom_right": "BOTTOM_RIGHT",
                "왼쪽 위": "TOP_LEFT", "가운데 위": "TOP_CENTER", "오른쪽 위": "TOP_RIGHT",
                "왼쪽 아래": "BOTTOM_LEFT", "가운데 아래": "BOTTOM_CENTER", "오른쪽 아래": "BOTTOM_RIGHT"}


def mm(v: float) -> int:
    return int(float(v) * HWPUNIT_PER_MM)


def _inst() -> str:
    return str(random.randint(100000000, 999999999))


def _p(inner: str, para_id="0", char_id="0", style_id="0") -> str:
    return (f'<hp:p {_NS} id="0" paraPrIDRef="{para_id}" styleIDRef="{style_id}" pageBreak="0" columnBreak="0" '
            f'merged="0"><hp:run charPrIDRef="{char_id}">{inner}</hp:run></hp:p>')


def _text_p(text: str, para_id="0", char_id="0", style_id="0", before: str = "") -> str:
    return _p(f"{before}<hp:t>{escape(str(text))}</hp:t>", para_id, char_id, style_id)


def picture_paragraph(bin_id: str, width: int, height: int, para_id="0", char_id="0", name: str = ""):
    """그림 한 장이 든 문단 (글자처럼 취급). bin_id는 HwpxDocument.add_image()가 준 이름."""
    w, h = int(width), int(height)
    pic = (f'<hp:pic id="{new_id()}" zOrder="0" numberingType="PICTURE" textWrap="TOP_AND_BOTTOM" '
           f'textFlow="BOTH_SIDES" lock="0" dropcapstyle="None" href="" groupLevel="0" instid="{_inst()}" reverse="0">'
           f'<hp:offset x="0" y="0"/><hp:orgSz width="{w}" height="{h}"/><hp:curSz width="0" height="0"/>'
           f'<hp:flip horizontal="0" vertical="0"/>'
           f'<hp:rotationInfo angle="0" centerX="{w // 2}" centerY="{h // 2}" rotateimage="1"/>{_MATRIX}'
           f'<hc:img binaryItemIDRef="{bin_id}" bright="0" contrast="0" effect="REAL_PIC" alpha="0"/>'
           f'<hp:imgRect><hc:pt0 x="0" y="0"/><hc:pt1 x="{w}" y="0"/><hc:pt2 x="{w}" y="{h}"/>'
           f'<hc:pt3 x="0" y="{h}"/></hp:imgRect><hp:imgClip left="0" right="0" top="0" bottom="0"/>'
           f'<hp:inMargin left="0" right="0" top="0" bottom="0"/><hp:imgDim dimwidth="0" dimheight="0"/><hp:effects/>'
           f'<hp:sz width="{w}" widthRelTo="ABSOLUTE" height="{h}" heightRelTo="ABSOLUTE" protect="0"/>{_POS}'
           f'<hp:outMargin left="0" right="0" top="0" bottom="0"/>'
           f'<hp:shapeComment>{escape(name or "그림입니다.")}</hp:shapeComment></hp:pic><hp:t/>')
    return etree.fromstring(_p(pic, para_id, char_id))


def resize_picture(pic, width: int | None, height: int | None) -> bool:
    """그림 크기를 바꾼다. 한쪽만 주면 가로세로 비율을 지킨다."""
    sz = pic.find(f"{{{HP}}}sz")
    if sz is None:
        return False
    w0, h0 = int(sz.get("width", "0") or 0), int(sz.get("height", "0") or 0)
    if not w0 or not h0:
        return False
    if width and not height:
        height = int(h0 * width / w0)
    elif height and not width:
        width = int(w0 * height / h0)
    if not width or not height:
        return False
    fx, fy = width / w0, height / h0
    sz.set("width", str(int(width)))
    sz.set("height", str(int(height)))
    cur = pic.find(f"{{{HP}}}curSz")
    if cur is not None:
        cur.set("width", str(int(width)))
        cur.set("height", str(int(height)))
    # 그림을 그리는 틀(크기 행렬)도 같은 비율로 늘린다
    sca = pic.find(f"{{{HP}}}renderingInfo/{{{HC}}}scaMatrix")
    if sca is not None:
        sca.set("e1", f"{float(sca.get('e1', '1')) * fx:.6f}")
        sca.set("e5", f"{float(sca.get('e5', '1')) * fy:.6f}")
    return True


def equation_size(script: str) -> tuple[int, int]:
    """수식 글로 어림한 (폭, 높이). 한글이 열 때 다시 재지만, 그 전까지 자리를 비슷하게 잡아 둔다."""
    tall = any(k in script for k in ("over", "sum", "int", "matrix", "cases", "lim", "prod"))
    width = max(2500, min(40000, int(len(script.replace("{", "").replace("}", "")) * 420)))
    return width, 2588 if tall else 1200


def equation_paragraph(script: str, para_id="0", char_id="0"):
    """한글 수식 (수식 편집기 글: 'x= {-b +- sqrt {b^2 -4ac}} over {2a}')."""
    script = str(script).strip()
    width, height = equation_size(script)
    eq = (f'<hp:equation id="{new_id()}" zOrder="0" numberingType="EQUATION" textWrap="TOP_AND_BOTTOM" '
          'textFlow="BOTH_SIDES" lock="0" dropcapstyle="None" version="Equation Version 60" baseLine="71" '
          'textColor="#000000" baseUnit="1000" lineMode="CHAR" font="HancomEQN">'
          f'<hp:sz width="{width}" widthRelTo="ABSOLUTE" height="{height}" heightRelTo="ABSOLUTE" '
          f'protect="0"/>{_POS.replace("COLUMN", "PARA")}<hp:outMargin left="56" right="56" top="0" bottom="0"/>'
          f'<hp:shapeComment>수식입니다.</hp:shapeComment><hp:script>{escape(script)}</hp:script></hp:equation><hp:t/>')
    return etree.fromstring(_p(eq, para_id, char_id))


def textbox_paragraph(lines: list[str], width: int, para_id="0", char_id="0", fill: str = "#FFFFFF",
                      border: bool = True):
    """테두리 있는 글상자 (글자처럼 취급). 높이는 줄 수에 맞춘다."""
    lines = [str(x) for x in lines] or [""]
    w, h = int(width), 1900 * len(lines) + 800
    body = "".join(_text_p(t, para_id, char_id).replace(f" {_NS}", "") for t in lines)
    rect = (f'<hp:rect id="{new_id()}" zOrder="0" numberingType="NONE" textWrap="TOP_AND_BOTTOM" '
            f'textFlow="BOTH_SIDES" lock="0" dropcapstyle="None" href="" groupLevel="0" instid="{_inst()}" ratio="0">'
            f'<hp:offset x="0" y="0"/><hp:orgSz width="{w}" height="{h}"/><hp:curSz width="0" height="0"/>'
            f'<hp:flip horizontal="0" vertical="0"/>'
            f'<hp:rotationInfo angle="0" centerX="{w // 2}" centerY="{h // 2}" rotateimage="1"/>{_MATRIX}'
            f'<hp:lineShape color="#000000" width="33" style="{"SOLID" if border else "NONE"}" endCap="FLAT" '
            'headStyle="NORMAL" tailStyle="NORMAL" headfill="1" tailfill="1" headSz="MEDIUM_MEDIUM" '
            'tailSz="MEDIUM_MEDIUM" outlineStyle="NORMAL" alpha="0"/>'
            f'<hc:fillBrush><hc:winBrush faceColor="{fill}" hatchColor="#000000" alpha="0"/></hc:fillBrush>'
            '<hp:shadow type="NONE" color="#B2B2B2" offsetX="0" offsetY="0" alpha="0"/>'
            f'<hp:drawText lastWidth="{w}" name="" editable="0">{_SUBLIST.format(va="CENTER", tw=0, th=0)}{body}'
            '</hp:subList><hp:textMargin left="567" right="567" top="283" bottom="283"/></hp:drawText>'
            f'<hc:pt0 x="0" y="0"/><hc:pt1 x="{w}" y="0"/><hc:pt2 x="{w}" y="{h}"/><hc:pt3 x="0" y="{h}"/>'
            f'<hp:sz width="{w}" widthRelTo="ABSOLUTE" height="{h}" heightRelTo="ABSOLUTE" protect="0"/>{_POS}'
            '<hp:outMargin left="0" right="0" top="0" bottom="0"/><hp:shapeComment>글상자입니다.</hp:shapeComment>'
            '</hp:rect><hp:t/>')
    return etree.fromstring(_p(rect, para_id, char_id))


def footnote_ctrl(text: str, ids: tuple = ("0", "0", "0"), endnote: bool = False):
    """각주(또는 미주) 하나 (본문 줄의 run 안에 넣는 hp:ctrl). 번호는 넣은 뒤 renumber_footnotes()로 매긴다.
    ids = 각주·미주 스타일의 (문단 모양, 글자 모양, 스타일) id."""
    tag, num_type = ("endNote", "ENDNOTE") if endnote else ("footNote", "FOOTNOTE")
    auto = (f'<hp:ctrl><hp:autoNum num="1" numType="{num_type}"><hp:autoNumFormat type="DIGIT" userChar="" '
            'prefixChar="" suffixChar=")" supscript="0"/></hp:autoNum></hp:ctrl>')
    xml = (f'<hp:ctrl {_NS}><hp:{tag} number="1" suffixChar="41" instId="{_inst()}">'
           f'{_SUBLIST.format(va="TOP", tw=0, th=0)}'
           f'{_text_p(" " + str(text).strip(), *ids, before=auto).replace(f" {_NS}", "")}'
           f'</hp:subList></hp:{tag}></hp:ctrl>')
    return etree.fromstring(xml)


def renumber_footnotes(roots) -> int:
    """각주와 미주 번호를 문서 순서대로 다시 매긴다 (각각 1부터)."""
    total = 0
    for tag in ("footNote", "endNote"):
        n = 0
        for root in roots:
            for fn in root.iter(f"{{{HP}}}{tag}"):
                n += 1
                fn.set("number", str(n))
                for auto in fn.iter(f"{{{HP}}}autoNum"):
                    auto.set("num", str(n))
        total += n
    return total


def hyperlink_runs(url: str, char_id="0"):
    """하이퍼링크의 시작·끝 표시가 든 run 두 개. 그 사이에 놓인 글자가 링크가 된다."""
    fid, inst = _inst(), _inst()
    url = escape(str(url).strip())
    begin = (f'<hp:run {_NS} charPrIDRef="{char_id}"><hp:ctrl><hp:fieldBegin id="{fid}" type="HYPERLINK" name="" '
             f'editable="0" dirty="1" zorder="-1" fieldid="{inst}"><hp:parameters cnt="6" name="">'
             '<hp:integerParam name="Prop">0</hp:integerParam>'
             f'<hp:stringParam name="Command">{url.replace(";", "%3B")};1;0;0;</hp:stringParam>'
             f'<hp:stringParam name="Path">{url}</hp:stringParam>'
             '<hp:stringParam name="Category">HWPHYPERLINK_TYPE_URL</hp:stringParam>'
             '<hp:stringParam name="TargetType">HWPHYPERLINK_TARGET_BOOKMARK</hp:stringParam>'
             '<hp:stringParam name="DocOpenType">HWPHYPERLINK_JUMP_CURRENTTAB</hp:stringParam>'
             '</hp:parameters></hp:fieldBegin></hp:ctrl></hp:run>')
    end = (f'<hp:run {_NS} charPrIDRef="{char_id}"><hp:ctrl><hp:fieldEnd beginIDRef="{fid}" fieldid="{inst}"/>'
           '</hp:ctrl></hp:run>')
    return etree.fromstring(begin), etree.fromstring(end)


def header_ctrl(kind: str, text: str, text_width: int, ids: tuple = ("0", "0", "0")):
    """머리말(kind='header')·꼬리말('footer'). 여러 줄이면 줄마다 문단."""
    body = "".join(_text_p(t, *ids).replace(f" {_NS}", "") for t in str(text).split("\n"))
    xml = (f'<hp:ctrl {_NS}><hp:{kind} id="{random.randint(1, 9999)}" applyPageType="BOTH">'
           f'{_SUBLIST.format(va="TOP" if kind == "header" else "BOTTOM", tw=int(text_width), th=4251)}{body}'
           f'</hp:subList></hp:{kind}></hp:ctrl>')
    return etree.fromstring(xml)


def page_num_ctrl(pos: str):
    return etree.fromstring(f'<hp:ctrl {_NS}><hp:pageNum pos="{pos}" formatType="DIGIT" sideChar="-"/></hp:ctrl>')
