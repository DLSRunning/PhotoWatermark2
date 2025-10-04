# watermark.py
from PIL import Image, ImageDraw, ImageFont, ImageEnhance
from io import BytesIO
from typing import Tuple, Optional
import math

RGBAColor = Tuple[int,int,int,int]

def apply_text_watermark(
    base_img: Image.Image,
    text: str,
    font_size: int = 36,
    color: Tuple[int,int,int] = (255,255,255),
    opacity: float = 0.5,
    position: Tuple[int,int] = (0,0),
    stroke_width: int = 0,
    stroke_fill: Tuple[int,int,int]=(0,0,0),
) -> Image.Image:
# 返回带文本水印的新 Image 对象（不修改原图）。
    img = base_img.convert('RGBA')
    txt_layer = Image.new('RGBA', img.size, (255,255,255,0))
    draw = ImageDraw.Draw(txt_layer)

    # 尝试加载字体
    try:
        pil_font_size = int(font_size * 4)
        font = ImageFont.truetype("arial.ttf", pil_font_size)
    except Exception:
        font = ImageFont.load_default()

    # 计算 color + alpha
    alpha = int(255 * max(0.0, min(1.0, opacity)))
    fill = (color[0], color[1], color[2], alpha)

    print(f"Watermark text: '{text}' at {position} with font size {font_size}, color {fill}, opacity {opacity}")

    # 在独立层上绘制文字
    draw.text(position, text, font=font, fill=fill, stroke_width=stroke_width, stroke_fill=stroke_fill)

    out = Image.alpha_composite(img, txt_layer)
    return out