from __future__ import annotations

from pathlib import Path
from typing import List, Optional

from PySide6.QtCore import QObject, QRunnable, Qt, QThreadPool, Signal, Slot
from PySide6.QtGui import QIcon, QImage, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from .video_ops import ExtractedVideoFrame, VideoMetadata, extract_video_frames, read_video_metadata


class VideoExtractSignals(QObject):
    progress = Signal(int, int)
    finished = Signal(list)
    failed = Signal(str)


class VideoExtractWorker(QRunnable):
    def __init__(self, path: Path, start: float, end: float, target_fps: float) -> None:
        super().__init__()
        self.path = path
        self.start = start
        self.end = end
        self.target_fps = target_fps
        self.signals = VideoExtractSignals()

    @Slot()
    def run(self) -> None:
        try:
            frames = extract_video_frames(self.path, self.start, self.end, self.target_fps)
            total = max(1, len(frames))
            for index in range(total):
                self.signals.progress.emit(index + 1, total)
            self.signals.finished.emit(frames)
        except Exception as exc:
            self.signals.failed.emit(str(exc))


class VideoImportDialog(QDialog):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("匯入影片")
        self.resize(1120, 760)
        self.thread_pool = QThreadPool.globalInstance()
        self.video_path: Optional[Path] = None
        self.metadata: Optional[VideoMetadata] = None
        self.frames: List[ExtractedVideoFrame] = []
        self.import_images: List[QImage] = []
        self.worker: Optional[VideoExtractWorker] = None

        self.path_label = QLabel("尚未選擇影片")
        self.path_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        browse_button = QPushButton("選擇影片")
        browse_button.clicked.connect(self.choose_video)

        self.info_label = QLabel("影片資訊會顯示在這裡")
        self.info_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)

        self.start_spin = QDoubleSpinBox()
        self.start_spin.setRange(0.0, 86400.0)
        self.start_spin.setDecimals(3)
        self.start_spin.setSingleStep(0.1)
        self.start_spin.setSuffix(" 秒")

        self.end_spin = QDoubleSpinBox()
        self.end_spin.setRange(0.0, 86400.0)
        self.end_spin.setDecimals(3)
        self.end_spin.setSingleStep(0.1)
        self.end_spin.setSuffix(" 秒")

        self.fps_spin = QDoubleSpinBox()
        self.fps_spin.setRange(0.1, 120.0)
        self.fps_spin.setDecimals(2)
        self.fps_spin.setSingleStep(1.0)
        self.fps_spin.setValue(12.0)
        self.fps_spin.setSuffix(" FPS")

        self.thumb_size = QSpinBox()
        self.thumb_size.setRange(48, 240)
        self.thumb_size.setValue(96)
        self.thumb_size.setSingleStep(16)
        self.thumb_size.valueChanged.connect(self.refresh_frame_list)

        extract_button = QPushButton("擷取預覽")
        extract_button.clicked.connect(self.extract_preview)

        settings = QFormLayout()
        settings.addRow("開始時間", self.start_spin)
        settings.addRow("結束時間", self.end_spin)
        settings.addRow("目標 FPS", self.fps_spin)
        settings.addRow("縮圖大小", self.thumb_size)
        settings.addRow("", extract_button)

        left = QWidget()
        left_layout = QVBoxLayout(left)
        path_row = QHBoxLayout()
        path_row.addWidget(self.path_label, 1)
        path_row.addWidget(browse_button)
        left_layout.addLayout(path_row)
        left_layout.addWidget(self.info_label)
        left_layout.addLayout(settings)
        left_layout.addStretch(1)

        self.frame_list = QListWidget()
        self.frame_list.setViewMode(QListWidget.ViewMode.IconMode)
        self.frame_list.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.frame_list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.frame_list.currentRowChanged.connect(self.update_preview)

        self.preview = QLabel("尚未擷取 frame")
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setMinimumSize(360, 300)
        self.preview.setStyleSheet("background:#2d2d2d; color:#f4f4f4;")

        center = QSplitter(Qt.Orientation.Horizontal)
        center.addWidget(self.frame_list)
        center.addWidget(self.preview)
        center.setStretchFactor(0, 2)
        center.setStretchFactor(1, 1)

        self.progress = QProgressBar()
        self.progress.setRange(0, 1)
        self.progress.setValue(0)

        select_all = QPushButton("全選")
        select_all.clicked.connect(lambda: self.set_all_checked(True))
        select_none = QPushButton("全不選")
        select_none.clicked.connect(lambda: self.set_all_checked(False))
        invert = QPushButton("反選")
        invert.clicked.connect(self.invert_selection)
        save_png = QPushButton("儲存 PNG")
        save_png.clicked.connect(self.save_selected_pngs)
        import_editor = QPushButton("匯入編輯器")
        import_editor.clicked.connect(self.accept_for_import)
        close_button = QPushButton("關閉")
        close_button.clicked.connect(self.reject)

        button_row = QHBoxLayout()
        for button in (select_all, select_none, invert):
            button_row.addWidget(button)
        button_row.addStretch(1)
        button_row.addWidget(save_png)
        button_row.addWidget(import_editor)
        button_row.addWidget(close_button)

        layout = QVBoxLayout(self)
        layout.addWidget(left)
        layout.addWidget(center, 1)
        layout.addWidget(self.progress)
        layout.addLayout(button_row)

    def choose_video(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "選擇影片",
            str(Path.home()),
            "Videos (*.mp4 *.mov *.avi *.webm *.mkv);;All Files (*.*)",
        )
        if not path:
            return
        try:
            self.metadata = read_video_metadata(Path(path))
        except ValueError as exc:
            QMessageBox.warning(self, "無法讀取影片", str(exc))
            return
        self.video_path = Path(path)
        self.path_label.setText(str(self.video_path))
        duration = max(0.0, self.metadata.duration)
        self.start_spin.setMaximum(max(1.0, duration))
        self.end_spin.setMaximum(max(1.0, duration))
        self.start_spin.setValue(0.0)
        self.end_spin.setValue(duration if duration > 0 else 1.0)
        if self.metadata.fps > 0:
            self.fps_spin.setValue(min(24.0, max(1.0, self.metadata.fps)))
        self.info_label.setText(
            f"{self.metadata.width} x {self.metadata.height} / "
            f"{self.metadata.fps:.2f} FPS / {self.metadata.frame_count} frames / "
            f"{self.metadata.duration:.3f} 秒"
        )

    def extract_preview(self) -> None:
        if self.video_path is None:
            QMessageBox.information(self, "尚未選擇影片", "請先選擇影片檔。")
            return
        start = self.start_spin.value()
        end = self.end_spin.value()
        if end <= start:
            QMessageBox.warning(self, "時間區間錯誤", "結束時間必須大於開始時間。")
            return
        self.frame_list.clear()
        self.preview.setText("正在擷取...")
        self.progress.setRange(0, 0)
        self.worker = VideoExtractWorker(self.video_path, start, end, self.fps_spin.value())
        self.worker.signals.progress.connect(self.on_extract_progress)
        self.worker.signals.finished.connect(self.on_extract_finished)
        self.worker.signals.failed.connect(self.on_extract_failed)
        self.thread_pool.start(self.worker)

    def on_extract_progress(self, done: int, total: int) -> None:
        self.progress.setRange(0, total)
        self.progress.setValue(done)

    def on_extract_finished(self, frames: list) -> None:
        self.frames = list(frames)
        self.progress.setRange(0, max(1, len(self.frames)))
        self.progress.setValue(len(self.frames))
        self.refresh_frame_list()
        if self.frames:
            self.frame_list.setCurrentRow(0)
        else:
            self.preview.setText("沒有擷取到 frame")

    def on_extract_failed(self, message: str) -> None:
        self.progress.setRange(0, 1)
        self.progress.setValue(0)
        self.preview.setText("擷取失敗")
        QMessageBox.warning(self, "擷取失敗", message)

    def refresh_frame_list(self) -> None:
        checked = {self.frame_list.item(row).data(Qt.ItemDataRole.UserRole): self.frame_list.item(row).checkState() for row in range(self.frame_list.count())}
        self.frame_list.clear()
        size = self.thumb_size.value()
        self.frame_list.setIconSize(QPixmap(size, size).size())
        for index, frame in enumerate(self.frames):
            pixmap = QPixmap.fromImage(frame.image).scaled(
                size,
                size,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.FastTransformation,
            )
            item = QListWidgetItem(QIcon(pixmap), f"{index + 1}\n{frame.timestamp:.3f}s")
            item.setData(Qt.ItemDataRole.UserRole, index)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(checked.get(index, Qt.CheckState.Checked))
            self.frame_list.addItem(item)

    def update_preview(self, row: int) -> None:
        if row < 0 or row >= len(self.frames):
            return
        frame = self.frames[row]
        pixmap = QPixmap.fromImage(frame.image).scaled(
            self.preview.size(),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.FastTransformation,
        )
        self.preview.setPixmap(pixmap)
        self.preview.setToolTip(f"Frame {row + 1} / {frame.timestamp:.3f}s / source #{frame.source_index}")

    def selected_frames(self) -> List[ExtractedVideoFrame]:
        selected: List[ExtractedVideoFrame] = []
        for row in range(self.frame_list.count()):
            item = self.frame_list.item(row)
            index = item.data(Qt.ItemDataRole.UserRole)
            if item.checkState() == Qt.CheckState.Checked and index is not None:
                selected.append(self.frames[index])
        return selected

    def set_all_checked(self, checked: bool) -> None:
        state = Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked
        for row in range(self.frame_list.count()):
            self.frame_list.item(row).setCheckState(state)

    def invert_selection(self) -> None:
        for row in range(self.frame_list.count()):
            item = self.frame_list.item(row)
            item.setCheckState(Qt.CheckState.Unchecked if item.checkState() == Qt.CheckState.Checked else Qt.CheckState.Checked)

    def save_selected_pngs(self) -> None:
        selected = self.selected_frames()
        if not selected:
            QMessageBox.information(self, "沒有選擇 frame", "請先勾選至少一個 frame。")
            return
        directory = QFileDialog.getExistingDirectory(self, "選擇儲存資料夾", str(Path.home()))
        if not directory:
            return
        output_dir = Path(directory)
        for index, frame in enumerate(selected, 1):
            filename = f"frame_{index:04d}_{frame.timestamp:08.3f}s.png".replace(".", "_", 1)
            frame.image.save(str(output_dir / filename), "PNG")
        QMessageBox.information(self, "儲存完成", f"已儲存 {len(selected)} 張 PNG。")

    def accept_for_import(self) -> None:
        selected = self.selected_frames()
        if not selected:
            QMessageBox.information(self, "沒有選擇 frame", "請先勾選至少一個 frame。")
            return
        self.import_images = [frame.image.copy() for frame in selected]
        self.accept()
