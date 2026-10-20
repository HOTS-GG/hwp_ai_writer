"""한큐(HanQ) 아이콘 생성: assets/icon.ico, assets/icon.png"""
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

OUT = Path(__file__).resolve().parent.parent / "assets"
S = 1024  # 크게 그린 뒤 줄여서 가장자리를 부드럽게


def lerp(a, b, t):
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


def draw() -> Image.Image:
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))

    # 배경: 위→아래 파란 그라데이션 둥근 사각형
    grad = Image.new("RGBA", (S, S))
    top, bottom = (47, 128, 255), (24, 70, 160)
    gd = ImageDraw.Draw(grad)
    for y in range(S):
        gd.line([(0, y), (S, y)], fill=lerp(top, bottom, y / S) + (255,))
    mask = Image.new("L", (S, S), 0)
    ImageDraw.Draw(mask).rounded_rectangle([40, 40, S - 40, S - 40], radius=220, fill=255)
    img.paste(grad, (0, 0), mask)

    d = ImageDraw.Draw(img)
    # 흰 종이 + 접힌 모서리
    l, t, r, b, fold = 250, 175, 774, 849, 150
    shadow = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    ImageDraw.Draw(shadow).polygon([(l + 18, t + 26), (r - fold + 18, t + 26), (r + 18, t + fold + 26),
                                    (r + 18, b + 26), (l + 18, b + 26)], fill=(10, 30, 80, 90))
    img.alpha_composite(shadow)
    d.polygon([(l, t), (r - fold, t), (r, t + fold), (r, b), (l, b)], fill=(255, 255, 255, 255))
    d.polygon([(r - fold, t), (r - fold, t + fold), (r, t + fold)], fill=(200, 216, 240, 255))

    # Q 고리
    cx, cy, ro, ri = 512, 520, 205, 128
    d.ellipse([cx - ro, cy - ro, cx + ro, cy + ro], fill=(29, 95, 210, 255))
    d.ellipse([cx - ri, cy - ri, cx + ri, cy + ri], fill=(255, 255, 255, 255))
    # Q 꼬리 = 주황 체크 표시
    w = 64
    p1, p2, p3 = (548, 610), (628, 700), (790, 500)
    for a, c in ((p1, p2), (p2, p3)):
        d.line([a, c], fill=(255, 255, 255, 255), width=w + 44)
    for a, c in ((p1, p2), (p2, p3)):
        d.line([a, c], fill=(255, 145, 30, 255), width=w)
    for p in (p1, p2, p3):
        d.ellipse([p[0] - w / 2, p[1] - w / 2, p[0] + w / 2, p[1] + w / 2], fill=(255, 145, 30, 255))

    # 종이 아래 글줄 두 개 (문서 느낌)
    for y, x2 in ((760, 700), (805, 600)):
        d.rounded_rectangle([320, y - 11, x2, y + 11], radius=11, fill=(170, 190, 225, 255))
    return img


def main():
    OUT.mkdir(exist_ok=True)
    big = draw()
    big.resize((256, 256), Image.LANCZOS).save(OUT / "icon.png")
    sizes = [16, 20, 24, 32, 40, 48, 64, 128, 256]
    big.resize((256, 256), Image.LANCZOS).save(OUT / "icon.ico", sizes=[(s, s) for s in sizes])
    # 확인용: 여러 크기를 나란히
    sheet = Image.new("RGBA", (sum(sizes) + 10 * len(sizes) + 10, 276), (240, 243, 248, 255))
    x = 10
    for s in sizes:
        sheet.alpha_composite(big.resize((s, s), Image.LANCZOS), (x, 266 - s))
        x += s + 10
    sheet.save(OUT / "icon_preview.png")
    print("saved", OUT)


if __name__ == "__main__":
    main()
