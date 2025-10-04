# io_ops.py
from PIL import Image
from pathlib import Path
from typing import Optional

SUPPORTED_IN = ('.jpg', '.jpeg', '.png', '.bmp', '.tif', '.tiff')

def load_image(path: Path) -> Image.Image:
    return Image.open(path)

def save_image(img: Image.Image, path: Path, fmt: Optional[str]=None, quality: int=100):
    fmt = fmt or (path.suffix.replace('.', '').upper())
    params = {}
    if fmt.lower() in ('jpg','jpeg'):
        params['quality'] = quality
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
