from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QPushButton, QVBoxLayout


class StartupDialog(QDialog):
    EDIT = "edit"
    VIDEO = "video"

    def __init__(self) -> None:
        super().__init__()
        self.choice = self.EDIT
        self.setWindowTitle("SpriteMaker PySide")
        self.setFixedSize(520, 240)

        title = QLabel("SpriteMaker PySide")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet("font-size: 24px; font-weight: 700;")

        subtitle = QLabel("請選擇要開始的工作流程")
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)

        video_button = QPushButton("匯入影片 / GIF")
        video_button.setMinimumHeight(56)
        video_button.clicked.connect(self.choose_video)

        edit_button = QPushButton("進入編輯模式")
        edit_button.setMinimumHeight(56)
        edit_button.clicked.connect(self.choose_edit)

        row = QHBoxLayout()
        row.addWidget(video_button)
        row.addWidget(edit_button)

        layout = QVBoxLayout(self)
        layout.addStretch(1)
        layout.addWidget(title)
        layout.addWidget(subtitle)
        layout.addSpacing(16)
        layout.addLayout(row)
        layout.addStretch(1)

    def choose_video(self) -> None:
        self.choice = self.VIDEO
        self.accept()

    def choose_edit(self) -> None:
        self.choice = self.EDIT
        self.accept()
