from __future__ import annotations

import io
import math
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

from PySide6.QtCore import QSize, Qt, QThreadPool, QTimer
from PySide6.QtGui import QAction, QActionGroup, QColor, QIcon, QImage, QKeySequence, QPainter, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QColorDialog,
    QDialog,
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

from .image_ops import add_outline, erase_color, qcolor_to_rgba, trim_alpha_edges
from .models import Frame, Layer, clone_image, frame_from_image, frame_from_qimage, make_blank_image
from .startup_dialog import StartupDialog
from .video_import_dialog import VideoImportDialog
from .widgets import CanvasWidget, FrameStripWidget
from .workers import UniversalEraseWorker


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
) -> QImage:
    images = []
    for frame in frames:
        image = frame.composite()
        if output_size is not None:
            image = centered_canvas_image(image, output_size.width(), output_size.height())
        if trim_pixels > 0:
            image = trim_alpha_edges(image, trim_pixels)
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


def centered_canvas_image(image: QImage, width: int, height: int) -> QImage:
    output = make_blank_image(width, height)
    painter = QPainter(output)
    painter.drawImage((width - image.width()) // 2, (height - image.height()) // 2, image)
    painter.end()
    return output


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
        self.layer_dock: Optional[QDockWidget] = None
        self.frame_dock: Optional[QDockWidget] = None
        self._thumb_timer = QTimer(self)
        self._thumb_timer.setSingleShot(True)
        self._thumb_timer.timeout.connect(self.refresh_thumbnails)

        self.canvas = CanvasWidget()
        self.canvas.editing_started.connect(self.push_undo)
        self.canvas.image_changed.connect(self.on_image_changed)
        self.canvas.frame_erase_requested.connect(self.run_frame_erase)
        self.canvas.universal_erase_requested.connect(self.run_universal_erase)
        self.canvas.color_sampled.connect(self.set_sampled_color)
        self.canvas.zoom_changed.connect(self.on_canvas_zoom_changed)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(False)
        self.scroll.setWidget(self.canvas)
        self.setCentralWidget(self.scroll)

        self.thumbnails = FrameStripWidget()
        self.thumbnails.setViewMode(QListWidget.ViewMode.IconMode)
        self.thumbnails.setIconSize(QSize(64, 64))
        self.thumbnails.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.thumbnails.setMovement(QListWidget.Movement.Static)
        self.thumbnails.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.thumbnails.setDragDropMode(QAbstractItemView.DragDropMode.NoDragDrop)
        self.thumbnails.currentRowChanged.connect(self.set_current_frame)
        self.thumbnails.frame_reordered.connect(self.reorder_frame)

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
        self.tolerance_spin.setToolTip("填色/去色的顏色容差")
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
        frame_row.addStretch(1)
        frame_layout.addLayout(frame_row)
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
        if self.layer_dock:
            self.layer_dock.show()
            self.layer_dock.raise_()

    def show_frame_dock(self) -> None:
        if self.frame_dock:
            self.frame_dock.show()
            self.frame_dock.raise_()

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
        dialog = VideoImportDialog(self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        self.add_video_frames(dialog.import_images)

    def add_video_frames(self, images: List[QImage]) -> None:
        if not images:
            return
        new_frames = [frame_from_qimage(image, f"video_frame_{index:04d}.png") for index, image in enumerate(images, 1)]
        if self.frames:
            self.push_undo()
            insert_at = self.current_index + 1
            self.frames[insert_at:insert_at] = new_frames
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
            str(Path.home()),
            "Images (*.png *.jpg *.jpeg *.bmp *.webp)",
        )
        return [Path(file) for file in files]

    def load_frames(self, paths: List[Path]) -> List[Frame]:
        frames = []
        for path in paths:
            try:
                frames.append(frame_from_image(path))
            except ValueError as exc:
                QMessageBox.warning(self, "讀取失敗", str(exc))
        return frames

    def set_current_frame(self, index: int) -> None:
        if index < 0 or index >= len(self.frames) or index == self.current_index:
            return
        self.canvas.commit_floating_selection()
        self.current_index = index
        self.canvas.set_frame(self.current_frame)
        self.update_canvas_extent()
        self.refresh_layers()
        self.update_ui()

    def reorder_frame(self, old: int, new: int) -> None:
        if not self.frames or old < 0 or old >= len(self.frames) or new < 0 or new >= len(self.frames) or old == new:
            return
        self.push_undo()
        frame = self.frames.pop(old)
        self.frames.insert(new, frame)
        self.current_index = new
        self.after_project_changed("影格順序已更新")

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
        self.push_undo()
        del self.frames[self.current_index]
        self.current_index = max(0, min(self.current_index, len(self.frames) - 1))
        self.after_project_changed("已刪除影格")

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

    def set_brush_size(self, value: int) -> None:
        self.canvas.brush_size = value

    def set_tolerance(self, value: int) -> None:
        self.canvas.tolerance = value

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

    def delete_selected_or_frame(self) -> None:
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
        return centered_canvas_image(frame.composite(), size.width(), size.height())

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
        path, _ = QFileDialog.getSaveFileName(self, "儲存目前影格", frame.name, "PNG (*.png)")
        if path:
            self.export_frame_image(frame).save(path, "PNG")
            self.status.showMessage(f"已儲存：{path}")

    def export_zip(self) -> None:
        self.canvas.commit_floating_selection()
        if not self.frames:
            return
        path, _ = QFileDialog.getSaveFileName(self, "儲存 ZIP", "frames.zip", "ZIP (*.zip)")
        if not path:
            return
        with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            for i, frame in enumerate(self.frames, 1):
                zf.writestr(frame.name or f"frame_{i:04d}.png", self.image_png_bytes(self.export_frame_image(frame)))
        self.status.showMessage(f"已儲存 ZIP：{path}")

    def export_spritesheet(self) -> None:
        self.canvas.commit_floating_selection()
        if not self.frames:
            return
        dialog = SpritesheetPreviewDialog(self.frames, self, self.export_size())
        dialog.exec()

    def show_animation_preview(self) -> None:
        if not self.frames:
            return
        dialog = AnimationDialog(self.frames, self)
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
        self.canvas.update()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if hasattr(self, "scroll"):
            self.update_canvas_extent()

    def schedule_thumbnail_refresh(self) -> None:
        self._thumb_timer.start(60)

    def refresh_thumbnails(self) -> None:
        self.thumbnails.blockSignals(True)
        self.thumbnails.clear()
        for index, frame in enumerate(self.frames):
            icon = QIcon(QPixmap.fromImage(frame.composite().scaled(64, 64, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.FastTransformation)))
            item = QListWidgetItem(icon, str(index + 1))
            item.setToolTip(frame.name)
            self.thumbnails.addItem(item)
        if self.frames:
            self.thumbnails.setCurrentRow(self.current_index)
        self.thumbnails.blockSignals(False)

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
    def __init__(self, frames: List[Frame], parent=None) -> None:
        super().__init__(parent, Qt.WindowType.Window)
        self.setWindowTitle("動畫預覽")
        self.frames = frames
        self.index = 0
        self.preview_zoom = 1.0
        self.label = QLabel(alignment=Qt.AlignmentFlag.AlignCenter)
        self.label.setMinimumSize(420, 320)
        self.label.setStyleSheet("background:#666;")
        self.preview_scroll = QScrollArea()
        self.preview_scroll.setWidgetResizable(False)
        self.preview_scroll.setWidget(self.label)
        self.speed = QSpinBox()
        self.speed.setRange(20, 1000)
        self.speed.setValue(120)
        self.start_frame = QSpinBox()
        self.start_frame.setRange(1, len(frames))
        self.start_frame.setValue(1)
        self.end_frame = QSpinBox()
        self.end_frame.setRange(1, len(frames))
        self.end_frame.setValue(len(frames))
        self.zoom_slider = QSlider(Qt.Orientation.Horizontal)
        self.zoom_slider.setRange(10, 800)
        self.zoom_slider.setValue(100)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.next)

        layout = QVBoxLayout(self)
        layout.addWidget(self.preview_scroll, 1)
        row = QHBoxLayout()
        row.addWidget(QLabel("間隔(ms)"))
        row.addWidget(self.speed)
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

        self.speed.valueChanged.connect(lambda value: self.timer.setInterval(value))
        self.start_frame.valueChanged.connect(self.normalize_range)
        self.end_frame.valueChanged.connect(self.normalize_range)
        self.zoom_slider.valueChanged.connect(self.set_preview_zoom)
        self.timer.setInterval(self.speed.value())
        self.timer.start()
        self.draw()

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
        image = self.frames[self.index].composite()
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
    def __init__(self, frames: List[Frame], parent=None, output_size: Optional[QSize] = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Spritesheet 預覽")
        self.resize(980, 720)
        self.frames = [frame.clone() for frame in frames]
        self.output_size = output_size
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
        self.trim_pixels.setValue(0)
        self.trim_pixels.setToolTip("每次扣除一圈與透明背景接觸的像素")
        self.trim_pixels.valueChanged.connect(self.queue_update)

        self.outline_pixels = QSpinBox()
        self.outline_pixels.setRange(0, 64)
        self.outline_pixels.setValue(0)
        self.outline_pixels.setToolTip("在與透明背景接觸的外側補黑線")
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
                Qt.TransformationMode.FastTransformation,
            )
        self.preview.setPixmap(pixmap)
        self.preview.resize(pixmap.size())

    def save_sheet(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "儲存 Spritesheet", "spritesheet.png", "PNG (*.png)")
        if path:
            self.current_sheet.save(path, "PNG")
            self.parent().statusBar().showMessage(f"已儲存 Spritesheet：{path}")


def run() -> int:
    app = QApplication([])
    app.setApplicationName("Sprite Maker PySide")
    startup = StartupDialog()
    if startup.exec() != QDialog.DialogCode.Accepted:
        return 0
    win = MainWindow()
    win.show()
    if startup.choice == StartupDialog.VIDEO:
        QTimer.singleShot(0, win.import_video)
    return app.exec()
