from __future__ import annotations
import sys
import io
import json
from pathlib import Path
from typing import Optional, Tuple, Dict, Any

from PySide6.QtCore import Qt, QSize, QPoint, Signal, QThread, QPointF
from PySide6.QtGui import QPixmap, QImage, QIcon, QAction, QPainter, QFont, QPen, QColor, QPainterPath, QBrush, QFontMetrics
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QFileDialog, QListWidget, QLabel, QPushButton,
    QHBoxLayout, QVBoxLayout, QLineEdit, QSpinBox, QSlider, QComboBox,
    QMessageBox, QColorDialog, QListWidgetItem, QProgressBar,
    QCheckBox, QGroupBox, QGridLayout, QFormLayout, QAbstractItemView
)

from core import templates as templates_mod
from core.io_ops import load_image, save_image, SUPPORTED_IN
from core.watermark import apply_text_watermark


def pil_to_qpixmap(pil_img) -> QPixmap:
    buf = io.BytesIO()
    pil_img.convert('RGBA').save(buf, format='PNG')
    qimg = QImage.fromData(buf.getvalue(), 'PNG')
    return QPixmap.fromImage(qimg)

def resource_path(relative_path: str) -> Path:
    """获取资源文件路径，支持 exe 打包"""
    try:
        # PyInstaller 打包后的临时目录
        base_path = Path(sys._MEIPASS)
    except AttributeError:
        # 脚本运行
        base_path = Path(__file__).parent.parent
    return base_path / relative_path


class ExportWorker(QThread):
    progress = Signal(int)
    finished = Signal()
    error = Signal(str)

    def __init__(self, tasks: list[Tuple[Path, Path, dict]]):
        super().__init__()
        self.tasks = tasks
        self._is_cancelled = False

    def run(self):
        total = len(self.tasks)
        try:
            for i, (src, dst, ctx) in enumerate(self.tasks, start=1):
                if self._is_cancelled:
                    break
                img = load_image(src).convert('RGBA')
                if ctx.get('use_text_mark'):
                    pil_font_size = int(ctx.get('font_size', 36))
                    
                    # 取百分比坐标并转换为实际像素坐标
                    percent_pos = ctx.get('text_pos_percent', (0.0, 0.0))
                    w, h = img.size
                    pos_x = int(percent_pos[0] * w)
                    pos_y = int(percent_pos[1] * h)

                    opacity = ctx.get('opacity', 60)
                    if opacity > 1:
                        opacity = opacity / 100.0

                    img = apply_text_watermark(
                        img,
                        ctx.get('text', ''),
                        font_size=pil_font_size,
                        color=tuple(ctx.get('color', (255, 255, 255))),
                        opacity=opacity,
                        position=(pos_x, pos_y),
                        stroke_width=ctx.get('stroke_width', 0),
                        stroke_fill=tuple(ctx.get('stroke_fill', (0, 0, 0)))
                    )

                # 直接保存原始尺寸和默认质量
                dst.parent.mkdir(parents=True, exist_ok=True)
                
                export_format = ctx.get('export_format', 'PNG')
                if export_format == "JPEG":
                    img = img.convert("RGB")
                    save_image(img, dst, fmt="JPEG", quality=95)
                else:
                    save_image(img, dst, fmt="PNG")

                self.progress.emit(int(i / total * 100))
        except Exception as e:
            self.error.emit(str(e))

    def cancel(self):
        self._is_cancelled = True


class DraggableOverlay(QLabel):
    """可在预览上拖动的水印显示层"""

    moved = Signal(QPoint)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, False)
        self.setMouseTracking(True)
        self.setStyleSheet("background: transparent")
        self.setAttribute(Qt.WA_TranslucentBackground, True)

        self._dragging = False
        self._last_pos = QPoint(0, 0)

        self._pixmap = None
        self._text = ''
        self._font = self.font()
        self._color = QColor(255, 255, 255)
        self._opacity = 1.0
        self._stroke_width = 0
        self._stroke_color = QColor(0, 0, 0)

        self._draw_pos = QPoint(0, 0)

        self.setCursor(Qt.OpenHandCursor)

    def set_draw_pos(self, x: int, y: int):
        self._draw_pos = QPoint(int(x), int(y))
        self.update()

    def set_text(self, text: str, font: QFont = None, color: QColor = None,
                 stroke_width: int = 0, stroke_color: QColor = None,
                 opacity: float = 1.0, position: QPoint | None = None):
        self._text = text
        self._font = font
        self._color = color
        self._stroke_color = stroke_color
        self._stroke_width = stroke_width
        self._opacity = opacity
        self._draw_pos = QPoint(position)
        self.update()

    def paintEvent(self, ev):
        super().paintEvent(ev)
        if not (self._text or self._pixmap):
            return

        painter = QPainter(self)
        painter.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform)
        painter.setOpacity(self._opacity)

        if self._text:
            painter.setFont(self._font)
            fm = QFontMetrics(self._font)

            dx = float(self._draw_pos.x())
            top_y = float(self._draw_pos.y())
            baseline_y = top_y + fm.ascent()

            path = QPainterPath()
            path.addText(QPointF(dx, baseline_y), self._font, self._text)

            if self._stroke_width > 0:
                pen = QPen(self._stroke_color)
                pen.setWidth(self._stroke_width)
                pen.setJoinStyle(Qt.RoundJoin)
                painter.strokePath(path, pen)

            painter.fillPath(path, QBrush(self._color))

    def mousePressEvent(self, ev):
        if ev.button() == Qt.LeftButton:
            self._dragging = True
            self._last_pos = ev.position().toPoint()
            self.setCursor(Qt.ClosedHandCursor)
            ev.accept()
        else:
            ev.ignore()

    def mouseMoveEvent(self, ev):
        if self._dragging:
            gp = ev.position().toPoint()
            delta = gp - self._last_pos
            self._last_pos = gp

            new = self._draw_pos + delta
            self._draw_pos = new
            self.moved.emit(self._draw_pos)
            self.update()
            ev.accept()
        else:
            ev.ignore()

    def mouseReleaseEvent(self, ev):
        if ev.button() == Qt.LeftButton:
            self._dragging = False
            self.setCursor(Qt.OpenHandCursor)
            ev.accept()
        else:
            ev.ignore()

    def resizeEvent(self, ev):
        old_size = ev.oldSize()
        new_size = ev.size()
        if old_size.width() > 0 and old_size.height() > 0:
            # 按比例调整 draw_pos
            scale_x = new_size.width() / old_size.width()
            scale_y = new_size.height() / old_size.height()
            self._draw_pos = QPoint(
                int(self._draw_pos.x() * scale_x),
                int(self._draw_pos.y() * scale_y)
            )
        super().resizeEvent(ev)
        self.update()


class MainWindow(QMainWindow):
    # 每张图片单独水印设置
    def __init__(self):
        super().__init__()
        self.preview_scale = 0.25
        self.image_settings: Dict[Path, dict] = {}
        self.setWindowTitle('WatermarkApp')
        self.resize(1200, 800)

        self.images: list[Path] = []
        self.current_index: Optional[int] = None
        self.current_pil = None 

        self._chosen_color = (255, 255, 255)
        self.mark_logo_pil = None  

        self._init_ui()
        self._connect_signals()

        json_path = resource_path("resource/default_templates.json")
        if json_path.exists():
            self.templates = json.loads(json_path.read_text(encoding='utf-8'))
        else:
            self.templates = {}

        self._load_template_names()
        self.export_worker: Optional[ExportWorker] = None

    def _init_ui(self):
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)

        self.file_list = QListWidget()
        self.file_list.setMaximumWidth(280)
        self.file_list.setIconSize(QSize(96, 96))
        self.file_list.setSelectionMode(QAbstractItemView.SingleSelection)
        self.file_list.setAcceptDrops(True)
        self.file_list.viewport().setAcceptDrops(True)

        self.import_file_btn = QPushButton('导入图片文件')
        self.import_folder_btn = QPushButton('导入图片文件夹')
        self.export_btn = QPushButton('批量导出')
        self.progress = QProgressBar()
        self.progress.setValue(0)

        # --- Templates---
        tpl_group = QGroupBox('模板')
        tpl_layout = QVBoxLayout()
        self.tpl_list = QListWidget()
        self.tpl_save_btn = QPushButton('保存为模板')
        self.tpl_load_btn = QPushButton('加载模板')
        self.tpl_del_btn = QPushButton('删除模板')
        tpl_layout.addWidget(self.tpl_list)
        tpl_layout.addWidget(self.tpl_save_btn)
        tpl_layout.addWidget(self.tpl_load_btn)
        tpl_layout.addWidget(self.tpl_del_btn)
        tpl_group.setLayout(tpl_layout)

        left_layout.addWidget(self.file_list, 1)
        left_layout.addWidget(self.import_file_btn)
        left_layout.addWidget(self.import_folder_btn)
        left_layout.addWidget(self.export_btn)
        left_layout.addWidget(tpl_group, 1)
        left_layout.addWidget(self.progress)

        # Center: preview only
        preview_container = QWidget()
        preview_layout = QVBoxLayout(preview_container)
        preview_layout.setContentsMargins(0, 0, 0, 0)

        self.preview_label = QLabel('预览')
        self.preview_label.setAlignment(Qt.AlignCenter)
        self.preview_label.setStyleSheet('background: #222; color: #eee;')
        self.preview_label.setMinimumSize(480, 320)
        self.preview_label.setScaledContents(False)
        preview_layout.addWidget(self.preview_label)

        self.overlay = DraggableOverlay(self.preview_label)
        self.overlay.hide()

        # Right: controls
        ctrl_widget = QWidget()
        ctrl_layout = QVBoxLayout(ctrl_widget)

        # --- Text watermark ---
        text_group = QGroupBox('文本水印')
        text_layout = QFormLayout()
        self.text_input = QLineEdit('')
        self.font_size = QSpinBox()
        self.font_size.setRange(6, 240)
        self.font_size.setValue(36)
        self.color_btn = QPushButton('颜色')
        self.opacity_slider = QSlider(Qt.Horizontal)
        self.opacity_slider.setRange(0, 100)
        self.opacity_slider.setValue(60)
        self.stroke_spin = QSpinBox()
        self.stroke_spin.setRange(0, 10)
        self.stroke_spin.setValue(0)
        text_layout.addRow('文字', self.text_input)
        text_layout.addRow('字号', self.font_size)
        text_layout.addRow('颜色', self.color_btn)
        text_layout.addRow('不透明度', self.opacity_slider)
        text_layout.addRow('描边宽度', self.stroke_spin)
        text_group.setLayout(text_layout)

        # --- Position presets ---
        pos_group = QGroupBox('位置/预设 (九宫格)')
        pos_layout = QGridLayout()
        self.pos_buttons = {}
        names = ['LT', 'CT', 'RT', 'LC', 'CC', 'RC', 'LB', 'CB', 'RB']
        coords = [(-1, -1), (0, -1), (1, -1), (-1, 0), (0, 0), (1, 0), (-1, 1), (0, 1), (1, 1)]
        for i, n in enumerate(names):
            btn = QPushButton(n)
            btn.setProperty('pos_coord', coords[i])
            self.pos_buttons[n] = btn
            pos_layout.addWidget(btn, i // 3, i % 3)
        pos_group.setLayout(pos_layout)

        # --- Export options ---
        export_group = QGroupBox('导出选项')
        export_layout = QFormLayout()
        self.naming_combo = QComboBox()
        self.naming_combo.addItems(['保留原名', '添加前缀', '添加后缀'])
        self.prefix_input = QLineEdit('wm_')
        self.suffix_input = QLineEdit('_watermarked')
        self.allow_export_to_src = QCheckBox('允许导出到源文件夹（默认禁止）')
        self.format_combo = QComboBox()
        self.format_combo.addItems(['PNG', 'JPEG'])
        export_layout.addRow('图片格式', self.format_combo)
        export_layout.addRow('命名规则', self.naming_combo)
        export_layout.addRow('前缀', self.prefix_input)
        export_layout.addRow('后缀', self.suffix_input)
        export_layout.addRow(self.allow_export_to_src)
        export_group.setLayout(export_layout)

        # 组装右侧控制
        ctrl_layout.addWidget(text_group)
        ctrl_layout.addWidget(pos_group)
        ctrl_layout.addWidget(export_group)
        ctrl_layout.addStretch()

        # --- Main layout: 三栏 ---
        main_layout = QHBoxLayout()
        main_layout.addWidget(left_widget)
        main_layout.addWidget(preview_container, 1)
        main_layout.addWidget(ctrl_widget)

        central = QWidget()
        central.setLayout(main_layout)
        self.setCentralWidget(central)

        # context menu actions
        self._add_actions()

    def _add_actions(self):
        clear_act = QAction('清除列表', self)
        clear_act.triggered.connect(self.clear_list)
        self.file_list.addAction(clear_act)

    def _connect_signals(self):
        self.import_file_btn.clicked.connect(self.import_files)
        self.import_folder_btn.clicked.connect(self.import_folder)
        self.export_btn.clicked.connect(self.export_all)
        self.file_list.itemSelectionChanged.connect(self.on_select_file)

        # text controls
        self.text_input.textChanged.connect(self.update_preview)
        self.font_size.valueChanged.connect(lambda _: self.update_preview())
        self.color_btn.clicked.connect(self.choose_color)
        self.opacity_slider.valueChanged.connect(lambda _: self.update_preview())
        self.stroke_spin.valueChanged.connect(lambda _: self.update_preview())

        # pos presets
        for btn in self.pos_buttons.values():
            btn.clicked.connect(self.on_pos_preset_clicked)

        # templates
        self.tpl_save_btn.clicked.connect(self.save_template)
        self.tpl_load_btn.clicked.connect(self.load_selected_template)
        self.tpl_del_btn.clicked.connect(self.delete_selected_template)

        # overlay move updates
        self.overlay.moved.connect(self.on_overlay_moved)

    # ---------------- file operations ----------------
    def import_files(self):
        files, _ = QFileDialog.getOpenFileNames(
            self,
            "选择图片文件",
            "",
            "Images (*.png *.jpg *.jpeg *.bmp *.tif *.tiff)"
        )
        paths = [Path(f) for f in files if Path(f).suffix.lower() in SUPPORTED_IN]
        if paths:
            self._add_images(paths)

    def import_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "选择文件夹")
        if folder:
            folder_path = Path(folder)
            all_files = [f for f in folder_path.rglob("*") if f.suffix.lower() in SUPPORTED_IN]
            if all_files:
                self._add_images(all_files)


    def clear_list(self):
        self.file_list.clear()
        self.images.clear()
        self.current_index = None
        self.current_pil = None
        self.preview_label.clear()
        self.overlay.hide()

    def on_select_file(self):
        idx = self.file_list.currentRow()
        if idx < 0 or idx >= len(self.images):
            return
        # 切换前保存当前图片设置
        if self.current_index is not None and self.current_index < len(self.images):
            cur_path = self.images[self.current_index]
            self.image_settings[cur_path] = self._gather_current_settings()
        self.current_index = idx
        p = self.images[idx]
        self.current_pil = load_image(p)
        if self.current_pil:
            w, h = self.current_pil.size
            # 预览按缩放因子
            pw, ph = int(w * self.preview_scale), int(h * self.preview_scale)
            self.preview_label.setMinimumSize(pw, ph)
            self.preview_label.setMaximumSize(pw, ph)
            self.preview_label.resize(pw, ph)
        # 加载该图片的设置
        settings = self.image_settings.get(p)
        if settings:
            self._apply_settings_dict(settings)
            self.update_preview()  # 应用设置后强制刷新预览
        self.show_preview(self.current_pil)

    # ---------------- preview / overlay ----------------
    def show_preview(self, pil_img):
        qpix = pil_to_qpixmap(pil_img)

        if qpix.width() > 0 and qpix.height() > 0:
            new_w = int(qpix.width() * self.preview_scale)
            new_h = int(qpix.height() * self.preview_scale)
            qpix = qpix.scaled(new_w, new_h, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        self.preview_label.setPixmap(qpix)
        self.preview_label.setScaledContents(False)

        self.overlay.setParent(self.preview_label)
        self.overlay.setGeometry(0, 0, self.preview_label.width(), self.preview_label.height())
        self.overlay.show()

    def update_preview(self):
        if not self.current_pil:
            return
        ctx = self._gather_current_settings()
        if self.current_index is not None and self.current_index < len(self.images):
            cur_path = self.images[self.current_index]
            self.image_settings[cur_path] = ctx.copy()

        percent_pos = ctx.get('text_pos_percent', (0.0, 0.0))
        label_pos = self.image_to_label_percent(*percent_pos)

        if ctx.get('use_text_mark') and ctx.get('text'):
            font = QFont()
            font.setPixelSize(self.font_size.value())
            color = QColor(*map(int, self._chosen_color))
            stroke_color = QColor(*map(int, ctx.get('stroke_fill', (0, 0, 0))))
            self.overlay.set_text(
                text=ctx['text'],
                font=font,
                color=color,
                stroke_width=ctx['stroke_width'],
                stroke_color=stroke_color,
                opacity=ctx['opacity'],
                position=label_pos
            )
        else:
            self.overlay._text = ''

        self.overlay.update()

    def _gather_current_settings(self) -> Dict[str, Any]:
        use_text = bool(self.text_input.text())
        percent_pos = (0.0, 0.0)
        if self.overlay and self.overlay.isVisible():
            draw_pt = self.overlay._draw_pos
            px, py = self.label_to_percent(draw_pt)
            percent_pos = (px, py)

        color = getattr(self, '_chosen_color', (255, 255, 255))
        ctx = {
            'use_text_mark': use_text,
            'text': self.text_input.text(),
            'font_size': self.font_size.value(),
            'color': color,
            'opacity': self.opacity_slider.value() / 100.0,
            'stroke_width': self.stroke_spin.value(),
            'stroke_fill': (0, 0, 0),
            'text_pos_percent': percent_pos,
            'anchor': 'rd'
        }
        return ctx

    def choose_color(self):
        col = QColorDialog.getColor()
        if col.isValid():
            # store color as rgb tuple (session only)
            self._chosen_color = (col.red(), col.green(), col.blue())
            self.update_preview()


    # ---------------- position buttons ----------------
    def on_pos_preset_clicked(self):
        btn = self.sender()
        if not self.current_pil:
            return
        # 九宫格百分比坐标
        font = QFont()
        scaled_font_px = max(1, int(self.font_size.value() * self.preview_scale))
        font.setPixelSize(scaled_font_px)
        fm = QFontMetrics(font)
        text = self.text_input.text()
        if text:
            rect = fm.boundingRect(text)
            wm_w = rect.width()
            wm_h = rect.height()
        else:
            wm_w, wm_h = 100, 30
        lw, lh = self.preview_label.width(), self.preview_label.height()
        # 百分比坐标为中心点
        pos_percent_map = {
            'LT': (0, 0),
            'CT': (0.5 - 2 * wm_w/lw, 0),
            'RT': (1.0 - 4 * wm_w/lw, 0),
            'LC': (0, 0.5 - 2 * wm_h/lh),
            'CC': (0.5 - 2 * wm_w/lw, 0.5 - 2 * wm_h/lh),
            'RC': (1.0 - 4 * wm_w/lw, 0.5 - 2 * wm_h/lh),
            'LB': (0, 1.0 - 4 * wm_h/lh),
            'CB': (0.5 - 2 * wm_w/lw, 1.0 - 4 * wm_h/lh),
            'RB': (1.0 - 4 * wm_w/lw, 1.0 - 4 * wm_h/lh)
        }
        btn_name = btn.text()
        px, py = pos_percent_map.get(btn_name, (0.5, 0.5))
        label_pt = self.image_to_label_percent(px, py)
        self.overlay.set_draw_pos(label_pt.x(), label_pt.y())
        self.update_preview()
        if self.current_index is not None and self.current_index < len(self.images):
            cur_path = self.images[self.current_index]
            self.image_settings[cur_path] = self._gather_current_settings()

    # ---------------- templates ----------------
    def _load_template_names(self):
        self.tpl_list.clear()
        if not isinstance(self.templates, dict):
            return
        for k in sorted([k for k in self.templates.keys() if not k.startswith('__')]):
            self.tpl_list.addItem(k)

    def save_template(self):
        resource_file = resource_path("resource/default_templates.json")
        # 获取当前模板名
        from PySide6.QtWidgets import QInputDialog
        name, ok = QInputDialog.getText(self, '模板名称', '请输入模板名称:')
        if not ok or not name.strip():
            return
        name = name.strip()
        # 读取原有模板
        try:
            if resource_path.exists():
                templates = json.loads(resource_path.read_text(encoding='utf-8'))
            else:
                templates = {}
        except Exception:
            templates = {}
        # 保存新模板，位置用百分比
        ctx = self._gather_current_settings()
        # 位置百分比化
        if self.current_pil and 'text_pos' in ctx:
            w, h = self.current_pil.size
            x, y = ctx['text_pos']
            ctx['text_pos_percent'] = (x / w if w else 0, y / h if h else 0)
            ctx.pop('text_pos', None)
        templates[name] = ctx
        resource_file.write_text(json.dumps(templates, ensure_ascii=False, indent=2), encoding='utf-8')
        # 刷新左侧模板列表
        self.templates = templates
        self._load_template_names()
        QMessageBox.information(self, '保存', f'已保存模板到 {resource_file}')

    def load_selected_template(self):
        it = self.tpl_list.currentItem()
        if not it:
            QMessageBox.warning(self, '错误', '请先选择模板')
            return
        name = it.text()
        resource_file = resource_path("resource/default_templates.json")
        if resource_file.exists():
            templates = json.loads(resource_file.read_text(encoding='utf-8'))
        else:
            templates = {}

        data = templates.get(name)
        if not data:
            QMessageBox.warning(self, '错误', '模板数据不存在')
            return
        self._apply_settings_dict(data)
        self.update_preview()

    def delete_selected_template(self):
        it = self.tpl_list.currentItem()
        if not it:
            return
        name = it.text()
        resource_file = resource_path("resource/default_templates.json")
        if resource_file.exists():
            templates = json.loads(resource_file.read_text(encoding='utf-8'))
        else:
            templates = {}
        if name in templates:
            del templates[name]
            resource_file.write_text(json.dumps(templates, ensure_ascii=False, indent=2), encoding='utf-8')
            self.templates = templates
            self._load_template_names()
            QMessageBox.information(self, '删除', f'已删除模板 {name}')

    def _apply_settings_dict(self, d: dict):
        try:
            if 'text' in d:
                self.text_input.setText(d.get('text', ''))
            if 'font_size' in d:
                self.font_size.setValue(int(d.get('font_size', 36)))
            if 'opacity' in d:
                self.opacity_slider.setValue(int(float(d.get('opacity', 0.6)) * 100))
            if 'color' in d:
                col = d.get('color', (255, 255, 255))
                self._chosen_color = tuple(col)
            if 'stroke_width' in d:
                self.stroke_spin.setValue(int(d.get('stroke_width', 0)))
            if 'stroke_fill' in d:
                stroke_col = d.get('stroke_fill', (0, 0, 0))
            if 'text_pos_percent' in d:
                px, py = d['text_pos_percent']
                label_pt = self.image_to_label_percent(px, py)
                self.overlay.set_draw_pos(label_pt.x(), label_pt.y())
        except Exception:
            pass

    # ---------------- export ----------------
    def export_all(self):
        if not self.images:
            QMessageBox.warning(self, '没有图片', '请先导入图片')
            return
        out_dir = QFileDialog.getExistingDirectory(self, '选择输出文件夹')
        if not out_dir:
            return
        out_dir = Path(out_dir)
        if not self.allow_export_to_src.isChecked():
            for p in self.images:
                if p.parent == out_dir:
                    QMessageBox.warning(self, '错误', '输出文件夹不能是源图片所在的文件夹（可在导出选项允许）')
                    return
        # build tasks，每张图片用独立设置
        export_format = self.format_combo.currentText().upper()
        ext = ".png" if export_format == "PNG" else ".jpg"
        tasks = []
        for idx, p in enumerate(self.images):
            # compute name
            if self.naming_combo.currentText() == '保留原名':
                name = p.stem + ext
            elif self.naming_combo.currentText() == '添加前缀':
                name = self.prefix_input.text() + p.stem + ext
            else:
                name = p.stem + self.suffix_input.text() + ext
            dst = out_dir / name
            ctx = self.image_settings.get(p)
            if not ctx:
                # fallback: 当前设置
                ctx = self._gather_current_settings()
            ctx['export_format'] = export_format
            tasks.append((p, dst, ctx.copy()))
        # start worker
        self.export_worker = ExportWorker(tasks)
        self.export_worker.progress.connect(lambda v: self.progress.setValue(v))
        self.export_worker.error.connect(lambda e: QMessageBox.critical(self, '导出错误', e))
        self.export_worker.finished.connect(self._on_export_finished, Qt.UniqueConnection)
        self.export_worker.start()

    def _on_export_finished(self):
        QMessageBox.information(self, '完成', '导出完成')
        self.export_worker.finished.disconnect(self._on_export_finished)


    # ---------------- overlay moved ----------------
    def on_overlay_moved(self, pos: QPoint):
        # 拖动水印时，更新当前图片的 text_pos_percent
        print(f"水印当前位置 label 坐标: {pos.x()}, {pos.y()}")
        px, py = self.label_to_percent(pos)
        if self.current_index is not None and self.current_index < len(self.images):
            cur_path = self.images[self.current_index]
            if cur_path in self.image_settings:
                self.image_settings[cur_path]['text_pos_percent'] = (px, py)
            else:
                ctx = self._gather_current_settings()
                ctx['text_pos_percent'] = (px, py)
                self.image_settings[cur_path] = ctx

    # ---------------- close ----------------
    def closeEvent(self, ev):
        # save last settings
        try:
            d = self._gather_current_settings()
            tpl = templates_mod.load_templates() if templates_mod else {}
            tpl['__last__'] = d
            templates_mod.save_templates(tpl)
        except Exception:
            pass
        super().closeEvent(ev)

    def image_to_label_percent(self, px: float, py: float) -> QPoint:
        """将百分比坐标映射到label像素坐标"""
        if not self.current_pil:
            return QPoint(0, 0)
        lw, lh = self.preview_label.width(), self.preview_label.height()
        x = int(px * lw)
        y = int(py * lh)
        return QPoint(x, y)

    def label_to_percent(self, pt: QPoint) -> tuple[float, float]:
        """将label上的像素坐标映射为百分比坐标"""
        lw, lh = self.preview_label.width(), self.preview_label.height()
        if lw == 0 or lh == 0:
            return (0.0, 0.0)
        return pt.x() / lw, pt.y() / lh

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        if self.overlay.isVisible() and self.current_pil:
            self.overlay.setGeometry(0, 0, self.preview_label.width(), self.preview_label.height())
            self.update_preview()

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            for url in event.mimeData().urls():
                if url.isLocalFile():
                    p = Path(url.toLocalFile())
                    if p.is_dir() or p.suffix.lower() in SUPPORTED_IN:
                        event.acceptProposedAction()
                        return
        event.ignore()

    def dropEvent(self, event):
        if event.mimeData().hasUrls():
            files = []
            for url in event.mimeData().urls():
                if url.isLocalFile():
                    p = Path(url.toLocalFile())
                    if p.is_dir():
                        # 文件夹 → 递归找图片
                        for f in p.rglob("*"):
                            if f.suffix.lower() in SUPPORTED_IN:
                                files.append(f)
                    elif p.suffix.lower() in SUPPORTED_IN:
                        files.append(p)
            if files:
                self._add_images(files)
                event.acceptProposedAction()

    def _add_images(self, files: list[Path]):
        for p in files:
            if p not in self.images:
                self.images.append(p)
                item = QListWidgetItem(p.name)
                try:
                    pil = load_image(p)
                    qpix = pil_to_qpixmap(pil).scaled(96, 96, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                    item.setIcon(QIcon(qpix))
                except Exception:
                    pass
                self.file_list.addItem(item)

                # 默认模板
                default_tpl = self.templates.get('默认') if hasattr(self, 'templates') else None
                if default_tpl:
                    self.image_settings[p] = default_tpl.copy()

# If run as script for debugging
if __name__ == '__main__':
    from PySide6.QtWidgets import QApplication
    app = QApplication(sys.argv)
    w = MainWindow()
    w.show()
    sys.exit(app.exec())
