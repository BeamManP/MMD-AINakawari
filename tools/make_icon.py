"""AIナカワリのアイコン（mmd_ainakawari/MMD-AINakawari.ico）を描く。描き直す時だけ回す（PIL が要る。窓の Python には無い）。

    python tools/make_icon.py [出す場所（省くと mmd_ainakawari）]

青緑の角丸の板（簡易操作パネルの色を少し明るく）に、白の「AI」と、キー（白いひし形）2 つの間を AI が埋める琥珀色の点の弧。
16・24px は点が潰れるので、ひし形 2 つを琥珀色の線でつなぐ簡略版。icon_sheet.png は大きさごとの見本（確かめる用）。11-06
"""
import math
import os
import sys
from PIL import Image, ImageDraw, ImageFont
OUT = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "mmd_ainakawari")
N = 1024
TOP, BOTTOM = (64, 140, 140), (20, 48, 56)       # 簡易操作パネル（49,99,99 → 22,45,45）を少し明るく
KEY, DOT = (255, 255, 255), (255, 200, 70)        # キーは白、AI が作った間は琥珀色

def draw(simple):
    img = Image.new("RGBA", (N, N), (0, 0, 0, 0))
    grad = Image.new("RGBA", (N, N))
    gd = ImageDraw.Draw(grad)
    for y in range(N):
        t = y / (N - 1)
        gd.line([(0, y), (N, y)], fill=tuple(round(a + (b - a) * t) for a, b in zip(TOP, BOTTOM)) + (255,))
    mask = Image.new("L", (N, N), 0)
    ImageDraw.Draw(mask).rounded_rectangle([16, 16, N - 16, N - 16], radius=200, fill=255)
    img.paste(grad, (0, 0), mask)
    d = ImageDraw.Draw(img)
    # AI の字
    font = ImageFont.truetype(r"C:\Windows\Fonts\seguibl.ttf", 560 if simple else 480)
    box = d.textbbox((0, 0), "AI", font=font)
    w, h = box[2] - box[0], box[3] - box[1]
    cy = 400 if simple else 360
    d.text(((N - w) / 2 - box[0], cy - h / 2 - box[1]), "AI", font=font, fill=(255, 255, 255, 255))
    # キー（ひし形）2 つと、その間の点の弧
    y0, xl, xr, r = (800 if simple else 790), 210, N - 210, (95 if simple else 72)
    if not simple:
        n = 5
        for i in range(1, n + 1):
            t = i / (n + 1)
            x = xl + (xr - xl) * t
            y = y0 - 150 * math.sin(math.pi * t)
            rr = 30
            d.ellipse([x - rr, y - rr, x + rr, y + rr], fill=DOT + (255,))
    else:
        d.line([(xl + r, y0), (xr - r, y0)], fill=DOT + (255,), width=60)
    for x in (xl, xr):
        d.polygon([(x, y0 - r), (x + r, y0), (x, y0 + r), (x - r, y0)], fill=KEY + (255,))
    return img

full, simple = draw(False), draw(True)
sizes = [16, 24, 32, 48, 64, 128, 256]
imgs = {s: (simple if s <= 24 else full).resize((s, s), Image.LANCZOS) for s in sizes}
imgs[256].save(f"{OUT}/MMD-AINakawari.ico", sizes=[(s, s) for s in sizes], append_images=[imgs[s] for s in sizes[:-1]])
# 見本: 明るい背景と暗い背景に、各大きさを実寸で並べ、右に 256 を置く
sheet = Image.new("RGB", (900, 330), (255, 255, 255))
dark = Image.new("RGB", (620, 165), (32, 32, 32)); sheet.paste(dark, (0, 165))
x = 10
for s in sizes[:-1]:
    for y0 in (10, 175):
        sheet.paste(imgs[s], (x, y0 + (64 - s) // 2 if s <= 64 else y0), imgs[s])
    x += s + 14
sheet.paste(imgs[256], (630, 37), imgs[256])
if len(sys.argv) > 1:   # 見本は、出す場所を指定した時だけ（リポジトリには置かない）
    sheet.save(f"{OUT}/icon_sheet.png")
print("ok")
