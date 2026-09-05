#!/usr/bin/env python
"""Generate a branded webp cover for the blog post 'راهنمای ارتفاع لایه و تنظیمات کیفیت چاپ'.
Style: layered 3D-print bands (layer-height theme) on soft-blue background with orange accent,
matching the Spaghetti Print brand palette (#dfe4f2 soft blue, #ff9a3d / #e07b2c orange, navy text).
"""
from PIL import Image, ImageDraw, ImageFont
import arabic_reshaper
from bidi.algorithm import get_display

def fa(text: str) -> str:
    """Reshape Persian text for correct connected rendering + RTL."""
    reshaped = arabic_reshaper.reshape(text)
    return get_display(reshaped)

W, H = 1280, 720

# Brand palette
SOFT_BLUE_TOP = (223, 228, 242)   # #dfe4f2
SOFT_BLUE_BOT = (206, 216, 240)
NAVY          = (30, 45, 80)
ORANGE        = (255, 154, 61)     # #ff9a3d
ORANGE_DEEP   = (224, 123, 44)     # #e07b2c
ORANGE_LIGHT  = (255, 176, 102)    # #ffc66e
WHITE         = (255, 255, 255)

FONT_BOLD = "C:/Users/barba/3djat-pricing/scripts/.fonts/Vazirmatn-Bold.ttf"
FONT_REG  = "C:/Users/barba/3djat-pricing/scripts/.fonts/Vazirmatn-Regular.ttf"

img = Image.new("RGB", (W, H))
draw = ImageDraw.Draw(img)

# Background gradient (soft blue)
for y in range(H):
    t = y / (H - 1)
    r = int(SOFT_BLUE_TOP[0] + (SOFT_BLUE_BOT[0] - SOFT_BLUE_TOP[0]) * t)
    g = int(SOFT_BLUE_TOP[1] + (SOFT_BLUE_BOT[1] - SOFT_BLUE_TOP[1]) * t)
    b = int(SOFT_BLUE_TOP[2] + (SOFT_BLUE_BOT[2] - SOFT_BLUE_TOP[2]) * t)
    draw.line([(0, y), (W, y)], fill=(r, g, b))

# ---- Layered "print bands" illustration on the left-center ----
# Stack of horizontal layers with increasing step widths (like a 3D print cross-section)
layers = 7
band_h = 30
start_x = 150
top_y = 96
palette = [ORANGE_LIGHT, ORANGE, ORANGE_DEEP, NAVY]
for i in range(layers):
    width_frac = 0.35 + 0.5 * (i / layers)   # staircase
    bw = int(W * width_frac)
    y_top = top_y + i * band_h
    color = palette[i % len(palette)]
    draw.rounded_rectangle([start_x, y_top, start_x + bw, y_top + band_h - 6],
                           radius=8, fill=color)
    # nozzle cursor line
    if i == layers - 1:
        draw.line([(start_x + bw + 8, y_top + band_h // 2 - 14),
                   (start_x + bw + 8, y_top + band_h - 6)], fill=ORANGE_DEEP, width=6)

# ---- Title text (right-aligned, RTL) ----
title_font = ImageFont.truetype(FONT_BOLD, 62)
subtitle_font = ImageFont.truetype(FONT_REG, 34)
brand_font = ImageFont.truetype(FONT_BOLD, 30)

zwnj = "\u200c"

title = fa(f"راهنمای ارتفاع لایه\nو تنظیمات کیفیت چاپ")
subtitle = fa(f"با درک ارتفاع لایه، چاپ س{zwnj}بعدی و تمیزتری داشته باشید")
brand = fa("اسپاگتی پرینت")

# Compute title block placement (right aligned)
title_box = draw.multiline_textbbox((0, 0), title, font=title_font, align="right")
title_x = W - 80 - (title_box[2] - title_box[0])
title_y = 332
draw.multiline_text((title_x, title_y), title, font=title_font,
                    fill=NAVY, align="right")

sub_w = draw.textlength(subtitle, font=subtitle_font)
sub_x = W - 80 - sub_w
draw.text((sub_x, title_y + 178), subtitle, font=subtitle_font, fill=NAVY)

# Brand chip bottom-right with orange underline
bw_txt = draw.textlength(brand, font=brand_font)
bw_x = W - 80 - bw_txt
bw_y = H - 95
draw.text((bw_x, bw_y), brand, font=brand_font, fill=NAVY)

# Save
out_png = "C:/Users/barba/3djat-pricing/backend/uploads/blog/layer-height-quality-guide.png"
out_webp = "C:/Users/barba/3djat-pricing/backend/uploads/blog/layer-height-quality-guide.webp"
img.save(out_png, "PNG")
img.save(out_webp, "WEBP", quality=88, method=6)
print("saved", out_png, img.size)
print("saved", out_webp)