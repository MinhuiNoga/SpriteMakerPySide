from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from .combat_timeline import CombatTimeline, build_animation_manifest, suggest_combat_timeline
from .motion_analysis import MotionAnalysisResult, analyze_motion
from .video_import_dialog import FRAME_THUMBNAIL_ROLE, VideoImportDialog


MOTION_JOLT_ROLE = int(Qt.ItemDataRole.UserRole) + 40
COMBAT_PHASE_ROLE = int(Qt.ItemDataRole.UserRole) + 41
COMBAT_HIT_ROLE = int(Qt.ItemDataRole.UserRole) + 42
COMBAT_CANCEL_ROLE = int(Qt.ItemDataRole.UserRole) + 43


class CombatTimelineBar(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.timeline: Optional[CombatTimeline] = None
        self.setMinimumHeight(52)

    def set_timeline(self, timeline: Optional[CombatTimeline]) -> None:
        self.timeline = timeline
        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = QRectF(8, 12, max(1.0, self.width() - 16.0), 24)
        painter.setPen(QPen(QColor("#374151"), 1))
        painter.setBrush(QColor("#1f2937"))
        painter.drawRoundedRect(rect, 4, 4)
        timeline = self.timeline
        if timeline is None or timeline.frame_count <= 0:
            painter.setPen(QColor("#9ca3af"))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "尚未建立戰鬥時間軸")
            painter.end()
            return

        colors = {
            "startup": QColor("#64748b"),
            "active": QColor("#dc2626"),
            "recovery": QColor("#2563eb"),
        }
        ranges = timeline.phase_ranges()
        for phase, bounds in ranges.items():
            start = bounds["start"]
            end = bounds["end_exclusive"]
            if end <= start:
                continue
            left = rect.left() + rect.width() * start / timeline.frame_count
            right = rect.left() + rect.width() * end / timeline.frame_count
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(colors[phase])
            painter.drawRect(QRectF(left, rect.top(), max(1.0, right - left), rect.height()))

        for frame in timeline.hit_frames:
            x = rect.left() + rect.width() * (frame + 0.5) / timeline.frame_count
            painter.setPen(QPen(QColor("#fde047"), 3))
            painter.drawLine(int(x), int(rect.top() - 6), int(x), int(rect.bottom() + 6))
        if timeline.cancel_frame is not None:
            x = rect.left() + rect.width() * (timeline.cancel_frame + 0.5) / timeline.frame_count
            painter.setPen(QPen(QColor("#22d3ee"), 2, Qt.PenStyle.DashLine))
            painter.drawLine(int(x), int(rect.top() - 4), int(x), int(rect.bottom() + 4))

        painter.setPen(QColor("#e5e7eb"))
        painter.drawText(8, 49, "灰=Startup　紅=Active　藍=Recovery　黃=Hit　青=Cancel")
        painter.end()


class VideoImportDialogV4(VideoImportDialog):
    """4.0.1 extensions: motion analysis, ARPG timing metadata and non-destructive curation."""

    def __init__(self, *args, **kwargs) -> None:
        self.motion_analysis: Optional[MotionAnalysisResult] = None
        self.combat_timeline: Optional[CombatTimeline] = None
        self._pending_project: Optional[dict] = None
        self._suppress_timeline_invalidation = False
        super().__init__(*args, **kwargs)
        self.setWindowTitle("匯入影片 / GIF — 4.0.1 ARPG 動畫工具")
        self._install_motion_panel()
        self._install_combat_panel()

    def _install_motion_panel(self) -> None:
        group = QGroupBox("動作分析 / 非破壞式選格")
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

    def _install_combat_panel(self) -> None:
        group = QGroupBox("ARPG 戰鬥時間軸 / Runtime Metadata")
        self.animation_name_edit = QLineEdit("animation")
        self.animation_name_edit.setPlaceholderText("例如 sword_slash_01")

        self.startup_end_spin = QSpinBox()
        self.startup_end_spin.setMinimum(0)
        self.startup_end_spin.setToolTip("Startup 使用前 N 格；0 代表沒有 Startup。")
        self.active_end_spin = QSpinBox()
        self.active_end_spin.setMinimum(1)
        self.active_end_spin.setToolTip("Active 結束於前 N 格；Recovery 從下一格開始。")
        self.hit_frames_edit = QLineEdit()
        self.hit_frames_edit.setPlaceholderText("例如 5 或 5,6（介面使用 1-based）")
        self.cancel_frame_spin = QSpinBox()
        self.cancel_frame_spin.setMinimum(0)
        self.cancel_frame_spin.setSpecialValueText("無")
        self.cancel_frame_spin.setToolTip("0=無；其餘數值為可取消起始 frame（1-based）。")

        self.timeline_auto_button = QPushButton("依動作自動分段")
        self.timeline_auto_button.clicked.connect(self.auto_suggest_combat_timeline)
        self.timeline_apply_button = QPushButton("套用時間軸")
        self.timeline_apply_button.clicked.connect(self.apply_combat_timeline_from_controls)
        self.export_animation_button = QPushButton("匯出 animation.json")
        self.export_animation_button.clicked.connect(self.export_animation_json)
        self.export_animation_button.setEnabled(False)

        form = QFormLayout()
        form.addRow("動畫名稱", self.animation_name_edit)
        form.addRow("Startup 結束（前 N 格）", self.startup_end_spin)
        form.addRow("Active 結束（前 N 格）", self.active_end_spin)
        form.addRow("Hit frame", self.hit_frames_edit)
        form.addRow("Cancel frame", self.cancel_frame_spin)

        buttons = QHBoxLayout()
        buttons.addWidget(self.timeline_auto_button)
        buttons.addWidget(self.timeline_apply_button)
        buttons.addWidget(self.export_animation_button)
        buttons.addStretch(1)

        self.timeline_bar = CombatTimelineBar()
        self.timeline_summary = QLabel("請先選擇要保留的 frame，再建立 Startup / Active / Recovery。")
        self.timeline_summary.setWordWrap(True)
        self.timeline_summary.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)

        group_layout = QVBoxLayout(group)
        group_layout.addLayout(form)
        group_layout.addLayout(buttons)
        group_layout.addWidget(self.timeline_bar)
        group_layout.addWidget(self.timeline_summary)
        layout = self.frame_page.layout()
        if layout is not None:
            layout.insertWidget(2, group)
        self._refresh_combat_control_ranges()

    def load_video(self, path: Path) -> bool:
        loaded = super().load_video(path)
        if loaded and hasattr(self, "animation_name_edit"):
            current = self.animation_name_edit.text().strip()
            if not current or current == "animation":
                self.animation_name_edit.setText(path.stem)
        return loaded

    def on_extract_finished(self, frames: list) -> None:
        self.motion_analysis = None
        self.combat_timeline = None
        super().on_extract_finished(frames)
        if hasattr(self, "motion_apply_button"):
            self.motion_apply_button.setEnabled(False)
            self.motion_summary.setText("尚未分析。分析只提供建議，不會自動刪除 frame。")
        self._clear_motion_item_roles()
        self._clear_combat_item_roles()
        self._refresh_combat_control_ranges()
        self._set_combat_timeline(None)
        if self._pending_project is not None:
            pending = self._pending_project
            self._pending_project = None
            self._apply_project_after_extract(pending)

    def on_frame_check_changed(self, *args) -> None:
        if not self._suppress_timeline_invalidation and self.combat_timeline is not None:
            self._set_combat_timeline(None, "選格已變更；舊的戰鬥時間軸已失效，請重新分段。")
        super().on_frame_check_changed(*args)
        self._refresh_combat_control_ranges()

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
            f"Y {result.drift_y_per_frame:+.2f} px/frame；實際對齊仍使用既有腳底對齊工具。"
        )
        return "\n".join(parts)

    def apply_recommended_motion_range(self) -> None:
        if self.motion_analysis is None or self.motion_analysis.recommended is None:
            return
        recommendation = self.motion_analysis.recommended.clamped(len(self.frames))
        self._suppress_timeline_invalidation = True
        self.frame_list.blockSignals(True)
        try:
            for row in range(self.frame_list.count()):
                item = self.frame_list.item(row)
                index = item.data(Qt.ItemDataRole.UserRole)
                checked = index is not None and recommendation.start <= int(index) <= recommendation.end
                item.setCheckState(Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked)
        finally:
            self.frame_list.blockSignals(False)
            self._suppress_timeline_invalidation = False
        self._set_combat_timeline(None, "已套用新的動作範圍；請建立戰鬥時間軸。")
        super().on_frame_check_changed()
        self._refresh_combat_control_ranges()
        self.animation_index = 0
        self.show_animation_frame(0)

    def clear_motion_analysis(self) -> None:
        self.motion_analysis = None
        self.motion_apply_button.setEnabled(False)
        self.motion_summary.setText("尚未分析。分析只提供建議，不會自動刪除 frame。")
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

    def _selected_extraction_indices(self) -> list[int]:
        indices: list[int] = []
        for row in range(self.frame_list.count()):
            item = self.frame_list.item(row)
            index = item.data(Qt.ItemDataRole.UserRole)
            if item.checkState() == Qt.CheckState.Checked and index is not None:
                indices.append(int(index))
        return indices

    def _refresh_combat_control_ranges(self) -> None:
        if not hasattr(self, "startup_end_spin"):
            return
        count = len(self._selected_extraction_indices())
        self.startup_end_spin.setRange(0, max(0, count - 1))
        self.active_end_spin.setRange(1, max(1, count))
        self.cancel_frame_spin.setRange(0, max(0, count))
        enabled = count > 0
        self.timeline_auto_button.setEnabled(enabled)
        self.timeline_apply_button.setEnabled(enabled)
        if self.combat_timeline is None and count > 0:
            startup = 1 if count >= 3 else 0
            active_end = min(count, max(startup + 1, round(count * 0.65)))
            self.startup_end_spin.setValue(startup)
            self.active_end_spin.setValue(active_end)
            self.hit_frames_edit.setText(str(max(1, min(count, startup + 1))))
            self.cancel_frame_spin.setValue(active_end + 1 if active_end < count else 0)

    def _parse_hit_frames(self, frame_count: int) -> tuple[int, ...]:
        text = self.hit_frames_edit.text().strip()
        if not text:
            return ()
        normalized = text.replace("，", ",").replace(";", ",").replace("；", ",")
        values = []
        for chunk in normalized.split(","):
            chunk = chunk.strip()
            if not chunk:
                continue
            try:
                value = int(chunk)
            except ValueError as exc:
                raise ValueError(f"Hit frame '{chunk}' 不是整數。") from exc
            if not 1 <= value <= frame_count:
                raise ValueError(f"Hit frame {value} 超出 1–{frame_count}。")
            values.append(value - 1)
        return tuple(sorted(set(values)))

    def auto_suggest_combat_timeline(self) -> None:
        selected = self.selected_frames()
        if not selected:
            QMessageBox.information(self, "沒有 frame", "請先勾選要保留的 frame。")
            return
        try:
            timeline = suggest_combat_timeline(
                [frame.image for frame in selected],
                fps=self.animation_fps_spin.value(),
                animation_name=self.animation_name_edit.text().strip() or "animation",
            )
        except Exception as exc:
            QMessageBox.warning(self, "自動分段失敗", str(exc))
            return
        self._set_combat_timeline(timeline)
        self._write_timeline_to_controls(timeline)
        self.refresh_frame_list()

    def apply_combat_timeline_from_controls(self) -> None:
        selected = self.selected_frames()
        frame_count = len(selected)
        if frame_count <= 0:
            QMessageBox.information(self, "沒有 frame", "請先勾選要保留的 frame。")
            return
        try:
            hit_frames = self._parse_hit_frames(frame_count)
            cancel_value = self.cancel_frame_spin.value()
            timeline = CombatTimeline(
                frame_count=frame_count,
                startup_end=self.startup_end_spin.value(),
                active_end=self.active_end_spin.value(),
                hit_frames=hit_frames,
                cancel_frame=None if cancel_value == 0 else cancel_value - 1,
                animation_name=self.animation_name_edit.text().strip() or "animation",
                fps=self.animation_fps_spin.value(),
                loop=self.animation_loop.isChecked(),
            ).validate()
        except ValueError as exc:
            QMessageBox.warning(self, "時間軸設定錯誤", str(exc))
            return
        self._set_combat_timeline(timeline)
        self.refresh_frame_list()

    def _write_timeline_to_controls(self, timeline: CombatTimeline) -> None:
        self.animation_name_edit.setText(timeline.animation_name)
        self.startup_end_spin.setValue(timeline.startup_end)
        self.active_end_spin.setValue(timeline.active_end)
        self.hit_frames_edit.setText(",".join(str(value + 1) for value in timeline.hit_frames))
        self.cancel_frame_spin.setValue(0 if timeline.cancel_frame is None else timeline.cancel_frame + 1)
        self.animation_fps_spin.setValue(timeline.fps)
        self.animation_loop.setChecked(timeline.loop)

    def _set_combat_timeline(self, timeline: Optional[CombatTimeline], reason: Optional[str] = None) -> None:
        self.combat_timeline = timeline
        if hasattr(self, "timeline_bar"):
            self.timeline_bar.set_timeline(timeline)
        if hasattr(self, "export_animation_button"):
            self.export_animation_button.setEnabled(timeline is not None)
        if timeline is None:
            if hasattr(self, "timeline_summary"):
                self.timeline_summary.setText(reason or "請建立 Startup / Active / Recovery 時間軸。")
            self._clear_combat_item_roles()
        else:
            self.timeline_summary.setText(self._timeline_summary_text(timeline))
            self._apply_combat_item_roles()

    def _timeline_summary_text(self, timeline: CombatTimeline) -> str:
        startup = "無" if timeline.startup_end == 0 else f"1–{timeline.startup_end}"
        active = f"{timeline.startup_end + 1}–{timeline.active_end}"
        recovery = "無" if timeline.active_end >= timeline.frame_count else f"{timeline.active_end + 1}–{timeline.frame_count}"
        hits = "無" if not timeline.hit_frames else ", ".join(str(value + 1) for value in timeline.hit_frames)
        cancel = "無" if timeline.cancel_frame is None else str(timeline.cancel_frame + 1)
        return (
            f"{timeline.animation_name}｜Startup {startup}｜Active {active}｜Recovery {recovery}｜"
            f"Hit {hits}｜Cancel {cancel}｜{timeline.fps:.2f} FPS｜"
            f"{'Loop' if timeline.loop else 'One-shot'}"
        )

    def _clear_combat_item_roles(self) -> None:
        if not hasattr(self, "frame_list"):
            return
        for row in range(self.frame_list.count()):
            item = self.frame_list.item(row)
            item.setData(COMBAT_PHASE_ROLE, None)
            item.setData(COMBAT_HIT_ROLE, False)
            item.setData(COMBAT_CANCEL_ROLE, False)

    def _apply_combat_item_roles(self) -> None:
        self._clear_combat_item_roles()
        timeline = self.combat_timeline
        if timeline is None:
            return
        selected = self._selected_extraction_indices()
        if len(selected) != timeline.frame_count:
            return
        order_by_extraction = {value: order for order, value in enumerate(selected)}
        for row in range(self.frame_list.count()):
            item = self.frame_list.item(row)
            extraction_index = item.data(Qt.ItemDataRole.UserRole)
            if extraction_index is None or int(extraction_index) not in order_by_extraction:
                continue
            order = order_by_extraction[int(extraction_index)]
            item.setData(COMBAT_PHASE_ROLE, timeline.phase_for_index(order))
            item.setData(COMBAT_HIT_ROLE, order in timeline.hit_frames)
            item.setData(COMBAT_CANCEL_ROLE, timeline.cancel_frame == order)

    def refresh_frame_list(self) -> None:
        super().refresh_frame_list()
        self._apply_motion_item_roles()
        self._apply_combat_item_roles()
        for row in range(self.frame_list.count()):
            self.update_frame_item_visual(self.frame_list.item(row))

    def update_frame_item_visual(self, item) -> None:
        super().update_frame_item_visual(item)
        source = item.data(FRAME_THUMBNAIL_ROLE)
        if not isinstance(source, QPixmap) or source.isNull():
            return
        display = item.icon().pixmap(source.size())
        if display.isNull():
            return
        painter = QPainter(display)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        if bool(item.data(MOTION_JOLT_ROLE)):
            badge = QRectF(4, max(4, display.height() - 24), min(58, max(1, display.width() - 8)), 20)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(225, 125, 20, 230))
            painter.drawRoundedRect(badge, 3, 3)
            painter.setPen(QColor("white"))
            painter.drawText(badge, Qt.AlignmentFlag.AlignCenter, "跳格?")

        phase = item.data(COMBAT_PHASE_ROLE)
        if phase in {"startup", "active", "recovery"}:
            labels = {"startup": "S", "active": "A", "recovery": "R"}
            colors = {"startup": QColor(100, 116, 139, 230), "active": QColor(220, 38, 38, 230), "recovery": QColor(37, 99, 235, 230)}
            badge = QRectF(max(4, display.width() - 26), 4, 22, 20)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(colors[phase])
            painter.drawRoundedRect(badge, 3, 3)
            painter.setPen(QColor("white"))
            painter.drawText(badge, Qt.AlignmentFlag.AlignCenter, labels[phase])

        if bool(item.data(COMBAT_HIT_ROLE)):
            badge = QRectF(max(4, display.width() - 40), max(4, display.height() - 24), 36, 20)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(202, 138, 4, 235))
            painter.drawRoundedRect(badge, 3, 3)
            painter.setPen(QColor("white"))
            painter.drawText(badge, Qt.AlignmentFlag.AlignCenter, "HIT")
        elif bool(item.data(COMBAT_CANCEL_ROLE)):
            badge = QRectF(max(4, display.width() - 30), max(4, display.height() - 24), 26, 20)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(8, 145, 178, 235))
            painter.drawRoundedRect(badge, 3, 3)
            painter.setPen(QColor("white"))
            painter.drawText(badge, Qt.AlignmentFlag.AlignCenter, "C")

        painter.end()
        blocked = self.frame_list.blockSignals(True)
        try:
            item.setIcon(QIcon(display))
        finally:
            self.frame_list.blockSignals(blocked)

    def frame_quality_tooltip(self, index, frame) -> str:
        text = super().frame_quality_tooltip(index, frame)
        notes = []
        if self.motion_analysis is not None:
            if index in self.motion_analysis.jolt_indices:
                notes.append("動作分析：此格前方 transition 為 movement spike")
            recommendation = self.motion_analysis.recommended
            if recommendation is not None and recommendation.start <= index <= recommendation.end:
                notes.append("動作分析：位於建議保留範圍")
        if self.combat_timeline is not None:
            selected = self._selected_extraction_indices()
            if index in selected:
                order = selected.index(index)
                phase = self.combat_timeline.phase_for_index(order)
                notes.append(f"戰鬥時間軸：第 {order + 1} 格 / {phase}")
                if order in self.combat_timeline.hit_frames:
                    notes.append("戰鬥時間軸：Hit frame")
                if self.combat_timeline.cancel_frame == order:
                    notes.append("戰鬥時間軸：Cancel frame")
        return text + ("\n" + "\n".join(notes) if notes else "")

    def _project_payload(self) -> dict:
        selected_indices = self._selected_extraction_indices()
        selected_frames = [self.frames[index] for index in selected_indices if 0 <= index < len(self.frames)]
        metadata = self.metadata
        return {
            "schema": "SpriteMakerPySide.video-curation",
            "schema_version": 2,
            "app_branch": "4.0.1",
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
            "combat_timeline": self.combat_timeline.to_dict() if self.combat_timeline else None,
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
            QMessageBox.warning(self, "格式不符", "這不是 SpriteMakerPySide 的 video-curation 專案。")
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
        self._suppress_timeline_invalidation = True
        self.frame_list.blockSignals(True)
        try:
            for row in range(self.frame_list.count()):
                item = self.frame_list.item(row)
                index = item.data(Qt.ItemDataRole.UserRole)
                item.setCheckState(Qt.CheckState.Checked if index is not None and int(index) in selection else Qt.CheckState.Unchecked)
        finally:
            self.frame_list.blockSignals(False)
            self._suppress_timeline_invalidation = False
        super().on_frame_check_changed()
        self._refresh_combat_control_ranges()

        analysis_payload = payload.get("motion_analysis")
        if isinstance(analysis_payload, dict):
            self.motion_analysis = MotionAnalysisResult.from_dict(analysis_payload)
            self.motion_apply_button.setEnabled(self.motion_analysis.recommended is not None)
            self.motion_summary.setText(self._motion_summary_text(self.motion_analysis))

        timeline_payload = payload.get("combat_timeline")
        if isinstance(timeline_payload, dict):
            try:
                timeline = CombatTimeline.from_dict(timeline_payload)
                if timeline.frame_count != len(self._selected_extraction_indices()):
                    raise ValueError("project.json 的戰鬥時間軸 frame_count 與目前選格數不一致。")
                self._write_timeline_to_controls(timeline)
                self._set_combat_timeline(timeline)
            except ValueError as exc:
                self._set_combat_timeline(None, f"戰鬥時間軸未還原：{exc}")
        else:
            self._set_combat_timeline(None)

        self.refresh_frame_list()
        self.show_animation_frame(0)

    def export_animation_json(self) -> None:
        timeline = self.combat_timeline
        if timeline is None:
            QMessageBox.information(self, "尚未建立時間軸", "請先使用「依動作自動分段」或「套用時間軸」。")
            return
        selected_indices = self._selected_extraction_indices()
        if len(selected_indices) != timeline.frame_count:
            self._set_combat_timeline(None, "選格數與時間軸不一致；請重新分段。")
            QMessageBox.warning(self, "時間軸已失效", "選格數與時間軸不一致，請重新建立時間軸。")
            return
        selected_frames = [self.frames[index] for index in selected_indices]
        try:
            manifest = build_animation_manifest(
                timeline,
                extraction_indices=selected_indices,
                source_indices=[frame.source_index for frame in selected_frames],
                timestamps=[frame.timestamp for frame in selected_frames],
                motion_analysis=self.motion_analysis.to_dict() if self.motion_analysis else None,
            )
        except ValueError as exc:
            QMessageBox.warning(self, "無法輸出 metadata", str(exc))
            return
        if self.video_path is not None:
            default = self.video_path.parent / f"{timeline.animation_name}.animation.json"
        else:
            default = self.initial_directory / f"{timeline.animation_name}.animation.json"
        path, _ = QFileDialog.getSaveFileName(self, "匯出 Runtime Animation Metadata", str(default), "Animation JSON (*.json);;JSON (*.json)")
        if not path:
            return
        try:
            Path(path).write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        except OSError as exc:
            QMessageBox.warning(self, "匯出失敗", str(exc))
            return
        QMessageBox.information(self, "匯出完成", f"已輸出 {Path(path).name}\nindex_base = 0，可直接由遊戲 runtime 讀取。")
