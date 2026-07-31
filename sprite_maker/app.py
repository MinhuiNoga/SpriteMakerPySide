from __future__ import annotations

import io
import math
import re
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

from PySide6.QtCore import QEvent, QItemSelectionModel, QRect, QRectF, QSize, Qt, QThreadPool, QTimer
from PySide6.QtGui import QAction, QActionGroup, QColor, QDragEnterEvent, QDropEvent, QIcon, QImage, QKeySequence, QPainter, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QColorDialog,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QDockWidget,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSlider,
    QAbstractItemView,
    QSpinBox,
    QStatusBar,
    QToolButton,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from .image_ops import add_outline, applyColorSpillCleanupToImageData, erase_color, qcolor_to_rgba, trim_alpha_edges
from .models import Frame, Layer, clone_image, frame_from_image, frame_from_qimage, make_blank_image
from .pixel_compression_dialog import PixelCompressionDialog
from .startup_dialog import StartupDialog
from .video_import_dialog import VideoImportDialog
from .widgets import CanvasWidget, FrameStripWidget
from .workers import UniversalEraseWorker


IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".bmp", ".webp"}
VIDEO_EXTENSIONS = {".mp4", ".mov", ".avi", ".webm", ".mkv"}


def natural_sort_key(path: Path) -> List[object]:
    return [int(part) if part.isdigit() else part.casefold() for part in re.split(r"(\d+)", path.name)]


def sort_image_paths(paths: List[Path]) -> List[Path]:
    return sorted(paths, key=natural_sort_key)


@dataclass
class ProjectState:
    frames: List[Frame]
    current_index: int


def choose_fixed_color(initial: QColor, parent: QWidget, title: str, show_alpha: bool = False) -> QColor:
    dialog = QColorDialog(initial, parent)
    dialog.setWindowTitle(title)
    dialog.setOption(QColorDialog.ColorDialogOption.DontUseNativeDialog, True)
    dialog.setOption(QColorDialog.ColorDialogOption.ShowAlphaChannel, show_alpha)

    def place_bottom_right() -> None:
        screen = None
        if parent is not None:
            window = parent.window()
            handle = window.windowHandle() if window is not None else None
            screen = handle.screen() if handle is not None else None
            if screen is None and window is not None:
                screen = QApplication.screenAt(window.mapToGlobal(window.rect().center()))
        if screen is None:
            screen = QApplication.primaryScreen()
        if screen is None:
            return

        dialog.adjustSize()
        size = dialog.size()
        hint = dialog.sizeHint()
        width = max(size.width(), hint.width())
        height = max(size.height(), hint.height())
        geometry = screen.availableGeometry()
        margin = 24
        x = max(geometry.left(), geometry.right() - width - margin)
        y = max(geometry.top(), geometry.bottom() - height - margin)
        dialog.move(x, y)

    place_bottom_right()
    QTimer.singleShot(0, place_bottom_right)
    return dialog.selectedColor() if dialog.exec() == QDialog.DialogCode.Accepted else QColor()


def build_spritesheet_image(
    frames: List[Frame],
    columns: int,
    trim_pixels: int,
    outline_pixels: int,
    outline_color: QColor,
    output_size: Optional[QSize] = None,
    trim_antialias: bool = True,
    trim_contour_smoothing: float = 1.0,
) -> QImage:
    images = []
    for frame in frames:
        image = frame.composite()
        if output_size is not None:
            center_x, center_y = frame.export_center
            image = cropped_canvas_image(image, output_size.width(), output_size.height(), center_x, center_y)
        if trim_pixels > 0:
            image = trim_alpha_edges(
                image,
                trim_pixels,
                antialias=trim_antialias,
                contour_smoothing=trim_contour_smoothing,
            )
        if outline_pixels > 0:
            image = add_outline(image, outline_color, outline_pixels)
        images.append(image)

    if not images:
        return make_blank_image(1, 1)

    columns = max(1, columns)
    width = max(img.width() for img in images)
    height = max(img.height() for img in images)
    rows = math.ceil(len(images) / columns)
    sheet = make_blank_image(width * columns, height * rows)
    painter = QPainter(sheet)
    for index, image in enumerate(images):
        x = (index % columns) * width
        y = (index // columns) * height
        painter.drawImage(x, y, image)
    painter.end()
    return sheet


def cropped_canvas_image(image: QImage, width: int, height: int, center_x: float, center_y: float) -> QImage:
    output = make_blank_image(width, height)
    source_left = round(center_x - width / 2)
    source_top = round(center_y - height / 2)
    painter = QPainter(output)
    painter.drawImage(-source_left, -source_top, image)
    painter.end()
    return output


def scaled_export_thumbnail(frame: Frame, output_size: QSize, maximum_size: QSize) -> QImage:
    output_width = max(1, output_size.width())
    output_height = max(1, output_size.height())
    scale = min(maximum_size.width() / output_width, maximum_size.height() / output_height)
    preview_width = max(1, round(output_width * scale))
    preview_height = max(1, round(output_height * scale))
    preview = make_blank_image(preview_width, preview_height)

    image = frame.composite()
    center_x, center_y = frame.export_center
    source_left = round(center_x - output_width / 2)
    source_top = round(center_y - output_height / 2)
    source_rect = QRect(source_left, source_top, output_width, output_height).intersected(image.rect())
    if source_rect.isEmpty():
        return preview

    target_rect = QRectF(
        (source_rect.left() - source_left) * scale,
        (source_rect.top() - source_top) * scale,
        source_rect.width() * scale,
        source_rect.height() * scale,
    )
    painter = QPainter(preview)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, False)
    painter.drawImage(target_rect, image, QRectF(source_rect))
    painter.end()
    return preview


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Sprite Maker PySide")
        self.resize(1440, 920)

        self.frames: List[Frame] = []
        self.current_index = 0
        self.undo_stack: List[ProjectState] = []
        self.redo_stack: List[ProjectState] = []
        self.max_history = 30
        self.thread_pool = QThreadPool.globalInstance()
        self.color = QColor("#ff0000")
        self.tool_actions = {}
        self._export_size_initialized = False
        self.last_import_directory: Optional[Path] = None
        self.layer_dock: Optional[QDockWidget] = None
        self.frame_dock: Optional[QDockWidget] = None
        self.spill_cleanup_dock: Optional[QDockWidget] = None
        self._pending_frame_selection: Optional[List[int]] = None
        self._thumb_timer = QTimer(self)
        self._thumb_timer.setSingleShot(True)
        self._thumb_timer.timeout.connect(self.refresh_thumbnails)
        self.last_spill_debug_stats: Optional[dict] = None

        self.canvas = CanvasWidget()
        self.canvas.editing_started.connect(self.push_undo)
        self.canvas.image_changed.connect(self.on_image_changed)
        self.canvas.frame_erase_requested.connect(self.run_frame_erase)
        self.canvas.universal_erase_requested.connect(self.run_universal_erase)
        self.canvas.color_sampled.connect(self.set_sampled_color)
        self.canvas.zoom_changed.connect(self.on_canvas_zoom_changed)
        self.canvas.workspace_expansion_requested.connect(self.expand_workspace)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(False)
        self.scroll.setWidget(self.canvas)
        self.setCentralWidget(self.scroll)

        self.thumbnails = FrameStripWidget()
        self.thumbnails.setViewMode(QListWidget.ViewMode.IconMode)
        self.thumbnails.setIconSize(QSize(64, 64))
        self.thumbnails.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.thumbnails.setMovement(QListWidget.Movement.Static)
        self.thumbnails.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.thumbnails.setDragDropMode(QAbstractItemView.DragDropMode.NoDragDrop)
        self.thumbnails.currentRowChanged.connect(self.set_current_frame)
        self.thumbnails.itemSelectionChanged.connect(self.update_synchronized_selection_targets)
        self.thumbnails.frames_reordered.connect(self.reorder_frames)

        self.layers = QListWidget()
        self.layers.currentRowChanged.connect(self.set_active_layer_from_list)
        self.opacity = QSlider(Qt.Orientation.Horizontal)
        self.opacity.setRange(0, 100)
        self.opacity.setValue(100)
        self.opacity.valueChanged.connect(self.set_active_layer_opacity)

        self.status = QStatusBar()
        self.setStatusBar(self.status)
        self.canvas.status_changed.connect(self.status.showMessage)
        self.status.showMessage("請匯入圖片開始")

        self.create_docks()
        self.create_toolbar()
        self.enable_file_drop()
        self.update_ui()
        self.update_canvas_extent()

    def create_toolbar(self) -> None:
        file_toolbar = self.make_toolbar("檔案", Qt.ToolBarArea.TopToolBarArea)
        file_button = QToolButton()
        file_button.setText("檔案")
        file_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        file_menu = QMenu(file_button)
        self.add_menu_action(file_menu, "匯入", self.import_images, "Ctrl+O")
        self.add_menu_action(file_menu, "插入", self.insert_images, "Ctrl+I")
        self.add_menu_action(file_menu, "清空", self.clear_project)
        self.add_menu_action(file_menu, "匯入影片", self.import_video)
        file_menu.addSeparator()
        self.add_menu_action(file_menu, "儲存單幀", self.export_current_frame, "Ctrl+S")
        self.add_menu_action(file_menu, "儲存ZIP", self.export_zip)
        file_button.setMenu(file_menu)
        file_toolbar.addWidget(file_button)

        tool_toolbar = self.make_toolbar("繪圖工具", Qt.ToolBarArea.LeftToolBarArea)
        tool_toolbar.setOrientation(Qt.Orientation.Vertical)
        tool_group = QActionGroup(self)
        tool_group.setExclusive(True)
        for label, tool, shortcut in (
            ("選取", "select", "V"),
            ("繩索", "lasso", "L"),
            ("畫筆", "pen", "B"),
            ("橡皮擦", "eraser", "E"),
            ("填色", "fill", "G"),
            ("色塊統一", "color_consolidate", None),
            ("魔術棒", "wand", "W"),
            ("單幀去色", "global_wand", "Shift+W"),
            ("全域去色", "universal_wand", "U"),
        ):
            action = self.add_action(
                tool_toolbar,
                label,
                lambda checked=False, t=tool: self.set_tool(t),
                shortcut=shortcut,
                checkable=True,
            )
            action.setActionGroup(tool_group)
            self.tool_actions[tool] = action
        self.tool_actions["pen"].setChecked(True)

        settings_toolbar = self.make_toolbar("工具設定", Qt.ToolBarArea.TopToolBarArea)
        self.color_button = QPushButton("顏色")
        self.color_button.setToolTip("目前畫筆/填色顏色")
        self.color_button.setMinimumWidth(92)
        self.color_button.clicked.connect(self.choose_color)
        settings_toolbar.addWidget(self.color_button)
        self.update_color_button()
        transparent_button = QPushButton("透明")
        transparent_button.setToolTip("將目前顏色設為完全透明")
        transparent_button.clicked.connect(self.set_transparent_color)
        settings_toolbar.addWidget(transparent_button)

        settings_toolbar.addWidget(QLabel("筆刷"))
        self.brush_spin = QSpinBox()
        self.brush_spin.setRange(1, 100)
        self.brush_spin.setValue(8)
        self.brush_spin.setToolTip("畫筆與橡皮擦大小")
        self.brush_spin.valueChanged.connect(self.set_brush_size)
        settings_toolbar.addWidget(self.brush_spin)

        settings_toolbar.addWidget(QLabel("容差"))
        self.tolerance_spin = QSpinBox()
        self.tolerance_spin.setRange(0, 255)
        self.tolerance_spin.setValue(15)
        self.tolerance_spin.setToolTip("填色、去色與色塊統一的顏色容差")
        self.tolerance_spin.valueChanged.connect(self.set_tolerance)
        settings_toolbar.addWidget(self.tolerance_spin)
        self.centerline_toggle = QCheckBox("中心線")
        self.centerline_toggle.stateChanged.connect(self.toggle_centerline)
        settings_toolbar.addWidget(self.centerline_toggle)
        self.bg_button = QPushButton("背景")
        self.bg_button.clicked.connect(self.choose_background_color)
        settings_toolbar.addWidget(self.bg_button)
        self.update_bg_button()
        self.checker_bg_toggle = QCheckBox("透明格")
        self.checker_bg_toggle.setChecked(True)
        self.checker_bg_toggle.stateChanged.connect(self.toggle_checker_background)
        settings_toolbar.addWidget(self.checker_bg_toggle)

        self.addToolBarBreak(Qt.ToolBarArea.TopToolBarArea)
        blend_toolbar = self.make_toolbar("像素融色畫筆", Qt.ToolBarArea.TopToolBarArea)
        self.pixel_blend_toggle = QCheckBox("像素融色")
        self.pixel_blend_toggle.setToolTip("只影響畫筆；讓筆畫邊緣融合附近既有像素顏色")
        blend_toolbar.addWidget(self.pixel_blend_toggle)

        blend_toolbar.addWidget(QLabel("強度"))
        self.pixel_blend_strength_spin = QSpinBox()
        self.pixel_blend_strength_spin.setRange(0, 100)
        self.pixel_blend_strength_spin.setValue(75)
        self.pixel_blend_strength_spin.setSuffix("%")
        self.pixel_blend_strength_spin.setToolTip("邊緣採用附近顏色的比例")
        blend_toolbar.addWidget(self.pixel_blend_strength_spin)

        blend_toolbar.addWidget(QLabel("邊緣"))
        self.pixel_blend_edge_spin = QSpinBox()
        self.pixel_blend_edge_spin.setRange(1, 8)
        self.pixel_blend_edge_spin.setValue(2)
        self.pixel_blend_edge_spin.setSuffix(" px")
        self.pixel_blend_edge_spin.setToolTip("筆畫外圍參與融色的寬度")
        blend_toolbar.addWidget(self.pixel_blend_edge_spin)

        blend_toolbar.addWidget(QLabel("取樣"))
        self.pixel_blend_radius_spin = QSpinBox()
        self.pixel_blend_radius_spin.setRange(1, 16)
        self.pixel_blend_radius_spin.setValue(5)
        self.pixel_blend_radius_spin.setSuffix(" px")
        self.pixel_blend_radius_spin.setToolTip("尋找附近既有顏色的半徑")
        blend_toolbar.addWidget(self.pixel_blend_radius_spin)

        self.pixel_blend_source_combo = QComboBox()
        self.pixel_blend_source_combo.addItem("目前圖層", "layer")
        self.pixel_blend_source_combo.addItem("所有可見圖層", "visible")
        self.pixel_blend_source_combo.setCurrentIndex(1)
        self.pixel_blend_source_combo.setToolTip("決定融色時從哪裡讀取鄰近顏色")
        blend_toolbar.addWidget(self.pixel_blend_source_combo)

        self.pixel_blend_transparent_toggle = QCheckBox("透明淡邊")
        self.pixel_blend_transparent_toggle.setToolTip(
            "開啟後，透明鄰近像素會降低筆畫邊緣 Alpha；關閉時透明像素不參與融色"
        )
        blend_toolbar.addWidget(self.pixel_blend_transparent_toggle)

        self.pixel_blend_setting_widgets = [
            self.pixel_blend_strength_spin,
            self.pixel_blend_edge_spin,
            self.pixel_blend_radius_spin,
            self.pixel_blend_source_combo,
            self.pixel_blend_transparent_toggle,
        ]
        self.pixel_blend_toggle.toggled.connect(self.update_pixel_blend_settings)
        self.pixel_blend_strength_spin.valueChanged.connect(self.update_pixel_blend_settings)
        self.pixel_blend_edge_spin.valueChanged.connect(self.update_pixel_blend_settings)
        self.pixel_blend_radius_spin.valueChanged.connect(self.update_pixel_blend_settings)
        self.pixel_blend_source_combo.currentIndexChanged.connect(self.update_pixel_blend_settings)
        self.pixel_blend_transparent_toggle.toggled.connect(self.update_pixel_blend_settings)
        self.update_pixel_blend_settings()

        edit_toolbar = self.make_toolbar("編輯與影格", Qt.ToolBarArea.TopToolBarArea)
        self.add_action(edit_toolbar, "復原", self.undo, "Ctrl+Z")
        self.add_action(edit_toolbar, "重做", self.redo, "Ctrl+Shift+Z")
        self.add_action(edit_toolbar, "複製", self.copy_selection, "Ctrl+C")
        self.add_action(edit_toolbar, "剪下", self.cut_selection, "Ctrl+X")
        self.add_action(edit_toolbar, "貼上", self.paste_selection, "Ctrl+V")
        self.add_action(edit_toolbar, "旋轉90", lambda: self.canvas.rotate_floating_selection(90), "R")
        self.add_action(edit_toolbar, "水平翻轉", lambda: self.canvas.flip_floating_selection(True), "H")
        self.add_action(edit_toolbar, "垂直翻轉", lambda: self.canvas.flip_floating_selection(False), "Shift+H")
        self.add_action(edit_toolbar, "刪除選取", self.delete_selected_or_frame, "Del")
        self.add_action(edit_toolbar, "像素壓縮化", self.show_pixel_compression)
        edit_toolbar.addSeparator()
        edit_toolbar.addWidget(QLabel("變形品質"))
        self.transform_quality_combo = QComboBox()
        self.transform_quality_combo.addItem("平滑", "smooth")
        self.transform_quality_combo.addItem("像素銳利", "pixel")
        self.transform_quality_combo.setToolTip(
            "平滑：縮放與旋轉使用插值以減少撕裂；像素銳利：保留 nearest-neighbor 像素邊緣"
        )
        self.transform_quality_combo.currentIndexChanged.connect(self.update_transform_quality)
        edit_toolbar.addWidget(self.transform_quality_combo)
        self.update_transform_quality()

        self.addToolBarBreak(Qt.ToolBarArea.TopToolBarArea)
        output_toolbar = self.make_toolbar("輸出與視窗", Qt.ToolBarArea.TopToolBarArea)
        self.add_action(output_toolbar, "Spritesheet", self.export_spritesheet)
        self.add_action(output_toolbar, "動畫預覽", self.show_animation_preview)
        output_toolbar.addSeparator()
        output_toolbar.addWidget(QLabel("輸出W"))
        self.export_width_spin = QSpinBox()
        self.export_width_spin.setRange(1, 12000)
        self.export_width_spin.setValue(64)
        self.export_width_spin.valueChanged.connect(self.update_export_preview_size)
        output_toolbar.addWidget(self.export_width_spin)
        output_toolbar.addWidget(QLabel("H"))
        self.export_height_spin = QSpinBox()
        self.export_height_spin.setRange(1, 12000)
        self.export_height_spin.setValue(64)
        self.export_height_spin.valueChanged.connect(self.update_export_preview_size)
        output_toolbar.addWidget(self.export_height_spin)
        self.add_action(output_toolbar, "目前尺寸", self.set_export_size_from_current)
        output_toolbar.addSeparator()
        self.add_action(output_toolbar, "圖層視窗", self.show_layer_dock)
        self.add_action(output_toolbar, "影格視窗", self.show_frame_dock)
        self.add_action(output_toolbar, "融色面板", self.show_spill_cleanup_dock)
        output_toolbar.addSeparator()
        self.add_action(output_toolbar, "縮放+", lambda: self.canvas.set_zoom(self.canvas.zoom + 0.25), "Ctrl++")
        self.add_action(output_toolbar, "縮放-", lambda: self.canvas.set_zoom(self.canvas.zoom - 0.25), "Ctrl+-")
        self.add_action(output_toolbar, "1:1", lambda: self.canvas.set_zoom(1.0), "Ctrl+0")

    def make_toolbar(self, title: str, area: Qt.ToolBarArea) -> QToolBar:
        toolbar = QToolBar(title)
        toolbar.setMovable(False)
        toolbar.setIconSize(QSize(18, 18))
        self.addToolBar(area, toolbar)
        return toolbar

    def create_docks(self) -> None:
        self.frame_dock = QDockWidget("影格", self)
        self.frame_dock.setObjectName("frameDock")
        frame_panel = QWidget()
        frame_layout = QVBoxLayout(frame_panel)
        frame_row = QHBoxLayout()
        for label, slot in (
            ("上一幀", self.prev_frame),
            ("下一幀", self.next_frame),
            ("複製幀", self.duplicate_frame),
            ("刪除幀", self.delete_frame),
        ):
            btn = QPushButton(label)
            btn.clicked.connect(slot)
            frame_row.addWidget(btn)
        self.sync_selection_toggle = QCheckBox("範圍選取框")
        self.sync_selection_toggle.setToolTip(
            "開啟後，選取框的移動、縮放、旋轉、翻轉與刪除會同步套用；"
            "作用範圍只包含影格列目前選取的 frame"
        )
        self.sync_selection_toggle.toggled.connect(self.toggle_synchronized_selection)
        frame_row.addWidget(self.sync_selection_toggle)
        frame_row.addStretch(1)
        frame_layout.addLayout(frame_row)
        selection_hint = QLabel("Shift + 點擊兩個 frame：選取包含端點的連續區間；拖曳可整組重新排序")
        selection_hint.setStyleSheet("color:#555;")
        frame_layout.addWidget(selection_hint)
        self.sync_selection_status = QLabel("範圍選取框：關閉")
        frame_layout.addWidget(self.sync_selection_status)
        frame_layout.addWidget(self.thumbnails)
        self.frame_dock.setWidget(frame_panel)
        self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, self.frame_dock)

        layer_panel = QWidget()
        layout = QVBoxLayout(layer_panel)
        row = QHBoxLayout()
        for label, slot in (
            ("新增", self.add_layer),
            ("複製", self.duplicate_layer),
            ("刪除", self.delete_layer),
            ("上移", lambda: self.move_layer(1)),
            ("下移", lambda: self.move_layer(-1)),
            ("顯/隱", self.toggle_layer_visibility),
        ):
            btn = QPushButton(label)
            btn.clicked.connect(slot)
            row.addWidget(btn)
        layout.addLayout(row)
        layout.addWidget(QLabel("透明度"))
        self.opacity.sliderPressed.connect(self.push_undo)
        layout.addWidget(self.opacity)
        layout.addWidget(self.layers)

        self.layer_dock = QDockWidget("圖層", self)
        self.layer_dock.setObjectName("layerDock")
        self.layer_dock.setWidget(layer_panel)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.layer_dock)

        spill_panel = QWidget()
        spill_layout = QFormLayout(spill_panel)
        self.spill_color_label = QLabel()
        self.spill_color_label.setToolTip("沿用工具列目前選取顏色，不另外建立色票")
        spill_layout.addRow("參考色", self.spill_color_label)
        self.spill_tolerance_label = QLabel()
        self.spill_tolerance_label.setToolTip("沿用工具列既有容差設定")
        spill_layout.addRow("容差", self.spill_tolerance_label)

        self.spill_strength_spin = QDoubleSpinBox()
        self.spill_strength_spin.setRange(0.0, 1.0)
        self.spill_strength_spin.setSingleStep(0.05)
        self.spill_strength_spin.setDecimals(2)
        self.spill_strength_spin.setValue(0.8)
        spill_layout.addRow("修復強度", self.spill_strength_spin)

        self.spill_edge_width_spin = QSpinBox()
        self.spill_edge_width_spin.setRange(1, 10)
        self.spill_edge_width_spin.setValue(3)
        spill_layout.addRow("邊緣寬度 px", self.spill_edge_width_spin)

        self.spill_erode_spin = QSpinBox()
        self.spill_erode_spin.setRange(0, 3)
        self.spill_erode_spin.setValue(0)
        spill_layout.addRow("Alpha 收縮 px", self.spill_erode_spin)

        self.spill_feather_spin = QSpinBox()
        self.spill_feather_spin.setRange(0, 3)
        self.spill_feather_spin.setValue(0)
        spill_layout.addRow("邊緣柔化 px", self.spill_feather_spin)

        self.spill_bleed_toggle = QCheckBox("啟用邊緣補色")
        self.spill_bleed_toggle.setChecked(True)
        spill_layout.addRow("", self.spill_bleed_toggle)

        self.spill_scope_combo = QComboBox()
        self.spill_scope_combo.addItem("目前選取圖層", "layer")
        self.spill_scope_combo.addItem("目前幀所有圖層", "frame")
        self.spill_scope_combo.addItem("所有幀所有圖層", "all")
        spill_layout.addRow("套用範圍", self.spill_scope_combo)

        spill_hint = QLabel("使用目前選取顏色作為殘邊污染色")
        spill_hint.setWordWrap(True)
        spill_layout.addRow("", spill_hint)

        spill_button = QPushButton("套用邊緣融色修復")
        spill_button.clicked.connect(self.apply_color_spill_cleanup)
        spill_layout.addRow("", spill_button)

        self.spill_debug_overlay_toggle = QCheckBox("顯示 Debug Overlay")
        spill_layout.addRow("Debug", self.spill_debug_overlay_toggle)
        self.spill_debug_overlay_combo = QComboBox()
        for label, value in (
            ("innerEdgeBand", "innerEdgeBand"),
            ("outerPaddingBand", "outerPaddingBand"),
            ("semiTransparentBand", "semiTransparentBand"),
            ("contaminatedMask", "contaminatedMask"),
            ("lookupFallback", "lookupFallback"),
            ("actualChangedPixels", "actualChangedPixels"),
            ("allDebugMasks", "allDebugMasks"),
        ):
            self.spill_debug_overlay_combo.addItem(label, value)
        spill_layout.addRow("Overlay 類型", self.spill_debug_overlay_combo)
        self.spill_test_paint_toggle = QCheckBox("污染像素測試塗色")
        self.spill_test_paint_toggle.setToolTip("命中的 contaminatedMask 會直接變成亮紅色，Alpha 保持原值")
        spill_layout.addRow("", self.spill_test_paint_toggle)
        self.spill_detect_only_toggle = QCheckBox("只執行偵測，不套用修復")
        spill_layout.addRow("", self.spill_detect_only_toggle)
        stats_button = QPushButton("輸出本次修復統計到 console")
        stats_button.clicked.connect(self.print_last_spill_debug_stats)
        spill_layout.addRow("", stats_button)

        self.spill_cleanup_dock = QDockWidget("邊緣融色修復", self)
        self.spill_cleanup_dock.setObjectName("spillCleanupDock")
        self.spill_cleanup_dock.setWidget(spill_panel)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.spill_cleanup_dock)
        self.tabifyDockWidget(self.layer_dock, self.spill_cleanup_dock)
        self.layer_dock.hide()
        self.spill_cleanup_dock.hide()
        self.frame_dock.show()
        self.frame_dock.raise_()
        self.update_spill_cleanup_labels()

    def add_action(self, toolbar: QToolBar, label: str, slot, shortcut: Optional[str] = None, checkable: bool = False) -> QAction:
        action = QAction(label, self)
        action.setCheckable(checkable)
        if shortcut:
            action.setShortcut(QKeySequence(shortcut))
            action.setShortcutContext(Qt.ShortcutContext.ApplicationShortcut)
        action.triggered.connect(slot)
        toolbar.addAction(action)
        return action

    def add_menu_action(self, menu: QMenu, label: str, slot, shortcut: Optional[str] = None) -> QAction:
        action = QAction(label, self)
        if shortcut:
            action.setShortcut(QKeySequence(shortcut))
            action.setShortcutContext(Qt.ShortcutContext.ApplicationShortcut)
            self.addAction(action)
        action.triggered.connect(slot)
        menu.addAction(action)
        return action

    def show_layer_dock(self) -> None:
        if self.layer_dock is not None:
            self.layer_dock.show()
            self.layer_dock.raise_()

    def show_frame_dock(self) -> None:
        if self.frame_dock is not None:
            self.frame_dock.show()
            self.frame_dock.raise_()

    def show_spill_cleanup_dock(self) -> None:
        if self.spill_cleanup_dock is not None:
            self.spill_cleanup_dock.show()
            self.spill_cleanup_dock.raise_()
            self.update_spill_cleanup_labels()

    def enable_file_drop(self) -> None:
        widgets = [
            self,
            self.scroll,
            self.scroll.viewport(),
            self.canvas,
            self.thumbnails,
            self.layers,
        ]
        for widget in widgets:
            widget.setAcceptDrops(True)
            widget.installEventFilter(self)

    def eventFilter(self, watched, event) -> bool:
        if event.type() in (QEvent.Type.DragEnter, QEvent.Type.DragMove):
            if self.is_supported_file_drop(event):
                event.acceptProposedAction()
                return True
        if event.type() == QEvent.Type.Drop:
            paths = self.paths_from_drop_event(event)
            if paths:
                event.acceptProposedAction()
                self.queue_dropped_files(paths)
                return True
        return super().eventFilter(watched, event)

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if self.is_supported_file_drop(event):
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dragMoveEvent(self, event) -> None:
        if self.is_supported_file_drop(event):
            event.acceptProposedAction()
        else:
            super().dragMoveEvent(event)

    def dropEvent(self, event: QDropEvent) -> None:
        paths = self.paths_from_drop_event(event)
        if paths:
            event.acceptProposedAction()
            self.queue_dropped_files(paths)
            return
        super().dropEvent(event)

    def is_supported_file_drop(self, event) -> bool:
        return bool(self.supported_drop_paths(event.mimeData()))

    def paths_from_drop_event(self, event) -> List[Path]:
        return self.supported_drop_paths(event.mimeData())

    def supported_drop_paths(self, mime_data) -> List[Path]:
        if mime_data is None or not mime_data.hasUrls():
            return []
        paths: List[Path] = []
        for url in mime_data.urls():
            if not url.isLocalFile():
                continue
            path = Path(url.toLocalFile())
            if path.suffix.lower() in IMAGE_EXTENSIONS | VIDEO_EXTENSIONS:
                paths.append(path)
        return paths

    def handle_dropped_files(self, paths: List[Path]) -> None:
        image_paths = [path for path in paths if path.suffix.lower() in IMAGE_EXTENSIONS]
        video_paths = [path for path in paths if path.suffix.lower() in VIDEO_EXTENSIONS]
        if image_paths:
            self.append_image_frames(image_paths)
        for video_path in video_paths:
            self.import_video_from_path(video_path)

    def queue_dropped_files(self, paths: List[Path]) -> None:
        queued_paths = list(paths)
        if queued_paths:
            QTimer.singleShot(0, lambda: self.handle_dropped_files(queued_paths))

    @property
    def current_frame(self) -> Optional[Frame]:
        if not self.frames:
            return None
        self.current_index = max(0, min(self.current_index, len(self.frames) - 1))
        return self.frames[self.current_index]

    def import_images(self) -> None:
        paths = self.pick_images()
        if not paths:
            return
        self.frames = self.load_frames(paths)
        self.current_index = 0
        self.undo_stack.clear()
        self.redo_stack.clear()
        self._export_size_initialized = False
        self.after_project_changed("載入完成")

    def insert_images(self) -> None:
        paths = self.pick_images()
        if not paths:
            return
        new_frames = self.load_frames(paths)
        if new_frames and self.frames:
            self.push_undo()
        if not self.frames:
            self.frames = new_frames
            self.current_index = 0
        else:
            insert_at = self.current_index + 1
            self.frames[insert_at:insert_at] = new_frames
            self.current_index = insert_at
        self.after_project_changed("已插入影格")

    def import_video(self) -> None:
        if not self.confirm_video_import_switch():
            return
        dialog = VideoImportDialog(
            self,
            show_switch_button=True,
            initial_directory=self.default_file_dialog_directory(),
        )
        self.reset_editor_for_video_import(dialog)
        self.run_video_import_dialog(dialog, editor_mode_switch=True)

    def import_video_from_path(self, path: Path) -> None:
        if not self.confirm_video_import_switch():
            return
        dialog = VideoImportDialog(self, show_switch_button=True, initial_directory=path.parent)
        if not dialog.load_video(path):
            return
        self.reset_editor_for_video_import(dialog)
        self.run_video_import_dialog(dialog, editor_mode_switch=True)

    def confirm_video_import_switch(self) -> bool:
        answer = QMessageBox.warning(
            self,
            "切換到匯入影片",
            "切換後會關閉目前編輯模式，並初始化所有 frame、圖層與復原/重做紀錄。\n"
            "尚未儲存的編輯內容將會遺失。是否繼續？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        return answer == QMessageBox.StandardButton.Yes

    def close_editor_auxiliary_windows(self, exclude_dialog: Optional[QDialog] = None) -> None:
        for dock in (self.frame_dock, self.layer_dock, self.spill_cleanup_dock):
            if dock is not None:
                dock.close()
        for dialog in self.findChildren(QDialog):
            if dialog is not exclude_dialog:
                dialog.close()

    def reset_editor_for_video_import(self, exclude_dialog: Optional[QDialog] = None) -> None:
        self.close_editor_auxiliary_windows(exclude_dialog)
        self.frames.clear()
        self.current_index = 0
        self.undo_stack.clear()
        self.redo_stack.clear()
        self._export_size_initialized = False
        self.last_spill_debug_stats = None
        self.canvas.clipboard_image = None
        self.canvas.set_debug_overlay(None)
        self.after_project_changed("已初始化編輯模式")

    def run_video_import_dialog(self, dialog: VideoImportDialog, editor_mode_switch: bool = False) -> None:
        if editor_mode_switch:
            self.hide()
        try:
            result = dialog.exec()
            if result != QDialog.DialogCode.Accepted:
                return
            if dialog.video_path is not None:
                self.remember_import_path(dialog.video_path)
            if dialog.switch_to_editor:
                return
            self.add_video_frames(dialog.import_images)
        finally:
            if editor_mode_switch:
                self.show()
                self.raise_()
                self.activateWindow()

    def append_image_frames(self, paths: List[Path]) -> None:
        new_frames = self.load_frames(paths)
        if not new_frames:
            return
        self.remember_import_path(sort_image_paths(paths)[-1])
        if self.frames:
            self.push_undo()
            insert_at = len(self.frames)
            self.frames.extend(new_frames)
            self.current_index = insert_at
        else:
            self.frames = new_frames
            self.current_index = 0
            self.undo_stack.clear()
            self.redo_stack.clear()
            self._export_size_initialized = False
        self.after_project_changed(f"已拖放匯入 {len(new_frames)} 張圖片")

    def add_video_frames(self, images: List[QImage]) -> None:
        if not images:
            return
        new_frames = [frame_from_qimage(image, f"video_frame_{index:04d}.png") for index, image in enumerate(images, 1)]
        if self.frames:
            self.push_undo()
            insert_at = len(self.frames)
            self.frames.extend(new_frames)
            self.current_index = insert_at
        else:
            self.frames = new_frames
            self.current_index = 0
            self.undo_stack.clear()
            self.redo_stack.clear()
            self._export_size_initialized = False
        self.after_project_changed(f"已匯入 {len(new_frames)} 張影片影格")

    def pick_images(self) -> List[Path]:
        files, _ = QFileDialog.getOpenFileNames(
            self,
            "選擇圖片",
            str(self.default_file_dialog_directory()),
            "Images (*.png *.jpg *.jpeg *.bmp *.webp)",
        )
        paths = [Path(file) for file in files]
        if paths:
            self.remember_import_path(paths[-1])
        return paths

    def remember_import_path(self, path: Path) -> None:
        source = Path(path)
        self.last_import_directory = source if source.is_dir() else source.parent

    def default_file_dialog_directory(self) -> Path:
        return self.last_import_directory or Path.home()

    def default_export_path(self, filename: str) -> str:
        return str(self.default_file_dialog_directory() / filename)

    def load_frames(self, paths: List[Path]) -> List[Frame]:
        frames = []
        for path in sort_image_paths(paths):
            try:
                frames.append(frame_from_image(path))
            except ValueError as exc:
                QMessageBox.warning(self, "讀取失敗", str(exc))
        return frames

    def set_current_frame(self, index: int) -> None:
        if index < 0 or index >= len(self.frames) or index == self.current_index:
            self.update_synchronized_selection_targets()
            return
        self.canvas.commit_floating_selection()
        self.current_index = index
        self.canvas.set_frame(self.current_frame)
        self.update_synchronized_selection_targets()
        self.update_canvas_extent()
        self.refresh_layers()
        self.update_ui()

    def selected_frame_rows(self) -> List[int]:
        return sorted({index.row() for index in self.thumbnails.selectedIndexes() if 0 <= index.row() < len(self.frames)})

    def toggle_synchronized_selection(self, enabled: bool) -> None:
        self.canvas.commit_floating_selection()
        if enabled:
            self.set_tool("select")
        self.update_synchronized_selection_targets()
        self.status.showMessage("已開啟範圍選取框" if enabled else "已關閉範圍選取框")

    def update_synchronized_selection_targets(self) -> None:
        if not hasattr(self, "sync_selection_toggle"):
            return
        selected_rows = self.selected_frame_rows()
        if not self.sync_selection_toggle.isChecked() or not self.frames:
            self.canvas.set_batch_selection_frames([], active=False)
            self.sync_selection_status.setText("範圍選取框：關閉")
            return
        targets = [self.frames[row] for row in selected_rows]
        if len(selected_rows) > 1:
            self.sync_selection_status.setText(
                f"範圍選取框：已選 {len(targets)} 幀（{selected_rows[0] + 1} - {selected_rows[-1] + 1}）"
            )
        elif selected_rows:
            self.sync_selection_status.setText(f"範圍選取框：第 {selected_rows[0] + 1} 幀")
        else:
            self.sync_selection_status.setText("範圍選取框：尚未選取 frame")
        self.canvas.set_batch_selection_frames(targets, active=True)

    def reorder_frames(self, rows: object, drop_row: int) -> None:
        valid_rows = sorted({int(row) for row in rows if 0 <= int(row) < len(self.frames)}) if isinstance(rows, (list, tuple, set)) else []
        if not self.frames or not valid_rows:
            return
        self.canvas.commit_floating_selection()
        drop_row = max(0, min(int(drop_row), len(self.frames)))
        moving_frames = [self.frames[row] for row in valid_rows]
        moving_row_set = set(valid_rows)
        remaining_frames = [frame for index, frame in enumerate(self.frames) if index not in moving_row_set]
        insert_at = drop_row - sum(1 for row in valid_rows if row < drop_row)
        insert_at = max(0, min(insert_at, len(remaining_frames)))
        reordered = remaining_frames[:insert_at] + moving_frames + remaining_frames[insert_at:]
        if all(before is after for before, after in zip(self.frames, reordered)):
            return
        current_frame = self.current_frame
        self.push_undo()
        self.frames = reordered
        if current_frame is not None:
            self.current_index = next(index for index, frame in enumerate(self.frames) if frame is current_frame)
        self._pending_frame_selection = list(range(insert_at, insert_at + len(moving_frames)))
        self.after_project_changed(f"已移動 {len(moving_frames)} 個影格")

    def reorder_frame(self, old: int, new: int) -> None:
        drop_row = new if new < old else new + 1
        self.reorder_frames([old], drop_row)

    def prev_frame(self) -> None:
        if self.current_index > 0:
            self.thumbnails.setCurrentRow(self.current_index - 1)

    def next_frame(self) -> None:
        if self.current_index < len(self.frames) - 1:
            self.thumbnails.setCurrentRow(self.current_index + 1)

    def duplicate_frame(self) -> None:
        frame = self.current_frame
        if not frame:
            return
        self.push_undo()
        copy = frame.clone()
        copy.name = self.copy_name(copy.name)
        self.frames.insert(self.current_index + 1, copy)
        self.current_index += 1
        self.after_project_changed("已複製影格")

    def delete_frame(self) -> None:
        if not self.frames:
            return
        selected_rows = self.selected_frame_rows()
        rows = selected_rows or [self.current_index]
        rows = sorted({row for row in rows if 0 <= row < len(self.frames)})
        if not rows:
            return
        self.canvas.commit_floating_selection()
        self.push_undo()
        row_set = set(rows)
        self.frames = [frame for index, frame in enumerate(self.frames) if index not in row_set]
        self.current_index = min(rows[0], len(self.frames) - 1) if self.frames else 0
        self._pending_frame_selection = [self.current_index] if self.frames else []
        if not self.frames:
            self._export_size_initialized = False
        count = len(rows)
        self.after_project_changed(f"已刪除 {count} 個影格" if count > 1 else "已刪除影格")

    def clear_project(self) -> None:
        if self.frames and QMessageBox.question(self, "清空", "確定清空所有影格？") != QMessageBox.StandardButton.Yes:
            return
        if self.frames:
            self.push_undo()
        self.frames.clear()
        self.current_index = 0
        self._export_size_initialized = False
        self.after_project_changed("已清空")

    def add_layer(self) -> None:
        frame = self.current_frame
        if not frame:
            return
        self.push_undo()
        layer = Layer(f"透明圖層 {len(frame.layers) + 1}", make_blank_image(frame.width, frame.height))
        frame.layers.insert(frame.active_layer_index + 1, layer)
        frame.active_layer_index += 1
        frame.mark_dirty()
        self.on_image_changed("已新增圖層")

    def duplicate_layer(self) -> None:
        frame = self.current_frame
        if not frame:
            return
        self.push_undo()
        layer = frame.active_layer.clone()
        layer.name = self.copy_name(layer.name)
        frame.layers.insert(frame.active_layer_index + 1, layer)
        frame.active_layer_index += 1
        frame.mark_dirty()
        self.on_image_changed("已複製圖層")

    def delete_layer(self) -> None:
        frame = self.current_frame
        if not frame or len(frame.layers) <= 1:
            return
        self.push_undo()
        del frame.layers[frame.active_layer_index]
        frame.active_layer_index = max(0, frame.active_layer_index - 1)
        frame.mark_dirty()
        self.on_image_changed("已刪除圖層")

    def move_layer(self, delta: int) -> None:
        frame = self.current_frame
        if not frame:
            return
        old = frame.active_layer_index
        new = old + delta
        if new < 0 or new >= len(frame.layers):
            return
        self.push_undo()
        frame.layers[old], frame.layers[new] = frame.layers[new], frame.layers[old]
        frame.active_layer_index = new
        frame.mark_dirty()
        self.on_image_changed("已移動圖層")

    def toggle_layer_visibility(self) -> None:
        frame = self.current_frame
        if not frame:
            return
        self.push_undo()
        frame.active_layer.visible = not frame.active_layer.visible
        frame.mark_dirty()
        self.on_image_changed("已切換圖層顯示")

    def set_active_layer_from_list(self, row: int) -> None:
        frame = self.current_frame
        if not frame or row < 0:
            return
        item = self.layers.item(row)
        if not item:
            return
        index = item.data(Qt.ItemDataRole.UserRole)
        if index is None or index == frame.active_layer_index:
            return
        self.canvas.cancel_color_consolidation(emit_status=False)
        frame.active_layer_index = index
        self.opacity.blockSignals(True)
        self.opacity.setValue(round(frame.active_layer.opacity * 100))
        self.opacity.blockSignals(False)
        self.canvas.update()
        self.status.showMessage(f"已切換到：{frame.active_layer.name}")

    def set_active_layer_opacity(self, value: int) -> None:
        frame = self.current_frame
        if not frame:
            return
        frame.active_layer.opacity = value / 100.0
        frame.mark_dirty()
        self.on_image_changed(f"透明度：{value}%")

    def set_tool(self, tool: str) -> None:
        self.canvas.set_tool(tool)
        if tool in self.tool_actions:
            self.tool_actions[tool].setChecked(True)

    def choose_color(self) -> None:
        color = choose_fixed_color(self.color, self, "選擇顏色", show_alpha=True)
        if color.isValid():
            self.color = color
            self.canvas.color = color
            self.update_color_button()

    def set_transparent_color(self) -> None:
        self.color = QColor(0, 0, 0, 0)
        self.canvas.color = self.color
        self.update_color_button()
        self.status.showMessage("目前顏色已設為透明")

    def set_sampled_color(self, color: QColor) -> None:
        self.color = QColor(color)
        self.canvas.color = QColor(color)
        self.update_color_button()

    def update_color_button(self) -> None:
        text_color = "#000000" if self.color.lightness() > 140 else "#ffffff"
        alpha = self.color.alpha()
        self.color_button.setText(f"{self.color.name().upper()} / {alpha}")
        self.color_button.setToolTip(f"目前顏色：{self.color.name().upper()}，透明度 Alpha={alpha}")
        background = self.color.name(QColor.NameFormat.HexArgb) if alpha < 255 else self.color.name()
        self.color_button.setStyleSheet(
            f"QPushButton {{ background: {background}; color: {text_color}; "
            "border: 2px solid #222; padding: 4px 10px; font-weight: 700; }}"
        )
        self.update_spill_cleanup_labels()

    def set_brush_size(self, value: int) -> None:
        self.canvas.brush_size = value

    def update_transform_quality(self) -> None:
        smooth = self.transform_quality_combo.currentData() == "smooth"
        self.canvas.smooth_selection_transform = smooth
        self.canvas.update()
        self.status.showMessage("變形品質：平滑" if smooth else "變形品質：像素銳利")

    def update_pixel_blend_settings(self) -> None:
        enabled = self.pixel_blend_toggle.isChecked()
        self.canvas.pixel_blend_enabled = enabled
        self.canvas.pixel_blend_strength = self.pixel_blend_strength_spin.value() / 100.0
        self.canvas.pixel_blend_edge_width = self.pixel_blend_edge_spin.value()
        self.canvas.pixel_blend_sample_radius = self.pixel_blend_radius_spin.value()
        self.canvas.pixel_blend_sample_visible_layers = (
            self.pixel_blend_source_combo.currentData() == "visible"
        )
        self.canvas.pixel_blend_include_transparent = self.pixel_blend_transparent_toggle.isChecked()
        for widget in self.pixel_blend_setting_widgets:
            widget.setEnabled(enabled)
        self.canvas.update()
        if enabled:
            self.status.showMessage(
                "像素融色畫筆："
                f"強度 {self.pixel_blend_strength_spin.value()}%、"
                f"邊緣 {self.pixel_blend_edge_spin.value()}px、"
                f"取樣 {self.pixel_blend_radius_spin.value()}px"
            )

    def set_tolerance(self, value: int) -> None:
        self.canvas.set_tolerance(value)
        self.update_spill_cleanup_labels()

    def update_spill_cleanup_labels(self) -> None:
        if not hasattr(self, "spill_color_label"):
            return
        alpha = self.color.alpha()
        self.spill_color_label.setText(f"{self.color.name().upper()} / Alpha {alpha}")
        self.spill_tolerance_label.setText(f"{self.canvas.tolerance}")

    def spill_cleanup_options(self) -> dict:
        options = {
            "spillColor": QColor(self.color),
            "colorTolerance": self.canvas.tolerance,
            "despillStrength": self.spill_strength_spin.value(),
            "edgeWidth": self.spill_edge_width_spin.value(),
            "erodePixels": self.spill_erode_spin.value(),
            "feather": self.spill_feather_spin.value(),
            "enableColorBleeding": self.spill_bleed_toggle.isChecked(),
            "alphaThreshold": 8,
            "semiTransparentThreshold": 128,
            "processTransparentPadding": True,
            "returnDebugData": True,
            "debugOverlayMode": self.spill_debug_overlay_combo.currentData() if hasattr(self, "spill_debug_overlay_combo") else "allDebugMasks",
            "testPaintContaminated": self.spill_test_paint_toggle.isChecked() if hasattr(self, "spill_test_paint_toggle") else False,
            "detectOnly": self.spill_detect_only_toggle.isChecked() if hasattr(self, "spill_detect_only_toggle") else False,
        }
        selection_mask = self.canvas.selection_mask_image()
        if selection_mask is not None:
            options["selectionMask"] = selection_mask
        return options

    def apply_color_spill_cleanup(self) -> None:
        frame = self.current_frame
        if not frame:
            QMessageBox.information(self, "邊緣融色修復", "請先選取要修復的圖片物件")
            return

        scope = self.spill_scope_combo.currentData()
        options = self.spill_cleanup_options()
        detect_only = bool(options.get("detectOnly", False))
        if not detect_only:
            self.push_undo()
        self.canvas.commit_floating_selection()

        processed_layers = 0
        debug_results = []
        overlay_image = None

        def process_layer(layer):
            nonlocal overlay_image
            result = applyColorSpillCleanupToImageData(layer.image, options)
            if isinstance(result, tuple):
                new_image, debug_data = result
                debug_results.append(debug_data.get("stats", {}))
                if overlay_image is None and self.spill_debug_overlay_toggle.isChecked():
                    overlay_image = debug_data.get("overlay")
            else:
                new_image = result
            if not detect_only:
                layer.image = new_image

        if scope == "layer":
            process_layer(frame.active_layer)
            if not detect_only:
                frame.mark_dirty()
            processed_layers = 1
        elif scope == "frame":
            for layer in frame.layers:
                process_layer(layer)
                processed_layers += 1
            if not detect_only:
                frame.mark_dirty()
        else:
            for project_frame in self.frames:
                for layer in project_frame.layers:
                    process_layer(layer)
                    processed_layers += 1
                if not detect_only:
                    project_frame.mark_dirty()

        self.canvas.set_debug_overlay(overlay_image if self.spill_debug_overlay_toggle.isChecked() else None)
        self.canvas.update()
        self.refresh_layers()
        self.schedule_thumbnail_refresh()
        self.last_spill_debug_stats = self.aggregate_spill_debug_stats(debug_results)
        self.print_spill_debug_stats(self.last_spill_debug_stats)
        action = "偵測" if detect_only else "套用"
        self.status.showMessage(
            f"已{action}邊緣融色修復：{processed_layers} 個圖層，參考色 {self.color.name().upper()}，容差 {self.canvas.tolerance}"
        )

    def aggregate_spill_debug_stats(self, stats_list: List[dict]) -> dict:
        if not stats_list:
            return {}
        aggregate = dict(stats_list[0])
        aggregate["processedLayerCount"] = len(stats_list)
        sum_keys = {
            "maskPixelCount",
            "innerEdgeBandPixelCount",
            "outerPaddingBandPixelCount",
            "semiTransparentPixelCount",
            "candidatePixelCount",
            "contaminatedMaskPixelCount",
            "contaminatedInnerEdgeCount",
            "contaminatedSemiTransparentCount",
            "contaminatedOuterPaddingCount",
            "cleanColorLookupSuccessCount",
            "cleanColorLookupFallbackCount",
            "recoloredPixelCount",
            "transparentPaddedPixelCount",
            "alphaModifiedPixelCount",
            "totalRGBChangedPixelCount",
            "totalAlphaChangedPixelCount",
            "beforeRGBSum",
            "afterRGBSum",
            "beforeAlphaSum",
            "afterAlphaSum",
        }
        for key in sum_keys:
            aggregate[key] = sum(int(stats.get(key, 0)) for stats in stats_list)
        changed = aggregate.get("totalRGBChangedPixelCount", 0)
        if changed:
            aggregate["averageColorDelta"] = sum(
                float(stats.get("averageColorDelta", 0.0)) * int(stats.get("totalRGBChangedPixelCount", 0))
                for stats in stats_list
            ) / changed
        else:
            aggregate["averageColorDelta"] = 0.0
        contaminated = aggregate.get("contaminatedMaskPixelCount", 0)
        if contaminated:
            aggregate["averageRepairWeight"] = sum(
                float(stats.get("averageRepairWeight", 0.0)) * int(stats.get("contaminatedMaskPixelCount", 0))
                for stats in stats_list
            ) / contaminated
        else:
            aggregate["averageRepairWeight"] = 0.0
        aggregate["maxRepairWeight"] = max(float(stats.get("maxRepairWeight", 0.0)) for stats in stats_list)
        return aggregate

    def print_last_spill_debug_stats(self) -> None:
        if not self.last_spill_debug_stats:
            self.status.showMessage("尚無邊緣融色修復統計，請先執行一次")
            print("No edge spill cleanup debug stats yet.")
            return
        self.print_spill_debug_stats(self.last_spill_debug_stats)

    def print_spill_debug_stats(self, stats: dict) -> None:
        if not stats:
            print("Edge spill cleanup debug stats: <empty>")
            return
        keys = [
            "processedLayerCount",
            "width",
            "height",
            "selectionApplied",
            "selectionPixelCount",
            "spillColor",
            "colorTolerance",
            "despillStrength",
            "edgeWidth",
            "alphaThreshold",
            "maskPixelCount",
            "innerEdgeBandPixelCount",
            "outerPaddingBandPixelCount",
            "semiTransparentPixelCount",
            "candidatePixelCount",
            "contaminatedMaskPixelCount",
            "contaminatedInnerEdgeCount",
            "contaminatedSemiTransparentCount",
            "contaminatedOuterPaddingCount",
            "cleanColorLookupSuccessCount",
            "cleanColorLookupFallbackCount",
            "recoloredPixelCount",
            "transparentPaddedPixelCount",
            "alphaModifiedPixelCount",
            "totalRGBChangedPixelCount",
            "totalAlphaChangedPixelCount",
            "averageColorDelta",
            "averageRepairWeight",
            "maxRepairWeight",
            "beforeRGBSum",
            "afterRGBSum",
            "beforeAlphaSum",
            "afterAlphaSum",
            "detectOnly",
            "testPaintContaminated",
        ]
        rows = [(key, stats.get(key, "")) for key in keys if key in stats]
        width = max(len(str(key)) for key, _ in rows)
        print("\nEdge Spill Cleanup Debug Stats")
        print("-" * (width + 32))
        for key, value in rows:
            print(f"{key:<{width}} | {value}")
        print("-" * (width + 32))

    def choose_background_color(self) -> None:
        color = choose_fixed_color(self.canvas.bg_color, self, "選擇背景色")
        if color.isValid():
            self.canvas.bg_color = color
            self.update_bg_button()
            self.canvas.update()

    def update_bg_button(self) -> None:
        color = self.canvas.bg_color
        text_color = "#000000" if color.lightness() > 140 else "#ffffff"
        self.bg_button.setText(color.name().upper())
        self.bg_button.setStyleSheet(
            f"QPushButton {{ background: {color.name()}; color: {text_color}; "
            "border: 2px solid #222; padding: 4px 10px; font-weight: 700; }}"
        )

    def toggle_centerline(self) -> None:
        self.canvas.show_axes = self.centerline_toggle.isChecked()
        self.canvas.update()

    def toggle_checker_background(self) -> None:
        self.canvas.show_checker_bg = self.checker_bg_toggle.isChecked()
        self.canvas.update()
        mode = "透明格" if self.canvas.show_checker_bg else "純色背景"
        self.status.showMessage(f"背景預覽：{mode}")

    def copy_selection(self) -> None:
        self.canvas.copy_selection()

    def cut_selection(self) -> None:
        self.canvas.cut_selection()

    def paste_selection(self) -> None:
        self.canvas.paste_selection()

    def show_pixel_compression(self) -> None:
        frame = self.current_frame
        if not frame or not frame.layers:
            self.status.showMessage("沒有可處理的目前圖層")
            return

        self.canvas.commit_floating_selection()
        selection_mask = self.canvas.selection_mask_image()
        dialog = PixelCompressionDialog(
            frame.active_layer.image,
            selection_mask,
            self,
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        processed = dialog.processed_image()
        if processed == frame.active_layer.image:
            self.status.showMessage("像素壓縮化沒有改變目前圖層")
            return

        self.push_undo()
        frame.active_layer.image = processed
        frame.mark_dirty()
        scope = "選取區域" if selection_mask is not None else "完整圖層"
        self.on_image_changed(
            f"已像素壓縮化目前圖層的{scope}：{dialog.processing_summary()}"
        )

    def delete_selected_or_frame(self) -> None:
        focus = QApplication.focusWidget()
        timeline_focused = focus is self.thumbnails or (
            focus is not None and self.thumbnails.isAncestorOf(focus)
        )
        if timeline_focused and self.selected_frame_rows():
            self.delete_frame()
            return
        if self.canvas.delete_selection():
            return
        self.delete_frame()

    def set_export_size_from_current(self) -> None:
        frame = self.current_frame
        if not frame:
            return
        self.export_width_spin.setValue(frame.width)
        self.export_height_spin.setValue(frame.height)
        self.update_export_preview_size()
        self.status.showMessage(f"輸出尺寸已設為 {frame.width} x {frame.height}")

    def export_size(self) -> QSize:
        return QSize(self.export_width_spin.value(), self.export_height_spin.value())

    def update_export_preview_size(self) -> None:
        if hasattr(self, "canvas"):
            self.canvas.set_export_size(self.export_size())
            self.update_canvas_extent()
            self.status.showMessage(f"全域輸出尺寸：{self.export_width_spin.value()} x {self.export_height_spin.value()}")

    def export_frame_image(self, frame: Frame) -> QImage:
        size = self.export_size()
        center_x, center_y = frame.export_center
        return cropped_canvas_image(frame.composite(), size.width(), size.height(), center_x, center_y)

    def push_undo(self) -> None:
        if not self.frames:
            return
        self.undo_stack.append(self.capture_project_state())
        if len(self.undo_stack) > self.max_history:
            self.undo_stack.pop(0)
        self.redo_stack.clear()

    def undo(self) -> None:
        if not self.undo_stack:
            self.status.showMessage("沒有可復原的紀錄")
            return
        self.redo_stack.append(self.capture_project_state())
        self.restore_project_state(self.undo_stack.pop(), "已復原")

    def redo(self) -> None:
        if not self.redo_stack:
            self.status.showMessage("沒有可重做的紀錄")
            return
        self.undo_stack.append(self.capture_project_state())
        self.restore_project_state(self.redo_stack.pop(), "已重做")

    def capture_project_state(self) -> ProjectState:
        return ProjectState(frames=[frame.clone() for frame in self.frames], current_index=self.current_index)

    def restore_project_state(self, state: ProjectState, message: str) -> None:
        self.frames = [frame.clone() for frame in state.frames]
        self.current_index = max(0, min(state.current_index, len(self.frames) - 1)) if self.frames else 0
        self.after_project_changed(message)

    def on_image_changed(self, message: str = "已更新") -> None:
        if self.canvas.color_consolidation_sample is not None:
            self.canvas.cancel_color_consolidation(emit_status=False)
        frame = self.current_frame
        if frame:
            frame.mark_dirty()
        self.canvas.update()
        self.refresh_layers()
        self.schedule_thumbnail_refresh()
        self.status.showMessage(message)

    def target_rgba_at(self, x: int, y: int):
        frame = self.current_frame
        if not frame or x < 0 or y < 0 or x >= frame.width or y >= frame.height:
            return None
        color = frame.composite().pixelColor(x, y)
        if color.alpha() == 0:
            return None
        return (color.red(), color.green(), color.blue(), color.alpha())

    def run_frame_erase(self, x: int, y: int) -> None:
        frame = self.current_frame
        if not frame:
            return
        target = qcolor_to_rgba(self.color)
        self.push_undo()
        for layer in frame.layers:
            layer.image = erase_color(layer.image, target, self.canvas.tolerance, contiguous=False)
        frame.mark_dirty()
        self.on_image_changed("已依目前顏色擦除目前影格所有圖層")

    def run_universal_erase(self, x: int, y: int) -> None:
        if not self.frames:
            return
        target = qcolor_to_rgba(self.color)
        self.push_undo()
        self.status.showMessage("正在批次擦除，視窗仍可操作...")
        worker = UniversalEraseWorker(self.frames, target, self.canvas.tolerance)
        worker.signals.progress.connect(lambda done, total: self.status.showMessage(f"批次處理 {done}/{total}"))
        worker.signals.finished.connect(self.finish_universal_erase)
        worker.signals.failed.connect(lambda msg: QMessageBox.warning(self, "批次失敗", msg))
        self.thread_pool.start(worker)

    def finish_universal_erase(self, frames: list) -> None:
        self.frames = frames
        self.current_index = max(0, min(self.current_index, len(self.frames) - 1))
        self.after_project_changed("批次擦除完成")

    def export_current_frame(self) -> None:
        self.canvas.commit_floating_selection()
        frame = self.current_frame
        if not frame:
            return
        filename = frame.name or "frame.png"
        path, _ = QFileDialog.getSaveFileName(
            self,
            "儲存目前影格",
            self.default_export_path(filename),
            "PNG (*.png)",
        )
        if path:
            self.export_frame_image(frame).save(path, "PNG")
            self.status.showMessage(f"已儲存：{path}")

    def export_zip(self) -> None:
        self.canvas.commit_floating_selection()
        if not self.frames:
            return
        path, _ = QFileDialog.getSaveFileName(
            self,
            "儲存 ZIP",
            self.default_export_path("frames.zip"),
            "ZIP (*.zip)",
        )
        if not path:
            return
        with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            for i, frame in enumerate(self.frames, 1):
                zf.writestr(f"video_frame_{i:04d}.png", self.image_png_bytes(self.export_frame_image(frame)))
        self.status.showMessage(f"已儲存 ZIP：{path}")

    def export_spritesheet(self) -> None:
        self.canvas.commit_floating_selection()
        if not self.frames:
            return
        dialog = SpritesheetPreviewDialog(
            self.frames,
            self,
            self.export_size(),
            self.default_file_dialog_directory(),
        )
        dialog.exec()

    def show_animation_preview(self) -> None:
        if not self.frames:
            return
        selected_rows = self.selected_frame_rows()
        start_index = selected_rows[0] if len(selected_rows) > 1 else 0
        end_index = selected_rows[-1] if len(selected_rows) > 1 else len(self.frames) - 1
        dialog = AnimationDialog(
            self.frames,
            self,
            start_index=start_index,
            end_index=end_index,
            output_size=self.export_size(),
        )
        dialog.show()

    def image_png_bytes(self, image: QImage) -> bytes:
        buffer = io.BytesIO()
        from PIL import Image
        from .image_ops import qimage_to_array

        arr = qimage_to_array(image)
        Image.fromarray(arr, "RGBA").save(buffer, format="PNG")
        return buffer.getvalue()

    def after_project_changed(self, message: str) -> None:
        self.canvas.set_frame(self.current_frame)
        if self.current_frame and not self._export_size_initialized:
            self.export_width_spin.setValue(self.current_frame.width)
            self.export_height_spin.setValue(self.current_frame.height)
            self._export_size_initialized = True
        self.canvas.set_export_size(self.export_size() if self.current_frame else None)
        self.update_canvas_extent()
        self.refresh_thumbnails()
        self.refresh_layers()
        self.update_ui()
        self.status.showMessage(message)

    def on_canvas_zoom_changed(self, zoom: float) -> None:
        self.update_canvas_extent()
        self.status.showMessage(f"縮放：{round(zoom * 100)}%")

    def update_canvas_extent(self) -> None:
        hint = self.canvas.sizeHint()
        viewport = self.scroll.viewport().size()
        width = max(hint.width(), viewport.width())
        height = max(hint.height(), viewport.height())
        self.canvas.resize(width, height)
        self.canvas.sync_image_rect_to_workspace()
        self.canvas.update()

    def expand_workspace(self, left: int, top: int, right: int, bottom: int) -> None:
        left = max(0, int(left))
        top = max(0, int(top))
        right = max(0, int(right))
        bottom = max(0, int(bottom))
        if not self.frames or not any((left, top, right, bottom)):
            return

        horizontal_scroll = self.scroll.horizontalScrollBar()
        vertical_scroll = self.scroll.verticalScrollBar()
        old_horizontal = horizontal_scroll.value()
        old_vertical = vertical_scroll.value()
        old_anchor = self.canvas.export_center_view_position()

        for frame in self.frames:
            center_x, center_y = frame.export_center
            new_width = frame.width + left + right
            new_height = frame.height + top + bottom
            for layer in frame.layers:
                expanded = make_blank_image(new_width, new_height)
                painter = QPainter(expanded)
                painter.drawImage(left, top, layer.image)
                painter.end()
                layer.image = expanded
            frame.export_center_x = center_x + left
            frame.export_center_y = center_y + top
            frame.mark_dirty()

        self.canvas.shift_workspace_coordinates(left, top)
        self.canvas.set_debug_overlay(None)
        self.update_canvas_extent()
        new_anchor = self.canvas.export_center_view_position()
        horizontal_scroll.setValue(old_horizontal + round(new_anchor.x() - old_anchor.x()))
        vertical_scroll.setValue(old_vertical + round(new_anchor.y() - old_anchor.y()))
        self.schedule_thumbnail_refresh()
        self.status.showMessage(
            f"工作區已擴張：左 {left}px、上 {top}px、右 {right}px、下 {bottom}px；輸出黑框不變"
        )

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if hasattr(self, "scroll"):
            self.update_canvas_extent()

    def closeEvent(self, event) -> None:
        self.close_editor_auxiliary_windows()
        super().closeEvent(event)

    def schedule_thumbnail_refresh(self) -> None:
        self._thumb_timer.start(60)

    def refresh_thumbnails(self) -> None:
        selected_rows = self._pending_frame_selection
        if selected_rows is None:
            selected_rows = self.selected_frame_rows()
        self._pending_frame_selection = None
        self.thumbnails.blockSignals(True)
        self.thumbnails.clear()
        for index, frame in enumerate(self.frames):
            thumbnail = scaled_export_thumbnail(frame, self.export_size(), QSize(64, 64))
            icon = QIcon(QPixmap.fromImage(thumbnail))
            item = QListWidgetItem(icon, str(index + 1))
            item.setToolTip(frame.name)
            self.thumbnails.addItem(item)
        if self.frames:
            self.thumbnails.setCurrentRow(self.current_index, QItemSelectionModel.SelectionFlag.NoUpdate)
            restored_rows = [row for row in selected_rows if 0 <= row < len(self.frames)]
            if not restored_rows:
                restored_rows = [self.current_index]
            for row in restored_rows:
                self.thumbnails.item(row).setSelected(True)
        self.thumbnails.blockSignals(False)
        self.update_synchronized_selection_targets()

    def refresh_layers(self) -> None:
        frame = self.current_frame
        self.layers.blockSignals(True)
        self.layers.clear()
        if frame:
            for index in range(len(frame.layers) - 1, -1, -1):
                layer = frame.layers[index]
                prefix = "👁 " if layer.visible else "－ "
                item = QListWidgetItem(f"{prefix}{layer.name}  {round(layer.opacity * 100)}%")
                item.setData(Qt.ItemDataRole.UserRole, index)
                self.layers.addItem(item)
                if index == frame.active_layer_index:
                    self.layers.setCurrentItem(item)
            self.opacity.blockSignals(True)
            self.opacity.setValue(round(frame.active_layer.opacity * 100))
            self.opacity.blockSignals(False)
        self.layers.blockSignals(False)

    def update_ui(self) -> None:
        count = len(self.frames)
        current = self.current_index + 1 if count else 0
        self.setWindowTitle(f"Sprite Maker PySide - {current}/{count}")

    def copy_name(self, name: str) -> str:
        path = Path(name)
        if path.suffix:
            return f"{path.stem}_copy{path.suffix}"
        return f"{name}_copy"


class AnimationDialog(QWidget):
    def __init__(
        self,
        frames: List[Frame],
        parent=None,
        start_index: int = 0,
        end_index: Optional[int] = None,
        output_size: Optional[QSize] = None,
    ) -> None:
        super().__init__(parent, Qt.WindowType.Window)
        self.setWindowTitle("動畫預覽")
        self.frames = frames
        self.output_size = QSize(output_size) if output_size is not None else None
        start_index = max(0, min(start_index, len(frames) - 1))
        end_index = len(frames) - 1 if end_index is None else max(start_index, min(end_index, len(frames) - 1))
        self.index = start_index
        self.preview_zoom = 1.0
        self._syncing_frame_list = False
        self.label = QLabel(alignment=Qt.AlignmentFlag.AlignCenter)
        self.label.setMinimumSize(420, 320)
        self.label.setStyleSheet("background:#666;")
        self.preview_scroll = QScrollArea()
        self.preview_scroll.setWidgetResizable(False)
        self.preview_scroll.setWidget(self.label)
        self.frame_list = QListWidget()
        self.frame_list.setViewMode(QListWidget.ViewMode.ListMode)
        self.frame_list.setIconSize(QSize(72, 72))
        self.frame_list.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.frame_list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.frame_list.setMinimumWidth(170)
        self.frame_list.setMaximumWidth(260)
        self.frame_list.currentRowChanged.connect(self.preview_frame_from_list)
        self.fps_spin = QDoubleSpinBox()
        self.fps_spin.setRange(0.1, 60.0)
        self.fps_spin.setValue(24.0)
        self.fps_spin.setDecimals(2)
        self.fps_spin.setSingleStep(1.0)
        self.fps_spin.setSuffix(" FPS")
        self.start_frame = QSpinBox()
        self.start_frame.setRange(1, len(frames))
        self.start_frame.setValue(start_index + 1)
        self.end_frame = QSpinBox()
        self.end_frame.setRange(1, len(frames))
        self.end_frame.setValue(end_index + 1)
        self.zoom_slider = QSlider(Qt.Orientation.Horizontal)
        self.zoom_slider.setRange(10, 800)
        self.zoom_slider.setValue(100)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.next)

        layout = QVBoxLayout(self)
        preview_row = QHBoxLayout()
        preview_row.addWidget(self.preview_scroll, 1)
        thumbnail_panel = QWidget()
        thumbnail_layout = QVBoxLayout(thumbnail_panel)
        thumbnail_layout.addWidget(QLabel("所有 frame"))
        thumbnail_layout.addWidget(self.frame_list, 1)
        set_start_button = QPushButton("設為開始")
        set_start_button.clicked.connect(self.set_selected_frame_as_start)
        set_end_button = QPushButton("設為結束")
        set_end_button.clicked.connect(self.set_selected_frame_as_end)
        thumbnail_layout.addWidget(set_start_button)
        thumbnail_layout.addWidget(set_end_button)
        preview_row.addWidget(thumbnail_panel)
        layout.addLayout(preview_row, 1)
        row = QHBoxLayout()
        row.addWidget(QLabel("播放 FPS"))
        row.addWidget(self.fps_spin)
        row.addWidget(QLabel("播放"))
        row.addWidget(self.start_frame)
        row.addWidget(QLabel("到"))
        row.addWidget(self.end_frame)
        start = QPushButton("播放/暫停")
        start.clicked.connect(self.toggle)
        row.addWidget(start)
        layout.addLayout(row)
        zoom_row = QHBoxLayout()
        zoom_row.addWidget(QLabel("縮放"))
        zoom_row.addWidget(self.zoom_slider, 1)
        self.zoom_label = QLabel("100%")
        zoom_row.addWidget(self.zoom_label)
        layout.addLayout(zoom_row)

        self.fps_spin.valueChanged.connect(self.update_timer_interval)
        self.start_frame.valueChanged.connect(self.normalize_range)
        self.end_frame.valueChanged.connect(self.normalize_range)
        self.zoom_slider.valueChanged.connect(self.set_preview_zoom)
        self.populate_frame_thumbnails()
        self.update_timer_interval()
        self.timer.start()
        self.draw()

    def update_timer_interval(self) -> None:
        interval = max(16, round(1000 / max(0.1, self.fps_spin.value())))
        self.timer.setInterval(interval)

    def populate_frame_thumbnails(self) -> None:
        self.frame_list.blockSignals(True)
        self.frame_list.clear()
        for index, frame in enumerate(self.frames):
            if self.output_size is None:
                thumbnail = frame.composite().scaled(
                    self.frame_list.iconSize(),
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.FastTransformation,
                )
            else:
                thumbnail = scaled_export_thumbnail(frame, self.output_size, self.frame_list.iconSize())
            pixmap = QPixmap.fromImage(thumbnail)
            item = QListWidgetItem(QIcon(pixmap), str(index + 1))
            item.setToolTip(frame.name)
            self.frame_list.addItem(item)
        self.frame_list.setCurrentRow(self.index)
        self.frame_list.blockSignals(False)

    def preview_frame_from_list(self, row: int) -> None:
        if self._syncing_frame_list or row < 0 or row >= len(self.frames):
            return
        self.index = row
        self.draw()

    def set_selected_frame_as_start(self) -> None:
        row = self.frame_list.currentRow()
        if row < 0:
            return
        self.start_frame.setValue(row + 1)

    def set_selected_frame_as_end(self) -> None:
        row = self.frame_list.currentRow()
        if row < 0:
            return
        self.end_frame.setValue(row + 1)

    def toggle(self) -> None:
        if self.timer.isActive():
            self.timer.stop()
        else:
            self.timer.start()

    def next(self) -> None:
        start = self.start_frame.value() - 1
        end = self.end_frame.value() - 1
        if self.index < start or self.index > end:
            self.index = start
        else:
            self.index += 1
            if self.index > end:
                self.index = start
        self.draw()

    def draw(self) -> None:
        image = self.preview_image(self.frames[self.index])
        pixmap = QPixmap.fromImage(image)
        if self.preview_zoom != 1.0:
            pixmap = pixmap.scaled(
                max(1, round(pixmap.width() * self.preview_zoom)),
                max(1, round(pixmap.height() * self.preview_zoom)),
                Qt.AspectRatioMode.IgnoreAspectRatio,
                Qt.TransformationMode.FastTransformation,
            )
        self.label.setPixmap(pixmap)
        self.label.resize(pixmap.size())
        if hasattr(self, "frame_list"):
            self._syncing_frame_list = True
            self.frame_list.setCurrentRow(self.index)
            current_item = self.frame_list.currentItem()
            if current_item is not None:
                self.frame_list.scrollToItem(current_item)
            self._syncing_frame_list = False

    def preview_image(self, frame: Frame) -> QImage:
        image = frame.composite()
        if self.output_size is None:
            return image
        center_x, center_y = frame.export_center
        return cropped_canvas_image(
            image,
            self.output_size.width(),
            self.output_size.height(),
            center_x,
            center_y,
        )

    def normalize_range(self) -> None:
        if self.start_frame.value() > self.end_frame.value():
            sender = self.sender()
            if sender is self.start_frame:
                self.end_frame.setValue(self.start_frame.value())
            else:
                self.start_frame.setValue(self.end_frame.value())
        self.index = max(self.start_frame.value() - 1, min(self.index, self.end_frame.value() - 1))
        self.draw()

    def set_preview_zoom(self, value: int) -> None:
        self.preview_zoom = max(0.1, value / 100.0)
        self.zoom_label.setText(f"{value}%")
        self.draw()

    def wheelEvent(self, event) -> None:
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            delta = 25 if event.angleDelta().y() > 0 else -25
            self.zoom_slider.setValue(max(10, min(800, self.zoom_slider.value() + delta)))
            event.accept()
            return
        super().wheelEvent(event)


class SpritesheetPreviewDialog(QDialog):
    def __init__(
        self,
        frames: List[Frame],
        parent=None,
        output_size: Optional[QSize] = None,
        default_directory: Optional[Path] = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Spritesheet 預覽")
        self.resize(980, 720)
        self.frames = [frame.clone() for frame in frames]
        self.output_size = output_size
        self.default_directory = default_directory or Path.home()
        self.outline_color = QColor("#000000")
        self.current_sheet = make_blank_image(1, 1)
        self.preview_zoom = 1.0
        self.update_timer = QTimer(self)
        self.update_timer.setSingleShot(True)
        self.update_timer.timeout.connect(self.update_preview)

        self.columns = QSpinBox()
        self.columns.setRange(1, 999)
        self.columns.setValue(min(5, len(frames)))
        self.columns.valueChanged.connect(self.queue_update)

        self.trim_pixels = QSpinBox()
        self.trim_pixels.setRange(0, 64)
        self.trim_pixels.setValue(1)
        self.trim_pixels.setToolTip("將角色輪廓向內收縮指定的 pixel 距離")
        self.trim_pixels.valueChanged.connect(self.queue_update)

        self.trim_antialias = QCheckBox("扣邊抗鋸齒")
        self.trim_antialias.setChecked(True)
        self.trim_antialias.setToolTip("扣邊後以 OpenCV 原尺寸抗鋸齒輪廓重繪新邊界")
        self.trim_antialias.stateChanged.connect(self.queue_update)

        self.trim_contour_smoothing = QDoubleSpinBox()
        self.trim_contour_smoothing.setRange(0.0, 2.0)
        self.trim_contour_smoothing.setSingleStep(0.25)
        self.trim_contour_smoothing.setDecimals(2)
        self.trim_contour_smoothing.setValue(2.0)
        self.trim_contour_smoothing.setSuffix(" px")
        self.trim_contour_smoothing.setToolTip("輪廓擬合的最大偏差；越高越平滑，尖角仍會保留")
        self.trim_contour_smoothing.valueChanged.connect(self.queue_update)
        self.trim_antialias.stateChanged.connect(
            lambda state: self.trim_contour_smoothing.setEnabled(bool(state))
        )

        self.outline_pixels = QSpinBox()
        self.outline_pixels.setRange(0, 64)
        self.outline_pixels.setValue(1)
        self.outline_pixels.setToolTip("在與透明背景接觸的外側補外框")
        self.outline_pixels.valueChanged.connect(self.queue_update)

        self.outline_enabled = QCheckBox("啟用外框")
        self.outline_enabled.stateChanged.connect(self.queue_update)

        self.color_button = QPushButton("外框顏色")
        self.color_button.clicked.connect(self.choose_outline_color)

        self.zoom_label = QLabel("100%")
        self.zoom_slider = QSlider(Qt.Orientation.Horizontal)
        self.zoom_slider.setRange(10, 800)
        self.zoom_slider.setValue(100)
        self.zoom_slider.setToolTip("只縮放預覽，不改變輸出尺寸")
        self.zoom_slider.valueChanged.connect(self.set_preview_zoom)

        zoom_out = QPushButton("縮小")
        zoom_out.clicked.connect(lambda: self.zoom_slider.setValue(max(10, self.zoom_slider.value() - 25)))
        zoom_100 = QPushButton("1:1")
        zoom_100.clicked.connect(lambda: self.zoom_slider.setValue(100))
        zoom_in = QPushButton("放大")
        zoom_in.clicked.connect(lambda: self.zoom_slider.setValue(min(800, self.zoom_slider.value() + 25)))

        controls = QFormLayout()
        controls.addRow("欄位數", self.columns)
        if output_size is not None:
            controls.addRow("單格輸出尺寸", QLabel(f"{output_size.width()} x {output_size.height()}"))
        controls.addRow("扣除邊緣 pixel", self.trim_pixels)
        controls.addRow("", self.trim_antialias)
        controls.addRow("輪廓平滑", self.trim_contour_smoothing)
        controls.addRow(self.outline_enabled, self.outline_pixels)
        controls.addRow("", self.color_button)
        zoom_row = QHBoxLayout()
        zoom_row.addWidget(zoom_out)
        zoom_row.addWidget(self.zoom_slider, 1)
        zoom_row.addWidget(self.zoom_label)
        zoom_row.addWidget(zoom_100)
        zoom_row.addWidget(zoom_in)
        controls.addRow("預覽縮放", zoom_row)

        self.preview = QLabel(alignment=Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        self.preview.setStyleSheet("background:#666;")
        preview_scroll = QScrollArea()
        preview_scroll.setWidgetResizable(False)
        preview_scroll.setWidget(self.preview)

        save_button = QPushButton("儲存 PNG")
        save_button.clicked.connect(self.save_sheet)
        close_button = QPushButton("關閉")
        close_button.clicked.connect(self.close)
        button_row = QHBoxLayout()
        button_row.addStretch(1)
        button_row.addWidget(save_button)
        button_row.addWidget(close_button)

        layout = QVBoxLayout(self)
        layout.addLayout(controls)
        layout.addWidget(preview_scroll, 1)
        layout.addLayout(button_row)
        self.update_preview()

    def wheelEvent(self, event) -> None:
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            delta = 25 if event.angleDelta().y() > 0 else -25
            self.zoom_slider.setValue(max(10, min(800, self.zoom_slider.value() + delta)))
            event.accept()
            return
        super().wheelEvent(event)

    def queue_update(self) -> None:
        self.update_timer.start(80)

    def choose_outline_color(self) -> None:
        color = choose_fixed_color(self.outline_color, self, "選擇外框顏色")
        if color.isValid():
            self.outline_color = color
            self.color_button.setStyleSheet(f"background:{color.name()};")
            self.queue_update()

    def update_preview(self) -> None:
        outline = self.outline_pixels.value() if self.outline_enabled.isChecked() else 0
        self.current_sheet = build_spritesheet_image(
            self.frames,
            self.columns.value(),
            self.trim_pixels.value(),
            outline,
            self.outline_color,
            self.output_size,
            self.trim_antialias.isChecked(),
            self.trim_contour_smoothing.value(),
        )
        self.apply_preview_zoom()

    def set_preview_zoom(self, value: int) -> None:
        self.preview_zoom = max(0.1, value / 100.0)
        self.zoom_label.setText(f"{value}%")
        self.apply_preview_zoom()

    def apply_preview_zoom(self) -> None:
        pixmap = QPixmap.fromImage(self.current_sheet)
        if self.preview_zoom != 1.0:
            pixmap = pixmap.scaled(
                max(1, round(pixmap.width() * self.preview_zoom)),
                max(1, round(pixmap.height() * self.preview_zoom)),
                Qt.AspectRatioMode.IgnoreAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        self.preview.setPixmap(pixmap)
        self.preview.resize(pixmap.size())

    def save_sheet(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self,
            "儲存 Spritesheet",
            str(self.default_directory / "spritesheet.png"),
            "PNG (*.png)",
        )
        if path:
            self.current_sheet.save(path, "PNG")
            self.parent().statusBar().showMessage(f"已儲存 Spritesheet：{path}")


def run() -> int:
    app = QApplication([])
    app.setApplicationName("Sprite Maker PySide")
    startup = StartupDialog()
    if startup.exec() != QDialog.DialogCode.Accepted:
        return 0
    if startup.choice == StartupDialog.VIDEO:
        video_dialog = VideoImportDialog(show_switch_button=True)
        if video_dialog.exec() != QDialog.DialogCode.Accepted:
            return 0
        win = MainWindow()
        if video_dialog.video_path is not None:
            win.remember_import_path(video_dialog.video_path)
        win.show()
        if video_dialog.import_images:
            win.add_video_frames(video_dialog.import_images)
        return app.exec()
    win = MainWindow()
    win.show()
    return app.exec()
