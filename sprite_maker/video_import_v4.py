from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QComboBox, QFileDialog, QGroupBox, QHBoxLayout, QLabel, QMessageBox, QPushButton, QVBoxLayout

from .motion_analysis import MotionAnalysisResult, analyze_motion
from .video_import_dialog import FRAME_THUMBNAIL_ROLE, VideoImportDialog


MOTION_JOLT_ROLE = int(Qt.ItemDataRole.UserRole) + 40


class VideoImportDialogV4(VideoImportDialog):
    """4.0 extensions: conservative motion analysis and non-destructive curation."""

    def __init__(self, *args, **kwargs) -> None:
        self.motion_analysis: Optional[MotionAnalysisResult] = None
        self._pending_project: Optional[dict] = None
        super().__init__(*args, **kwargs)
        self.setWindowTitle("匯入影片 / GIF — 4.0 動作分析")
        self._install_motion_panel()

    def _install_motion_panel(self) -> None:
        group = QGroupBox("4.0 動作分析 / 非破壞式選格")
        self.motion_mode = QComboBox()
        self.motion_mode.addItem("自動判斷", "auto")
        self.motion_mode.addItem("循環動作（走路 / 跑步 / idle）", "loop")
        self.motion_mode.addItem("單次動作（攻擊 / 受擊 / 跳躍）", "one_shot")

        self.motion_analyze_button = QPushButton("分析動作")
        self.motion_analyze_button.clicked.connect(self.analyze_current_motion)
        self.motion_apply_button = QPushButton("套用建議範圍")
        self.motion_apply_button.clicked.connect(self.apply_recommended_motion_range)
        self.motion_apply_button.setEnabled(False)
        self.motion_clear_button = QPushButton("清除分析標記")
        self.motion_clear_button.clicked.connect(self.clear_motion_analysis)
        self.save_project_button = QPushButton("儲存 project.json")
        self.save_project_button.clicked.connect(self.save_project_json)
        self.load_project_button = QPushButton("載入 project.json")
        self.load_project_button.clicked.connect(self.load_project_json)

        self.motion_summary = QLabel("尚未分析。分析只提供建議，不會自動刪除 frame。")
        self.motion_summary.setWordWrap(True)
        self.motion_summary.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)

        first_row = QHBoxLayout()
        first_row.addWidget(self.motion_mode, 1)
        first_row.addWidget(self.motion_analyze_button)
        first_row.addWidget(self.motion_apply_button)
        first_row.addWidget(self.motion_clear_button)
        second_row = QHBoxLayout()
        second_row.addWidget(self.save_project_button)
        second_row.addWidget(self.load_project_button)
        second_row.addStretch(1)
        group_layout = QVBoxLayout(group)
        group_layout.addLayout(first_row)
        group_layout.addWidget(self.motion_summary)
        group_layout.addLayout(second_row)
        layout = self.frame_page.layout()
        if layout is not None:
            layout.insertWidget(1, group)

    def on_extract_finished(self, frames: list) -> None:
        self.motion_analysis = None
        super().on_extract_finished(frames)
        if hasattr(self, "motion_apply_button"):
            self.motion_apply_button.setEnabled(False)
            self.motion_summary.setText("尚未分析。分析只提供建議，不會自動刪除 frame。")
        self._clear_motion_item_roles()
        if self._pending_project is not None:
            pending = self._pending_project
            self._pending_project = None
            self._apply_project_after_extract(pending)

    def analyze_current_motion(self) -> None:
        if len(self.frames) < 3:
            QMessageBox.information(self, "frame 不足", "至少需要 3 個 frame 才能分析動作。")
            return
        try:
            result = analyze_motion(
                [frame.image for frame in self.frames],
                fps=self.fps_spin.value(),
                mode=str(self.motion_mode.currentData() or "auto"),
            )
        except Exception as exc:
            QMessageBox.warning(self, "動作分析失敗", str(exc))
            return
        self.motion_analysis = result
        self.motion_apply_button.setEnabled(result.recommended is not None)
        self._apply_motion_item_roles()
        self.motion_summary.setText(self._motion_summary_text(result))
        self.refresh_frame_list()

    def _motion_summary_text(self, result: MotionAnalysisResult) -> str:
        parts = []
        recommendation = result.recommended
        if recommendation is not None:
            kind = "循環" if recommendation.period is not None else "單次"
            parts.append(
                f"建議：{kind} frame {recommendation.start + 1}–{recommendation.end + 1}"
                f"（可信度 {recommendation.confidence * 100:.0f}%"
                + (f"，週期 {recommendation.period} frame" if recommendation.period else "")
                + "）"
            )
        else:
            parts.append("未找到可信的動作範圍。")
        if result.loop_candidates:
            candidates = ", ".join(f"{item.period}f/{item.confidence * 100:.0f}%" for item in result.loop_candidates)
            parts.append(f"Loop 候選：{candidates}")
        if result.jolt_indices:
            display = ", ".join(str(index + 1) for index in result.jolt_indices[:12])
            suffix = "…" if len(result.jolt_indices) > 12 else ""
            parts.append(f"疑似跳格：{display}{suffix}（只標記，不自動移除）")
        else:
            parts.append("未偵測到明顯 movement spike。")
        parts.append(
            f"重心長期漂移：約 X {result.drift_x_per_frame:+.2f} px/frame、"
            f"Y {result.drift_y_per_frame:+.2f} px/frame；實際對齊仍建議使用既有腳底對齊工具。"
        )
        return "\n".join(parts)

    def apply_recommended_motion_range(self) -> None:
        if self.motion_analysis is None or self.motion_analysis.recommended is None:
            return
        recommendation = self.motion_analysis.recommended.clamped(len(self.frames))
        self.frame_list.blockSignals(True)
        try:
            for row in range(self.frame_list.count()):
                item = self.frame_list.item(row)
                index = item.data(Qt.ItemDataRole.UserRole)
                checked = index is not None and recommendation.start <= int(index) <= recommendation.end
                item.setCheckState(Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked)
        finally:
            self.frame_list.blockSignals(False)
        self.on_frame_check_changed()
        self.animation_index = 0
        self.show_animation_frame(0)

    def clear_motion_analysis(self) -> None:
        self.motion_analysis = None
        self.motion_apply_button.setEnabled(False)
        self.motion_summary.setText("尚未分析。分析只提供建議，不會自動刪除 frame。")
        self._clear_motion_item_roles()
        self.refresh_frame_list()

    def _clear_motion_item_roles(self) -> None:
        if not hasattr(self, "frame_list"):
            return
        for row in range(self.frame_list.count()):
            self.frame_list.item(row).setData(MOTION_JOLT_ROLE, False)

    def _apply_motion_item_roles(self) -> None:
        if self.motion_analysis is None:
            self._clear_motion_item_roles()
            return
        jolts = set(self.motion_analysis.jolt_indices)
        for row in range(self.frame_list.count()):
            item = self.frame_list.item(row)
            index = item.data(Qt.ItemDataRole.UserRole)
            item.setData(MOTION_JOLT_ROLE, index is not None and int(index) in jolts)

    def refresh_frame_list(self) -> None:
        super().refresh_frame_list()
        self._apply_motion_item_roles()
        for row in range(self.frame_list.count()):
            self.update_frame_item_visual(self.frame_list.item(row))

    def update_frame_item_visual(self, item) -> None:
        super().update_frame_item_visual(item)
        if not bool(item.data(MOTION_JOLT_ROLE)):
            return
        source = item.data(FRAME_THUMBNAIL_ROLE)
        if not isinstance(source, QPixmap) or source.isNull():
            return
        display = item.icon().pixmap(source.size())
        if display.isNull():
            return
        painter = QPainter(display)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        badge = QRectF(4, max(4, display.height() - 24), min(58, max(1, display.width() - 8)), 20)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(225, 125, 20, 230))
        painter.drawRoundedRect(badge, 3, 3)
        painter.setPen(QColor("white"))
        painter.drawText(badge, Qt.AlignmentFlag.AlignCenter, "跳格?")
        painter.end()
        blocked = self.frame_list.blockSignals(True)
        try:
            item.setIcon(QIcon(display))
        finally:
            self.frame_list.blockSignals(blocked)

    def frame_quality_tooltip(self, index, frame) -> str:
        text = super().frame_quality_tooltip(index, frame)
        if self.motion_analysis is None:
            return text
        notes = []
        if index in self.motion_analysis.jolt_indices:
            notes.append("動作分析：此格前方 transition 為 movement spike")
        recommendation = self.motion_analysis.recommended
        if recommendation is not None and recommendation.start <= index <= recommendation.end:
            notes.append("動作分析：位於建議保留範圍")
        return text + ("\n" + "\n".join(notes) if notes else "")

    def _project_payload(self) -> dict:
        selected_indices = []
        for row in range(self.frame_list.count()):
            item = self.frame_list.item(row)
            index = item.data(Qt.ItemDataRole.UserRole)
            if item.checkState() == Qt.CheckState.Checked and index is not None:
                selected_indices.append(int(index))
        selected_frames = [self.frames[index] for index in selected_indices if 0 <= index < len(self.frames)]
        metadata = self.metadata
        return {
            "schema": "SpriteMakerPySide.video-curation",
            "schema_version": 1,
            "app_branch": "4.0.0",
            "source": {
                "path": str(self.video_path) if self.video_path is not None else None,
                "width": metadata.width if metadata else None,
                "height": metadata.height if metadata else None,
                "fps": metadata.fps if metadata else None,
                "frame_count": metadata.frame_count if metadata else None,
                "duration": metadata.duration if metadata else None,
            },
            "sampling": {
                "start": self.start_spin.value(),
                "end": self.end_spin.value(),
                "target_fps": self.fps_spin.value(),
                "extraction_mode": str(self.extraction_mode_combo.currentData() or "balanced"),
            },
            "selection": {
                "indices": selected_indices,
                "source_indices": [frame.source_index for frame in selected_frames],
                "timestamps": [frame.timestamp for frame in selected_frames],
            },
            "preview": {
                "fps": self.animation_fps_spin.value(),
                "loop": self.animation_loop.isChecked(),
            },
            "motion_analysis": self.motion_analysis.to_dict() if self.motion_analysis else None,
        }

    def save_project_json(self) -> None:
        if self.video_path is None or not self.frames:
            QMessageBox.information(self, "沒有可儲存的專案", "請先載入影片並擷取 frame。")
            return
        default = self.video_path.with_suffix(".sprite-project.json")
        path, _ = QFileDialog.getSaveFileName(self, "儲存非破壞式選格專案", str(default), "Sprite Project (*.json);;JSON (*.json)")
        if not path:
            return
        try:
            Path(path).write_text(json.dumps(self._project_payload(), ensure_ascii=False, indent=2), encoding="utf-8")
        except OSError as exc:
            QMessageBox.warning(self, "儲存失敗", str(exc))
            return
        QMessageBox.information(self, "儲存完成", f"已儲存：{Path(path).name}")

    def load_project_json(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "載入非破壞式選格專案", str(self.initial_directory), "Sprite Project (*.json);;JSON (*.json)")
        if not path:
            return
        try:
            payload = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            QMessageBox.warning(self, "讀取失敗", str(exc))
            return
        if payload.get("schema") != "SpriteMakerPySide.video-curation":
            QMessageBox.warning(self, "格式不符", "這不是 SpriteMakerPySide 4.0 的 video-curation 專案。")
            return
        source_path = payload.get("source", {}).get("path")
        source = Path(source_path) if source_path else None
        if source is None or not source.exists():
            QMessageBox.warning(self, "找不到來源影片", f"project.json 指向的來源檔不存在：\n{source_path}")
            return
        if not self.load_video(source):
            return
        sampling = payload.get("sampling", {})
        self.start_spin.setValue(float(sampling.get("start", 0.0)))
        self.end_spin.setValue(float(sampling.get("end", self.metadata.duration if self.metadata else 0.0)))
        self.fps_spin.setValue(float(sampling.get("target_fps", 12.0)))
        extraction_mode = str(sampling.get("extraction_mode", "balanced"))
        combo_index = self.extraction_mode_combo.findData(extraction_mode)
        if combo_index >= 0:
            self.extraction_mode_combo.setCurrentIndex(combo_index)
        preview = payload.get("preview", {})
        self.animation_fps_spin.setValue(float(preview.get("fps", 24.0)))
        self.animation_loop.setChecked(bool(preview.get("loop", True)))
        self._pending_project = payload
        self.extract_preview()

    def _apply_project_after_extract(self, payload: dict) -> None:
        selection = {int(value) for value in payload.get("selection", {}).get("indices", [])}
        self.frame_list.blockSignals(True)
        try:
            for row in range(self.frame_list.count()):
                item = self.frame_list.item(row)
                index = item.data(Qt.ItemDataRole.UserRole)
                item.setCheckState(Qt.CheckState.Checked if index is not None and int(index) in selection else Qt.CheckState.Unchecked)
        finally:
            self.frame_list.blockSignals(False)
        analysis_payload = payload.get("motion_analysis")
        if isinstance(analysis_payload, dict):
            self.motion_analysis = MotionAnalysisResult.from_dict(analysis_payload)
            self.motion_apply_button.setEnabled(self.motion_analysis.recommended is not None)
            self.motion_summary.setText(self._motion_summary_text(self.motion_analysis))
            self._apply_motion_item_roles()
        self.on_frame_check_changed()
        self.refresh_frame_list()
        self.show_animation_frame(0)
