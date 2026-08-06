#!/usr/bin/env python3
"""生成模拟绩效排名截图，用于测试 ClockIn PNG/JPG OCR 导入."""
from PIL import Image, ImageDraw, ImageFont
import os

OUT = os.path.join(os.path.dirname(__file__), 'perf_ranking.png')
CSV_OUT = os.path.join(os.path.dirname(__file__), 'perf_ranking.csv')

ROWS = [
    ('名称', '绩效排名'),
    ('133122', '1.00'),
    ('3051105', '0.95'),
    ('3060017', '0.88'),
    ('3065861', '0.82'),
    ('3072437', '0.79'),
]

# Save CSV for reference / CSV-import test
with open(CSV_OUT, 'w', encoding='utf-8-sig') as f:
    for name, rank in ROWS:
        f.write(f'{name},{rank}\n')

# Draw image
W, H = 360, 40 + len(ROWS) * 44
img = Image.new('RGB', (W, H), color=(255, 255, 255))
draw = ImageDraw.Draw(img)

# Try to load a CJK font; fall back to default if unavailable
font_paths = [
    '/System/Library/Fonts/PingFang.ttc',
    '/System/Library/Fonts/STHeiti Light.ttc',
    '/System/Library/Fonts/Hiragino Sans GB.ttc',
]
font = None
for fp in font_paths:
    try:
        font = ImageFont.truetype(fp, 22)
        break
    except Exception:
        pass
if font is None:
    font = ImageFont.load_default()

header_font = ImageFont.truetype('/System/Library/Fonts/PingFang.ttc', 24) if font and '/PingFang' in str(font) else font

y = 20
for i, (name, rank) in enumerate(ROWS):
    is_header = i == 0
    fz = header_font if is_header else font
    draw.text((30, y), name, fill=(0, 0, 0) if not is_header else (37, 99, 235), font=fz)
    draw.text((200, y), rank, fill=(0, 0, 0) if not is_header else (37, 99, 235), font=fz)
    if not is_header:
        draw.line([(20, y + 34), (W - 20, y + 34)], fill=(230, 230, 230), width=1)
    y += 44

img.save(OUT)
print(f'Generated {OUT} and {CSV_OUT}')
