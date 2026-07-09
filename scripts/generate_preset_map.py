"""
scripts/generate_preset_map.py — 설정 페이지용 플레이스홀더 지도 이미지 생성

실제 GOP 관할구역 지도 이미지가 준비되면 assets/gop_preset_map.png 파일을
그 이미지로 교체하면 됩니다 (config.PRESET_MAP_IMAGE_PATH가 이 경로를 가리킴).
이 스크립트는 그 전까지 화면 동작을 확인할 수 있도록 임시 지도를 그립니다.
"""
import math
import os
import random

from PIL import Image, ImageDraw, ImageFilter, ImageFont

random.seed(7)

W, H = 1280, 720
OUT_PATH = os.path.join(os.path.dirname(__file__), "..", "assets", "gop_preset_map.png")

# ------------------------------------------------------------------ #
# 배경 — 산악 지형 느낌의 그라디언트
# ------------------------------------------------------------------ #
img = Image.new("RGB", (W, H), "#dfe8d8")
draw = ImageDraw.Draw(img)

for y in range(H):
    t = y / H
    r = int(0xB8 + (0x6F - 0xB8) * t)
    g = int(0xC9 + (0x8F - 0xC9) * t)
    b = int(0xA6 + (0x5A - 0xA6) * t)
    draw.line([(0, y), (W, y)], fill=(r, g, b))

# 능선(산) 실루엣 — 여러 겹의 반투명 산 모양
def ridge(base_y, amplitude, seed, color, alpha):
    rnd = random.Random(seed)
    pts = [(0, H)]
    x = 0
    y = base_y
    while x <= W:
        y = base_y + math.sin(x / 180 + seed) * amplitude + rnd.randint(-18, 18)
        pts.append((x, y))
        x += 40
    pts.append((W, H))
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(layer).polygon(pts, fill=color + (alpha,))
    return layer

img = img.convert("RGBA")
img.alpha_composite(ridge(430, 40, 1, (94, 122, 82), 140))
img.alpha_composite(ridge(500, 55, 5, (74, 102, 66), 170))
img.alpha_composite(ridge(580, 35, 9, (60, 86, 55), 210))
img = img.convert("RGB")
draw = ImageDraw.Draw(img)

# 하천 — 구불구불한 곡선
river_pts = []
x = -20
y = 120
rnd = random.Random(3)
while x <= W + 20:
    y += rnd.randint(-14, 14)
    y = max(60, min(260, y))
    river_pts.append((x, y))
    x += 26
draw.line(river_pts, fill="#6fa8d6", width=10, joint="curve")
draw.line(river_pts, fill="#8ec2e8", width=4, joint="curve")

# 도로/순찰로 — 점선
road_pts = []
x = 30
y = H - 90
rnd = random.Random(11)
while x <= W - 30:
    y += rnd.randint(-20, 20)
    y = max(H - 220, min(H - 40, y))
    road_pts.append((x, y))
    x += 24
for i in range(0, len(road_pts) - 1, 2):
    draw.line([road_pts[i], road_pts[i + 1]], fill="#c9b892", width=6)

# 군사분계선(예시) — 상단을 가로지르는 붉은 점선
for x in range(0, W, 26):
    draw.line([(x, 40), (x + 14, 40)], fill="#c0392b", width=3)
draw.text((16, 14), "군사분계선 (예시)", fill="#8c2d21")

# 숲 텍스처 — 작은 원들을 흩뿌려 나무처럼 표현
rnd = random.Random(21)
for _ in range(420):
    cx = rnd.randint(0, W)
    cy = rnd.randint(300, H)
    if abs(cy - 150) < 40:
        continue
    r = rnd.randint(2, 5)
    shade = rnd.randint(-14, 14)
    base = (46 + shade, 92 + shade, 58 + shade)
    draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=base)

img = img.filter(ImageFilter.SMOOTH_MORE)
draw = ImageDraw.Draw(img)

# 안내 문구
try:
    font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 22)
    font_small = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 15)
except Exception:
    font = ImageFont.load_default()
    font_small = font

label = "GOP 관할구역 지도 (예시 · 실제 이미지로 교체 예정)"
tw = draw.textlength(label, font=font)
draw.rectangle([W / 2 - tw / 2 - 14, 16, W / 2 + tw / 2 + 14, 50], fill=(20, 20, 20, 160))
draw.text((W / 2 - tw / 2, 20), label, fill="white", font=font)

os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
img.save(OUT_PATH)
print("saved:", OUT_PATH, img.size)
