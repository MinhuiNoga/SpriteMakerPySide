from __future__ import annotations

from typing import Optional

from PySide6.QtCore import QRect, QSize, Qt, QTimer
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QSlider,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from .image_ops import pixel_compress_image, pixel_compression_bounds


class PixelCompressionDialog(QDialog):
    def __init__(
        self,
        source_image: QImage,
        selection_mask: Optional[QImage] = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("像素壓縮化")
        self.resize(920, 680)
        self.source_image = source_image.copy()
        self.selection_mask = selection_mask.copy() if selection_mask is not None else None
        self.region_x, self.region_y, self.region_width, self.region_height = pixel_compression_bounds(
            self.source_image,
            self.selection_mask,
        )
        self._syncing_size = False
        self._ratio_dragging = False
        self._processed_image = self.source_image.copy()
        self._original_preview = QImage()
        self._result_preview = QImage()

        scope = "目前選取區域" if self.selection_mask is not None else "目前圖層"
        self.scope_label = QLabel(f"{scope}  {self.region_width} × {self.region_height}")

        self.target_width = QSpinBox()
        self.target_width.setRange(1, max(1, self.region_width))
        self.target_width.setValue(max(1, round(self.region_width / 4)))
        self.target_width.setSuffix(" px")

        self.target_height = QSpinBox()
        self.target_height.setRange(1, max(1, self.region_height))
        self.target_height.setValue(max(1, round(self.region_height / 4)))
        self.target_height.setSuffix(" px")

        self.lock_ratio = QCheckBox("鎖定比例")
        self.lock_ratio.setChecked(True)

        self.ratio_slider = QSlider(Qt.Orientation.Horizontal)
        self.ratio_slider.setRange(2, 200)
        self.ratio_slider.setValue(50)
        self.ratio_slider.setSingleStep(1)
        self.ratio_slider.setPageStep(10)
        self.ratio_slider.setTickInterval(10)
        self.ratio_slider.setTickPosition(QSlider.TickPosition.TicksBelow)
        self.ratio_slider.setToolTip("邏輯解析度相對於作用範圍的比例；越低越像素化")
        self.ratio_value_label = QLabel()
        self.ratio_value_label.setMinimumWidth(150)
        self.ratio_value_label.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        self.update_ratio_label(25.0)

        self.mode_combo = QComboBox()
        self.mode_combo.addItem("Alpha 加權區域取樣", "area")
        self.mode_combo.addItem("區域主色", "dominant")
        self.mode_combo.addItem("最近鄰", "nearest")

        size_row = QHBoxLayout()
        size_row.addWidget(self.target_width)
        size_row.addWidget(QLabel("×"))
        size_row.addWidget(self.target_height)
        size_row.addWidget(self.lock_ratio)
        size_row.addStretch(1)
        size_widget = QWidget()
        size_widget.setLayout(size_row)

        ratio_row = QHBoxLayout()
        ratio_row.addWidget(self.ratio_slider, 1)
        ratio_row.addWidget(self.ratio_value_label)
        ratio_widget = QWidget()
        ratio_widget.setLayout(ratio_row)

        controls = QFormLayout()
        controls.addRow("作用範圍", self.scope_label)
        controls.addRow("邏輯解析度", size_widget)
        controls.addRow("輸出比例", ratio_widget)
        controls.addRow("縮小取樣", self.mode_combo)

        self.original_label = self.make_preview_label()
        self.result_label = self.make_preview_label()
        preview_row = QHBoxLayout()
        preview_row.addLayout(self.preview_column("原始", self.original_label), 1)
        preview_row.addLayout(self.preview_column("結果", self.result_label), 1)

        self.result_size_label = QLabel()

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("套用")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        buttons.accepted.connect(self.accept_processed)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(controls)
        layout.addLayout(preview_row, 1)
        layout.addWidget(self.result_size_label)
        layout.addWidget(buttons)

        self.preview_timer = QTimer(self)
        self.preview_timer.setSingleShot(True)
        self.preview_timer.timeout.connect(self.update_preview)
        self.target_width.valueChanged.connect(self.width_changed)
        self.target_height.valueChanged.connect(self.height_changed)
        self.lock_ratio.toggled.connect(self.ratio_lock_changed)
        self.ratio_slider.sliderPressed.connect(self.begin_ratio_drag)
        self.ratio_slider.sliderReleased.connect(self.end_ratio_drag)
        self.ratio_slider.valueChanged.connect(self.ratio_changed)
        self.mode_combo.currentIndexChanged.connect(self.queue_preview)
        self.update_preview()

    @staticmethod
    def make_preview_label() -> QLabel:
        label = QLabel()
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label.setMinimumSize(320, 320)
        label.setStyleSheet("background:#555; border:1px solid #222;")
        return label

    @staticmethod
    def preview_column(title: str, label: QLabel) -> QVBoxLayout:
        layout = QVBoxLayout()
        heading = QLabel(title)
        heading.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(heading)
        layout.addWidget(label, 1)
        return layout

    def ratio_changed(self, slider_value: int) -> None:
        ratio_percent = slider_value / 2.0
        ratio = ratio_percent / 100.0
        self._syncing_size = True
        self.target_width.setValue(max(1, round(self.region_width * ratio)))
        self.target_height.setValue(max(1, round(self.region_height * ratio)))
        self._syncing_size = False
        self.update_ratio_label(ratio_percent)
        if not self._ratio_dragging:
            self.queue_preview()

    def begin_ratio_drag(self) -> None:
        self._ratio_dragging = True
        self.preview_timer.stop()

    def end_ratio_drag(self) -> None:
        self._ratio_dragging = False
        self.queue_preview()

    def ratio_lock_changed(self, locked: bool) -> None:
        self.ratio_slider.setEnabled(locked)
        if locked and self.region_width > 0:
            ratio_percent = self.target_width.value() / self.region_width * 100.0
            self._syncing_size = True
            self.target_height.setValue(
                max(1, round(self.target_width.value() * self.region_height / self.region_width))
            )
            self._syncing_size = False
            self.set_ratio_indicator(ratio_percent)
        else:
            self.update_custom_ratio_label()
        self.queue_preview()

    def width_changed(self, value: int) -> None:
        if self._syncing_size:
            return
        if self.lock_ratio.isChecked() and self.region_width > 0:
            self._syncing_size = True
            self.target_height.setValue(
                max(1, round(value * self.region_height / self.region_width))
            )
            self._syncing_size = False
            self.set_ratio_indicator(value / self.region_width * 100.0)
        else:
            self.update_custom_ratio_label()
        self.queue_preview()

    def height_changed(self, value: int) -> None:
        if self._syncing_size:
            return
        if self.lock_ratio.isChecked() and self.region_height > 0:
            self._syncing_size = True
            self.target_width.setValue(
                max(1, round(value * self.region_width / self.region_height))
            )
            self._syncing_size = False
            self.set_ratio_indicator(value / self.region_height * 100.0)
        else:
            self.update_custom_ratio_label()
        self.queue_preview()

    def set_ratio_indicator(self, ratio_percent: float) -> None:
        ratio_percent = max(1.0, min(100.0, float(ratio_percent)))
        self.ratio_slider.blockSignals(True)
        self.ratio_slider.setValue(round(ratio_percent * 2.0))
        self.ratio_slider.blockSignals(False)
        self.update_ratio_label(ratio_percent)

    def update_ratio_label(self, ratio_percent: float) -> None:
        known_ratios = {50.0: "1/2", 25.0: "1/4", 12.5: "1/8"}
        fraction = known_ratios.get(round(ratio_percent, 1))
        suffix = f"（{fraction}）" if fraction else ""
        self.ratio_value_label.setText(f"{ratio_percent:.1f}%{suffix}")

    def update_custom_ratio_label(self) -> None:
        width_ratio = self.target_width.value() / max(1, self.region_width) * 100.0
        height_ratio = self.target_height.value() / max(1, self.region_height) * 100.0
        self.ratio_value_label.setText(
            f"自訂：寬 {width_ratio:.1f}% / 高 {height_ratio:.1f}%"
        )

    def queue_preview(self, *_args) -> None:
        self.preview_timer.start(80)

    def update_preview(self) -> None:
        self._processed_image = pixel_compress_image(
            self.source_image,
            self.target_width.value(),
            self.target_height.value(),
            str(self.mode_combo.currentData()),
            self.selection_mask,
        )
        bounds = QRect(
            self.region_x,
            self.region_y,
            self.region_width,
            self.region_height,
        )
        self._original_preview = self.source_image.copy(bounds)
        self._result_preview = self._processed_image.copy(bounds)
        self.result_size_label.setText(
            f"邏輯 {self.target_width.value()} × {self.target_height.value()}"
            f"  →  回放 {self.region_width} × {self.region_height}"
        )
        self.refresh_preview_pixmaps()

    def refresh_preview_pixmaps(self) -> None:
        self.set_preview_pixmap(self.original_label, self._original_preview)
        self.set_preview_pixmap(self.result_label, self._result_preview)

    @staticmethod
    def set_preview_pixmap(label: QLabel, image: QImage) -> None:
        if image.isNull():
            label.clear()
            return
        available = QSize(max(1, label.width() - 12), max(1, label.height() - 12))
        pixmap = QPixmap.fromImage(image).scaled(
            available,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.FastTransformation,
        )
        label.setPixmap(pixmap)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if hasattr(self, "original_label"):
            self.refresh_preview_pixmaps()

    def accept_processed(self) -> None:
        self.preview_timer.stop()
        self.update_preview()
        self.accept()

    def processed_image(self) -> QImage:
        return self._processed_image.copy()

    def processing_summary(self) -> str:
        ratio = (
            self.ratio_value_label.text()
            if self.lock_ratio.isChecked()
            else "自訂寬高"
        )
        return (
            f"{self.target_width.value()} × {self.target_height.value()}"
            f"（{ratio}，{self.mode_combo.currentText()}）"
        )
