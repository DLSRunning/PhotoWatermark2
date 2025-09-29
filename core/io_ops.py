# io_ops.py
from PIL import Image
from pathlib import Path
from typing import Tuple, Optional

SUPPORTED_IN = ('.jpg', '.jpeg', '.png', '.bmp', '.tif', '.tiff')

def load_image(path: Path) -> Image.Image:
    return Image.open(path)

def save_image(img: Image.Image, path: Path, fmt: Optional[str]=None, quality: int=95):
    fmt = fmt or (path.suffix.replace('.', '').upper())
    params = {}
    if fmt.lower() in ('jpg','jpeg'):
        params['quality'] = int(max(1, min(100, quality)))
    # 转换为 RGB，因为 JPEG 不支持 alpha
        if img.mode in ('RGBA','LA'):
            bg = Image.new('RGB', img.size, (255,255,255))
            bg.paste(img, mask=img.split()[3])
            img_to_save = bg
        else:
            img_to_save = img.convert('RGB')
    else:
        img_to_save = img

    img_to_save.save(path, **params)

def resize_image(img: Image.Image, width: int=None, height: int=None, percent: float=None) -> Image.Image:
    if percent is not None:
        w = int(img.width * percent)
        h = int(img.height * percent)
    else:
        w = width or img.width
        h = height or img.height
    return img.resize((w,h), Image.LANCZOS)