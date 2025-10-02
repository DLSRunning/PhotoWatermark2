# watermark.py
from PIL import Image, ImageDraw, ImageFont, ImageEnhance
from io import BytesIO
from typing import Tuple, Optional
import math

RGBAColor = Tuple[int,int,int,int]

def apply_text_watermark(
    base_img: Image.Image,
    text: str,
    font_path: Optional[str],
    font_size: int = 36,
    color: Tuple[int,int,int] = (255,255,255),
    opacity: float = 0.5,
    position: Tuple[int,int] = (0,0),
    anchor: str = "lt",
    rotation: float = 0.0,
    stroke_width: int = 0,
    stroke_fill: Tuple[int,int,int]=(0,0,0),
) -> Image.Image:
# 返回带文本水印的新 Image 对象（不修改原图）。
# opacity: 0.0-1.0
# position: (x,y) 顶点
# anchor: 使用 Pillow 的 anchor 选项，比如 "mm" 中心
    img = base_img.convert('RGBA')
    txt_layer = Image.new('RGBA', img.size, (255,255,255,0))
    draw = ImageDraw.Draw(txt_layer)

    # 尝试加载字体
    try:
        pil_font_size = int(font_size * 72 / 96)

        if font_path:
            font = ImageFont.truetype(font_path, pil_font_size)
        else:
            font = ImageFont.truetype("arial.ttf", pil_font_size)
    except Exception:
        # 兜底：依然尝试默认字体，但字号不可控
        font = ImageFont.load_default()

    # 计算 color + alpha
    alpha = int(255 * max(0.0, min(1.0, opacity)))
    fill = (color[0], color[1], color[2], alpha)

    # 在独立层上绘制文字
    # 位置参数已由 UI label_to_image 映射为原图坐标，字号直接用 font_size
    draw.text(position, text, font=font, fill=fill, anchor=anchor, stroke_width=stroke_width, stroke_fill=stroke_fill)

    if rotation and rotation % 360 != 0:
        txt_layer = txt_layer.rotate(rotation, resample=Image.BICUBIC, expand=False)


    out = Image.alpha_composite(img, txt_layer)
    return out

def apply_image_watermark(
    base_img: Image.Image,
    mark_img: Image.Image,
    position: Tuple[int,int] = (0,0),
    scale: float = 1.0,
    opacity: float = 0.5,
    rotation: float = 0.0,
) -> Image.Image:
    base = base_img.convert('RGBA')
    mark = mark_img.convert('RGBA')

    # 缩放
    if scale != 1.0:
        new_size = (int(mark.width * scale), int(mark.height * scale))
        mark = mark.resize(new_size, Image.ANTIALIAS)

    # 旋转
    if rotation and rotation % 360 != 0:
        mark = mark.rotate(rotation, expand=True)

    # 调整透明度
    if opacity < 1.0:
        alpha = mark.split()[3]
        alpha = ImageEnhance.Brightness(alpha).enhance(opacity)
        mark.putalpha(alpha)

    layer = Image.new('RGBA', base.size, (255,255,255,0))
    layer.paste(mark, position, mark)
    out = Image.alpha_composite(base, layer)
    return out