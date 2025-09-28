import json
from pathlib import Path
from typing import Dict, Any

CONFIG_DIR = Path.home() / '.watermark_app'
CONFIG_DIR.mkdir(exist_ok=True)
TEMPLATES_FILE = CONFIG_DIR / 'templates.json'


def load_templates() -> Dict[str, Any]:
    if not TEMPLATES_FILE.exists():
        return {}
    return json.loads(TEMPLATES_FILE.read_text(encoding='utf-8'))


def save_templates(d: Dict[str, Any]):
    TEMPLATES_FILE.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding='utf-8')


def save_template(name: str, data: Dict[str, Any]):
    t = load_templates()
    t[name] = data
    save_templates(t)


def delete_template(name: str):
    t = load_templates()
    if name in t:
        del t[name]
        save_templates(t)