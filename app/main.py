#!/usr/bin/env python3
"""Roxy YouTube TV - lightweight PySide6 frontend for yt-dlp + mpv."""
from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path

from PySide6.QtCore import Qt, QProcess
from PySide6.QtWidgets import (
    QApplication, QComboBox, QHBoxLayout, QLabel, QLineEdit, QListWidget,
    QListWidgetItem, QMainWindow, QMessageBox, QPushButton, QVBoxLayout, QWidget,
)

APP_NAME = "Roxy YouTube TV"
CONFIG_DIR = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
SAFE_AREA_FILE = CONFIG_DIR / "roxy-display" / "safe-area.json"
YTDLP = os.environ.get("ROXY_YT_DLP", "yt-dlp")
MPV = os.environ.get("ROXY_MPV", "mpv")
QUALITY_FORMATS = {
    "Auto": "best",
    "360p": "best[height<=360]",
    "480p": "best[height<=480]",
    "720p": "best[height<=720]",
}


def safe_area_margins():
    values = {"margin_left": 5, "margin_right": 5, "margin_top": 5, "margin_bottom": 5}
    try:
        data = json.loads(SAFE_AREA_FILE.read_text(encoding="utf-8"))
        for key in values:
            values[key] = max(0.0, min(15.0, float(data.get(key, values[key]))))
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        pass
    return values


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.resize(960, 720)
        self.setMinimumSize(640, 480)
        self.results = []
        self.search_process = None
        self.player_process = None
        m = safe_area_margins()
        layout = QVBoxLayout()
        layout.setContentsMargins(
            int(960 * m["margin_left"] / 100), int(720 * m["margin_top"] / 100),
            int(960 * m["margin_right"] / 100), int(720 * m["margin_bottom"] / 100),
        )
        layout.setSpacing(14)
        self.setStyleSheet("""
            QMainWindow, QWidget { background:#101318; color:#f4f6f8; font-family:Sans; }
            QLabel#brand { color:#ff4545; font-size:28px; font-weight:800; }
            QLabel#hint { color:#aeb8c5; font-size:14px; }
            QLineEdit,QComboBox { background:#202733; color:white; border:2px solid #465366;
                border-radius:8px; padding:12px; font-size:18px; min-height:28px; }
            QPushButton { background:#d92727; color:white; border:0; border-radius:8px;
                padding:12px 20px; font-size:17px; font-weight:700; }
            QPushButton:focus,QLineEdit:focus,QComboBox:focus,QListWidget:focus { border:3px solid #ffd166; }
            QListWidget { background:#171d26; border:1px solid #394454; border-radius:10px;
                padding:8px; font-size:17px; }
            QListWidget::item { padding:14px; border-bottom:1px solid #303a49; }
            QListWidget::item:selected { background:#35465d; color:white; }
        """)
        brand = QLabel("ROXY  /  YouTube")
        brand.setObjectName("brand")
        layout.addWidget(brand)
        hint = QLabel("Cari video YouTube • pilih hasil • putar dengan MPV")
        hint.setObjectName("hint")
        layout.addWidget(hint)

        search_row = QHBoxLayout()
        self.query = QLineEdit()
        self.query.setPlaceholderText("Masukkan kata pencarian atau URL YouTube…")
        self.query.returnPressed.connect(self.search)
        self.search_button = QPushButton("CARI")
        self.search_button.clicked.connect(self.search)
        search_row.addWidget(self.query, 1)
        search_row.addWidget(self.search_button)
        layout.addLayout(search_row)

        quality_row = QHBoxLayout()
        quality_row.addWidget(QLabel("Kualitas video:"))
        self.quality = QComboBox()
        self.quality.addItems(list(QUALITY_FORMATS))
        quality_row.addWidget(self.quality)
        quality_row.addStretch(1)
        layout.addLayout(quality_row)

        self.list = QListWidget()
        self.list.itemActivated.connect(self.play_selected)
        layout.addWidget(self.list, 1)
        bottom = QHBoxLayout()
        self.play_button = QPushButton("PUTAR")
        self.play_button.clicked.connect(self.play_selected)
        self.status = QLabel("Siap. Masukkan pencarian atau URL video.")
        self.status.setObjectName("hint")
        bottom.addWidget(self.play_button)
        bottom.addWidget(self.status, 1)
        layout.addLayout(bottom)
        root = QWidget()
        root.setLayout(layout)
        self.setCentralWidget(root)
        self.query.setFocus()

    def search(self):
        term = self.query.text().strip()
        if not term:
            self.status.setText("Masukkan kata pencarian atau URL.")
            return
        if not shutil.which(YTDLP):
            QMessageBox.critical(self, APP_NAME, f"yt-dlp tidak ditemukan: {YTDLP}")
            return
        self.search_button.setEnabled(False)
        self.list.clear()
        self.results = []
        self.status.setText("Mencari…")
        target = term if term.startswith(("http://", "https://")) else f"ytsearch12:{term}"
        self.search_process = QProcess(self)
        self.search_process.setProgram(YTDLP)
        self.search_process.setArguments(["--no-warnings", "--flat-playlist", "--dump-single-json", target])
        self.search_process.finished.connect(self.search_finished)
        self.search_process.start()

    def search_finished(self, exit_code, _exit_status):
        self.search_button.setEnabled(True)
        raw = bytes(self.search_process.readAllStandardOutput()).decode("utf-8", "replace")
        err = bytes(self.search_process.readAllStandardError()).decode("utf-8", "replace")
        if exit_code != 0 or not raw.strip():
            self.status.setText("Pencarian gagal. Periksa koneksi / yt-dlp.")
            if err.strip():
                QMessageBox.warning(self, APP_NAME, err[-1800:])
            return
        try:
            data = json.loads(raw)
            for entry in (data.get("entries") or [data]):
                if not entry:
                    continue
                video_id = entry.get("id")
                url = entry.get("url") or entry.get("webpage_url")
                if not url and video_id:
                    url = f"https://www.youtube.com/watch?v={video_id}"
                if not url:
                    continue
                title = entry.get("title") or "Video tanpa judul"
                channel = entry.get("channel") or entry.get("uploader") or "YouTube"
                duration = entry.get("duration")
                duration_text = f"  •  {int(duration)//60}:{int(duration)%60:02d}" if duration else ""
                self.results.append({"url": url, "title": title})
                item = QListWidgetItem(f"{title}\n{channel}{duration_text}")
                item.setData(Qt.UserRole, len(self.results) - 1)
                self.list.addItem(item)
        except (json.JSONDecodeError, TypeError, ValueError) as exc:
            self.status.setText(f"Format hasil tidak dikenali: {exc}")
            return
        self.status.setText(f"{len(self.results)} hasil ditemukan.")
        if self.results:
            self.list.setCurrentRow(0)
            self.list.setFocus()

    def play_selected(self):
        item = self.list.currentItem()
        if item is None:
            return
        video = self.results[item.data(Qt.UserRole)]
        if not shutil.which(MPV):
            QMessageBox.critical(self, APP_NAME, f"mpv tidak ditemukan: {MPV}")
            return
        fmt = QUALITY_FORMATS[self.quality.currentText()]
        self.player_process = QProcess(self)
        self.player_process.setProgram(MPV)
        self.player_process.setArguments(["--force-window=yes", f"--ytdl-format={fmt}", video["url"]])
        self.player_process.start()
        self.status.setText(f"Membuka: {video['title']}")

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self.query.setFocus()
            return
        if event.key() in (Qt.Key_Return, Qt.Key_Enter) and self.list.hasFocus():
            self.play_selected()
            return
        super().keyPressEvent(event)


def main():
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
