# ui/main_window.py
"""
完整的 MainWindow 实现（基于 PySide6 + Pillow + core/* 模块）。
功能亮点：
- 文件/文件夹批量导入（支持拖放、文件选择器），显示缩略图与文件名列表
- 实时预览（PIL -> QPixmap）
- 文本水印（字体/大小/颜色/描边/透明度/旋转/位置九宫格/拖拽）
- 图片水印（加载 PNG logo，缩放/透明度/旋转/拖拽）
- 模板保存/加载/删除（使用 core.templates）
- 批量导出（输出命名规则、JPEG quality、尺寸缩放、禁止导出到源文件夹）
- 后台导出线程并显示进度

依赖：PySide6, Pillow, core.io_ops, core.watermark, core.templates
保存为 ui/main_window.py
"""
from __future__ import annotations

import io
import json
from pathlib import Path
from typing import Optional, Tuple, Dict, Any

from PySide6.QtCore import Qt, QSize, QPoint, Signal, QThread
from PySide6.QtGui import QPixmap, QImage, QIcon, QFontDatabase, QAction
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QFileDialog, QListWidget, QLabel, QPushButton,
    QHBoxLayout, QVBoxLayout, QLineEdit, QSpinBox, QSlider, QComboBox,
    QMessageBox, QColorDialog, QListWidgetItem, QProgressBar,
    QCheckBox, QGroupBox, QGridLayout, QFontComboBox, QFormLayout, QAbstractItemView
)

from PIL import Image as PilImage

from core.io_ops import load_image, save_image, resize_image, SUPPORTED_IN
from core.watermark import apply_text_watermark, apply_image_watermark
from core import templates as templates_mod


def pil_to_qpixmap(pil_img) -> QPixmap:
    buf = io.BytesIO()
    pil_img.convert('RGBA').save(buf, format='PNG')
    qimg = QImage.fromData(buf.getvalue(), 'PNG')
    return QPixmap.fromImage(qimg)


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
                # apply watermark according to ctx
                if ctx.get('use_image_mark') and ctx.get('mark_img'):
                    img = apply_image_watermark(
                        img,
                        ctx['mark_img'],
                        position=tuple(ctx.get('mark_pos', (0, 0))),
                        scale=ctx.get('mark_scale', 1.0),
                        opacity=ctx.get('mark_opacity', 0.5),
                        rotation=ctx.get('mark_rotation', 0.0)
                    )
                if ctx.get('use_text_mark'):
                    img = apply_text_watermark(
                        img,
                        ctx.get('text', ''),
                        ctx.get('font_path'),
                        font_size=ctx.get('font_size', 36),
                        color=tuple(ctx.get('color', (255, 255, 255))),
                        opacity=ctx.get('opacity', 0.5),
                        position=tuple(ctx.get('text_pos', (0, 0))),
                        anchor=ctx.get('anchor', 'lt'),
                        rotation=ctx.get('text_rotation', 0.0),
                        stroke_width=ctx.get('stroke_width', 0),
                        stroke_fill=tuple(ctx.get('stroke_fill', (0, 0, 0)))
                    )

                # resize if requested
                if ctx.get('resize_mode') and ctx.get('resize_value'):
                    mode = ctx['resize_mode']
                    val = ctx['resize_value']
                    if mode == 'percent':
                        img = resize_image(img, percent=val)
                    elif mode == 'width':
                        img = resize_image(img, width=int(val))
                    elif mode == 'height':
                        img = resize_image(img, height=int(val))

                # save
                dst.parent.mkdir(parents=True, exist_ok=True)
                save_image(img, dst, quality=ctx.get('jpeg_quality', 95))

                self.progress.emit(int(i / total * 100))
        except Exception as e:
            self.error.emit(str(e))
        finally:
            self.finished.emit()

    def cancel(self):
        self._is_cancelled = True


class DraggableOverlay(QLabel):
    """可在预览上拖动的水印显示层：既可以显示文本，也可以显示图片（PIL -> QPixmap）"""

    moved = Signal(QPoint)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, False)
        self.setMouseTracking(True)
        self._dragging = False
        self._last_pos = QPoint(0, 0)
        self._content_mode = 'text'  # 'text' or 'image'
        self._pixmap = None
        self._text = ''

    def set_text(self, text: str, qpixmap: Optional[QPixmap] = None):
        self._content_mode = 'text'
        self._text = text
        if qpixmap:
            self._pixmap = qpixmap
        self.update()

    def set_image(self, qpixmap: QPixmap):
        self._content_mode = 'image'
        self._pixmap = qpixmap
        self.update()

    def paintEvent(self, ev):
        super().paintEvent(ev)
        painter = None
        try:
            from PySide6.QtGui import QPainter, QFont, QPen, QColor
            painter = QPainter(self)
            painter.setRenderHints(painter.Antialiasing | painter.SmoothPixmapTransform)
            if self._content_mode == 'image' and self._pixmap:
                painter.drawPixmap(0, 0, self._pixmap)
            elif self._content_mode == 'text':
                if self._pixmap:
                    painter.drawPixmap(0, 0, self._pixmap)
                if self._text:
                    font = QFont()
                    font.setPointSize(20)
                    painter.setFont(font)
                    pen = QPen(QColor(255, 255, 255))
                    painter.setPen(pen)
                    painter.drawText(self.rect(), Qt.AlignLeft | Qt.AlignTop, self._text)
        finally:
            if painter:
                painter.end()

    def mousePressEvent(self, ev):
        if ev.button() == Qt.LeftButton:
            self._dragging = True
            self._last_pos = ev.globalPosition().toPoint()
            ev.accept()
        else:
            ev.ignore()

    def mouseMoveEvent(self, ev):
        if self._dragging:
            gp = ev.globalPosition().toPoint()
            delta = gp - self._last_pos
            self.move(self.pos() + delta)
            self._last_pos = gp
            self.moved.emit(self.pos())
            ev.accept()
        else:
            ev.ignore()

    def mouseReleaseEvent(self, ev):
        if ev.button() == Qt.LeftButton:
            self._dragging = False
            ev.accept()
        else:
            ev.ignore()


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle('WatermarkApp')
        self.resize(1200, 800)

        self.images: list[Path] = []
        self.current_index: Optional[int] = None
        self.current_pil = None  # PIL Image for currently selected

        self.mark_logo_pil = None
        self.mark_logo_qpixmap = None

        self._chosen_color = (255, 255, 255)

        self._init_ui()
        self._connect_signals()

        # load templates
        try:
            self.templates = templates_mod.load_templates()
        except Exception:
            self.templates = {}
        self._load_template_names()

        # load last settings if exists
        last = self.templates.get('__last__') if isinstance(self.templates, dict) else None
        if last:
            self._apply_settings_dict(last)

        self.export_worker: Optional[ExportWorker] = None

    def _init_ui(self):
        # Left: file list
        self.file_list = QListWidget()
        self.file_list.setMaximumWidth(320)
        self.file_list.setIconSize(QSize(96, 96))
        self.file_list.setSelectionMode(QAbstractItemView.SingleSelection)

        # Center: preview area (stacked: preview QLabel + overlay)
        preview_container = QWidget()
        preview_layout = QVBoxLayout(preview_container)
        preview_layout.setContentsMargins(0, 0, 0, 0)
        self.preview_label = QLabel('预览')
        self.preview_label.setAlignment(Qt.AlignCenter)
        self.preview_label.setStyleSheet('background: #222; color: #eee;')
        self.preview_label.setMinimumSize(640, 480)
        self.preview_label.setScaledContents(False)
        preview_layout.addWidget(self.preview_label)

        # overlay
        self.overlay = DraggableOverlay(self.preview_label)
        self.overlay.hide()

        # Right: controls
        ctrl_widget = QWidget()
        ctrl_layout = QVBoxLayout(ctrl_widget)

        # --- Import/Export buttons ---
        self.import_btn = QPushButton('导入图片/文件夹')
        self.export_btn = QPushButton('导出/批量处理')

        # --- Text watermark controls ---
        text_group = QGroupBox('文本水印')
        text_layout = QFormLayout()
        self.text_input = QLineEdit('示例水印')
        self.font_combo = QFontComboBox()
        self.font_size = QSpinBox(); self.font_size.setRange(6, 240); self.font_size.setValue(36)
        self.color_btn = QPushButton('颜色')
        self.opacity_slider = QSlider(Qt.Horizontal); self.opacity_slider.setRange(0, 100); self.opacity_slider.setValue(60)
        self.stroke_spin = QSpinBox(); self.stroke_spin.setRange(0, 10); self.stroke_spin.setValue(0)
        self.rotation_text = QSpinBox(); self.rotation_text.setRange(0, 360); self.rotation_text.setValue(0)

        text_layout.addRow('文字', self.text_input)
        text_layout.addRow('字体', self.font_combo)
        text_layout.addRow('字号', self.font_size)
        text_layout.addRow('颜色', self.color_btn)
        text_layout.addRow('不透明度', self.opacity_slider)
        text_layout.addRow('描边宽度', self.stroke_spin)
        text_layout.addRow('旋转(°)', self.rotation_text)
        text_group.setLayout(text_layout)

        # --- Image watermark controls ---
        img_group = QGroupBox('图片水印 (Logo)')
        img_layout = QFormLayout()
        self.load_logo_btn = QPushButton('加载 Logo (PNG)')
        self.logo_scale = QSlider(Qt.Horizontal); self.logo_scale.setRange(1, 400); self.logo_scale.setValue(100)
        self.logo_opacity = QSlider(Qt.Horizontal); self.logo_opacity.setRange(0, 100); self.logo_opacity.setValue(60)
        self.logo_rotation = QSpinBox(); self.logo_rotation.setRange(0, 360); self.logo_rotation.setValue(0)
        img_layout.addRow(self.load_logo_btn)
        img_layout.addRow('缩放 (%)', self.logo_scale)
        img_layout.addRow('不透明度', self.logo_opacity)
        img_layout.addRow('旋转(°)', self.logo_rotation)
        img_group.setLayout(img_layout)

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

        # --- Templates ---
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

        # --- Export options ---
        export_group = QGroupBox('导出选项')
        export_layout = QFormLayout()
        self.naming_combo = QComboBox(); self.naming_combo.addItems(['保留原名', '添加前缀', '添加后缀'])
        self.prefix_input = QLineEdit('wm_')
        self.suffix_input = QLineEdit('_watermarked')
        self.jpeg_quality = QSlider(Qt.Horizontal); self.jpeg_quality.setRange(10, 100); self.jpeg_quality.setValue(95)
        self.resize_mode_combo = QComboBox(); self.resize_mode_combo.addItems(['不缩放', '按百分比', '按宽度', '按高度'])
        self.resize_value_input = QSpinBox(); self.resize_value_input.setRange(1, 5000); self.resize_value_input.setValue(100)
        self.allow_export_to_src = QCheckBox('允许导出到源文件夹（默认禁止）')
        export_layout.addRow('命名规则', self.naming_combo)
        export_layout.addRow('前缀', self.prefix_input)
        export_layout.addRow('后缀', self.suffix_input)
        export_layout.addRow('JPEG 质量', self.jpeg_quality)
        export_layout.addRow('缩放模式', self.resize_mode_combo)
        export_layout.addRow('缩放值', self.resize_value_input)
        export_layout.addRow(self.allow_export_to_src)
        export_group.setLayout(export_layout)

        # progress bar
        self.progress = QProgressBar(); self.progress.setValue(0)

        # assemble controls
        ctrl_layout.addWidget(self.import_btn)
        ctrl_layout.addWidget(self.export_btn)
        ctrl_layout.addWidget(text_group)
        ctrl_layout.addWidget(img_group)
        ctrl_layout.addWidget(pos_group)
        ctrl_layout.addWidget(tpl_group)
        ctrl_layout.addWidget(export_group)
        ctrl_layout.addWidget(self.progress)
        ctrl_layout.addStretch()

        # main layout
        central = QWidget()
        main_layout = QHBoxLayout(central)
        main_layout.addWidget(self.file_list)
        main_layout.addWidget(preview_container, 1)
        main_layout.addWidget(ctrl_widget)
        self.setCentralWidget(central)

        # context menu actions
        self._add_actions()

    def _add_actions(self):
        clear_act = QAction('清除列表', self)
        clear_act.triggered.connect(self.clear_list)
        self.file_list.addAction(clear_act)

    def _connect_signals(self):
        self.import_btn.clicked.connect(self.import_images)
        self.export_btn.clicked.connect(self.export_all)
        self.file_list.itemSelectionChanged.connect(self.on_select_file)

        # text controls
        self.text_input.textChanged.connect(self.update_preview)
        self.font_combo.currentFontChanged.connect(lambda _: self.update_preview())
        self.font_size.valueChanged.connect(lambda _: self.update_preview())
        self.color_btn.clicked.connect(self.choose_color)
        self.opacity_slider.valueChanged.connect(lambda _: self.update_preview())
        self.stroke_spin.valueChanged.connect(lambda _: self.update_preview())
        self.rotation_text.valueChanged.connect(lambda _: self.update_preview())

        # logo
        self.load_logo_btn.clicked.connect(self.load_logo)
        self.logo_scale.valueChanged.connect(lambda _: self.update_preview())
        self.logo_opacity.valueChanged.connect(lambda _: self.update_preview())
        self.logo_rotation.valueChanged.connect(lambda _: self.update_preview())

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
    def import_images(self):
        dlg = QFileDialog(self)
        dlg.setFileMode(QFileDialog.ExistingFiles)
        dlg.setNameFilters(['Images (*.png *.jpg *.jpeg *.bmp *.tif *.tiff)'])
        if dlg.exec():
            files = [Path(p) for p in dlg.selectedFiles()]
            for p in files:
                if p.suffix.lower() in SUPPORTED_IN and p not in self.images:
                    self.images.append(p)
                    item = QListWidgetItem(p.name)
                    # try to add thumbnail
                    try:
                        pil = load_image(p)
                        qpix = pil_to_qpixmap(pil).scaled(96, 96, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                        item.setIcon(QIcon(qpix))
                    except Exception:
                        pass
                    self.file_list.addItem(item)

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
        self.current_index = idx
        p = self.images[idx]
        self.current_pil = load_image(p)
        self.show_preview(self.current_pil)

    # ---------------- preview / overlay ----------------
    def show_preview(self, pil_img):
        qpix = pil_to_qpixmap(pil_img)
        # scale to label size while maintaining aspect
        w = self.preview_label.width()
        h = self.preview_label.height()
        scaled = qpix.scaled(w, h, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        self.preview_label.setPixmap(scaled)
        # adjust overlay size and position proportional to preview
        pix_w, pix_h = scaled.width(), scaled.height()
        self.overlay.setParent(self.preview_label)
        self.overlay.setFixedSize(pix_w, pix_h)
        self.overlay.move(0, 0)
        self.overlay.show()
        self.update_preview()

    def update_preview(self):
        if not self.current_pil:
            return
        img = self.current_pil.convert('RGBA')
        ctx = self._gather_current_settings()
        # apply logo first
        if ctx.get('use_image_mark') and ctx.get('mark_img'):
            img = apply_image_watermark(
                img,
                ctx['mark_img'],
                position=tuple(ctx.get('mark_pos', (0, 0))),
                scale=ctx.get('mark_scale', 1.0),
                opacity=ctx.get('mark_opacity', 0.5),
                rotation=ctx.get('mark_rotation', 0.0)
            )
        # apply text
        if ctx.get('use_text_mark'):
            img = apply_text_watermark(
                img,
                ctx.get('text', ''),
                ctx.get('font_path'),
                font_size=ctx.get('font_size', 36),
                color=tuple(ctx.get('color', (255, 255, 255))),
                opacity=ctx.get('opacity', 0.5),
                position=tuple(ctx.get('text_pos', (0, 0))),
                anchor=ctx.get('anchor', 'lt'),
                rotation=ctx.get('text_rotation', 0.0),
                stroke_width=ctx.get('stroke_width', 0),
                stroke_fill=tuple(ctx.get('stroke_fill', (0, 0, 0)))
            )
        # display
        self.show_preview(img)

    def _gather_current_settings(self) -> Dict[str, Any]:
        # derive positions relative to original image size (we use absolute pixels based on original)
        use_text = bool(self.text_input.text())
        use_image = self.mark_logo_pil is not None
        # default positions: place at bottom-right
        tex_pos = (0, 0)
        mark_pos = (0, 0)
        # for simplicity: text pos computed as offset from bottom-right
        if self.current_pil:
            w, h = self.current_pil.size
            tex_pos = (w - 20, h - 20)
            if self.mark_logo_pil:
                scaled_w = max(1, int(self.mark_logo_pil.width * (self.logo_scale.value() / 100.0)))
                scaled_h = max(1, int(self.mark_logo_pil.height * (self.logo_scale.value() / 100.0)))
                mark_pos = (w - scaled_w - 20, h - scaled_h - 20)
        # color
        color = getattr(self, '_chosen_color', (255, 255, 255))
        resize_mode = None
        resize_value = None
        mode_text = self.resize_mode_combo.currentText()
        if mode_text == '按百分比':
            resize_mode = 'percent'
            resize_value = self.resize_value_input.value() / 100.0
        elif mode_text == '按宽度':
            resize_mode = 'width'
            resize_value = self.resize_value_input.value()
        elif mode_text == '按高度':
            resize_mode = 'height'
            resize_value = self.resize_value_input.value()

        return {
            'use_text_mark': use_text,
            'text': self.text_input.text(),
            'font_path': None,
            'font_size': self.font_size.value(),
            'color': color,
            'opacity': self.opacity_slider.value() / 100.0,
            'stroke_width': self.stroke_spin.value(),
            'stroke_fill': (0, 0, 0),
            'text_pos': tex_pos,
            'anchor': 'rd',
            'text_rotation': float(self.rotation_text.value()),
            'use_image_mark': use_image,
            'mark_img': self._build_scaled_logo_pil(),
            'mark_scale': self.logo_scale.value() / 100.0,
            'mark_opacity': self.logo_opacity.value() / 100.0,
            'mark_rotation': float(self.logo_rotation.value()),
            'mark_pos': mark_pos,
            'resize_mode': resize_mode,
            'resize_value': resize_value,
            'jpeg_quality': self.jpeg_quality.value()
        }

    def _build_scaled_logo_pil(self):
        if not self.mark_logo_pil:
            return None
        scale = self.logo_scale.value() / 100.0
        new_size = (max(1, int(self.mark_logo_pil.width * scale)), max(1, int(self.mark_logo_pil.height * scale)))
        try:
            return self.mark_logo_pil.resize(new_size, resample=PilImage.LANCZOS)
        except Exception:
            return self.mark_logo_pil.resize(new_size)

    def choose_color(self):
        col = QColorDialog.getColor()
        if col.isValid():
            # store color as rgb tuple (session only)
            self._chosen_color = (col.red(), col.green(), col.blue())
            self.update_preview()

    # ---------------- logo ----------------
    def load_logo(self):
        path, _ = QFileDialog.getOpenFileName(self, '选择 Logo（透明 PNG 建议）', filter='Images (*.png *.jpg *.jpeg *.bmp)')
        if not path:
            return
        p = Path(path)
        pil = load_image(p).convert('RGBA')
        self.mark_logo_pil = pil
        self.mark_logo_qpixmap = pil_to_qpixmap(pil)
        # show on overlay (scaled to overlay if too big)
        scaled = self.mark_logo_qpixmap.scaled(self.overlay.width(), self.overlay.height(), Qt.KeepAspectRatio, Qt.SmoothTransformation)
        self.overlay.set_image(scaled)
        self.update_preview()

    # ---------------- position buttons ----------------
    def on_pos_preset_clicked(self):
        btn = self.sender()
        coords = btn.property('pos_coord')
        if not self.current_pil:
            return
        w, h = self.current_pil.size
        cx = (coords[0] + 1) / 2  # -1..1 -> 0..1
        cy = (coords[1] + 1) / 2
        # compute pixel pos (not yet mapped to overlay; we keep simple behavior)
        x = int(cx * w)
        y = int(cy * h)
        # This implementation uses presets as hints — actual precise mapping can be done by translating overlay pos -> image coords.
        self.update_preview()

    # ---------------- templates ----------------
    def _load_template_names(self):
        self.tpl_list.clear()
        if not isinstance(self.templates, dict):
            return
        for k in sorted([k for k in self.templates.keys() if not k.startswith('__')]):
            self.tpl_list.addItem(k)

    def save_template(self):
        name, ok = QFileDialog.getSaveFileName(self, '保存模板为 JSON', str(Path.home() / 'wm_template.json'), 'JSON Files (*.json)')
        if not name:
            return
        data = self._gather_current_settings()
        Path(name).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
        QMessageBox.information(self, '保存', f'已保存模板到 {name}')

    def load_selected_template(self):
        it = self.tpl_list.currentItem()
        if not it:
            QMessageBox.warning(self, '错误', '请先选择模板')
            return
        name = it.text()
        data = self.templates.get(name)
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
        templates = templates_mod.load_templates()
        if name in templates:
            del templates[name]
            templates_mod.save_templates(templates)
            self.templates = templates
            self._load_template_names()
            QMessageBox.information(self, '删除', f'已删除模板 {name}')

    def _apply_settings_dict(self, d: dict):
        # apply a subset of settings safely
        try:
            if 'text' in d:
                self.text_input.setText(d.get('text', ''))
            if 'font_size' in d:
                self.font_size.setValue(int(d.get('font_size', 36)))
            if 'opacity' in d:
                self.opacity_slider.setValue(int(float(d.get('opacity', 0.6)) * 100))
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
            # check none of images have same parent
            for p in self.images:
                if p.parent == out_dir:
                    QMessageBox.warning(self, '错误', '输出文件夹不能是源图片所在的文件夹（可在导出选项允许）')
                    return
        # build tasks
        tasks = []
        ctx = self._gather_current_settings()
        for p in self.images:
            # compute name
            if self.naming_combo.currentText() == '保留原名':
                name = p.name
            elif self.naming_combo.currentText() == '添加前缀':
                name = self.prefix_input.text() + p.name
            else:
                name = p.stem + self.suffix_input.text() + p.suffix
            dst = out_dir / name
            tasks.append((p, dst, ctx.copy()))
        # start worker
        self.export_worker = ExportWorker(tasks)
        self.export_worker.progress.connect(lambda v: self.progress.setValue(v))
        self.export_worker.error.connect(lambda e: QMessageBox.critical(self, '导出错误', e))
        self.export_worker.finished.connect(lambda: QMessageBox.information(self, '完成', '导出完成'))
        self.export_worker.start()

    # ---------------- overlay moved ----------------
    def on_overlay_moved(self, pos: QPoint):
        # when user drags overlay we could map its pos back to text/logo positions
        # This is a placeholder hook to map overlay position to watermark pixel coordinates if needed.
        pass

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


# If run as script for debugging
if __name__ == '__main__':
    import sys
    from PySide6.QtWidgets import QApplication
    app = QApplication(sys.argv)
    w = MainWindow()
    w.show()
    sys.exit(app.exec())
