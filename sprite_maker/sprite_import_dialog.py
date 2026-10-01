from __future__ import annotations

from pathlib import Path
from typing import List, Optional

from PySide6.QtCore import QEvent, QRect, QSize, Qt, QTimer
from PySide6.QtGui import QAction, QColor, QIcon, QImage, QKeySequence, QPainter, QPixmap, QWheelEvent
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QColorDialog,
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
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from .models import RGBA_FORMAT, frame_from_image
from .image_file_types import IMAGE_EXTENSIONS, IMAGE_FILE_FILTER
from .sprite_analysis import BackgroundSettings, background_mask, detect_empty_frames, detect_spritesheet
from .sprite_grid_preview import SpriteGridPreviewWidget
from .sprite_ops import (
    SpriteSheetGeometry,
    SpriteSheetLayout,
    calculate_sprite_geometry,
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
        image_filter: str = IMAGE_FILE_FILTER,
    ) -> None:
        super().__init__(parent)
        self.initial_directory = Path(initial_directory) if initial_directory else Path.home()
        self.image_filter = image_filter
        self.source_path: Optional[Path] = None
        self.source_image = QImage()
        self.frames: List[QImage] = []
        self.empty_frames: List[bool] = []
        self._mask_cache = None
        self._mask_settings = None
        self.background_color = QColor("#00ff00")
        self.import_images: List[QImage] = []
        self.geometry: Optional[SpriteSheetGeometry] = None
        self.animation_index = 0

        self.refresh_timer = QTimer(self)
        self.refresh_timer.setSingleShot(True)
        self.refresh_timer.setInterval(80)
        self.refresh_timer.timeout.connect(self.refresh_split)
        self.animation_timer = QTimer(self)
        self.animation_timer.timeout.connect(self.advance_animation)
        self._pending_drop_path = None
        self.drop_timer = QTimer(self)
        self.drop_timer.setSingleShot(True)
        self.drop_timer.timeout.connect(self.load_dropped_sheet)

        self.setWindowTitle("匯入 Sprite 圖")
        self.setWindowFlags(self.windowFlags() | Qt.WindowType.WindowMinimizeButtonHint
                            | Qt.WindowType.WindowMaximizeButtonHint | Qt.WindowType.WindowCloseButtonHint)
        self.setSizeGripEnabled(True)
        self._fullscreen_restore_state = Qt.WindowState.WindowNoState
        self.resize(1280, 820)
        self.setMinimumSize(900, 620)
        self.build_ui()
        self.enable_file_drop()
        self.fullscreen_action = QAction("全螢幕", self)
        self.fullscreen_action.setShortcut(QKeySequence("F11"))
        self.fullscreen_action.triggered.connect(self.toggle_fullscreen)
        self.addAction(self.fullscreen_action)
        # Editing a numeric field must not activate a dialog button via Enter.
        for button in self.findChildren(QPushButton):
            button.setAutoDefault(False)
        self.update_animation_interval()

    def toggle_fullscreen(self) -> None:
        if self.isFullScreen():
            self.setWindowState(self._fullscreen_restore_state)
        else:
            self._fullscreen_restore_state = (Qt.WindowState.WindowMaximized if self.isMaximized()
                                               else Qt.WindowState.WindowNoState)
            self.showFullScreen()

    def enable_file_drop(self) -> None:
        # Like the editor, intercept child surfaces so scroll areas and item
        # views cannot consume the file drop before it reaches the importer.
        for widget in [self, *self.findChildren(QWidget)]:
            widget.setAcceptDrops(True)
            widget.installEventFilter(self)

    def supported_drop_paths(self, mime_data) -> List[Path]:
        if mime_data is None or not mime_data.hasUrls():
            return []
        return [Path(url.toLocalFile()) for url in mime_data.urls()
                if url.isLocalFile() and Path(url.toLocalFile()).suffix.lower() in IMAGE_EXTENSIONS
                and Path(url.toLocalFile()).is_file()]

    def eventFilter(self, watched, event) -> bool:
        if event.type() in (QEvent.Type.DragEnter, QEvent.Type.DragMove, QEvent.Type.Drop):
            paths = self.supported_drop_paths(event.mimeData())
            if paths:
                event.acceptProposedAction()
                if event.type() == QEvent.Type.Drop:
                    self._pending_drop_path = paths[0]
                    self.drop_timer.start(0)
                return True
            event.ignore()
            return True
        return super().eventFilter(watched, event)

    def load_dropped_sheet(self) -> None:
        path = self._pending_drop_path
        self._pending_drop_path = None
        if path is not None:
            self.load_sheet(path)

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key.Key_Escape and self.isFullScreen():
            self.toggle_fullscreen()
            event.accept()
            return
        super().keyPressEvent(event)

    def build_ui(self) -> None:
        self.source_label = QLabel("選擇或拖入 Sprite 圖")
        self.source_label.setToolTip("可拖入本機圖片；多檔拖入時讀取第一張支援的圖片。")
        self.source_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.source_label.setWordWrap(True)
        choose_button = QPushButton("選擇 Sprite 圖")
        choose_button.clicked.connect(self.choose_sheet)

        source_row = QHBoxLayout()
        title = QLabel("匯入 Sprite 圖")
        title.setStyleSheet("font-size: 18px; font-weight: 700;")
        source_row.addWidget(title)
        source_row.addWidget(self.source_label, 1)
        source_row.addWidget(choose_button)
        self.settings_button = QPushButton("收合設定")
        self.settings_button.setCheckable(True)
        self.settings_button.setChecked(True)
        self.settings_button.toggled.connect(self.toggle_settings)
        source_row.addWidget(self.settings_button)

        self.columns_spin = QSpinBox()
        self.columns_spin.setRange(1, 128)
        self.columns_spin.setValue(4)
        self.rows_spin = QSpinBox()
        self.rows_spin.setRange(1, 128)
        self.rows_spin.setValue(4)
        self.horizontal_spacing_spin = QSpinBox()
        self.horizontal_spacing_spin.setRange(-4096, 4096)
        self.horizontal_spacing_spin.setToolTip("可輸入負值，使左右相鄰圖格互相重疊。")
        self.vertical_spacing_spin = QSpinBox()
        self.vertical_spacing_spin.setRange(-4096, 4096)
        self.vertical_spacing_spin.setToolTip("可輸入負值，使上下相鄰圖格互相重疊。")
        for name in ("grid_x", "grid_y", "grid_width", "grid_height"):
            spin = QSpinBox()
            spin.setRange(1 if name in ("grid_width", "grid_height") else -1000000, 1000000)
            setattr(self, name + "_spin", spin)

        settings = QFormLayout()
        settings.addRow("欄數", self.columns_spin)
        settings.addRow("列數", self.rows_spin)
        settings.addRow("Grid X", self.grid_x_spin)
        settings.addRow("Grid Y", self.grid_y_spin)
        settings.addRow("Grid Width", self.grid_width_spin)
        settings.addRow("Grid Height", self.grid_height_spin)

        advanced = QFormLayout()
        advanced.addRow(QLabel("Advanced — 原圖格間空白／重疊"))
        advanced.addRow("Separation X", self.horizontal_spacing_spin)
        advanced.addRow("Separation Y", self.vertical_spacing_spin)
        advanced_panel = QWidget()
        advanced_panel.setLayout(advanced)

        self.background_combo = QComboBox()
        for text, value in (("Transparent", "transparent"), ("Green Screen", "green"),
                            ("Blue Screen", "blue"), ("Custom Color", "custom")):
            self.background_combo.addItem(text, value)
        self.alpha_threshold_spin = QSpinBox()
        self.alpha_threshold_spin.setRange(0, 255)
        self.alpha_threshold_spin.setValue(10)
        self.background_color_button = QPushButton("#00FF00")
        self.background_color_button.clicked.connect(self.choose_background_color)
        self.tolerance_spin = QSpinBox()
        self.tolerance_spin.setRange(0, 442)
        self.tolerance_spin.setValue(20)
        self.empty_threshold_spin = QDoubleSpinBox()
        self.empty_threshold_spin.setRange(0, 100)
        self.empty_threshold_spin.setDecimals(2)
        self.empty_threshold_spin.setValue(0.10)
        self.empty_threshold_spin.setSuffix(" %")
        self.auto_detect_button = QPushButton("Auto Detect Grid")
        self.auto_detect_button.setEnabled(False)
        self.auto_detect_button.clicked.connect(self.auto_detect_grid)
        self.confidence_label = QLabel("Confidence: —")
        self.warnings_label = QLabel()
        self.warnings_label.setWordWrap(True)
        self.warnings_label.setMaximumWidth(360)
        detection = QFormLayout()
        detection.addRow("Auto Detection", self.auto_detect_button)
        detection.addRow("Background", self.background_combo)
        detection.addRow("Background Color", self.background_color_button)
        thresholds = QFormLayout()
        thresholds.addRow("Alpha Threshold", self.alpha_threshold_spin)
        thresholds.addRow("Tolerance", self.tolerance_spin)
        thresholds.addRow("Empty Threshold", self.empty_threshold_spin)
        detection_panel = QWidget()
        detection_row = QHBoxLayout(detection_panel)
        for form in (detection, thresholds):
            panel = QWidget()
            panel.setLayout(form)
            panel.setMaximumWidth(330)
            detection_row.addWidget(panel, 0, Qt.AlignmentFlag.AlignTop)
        detection_status = QVBoxLayout()
        detection_status.addWidget(self.confidence_label)
        detection_status.addWidget(self.warnings_label)
        detection_status.addStretch(1)
        detection_row.addLayout(detection_status)
        detection_row.addStretch(1)
        self.background_combo.currentIndexChanged.connect(self.background_changed)
        for spin in (self.alpha_threshold_spin, self.tolerance_spin, self.empty_threshold_spin):
            spin.valueChanged.connect(self.background_changed)
        self.background_color_button.setEnabled(False)
        self.tolerance_spin.setEnabled(False)

        settings_panel = QWidget()
        settings_panel.setLayout(settings)
        settings_row = QHBoxLayout()
        settings_row.addWidget(settings_panel)
        settings_row.addWidget(advanced_panel)
        self.geometry_label = QLabel("請先選擇圖片")
        self.geometry_label.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self.geometry_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        settings_row.addWidget(self.geometry_label, 1)
        grid_panel = QWidget()
        grid_panel.setLayout(settings_row)
        self.settings_tabs = QTabWidget()
        self.settings_tabs.setMaximumHeight(230)
        for label, panel in (("網格與間距", grid_panel), ("背景與自動辨識", detection_panel)):
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setWidget(panel)
            self.settings_tabs.addTab(scroll, label)

        for spin in (
            self.columns_spin,
            self.rows_spin,
            self.horizontal_spacing_spin,
            self.vertical_spacing_spin,
            self.grid_x_spin,
            self.grid_y_spin,
            self.grid_width_spin,
            self.grid_height_spin,
        ):
            spin.setMinimumWidth(96)
            spin.valueChanged.connect(self.schedule_refresh)

        self.sheet_preview = SpriteGridPreviewWidget()
        self.sheet_preview.gridRectChanged.connect(self.on_grid_rect_changed)
        self.sheet_preview.gridRectChangeFinished.connect(self.refresh_split)
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
        preview_splitter.setChildrenCollapsible(False)
        preview_splitter.setHandleWidth(8)
        preview_splitter.addWidget(sheet_panel)
        preview_splitter.addWidget(animation_panel)
        preview_splitter.setSizes([680, 500])
        preview_splitter.setStretchFactor(0, 1)
        preview_splitter.setStretchFactor(1, 1)

        self.frame_list = QListWidget()
        self.frame_list.setViewMode(QListWidget.ViewMode.IconMode)
        self.frame_list.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.frame_list.setMovement(QListWidget.Movement.Static)
        self.frame_list.setDragDropMode(QAbstractItemView.DragDropMode.NoDragDrop)
        self.frame_list.setIconSize(QSize(96, 96))
        self.frame_list.setMinimumHeight(80)
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

        self.content_splitter = QSplitter(Qt.Orientation.Vertical)
        self.content_splitter.setObjectName("spritePreviewHeightSplitter")
        self.content_splitter.setChildrenCollapsible(False)
        self.content_splitter.setHandleWidth(12)
        self.content_splitter.setStyleSheet(
            "QSplitter#spritePreviewHeightSplitter::handle:vertical {"
            " background: #cbd5e1; border-top: 1px solid #94a3b8;"
            " border-bottom: 1px solid #94a3b8; margin: 2px 12px; }"
            "QSplitter#spritePreviewHeightSplitter::handle:vertical:hover { background: #38bdf8; }"
        )
        self.content_splitter.addWidget(preview_splitter)
        self.content_splitter.addWidget(frames_panel)
        self.content_splitter.handle(1).setCursor(Qt.CursorShape.SplitVCursor)
        self.content_splitter.handle(1).setToolTip("上下拖曳，調整動畫／格線預覽高度")
        self.content_splitter.setSizes([350, 220])

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
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)
        layout.addLayout(source_row)
        layout.addWidget(self.settings_tabs)
        layout.addWidget(self.content_splitter, 1)
        layout.addLayout(button_row)

    def toggle_settings(self, visible: bool) -> None:
        self.settings_tabs.setVisible(visible)
        self.settings_button.setText("收合設定" if visible else "顯示設定")

    def current_layout(self) -> SpriteSheetLayout:
        return SpriteSheetLayout(
            columns=self.columns_spin.value(),
            rows=self.rows_spin.value(),
            horizontal_spacing=self.horizontal_spacing_spin.value(),
            vertical_spacing=self.vertical_spacing_spin.value(),
            grid_x=self.grid_x_spin.value(),
            grid_y=self.grid_y_spin.value(),
            grid_width=self.grid_width_spin.value(),
            grid_height=self.grid_height_spin.value(),
        )

    def _set_values(self, values) -> None:
        # Restore prior signal state, including nested callers.
        for name, value in values.items():
            if value is not None:
                spin = getattr(self, name + "_spin")
                blocked = spin.blockSignals(True)
                try:
                    spin.setValue(value)
                finally:
                    spin.blockSignals(blocked)

    def background_settings(self) -> BackgroundSettings:
        mode = self.background_combo.currentData()
        color = {"green": QColor("#00ff00"), "blue": QColor("#0000ff")}.get(mode, self.background_color)
        return BackgroundSettings("transparent" if mode == "transparent" else "color",
                                  self.alpha_threshold_spin.value(),
                                  (color.red(), color.green(), color.blue()), self.tolerance_spin.value())

    def background_changed(self) -> None:
        mode = self.background_combo.currentData()
        self.background_color_button.setEnabled(mode == "custom")
        self.tolerance_spin.setEnabled(mode != "transparent")
        settings = self.background_settings()
        self.background_color_button.setText(QColor(*settings.color).name().upper())
        self.confidence_label.setText("Confidence: —")
        self.warnings_label.clear()
        self.schedule_refresh()

    def choose_background_color(self) -> None:
        color = QColorDialog.getColor(self.background_color, self, "Background Color")
        if color.isValid():
            self.background_color = color
            self.background_changed()

    def auto_detect_grid(self) -> None:
        if self.source_image.isNull():
            return
        self.refresh_timer.stop()
        result = detect_spritesheet(self.source_image, self.background_settings())
        self._set_values({name: getattr(result, name) for name in (
            "columns", "rows", "grid_x", "grid_y", "grid_width", "grid_height",
            "horizontal_spacing", "vertical_spacing")})
        self.refresh_split(reset_checks=result.columns is not None or result.rows is not None)
        self.confidence_label.setText(f"Confidence: {result.confidence:.0%}")
        self.warnings_label.setText("\n".join(result.warnings))

    def on_grid_rect_changed(self, rect: QRect) -> None:
        self.refresh_timer.stop()
        self._set_values(dict(grid_x=rect.x(), grid_y=rect.y(),
                              grid_width=rect.width(), grid_height=rect.height()))
        self.confidence_label.setText("Confidence: —（手動調整）")

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
        self.stop_animation()
        self.animation_index = 0
        self.import_images = []
        self.source_path = Path(path)
        self.initial_directory = self.source_path.parent
        self.source_image = frame.active_layer.image.copy()
        self._mask_cache = None
        self._set_values(dict(grid_x=0, grid_y=0, grid_width=self.source_image.width(),
                              grid_height=self.source_image.height(), horizontal_spacing=0, vertical_spacing=0,
                              columns=min(self.columns_spin.value(), self.source_image.width()),
                              rows=min(self.rows_spin.value(), self.source_image.height())))
        self.sheet_preview.setImage(image_over_checkerboard(self.source_image))
        self.auto_detect_button.setEnabled(True)
        self.confidence_label.setText("Confidence: —")
        self.warnings_label.clear()
        self.source_label.setText(str(self.source_path))
        self.refresh_split(reset_checks=True)
        return True

    def schedule_refresh(self) -> None:
        if not self.source_image.isNull():
            self.confidence_label.setText("Confidence: —")
            try:
                calculate_sprite_geometry(self.source_image, self.current_layout())
                self.sheet_preview.setGrid(self.current_layout(), self.selected_indices(), ())
            except ValueError:
                self.sheet_preview.setGrid(None)
            self.split_button.setEnabled(False)
            self.refresh_timer.start()

    def refresh_split(self, reset_checks: bool = False) -> None:
        self.refresh_timer.stop()
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
            settings = self.background_settings()
            if self._mask_cache is None or self._mask_settings != settings:
                self._mask_cache = background_mask(self.source_image, settings)
                self._mask_settings = settings
            empty = detect_empty_frames(self._mask_cache,
                [sprite_cell_rect(layout, geometry, index) for index in range(layout.cell_count)],
                self.empty_threshold_spin.value() / 100)
        except ValueError as exc:
            self.geometry = None
            self.frames = []
            self.empty_frames = []
            self.sheet_preview.setGrid(None)
            self.frame_list.clear()
            self.geometry_label.setText(f"設定無效：{exc}")
            self.split_button.setEnabled(False)
            self.update_selection_state()
            return

        self.geometry = geometry
        self.frames = frames
        checks = [not value for value in empty]
        if not reset_checks and len(previous_checks) == len(frames):
            checks = [previous_checks[i] if i < len(self.empty_frames) and self.empty_frames[i] == value
                      else not value for i, value in enumerate(empty)]
        self.empty_frames = empty
        self.populate_frame_list(checks)
        self.geometry_label.setText(
            f"來源：{self.source_image.width()} x {self.source_image.height()} px\n"
            f"單格：{geometry.cell_size.width()} x {geometry.cell_size.height()} px\n"
            f"各格透明補齊合計：右 {geometry.padding_right} px、下 {geometry.padding_bottom} px\n"
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
            item = QListWidgetItem(QIcon(thumb), str(index + 1) + (" EMPTY" if self.empty_frames[index] else ""))
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
        try:
            layout = self.current_layout()
            calculate_sprite_geometry(self.source_image, layout)
        except ValueError:
            self.sheet_preview.setGrid(None)
            return
        self.sheet_preview.setGrid(layout, self.selected_indices(), self.empty_frames)

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
        if self.refresh_timer.isActive():
            self.refresh_split()
        selected = self.selected_images()
        if not selected:
            QMessageBox.information(self, "沒有選擇格子", "請先勾選至少一格。")
            return
        self.import_images = [image.copy() for image in selected]
        self.accept()

    def done(self, result: int) -> None:
        self.drop_timer.stop()
        self._pending_drop_path = None
        self.refresh_timer.stop()
        self.stop_animation()
        super().done(result)
