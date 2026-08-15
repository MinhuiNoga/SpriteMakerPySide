from __future__ import annotations

from pathlib import Path
from typing import List, Optional

from PySide6.QtCore import QRectF, QSize, Qt, QTimer
from PySide6.QtGui import QColor, QIcon, QImage, QPainter, QPen, QPixmap, QWheelEvent
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QDialog,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSlider,
    QSpinBox,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from .models import RGBA_FORMAT, frame_from_image
from .sprite_ops import (
    SpriteSheetGeometry,
    SpriteSheetLayout,
    calculate_sprite_geometry,
    padded_spritesheet_image,
    split_spritesheet,
    sprite_cell_rect,
)


SPRITE_THUMBNAIL_ROLE = int(Qt.ItemDataRole.UserRole) + 1


def checkerboard_image(size: QSize, square: int = 12) -> QImage:
    image = QImage(max(1, size.width()), max(1, size.height()), RGBA_FORMAT)
    painter = QPainter(image)
    colors = (QColor("#707070"), QColor("#909090"))
    for y in range(0, image.height(), square):
        for x in range(0, image.width(), square):
            painter.fillRect(x, y, square, square, colors[(x // square + y // square) % 2])
    painter.end()
    return image


def image_over_checkerboard(image: QImage) -> QImage:
    result = checkerboard_image(image.size())
    painter = QPainter(result)
    painter.drawImage(0, 0, image)
    painter.end()
    return result


class ZoomImageLabel(QLabel):
    def __init__(self, placeholder: str) -> None:
        super().__init__(placeholder)
        self._image = QImage()
        self._zoom = 1.0
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setStyleSheet("background:#111827; color:#e5e7eb;")
        self.setMinimumSize(280, 220)

    def setImage(self, image: QImage) -> None:
        self._image = image.copy()
        self._refresh_pixmap()

    def setZoom(self, zoom: float) -> None:
        self._zoom = max(0.1, min(8.0, float(zoom)))
        self._refresh_pixmap()

    def wheelEvent(self, event: QWheelEvent) -> None:
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            factor = 1.12 if event.angleDelta().y() > 0 else 1 / 1.12
            self.setZoom(self._zoom * factor)
            event.accept()
            return
        super().wheelEvent(event)

    def _refresh_pixmap(self) -> None:
        if self._image.isNull():
            return
        size = QSize(
            max(1, round(self._image.width() * self._zoom)),
            max(1, round(self._image.height() * self._zoom)),
        )
        pixmap = QPixmap.fromImage(self._image).scaled(
            size,
            Qt.AspectRatioMode.IgnoreAspectRatio,
            Qt.TransformationMode.FastTransformation,
        )
        self.setPixmap(pixmap)
        self.resize(pixmap.size())


class SpriteImportDialog(QDialog):
    def __init__(
        self,
        parent: Optional[QWidget] = None,
        initial_directory: Optional[Path] = None,
        image_filter: str = "Images (*.png *.jpg *.jpeg *.bmp *.gif *.webp)",
    ) -> None:
        super().__init__(parent)
        self.initial_directory = Path(initial_directory) if initial_directory else Path.home()
        self.image_filter = image_filter
        self.source_path: Optional[Path] = None
        self.source_image = QImage()
        self.frames: List[QImage] = []
        self.import_images: List[QImage] = []
        self.geometry: Optional[SpriteSheetGeometry] = None
        self.animation_index = 0

        self.refresh_timer = QTimer(self)
        self.refresh_timer.setSingleShot(True)
        self.refresh_timer.setInterval(80)
        self.refresh_timer.timeout.connect(self.refresh_split)
        self.animation_timer = QTimer(self)
        self.animation_timer.timeout.connect(self.advance_animation)

        self.setWindowTitle("匯入 Sprite 圖")
        self.resize(1240, 820)
        self.setMinimumSize(900, 620)
        self.build_ui()
        self.update_animation_interval()

    def build_ui(self) -> None:
        self.source_label = QLabel("尚未選擇 Sprite 圖")
        self.source_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        choose_button = QPushButton("選擇 Sprite 圖")
        choose_button.clicked.connect(self.choose_sheet)

        source_row = QHBoxLayout()
        source_row.addWidget(self.source_label, 1)
        source_row.addWidget(choose_button)

        self.columns_spin = QSpinBox()
        self.columns_spin.setRange(1, 128)
        self.columns_spin.setValue(4)
        self.rows_spin = QSpinBox()
        self.rows_spin.setRange(1, 128)
        self.rows_spin.setValue(4)
        self.horizontal_spacing_spin = QSpinBox()
        self.horizontal_spacing_spin.setRange(0, 4096)
        self.vertical_spacing_spin = QSpinBox()
        self.vertical_spacing_spin.setRange(0, 4096)
        self.outer_margin_spin = QSpinBox()
        self.outer_margin_spin.setRange(0, 4096)

        settings = QFormLayout()
        settings.addRow("欄數", self.columns_spin)
        settings.addRow("列數", self.rows_spin)
        settings.addRow("左右間距 px", self.horizontal_spacing_spin)
        settings.addRow("上下間距 px", self.vertical_spacing_spin)
        settings.addRow("外圍邊距 px", self.outer_margin_spin)

        settings_panel = QWidget()
        settings_panel.setLayout(settings)
        settings_row = QHBoxLayout()
        settings_row.addWidget(settings_panel)
        self.geometry_label = QLabel("請先選擇圖片")
        self.geometry_label.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self.geometry_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        settings_row.addWidget(self.geometry_label, 1)

        for spin in (
            self.columns_spin,
            self.rows_spin,
            self.horizontal_spacing_spin,
            self.vertical_spacing_spin,
            self.outer_margin_spin,
        ):
            spin.valueChanged.connect(self.schedule_refresh)

        self.sheet_preview = ZoomImageLabel("選擇圖片後會顯示拆分格線")
        sheet_scroll = QScrollArea()
        sheet_scroll.setWidget(self.sheet_preview)
        sheet_scroll.setWidgetResizable(False)
        sheet_scroll.setAlignment(Qt.AlignmentFlag.AlignCenter)

        sheet_panel = QWidget()
        sheet_layout = QVBoxLayout(sheet_panel)
        sheet_layout.addWidget(QLabel("Sprite 圖格線預覽（Ctrl + 滾輪縮放）"))
        sheet_layout.addWidget(sheet_scroll, 1)

        self.animation_preview = ZoomImageLabel("已勾選格子的動畫預覽")
        animation_scroll = QScrollArea()
        animation_scroll.setWidget(self.animation_preview)
        animation_scroll.setWidgetResizable(False)
        animation_scroll.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.animation_progress = QSlider(Qt.Orientation.Horizontal)
        self.animation_progress.setRange(0, 0)
        self.animation_progress.sliderMoved.connect(self.seek_animation)
        self.play_button = QPushButton("播放")
        self.play_button.clicked.connect(self.toggle_animation)
        self.animation_fps_spin = QDoubleSpinBox()
        self.animation_fps_spin.setRange(0.1, 60.0)
        self.animation_fps_spin.setDecimals(2)
        self.animation_fps_spin.setValue(12.0)
        self.animation_fps_spin.setSuffix(" FPS")
        self.animation_fps_spin.valueChanged.connect(self.update_animation_interval)
        self.loop_checkbox = QCheckBox("循環播放")
        self.loop_checkbox.setChecked(True)
        self.animation_info = QLabel("0 frames")

        animation_controls = QHBoxLayout()
        animation_controls.addWidget(self.play_button)
        animation_controls.addWidget(self.animation_fps_spin)
        animation_controls.addWidget(self.loop_checkbox)
        animation_controls.addStretch(1)

        animation_panel = QWidget()
        animation_layout = QVBoxLayout(animation_panel)
        animation_layout.addWidget(QLabel("勾選格動畫預覽（Ctrl + 滾輪縮放）"))
        animation_layout.addWidget(animation_scroll, 1)
        animation_layout.addWidget(self.animation_progress)
        animation_layout.addLayout(animation_controls)
        animation_layout.addWidget(self.animation_info)

        preview_splitter = QSplitter(Qt.Orientation.Horizontal)
        preview_splitter.addWidget(sheet_panel)
        preview_splitter.addWidget(animation_panel)
        preview_splitter.setSizes([680, 500])

        self.frame_list = QListWidget()
        self.frame_list.setViewMode(QListWidget.ViewMode.IconMode)
        self.frame_list.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.frame_list.setMovement(QListWidget.Movement.Static)
        self.frame_list.setDragDropMode(QAbstractItemView.DragDropMode.NoDragDrop)
        self.frame_list.setIconSize(QSize(96, 96))
        self.frame_list.setSpacing(6)
        self.frame_list.itemChanged.connect(self.on_frame_check_changed)
        self.frame_list.currentRowChanged.connect(self.show_single_frame)

        select_all_button = QPushButton("全選")
        select_all_button.clicked.connect(lambda: self.set_all_checked(True))
        select_none_button = QPushButton("全部取消")
        select_none_button.clicked.connect(lambda: self.set_all_checked(False))
        invert_button = QPushButton("反向選取")
        invert_button.clicked.connect(self.invert_checked)
        self.selection_label = QLabel("已選擇 0 / 0 格")

        selection_controls = QHBoxLayout()
        selection_controls.addWidget(select_all_button)
        selection_controls.addWidget(select_none_button)
        selection_controls.addWidget(invert_button)
        selection_controls.addStretch(1)
        selection_controls.addWidget(self.selection_label)

        frames_panel = QWidget()
        frames_layout = QVBoxLayout(frames_panel)
        frames_layout.addWidget(QLabel("選擇要保留的格子（取消勾選會顯示灰色遮罩）"))
        frames_layout.addLayout(selection_controls)
        frames_layout.addWidget(self.frame_list, 1)

        content_splitter = QSplitter(Qt.Orientation.Vertical)
        content_splitter.addWidget(preview_splitter)
        content_splitter.addWidget(frames_panel)
        content_splitter.setSizes([500, 260])

        self.split_button = QPushButton("拆分精靈圖")
        self.split_button.setEnabled(False)
        self.split_button.clicked.connect(self.accept_split)
        close_button = QPushButton("關閉")
        close_button.clicked.connect(self.reject)
        button_row = QHBoxLayout()
        button_row.addStretch(1)
        button_row.addWidget(self.split_button)
        button_row.addWidget(close_button)

        layout = QVBoxLayout(self)
        layout.addLayout(source_row)
        layout.addLayout(settings_row)
        layout.addWidget(content_splitter, 1)
        layout.addLayout(button_row)

    def current_layout(self) -> SpriteSheetLayout:
        return SpriteSheetLayout(
            columns=self.columns_spin.value(),
            rows=self.rows_spin.value(),
            horizontal_spacing=self.horizontal_spacing_spin.value(),
            vertical_spacing=self.vertical_spacing_spin.value(),
            outer_margin=self.outer_margin_spin.value(),
        )

    def choose_sheet(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "選擇 Sprite 圖",
            str(self.initial_directory),
            self.image_filter,
        )
        if path:
            self.load_sheet(Path(path))

    def load_sheet(self, path: Path) -> bool:
        try:
            frame = frame_from_image(Path(path))
        except Exception as exc:
            QMessageBox.warning(self, "無法讀取 Sprite 圖", str(exc))
            return False
        self.source_path = Path(path)
        self.initial_directory = self.source_path.parent
        self.source_image = frame.active_layer.image.copy()
        self.source_label.setText(str(self.source_path))
        self.refresh_split(reset_checks=True)
        return True

    def schedule_refresh(self) -> None:
        if not self.source_image.isNull():
            self.refresh_timer.start()

    def refresh_split(self, reset_checks: bool = False) -> None:
        if self.source_image.isNull():
            return
        previous_checks = [
            self.frame_list.item(row).checkState() == Qt.CheckState.Checked
            for row in range(self.frame_list.count())
        ]
        try:
            layout = self.current_layout()
            geometry = calculate_sprite_geometry(self.source_image, layout)
            frames = split_spritesheet(self.source_image, layout)
        except ValueError as exc:
            self.geometry = None
            self.frames = []
            self.frame_list.clear()
            self.geometry_label.setText(f"設定無效：{exc}")
            self.split_button.setEnabled(False)
            self.update_selection_state()
            return

        self.geometry = geometry
        self.frames = frames
        checks = previous_checks if not reset_checks and len(previous_checks) == len(frames) else [True] * len(frames)
        self.populate_frame_list(checks)
        self.geometry_label.setText(
            f"來源：{self.source_image.width()} x {self.source_image.height()} px\n"
            f"單格：{geometry.cell_size.width()} x {geometry.cell_size.height()} px\n"
            f"透明補齊：右 {geometry.padding_right} px、下 {geometry.padding_bottom} px\n"
            f"拆分總數：{len(frames)} 格"
        )
        self.split_button.setEnabled(bool(frames))
        self.update_selection_state()

    def populate_frame_list(self, checks: List[bool]) -> None:
        self.frame_list.blockSignals(True)
        self.frame_list.clear()
        for index, frame in enumerate(self.frames):
            thumb = QPixmap.fromImage(image_over_checkerboard(frame)).scaled(
                96,
                96,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.FastTransformation,
            )
            item = QListWidgetItem(QIcon(thumb), str(index + 1))
            item.setData(Qt.ItemDataRole.UserRole, index)
            item.setData(SPRITE_THUMBNAIL_ROLE, thumb)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked if checks[index] else Qt.CheckState.Unchecked)
            self.frame_list.addItem(item)
            self.update_frame_item_visual(item)
        self.frame_list.blockSignals(False)
        if self.frame_list.count():
            self.frame_list.setCurrentRow(0)

    def selected_indices(self) -> List[int]:
        result: List[int] = []
        for row in range(self.frame_list.count()):
            item = self.frame_list.item(row)
            if item.checkState() == Qt.CheckState.Checked:
                result.append(int(item.data(Qt.ItemDataRole.UserRole)))
        return result

    def selected_images(self) -> List[QImage]:
        return [self.frames[index] for index in self.selected_indices()]

    def set_all_checked(self, checked: bool) -> None:
        state = Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked
        self.frame_list.blockSignals(True)
        for row in range(self.frame_list.count()):
            item = self.frame_list.item(row)
            item.setCheckState(state)
            self.update_frame_item_visual(item)
        self.frame_list.blockSignals(False)
        self.update_selection_state()

    def invert_checked(self) -> None:
        self.frame_list.blockSignals(True)
        for row in range(self.frame_list.count()):
            item = self.frame_list.item(row)
            checked = item.checkState() == Qt.CheckState.Checked
            item.setCheckState(Qt.CheckState.Unchecked if checked else Qt.CheckState.Checked)
            self.update_frame_item_visual(item)
        self.frame_list.blockSignals(False)
        self.update_selection_state()

    def on_frame_check_changed(self, item: QListWidgetItem) -> None:
        self.update_frame_item_visual(item)
        self.update_selection_state()

    def update_frame_item_visual(self, item: QListWidgetItem) -> None:
        source = item.data(SPRITE_THUMBNAIL_ROLE)
        if not isinstance(source, QPixmap) or source.isNull():
            return
        display = QPixmap(source)
        if item.checkState() != Qt.CheckState.Checked:
            painter = QPainter(display)
            painter.fillRect(display.rect(), QColor(65, 65, 65, 170))
            painter.end()
        signals_were_blocked = self.frame_list.blockSignals(True)
        try:
            item.setIcon(QIcon(display))
        finally:
            self.frame_list.blockSignals(signals_were_blocked)

    def update_selection_state(self) -> None:
        selected = self.selected_indices()
        self.selection_label.setText(f"已選擇 {len(selected)} / {len(self.frames)} 格")
        self.split_button.setEnabled(bool(selected))
        self.animation_index = min(self.animation_index, max(0, len(selected) - 1))
        self.refresh_sheet_preview()
        self.show_animation_frame(self.animation_index)

    def refresh_sheet_preview(self) -> None:
        if self.source_image.isNull() or self.geometry is None:
            return
        layout = self.current_layout()
        padded = padded_spritesheet_image(self.source_image, self.geometry)
        display = checkerboard_image(padded.size())
        painter = QPainter(display)
        painter.drawImage(0, 0, padded)
        checked = set(self.selected_indices())
        for index in range(layout.cell_count):
            rect = sprite_cell_rect(layout, self.geometry, index)
            if index not in checked:
                painter.fillRect(rect, QColor(55, 55, 55, 175))
            painter.setPen(QPen(QColor("#22d3ee"), 1))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(rect.adjusted(0, 0, -1, -1))
            badge = QRectF(rect.x() + 2, rect.y() + 2, min(42, max(18, rect.width() - 4)), 18)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(0, 0, 0, 170))
            painter.drawRect(badge)
            painter.setPen(QColor("white"))
            painter.drawText(badge, Qt.AlignmentFlag.AlignCenter, str(index + 1))
        painter.end()
        self.sheet_preview.setImage(display)

    def show_single_frame(self, row: int) -> None:
        if 0 <= row < len(self.frames):
            self.animation_preview.setImage(image_over_checkerboard(self.frames[row]))

    def toggle_animation(self) -> None:
        if not self.selected_indices():
            QMessageBox.information(self, "沒有選擇格子", "請先勾選至少一格。")
            return
        if self.animation_timer.isActive():
            self.stop_animation()
            return
        self.update_animation_interval()
        self.animation_timer.start()
        self.play_button.setText("暫停")
        self.show_animation_frame(self.animation_index)

    def stop_animation(self) -> None:
        self.animation_timer.stop()
        self.play_button.setText("播放")

    def update_animation_interval(self) -> None:
        interval = max(16, round(1000 / max(0.1, self.animation_fps_spin.value())))
        self.animation_timer.setInterval(interval)

    def seek_animation(self, value: int) -> None:
        self.animation_index = max(0, value)
        self.show_animation_frame(self.animation_index)

    def advance_animation(self) -> None:
        selected = self.selected_indices()
        if not selected:
            self.stop_animation()
            return
        self.animation_index += 1
        if self.animation_index >= len(selected):
            if self.loop_checkbox.isChecked():
                self.animation_index = 0
            else:
                self.animation_index = len(selected) - 1
                self.stop_animation()
        self.show_animation_frame(self.animation_index)

    def show_animation_frame(self, index: int) -> None:
        selected = self.selected_indices()
        if not selected:
            self.stop_animation()
            self.animation_preview.clear()
            self.animation_preview.setText("沒有已勾選格子")
            self.animation_info.setText("0 frames")
            self.animation_progress.setRange(0, 0)
            return
        self.animation_index = max(0, min(index, len(selected) - 1))
        source_index = selected[self.animation_index]
        self.animation_preview.setImage(image_over_checkerboard(self.frames[source_index]))
        self.animation_progress.blockSignals(True)
        self.animation_progress.setRange(0, len(selected) - 1)
        self.animation_progress.setValue(self.animation_index)
        self.animation_progress.blockSignals(False)
        self.animation_info.setText(
            f"{self.animation_index + 1}/{len(selected)}  "
            f"原始格 #{source_index + 1}  {self.animation_fps_spin.value():.2f} FPS"
        )

    def accept_split(self) -> None:
        selected = self.selected_images()
        if not selected:
            QMessageBox.information(self, "沒有選擇格子", "請先勾選至少一格。")
            return
        self.import_images = [image.copy() for image in selected]
        self.accept()

    def done(self, result: int) -> None:
        self.refresh_timer.stop()
        self.stop_animation()
        super().done(result)
