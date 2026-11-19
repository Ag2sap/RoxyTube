#!/usr/bin/env python3
"""Roxy YouTube TV - PySide6 frontend for yt-dlp + mpv."""
from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path

from PySide6.QtCore import Qt, QEvent, QProcess, QUrl, QSize
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkRequest
from PySide6.QtWidgets import (
    QApplication, QComboBox, QDialog, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QListWidget,
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
    defaults = {"margin_left": 5, "margin_right": 5, "margin_top": 5, "margin_bottom": 5}
    try:
        data = json.loads(SAFE_AREA_FILE.read_text(encoding="utf-8"))
        for key in defaults:
            defaults[key] = max(0.0, min(15.0, float(data.get(key, defaults[key]))))
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        pass
    return defaults


def video_url(entry):
    """Normalize flat-playlist IDs and relative YouTube URLs."""
    candidate = entry.get("webpage_url") or entry.get("url")
    video_id = entry.get("id")
    if candidate and candidate.startswith(("http://", "https://")):
        return candidate
    if video_id:
        return f"https://www.youtube.com/watch?v={video_id}"
    if candidate and len(candidate) >= 8 and "/" not in candidate:
        return f"https://www.youtube.com/watch?v={candidate}"
    return None



class VirtualKeyboardDialog(QDialog):
    """Large on-screen keyboard designed for D-pad navigation."""
    def __init__(self, target, parent=None):
        super().__init__(parent)
        self.target = target
        self.setWindowTitle("Keyboard Roxy")
        self.setMinimumSize(600, 390)
        self.setStyleSheet("""
            QDialog { background:#151b24; color:white; }
            QPushButton { background:#303c4d; color:white; border:2px solid #536176;
                border-radius:7px; padding:9px; font-size:18px; min-width:34px; min-height:34px; }
            QPushButton:focus { background:#526781; border:3px solid #ffd166; }
        """)
        layout = QVBoxLayout(self)
        self.preview = QLineEdit(target.text())
        self.preview.setReadOnly(True)
        self.preview.setStyleSheet("font-size:20px; padding:9px;")
        layout.addWidget(self.preview)
        grid = QGridLayout()
        grid.setSpacing(5)
        layout.addLayout(grid)
        rows = ["1234567890", "QWERTYUIOP", "ASDFGHJKL", "ZXCVBNM"]
        first_key = None
        for row_index, chars in enumerate(rows):
            offset = 0 if row_index < 2 else (1 if row_index == 2 else 2)
            for col, char in enumerate(chars):
                button = QPushButton(char)
                button.clicked.connect(lambda checked=False, key=char: self.add_text(key))
                grid.addWidget(button, row_index, col + offset)
                if first_key is None:
                    first_key = button
        actions = [
            ("SPASI", lambda: self.add_text(" "), 4),
            ("HAPUS", self.backspace, 2),
            ("KOSONGKAN", self.clear_text, 2),
            ("BATAL", self.reject, 2),
            ("SELESAI", self.accept, 2),
        ]
        row_index = len(rows)
        for label, callback, span in actions:
            button = QPushButton(label)
            button.clicked.connect(callback)
            grid.addWidget(button, row_index, 0, 1, span)
            row_index += 1
        if first_key:
            first_key.setFocus()

    def add_text(self, value):
        self.preview.setText(self.preview.text() + value)

    def backspace(self):
        self.preview.setText(self.preview.text()[:-1])

    def clear_text(self):
        self.preview.clear()

    def accept(self):
        self.target.setText(self.preview.text())
        super().accept()


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.resize(960, 720)
        self.setMinimumSize(640, 480)
        self.results = []
        self.search_process = None
        self.player_process = None
        self.network = QNetworkAccessManager(self)
        self.thumbnail_items = {}
        self.root_layout = QVBoxLayout()
        self.root_layout.setSpacing(12)
        self.setStyleSheet("""
            QMainWindow, QWidget { background:#101318; color:#f4f6f8; font-family:Sans; }
            QLabel#brand { color:#ff4545; font-size:27px; font-weight:800; }
            QLabel#hint { color:#aeb8c5; font-size:14px; }
            QLineEdit,QComboBox { background:#202733; color:white; border:2px solid #465366;
                border-radius:8px; padding:10px; font-size:17px; min-height:28px; }
            QPushButton { background:#d92727; color:white; border:2px solid transparent;
                border-radius:8px; padding:10px 18px; font-size:17px; font-weight:700; }
            QPushButton:focus,QLineEdit:focus,QComboBox:focus,QListWidget:focus {
                border:3px solid #ffd166; }
            QListWidget { background:#171d26; border:1px solid #394454; border-radius:10px;
                padding:6px; font-size:16px; }
            QListWidget::item { padding:9px; border-bottom:1px solid #303a49; min-height:66px; }
            QListWidget::item:selected { background:#35465d; color:white; }
        """)

        brand = QLabel("ROXY  /  YouTube")
        brand.setObjectName("brand")
        self.root_layout.addWidget(brand)
        hint = QLabel("Cari video YouTube • navigasi dengan tombol arah / remote")
        hint.setObjectName("hint")
        self.root_layout.addWidget(hint)
        top_row = QHBoxLayout()
        top_row.addStretch(1)
        self.minimize_button = QPushButton("MINIMIZE")
        self.minimize_button.clicked.connect(self.showMinimized)
        top_row.addWidget(self.minimize_button)
        self.root_layout.addLayout(top_row)

        search_row = QHBoxLayout()
        self.query = QLineEdit()
        self.query.setPlaceholderText("Masukkan kata pencarian atau URL YouTube…")
        self.query.returnPressed.connect(self.search)
        self.keyboard_button = QPushButton("KEYBOARD")
        self.keyboard_button.clicked.connect(self.open_keyboard)
        self.search_button = QPushButton("CARI")
        self.search_button.clicked.connect(self.search)
        search_row.addWidget(self.query, 1)
        search_row.addWidget(self.keyboard_button)
        search_row.addWidget(self.search_button)
        self.root_layout.addLayout(search_row)

        quality_row = QHBoxLayout()
        quality_row.addWidget(QLabel("Kualitas video:"))
        self.quality = QComboBox()
        self.quality.addItems(list(QUALITY_FORMATS))
        self.quality.setMaximumWidth(180)
        quality_row.addWidget(self.quality)
        quality_row.addStretch(1)
        self.root_layout.addLayout(quality_row)

        self.list = QListWidget()
        self.list.setIconSize(QSize(112, 64))
        self.list.setWordWrap(True)
        self.list.itemActivated.connect(self.play_selected)
        self.root_layout.addWidget(self.list, 1)

        bottom = QHBoxLayout()
        self.play_button = QPushButton("PUTAR")
        self.play_button.clicked.connect(self.play_selected)
        self.stop_button = QPushButton("STOP")
        self.stop_button.setEnabled(False)
        self.stop_button.clicked.connect(self.stop_player)
        self.status = QLabel("Siap. Masukkan pencarian atau URL video.")
        self.status.setObjectName("hint")
        self.status.setWordWrap(True)
        bottom.addWidget(self.play_button)
        bottom.addWidget(self.stop_button)
        bottom.addWidget(self.status, 1)
        self.root_layout.addLayout(bottom)

        root = QWidget()
        root.setLayout(self.root_layout)
        self.setCentralWidget(root)
        self.apply_safe_area()
        self.query.setFocus()
        QApplication.instance().installEventFilter(self)
        self.setTabOrder(self.query, self.keyboard_button)
        self.setTabOrder(self.keyboard_button, self.search_button)
        self.setTabOrder(self.search_button, self.quality)
        self.setTabOrder(self.quality, self.list)
        self.setTabOrder(self.list, self.play_button)
        self.setTabOrder(self.play_button, self.stop_button)
        self.setTabOrder(self.stop_button, self.minimize_button)

    def open_keyboard(self):
        dialog = VirtualKeyboardDialog(self.query, self)
        dialog.exec()
        self.query.setFocus()

    def apply_safe_area(self):
        m = safe_area_margins()
        w, h = max(1, self.width()), max(1, self.height())
        self.root_layout.setContentsMargins(
            round(w * m["margin_left"] / 100),
            round(h * m["margin_top"] / 100),
            round(w * m["margin_right"] / 100),
            round(h * m["margin_bottom"] / 100),
        )

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.apply_safe_area()

    def search(self):
        term = self.query.text().strip()
        if not term:
            self.status.setText("Masukkan kata pencarian atau URL.")
            return
        if not shutil.which(YTDLP):
            QMessageBox.critical(self, APP_NAME, f"yt-dlp tidak ditemukan: {YTDLP}")
            return
        if self.search_process and self.search_process.state() != QProcess.NotRunning:
            self.search_process.kill()
        self.search_button.setEnabled(False)
        self.list.clear()
        self.results = []
        self.thumbnail_items.clear()
        self.status.setText("Mencari video…")
        target = term if term.startswith(("http://", "https://")) else f"ytsearch12:{term}"
        process = QProcess(self)
        self.search_process = process
        process.setProgram(YTDLP)
        process.setArguments(["--no-warnings", "--flat-playlist", "--dump-single-json", target])
        process.finished.connect(lambda code, status, p=process: self.search_finished(p, code, status))
        process.errorOccurred.connect(lambda _err, p=process: self.search_error(p))
        process.start()

    def search_error(self, process):
        if process is self.search_process:
            self.search_button.setEnabled(True)
            self.status.setText("Tidak dapat menjalankan yt-dlp. Periksa instalasi dan PATH.")

    def search_finished(self, process, exit_code, _exit_status):
        raw = bytes(process.readAllStandardOutput()).decode("utf-8", "replace")
        err = bytes(process.readAllStandardError()).decode("utf-8", "replace")
        if process is not self.search_process:
            return
        self.search_button.setEnabled(True)
        if exit_code != 0 or not raw.strip():
            self.status.setText("Pencarian gagal. Periksa koneksi / yt-dlp.")
            if err.strip():
                QMessageBox.warning(self, APP_NAME, err[-1800:])
            return
        try:
            data = json.loads(raw)
            entries = data.get("entries") or [data]
            for entry in entries:
                if not entry:
                    continue
                url = video_url(entry)
                if not url:
                    continue
                title = entry.get("title") or "Video tanpa judul"
                channel = entry.get("channel") or entry.get("uploader") or "YouTube"
                duration = entry.get("duration")
                duration_text = f"  •  {int(duration)//60}:{int(duration)%60:02d}" if duration else ""
                result = {"url": url, "title": title, "thumbnail": entry.get("thumbnail")}
                self.results.append(result)
                item = QListWidgetItem(f"{title}\n{channel}{duration_text}")
                item.setData(Qt.UserRole, len(self.results) - 1)
                self.list.addItem(item)
                if result["thumbnail"]:
                    self.thumbnail_items[result["thumbnail"]] = item
                    request = QNetworkRequest(QUrl(result["thumbnail"]))
                    request.setTransferTimeout(12000)
                    reply = self.network.get(request)
                    reply.finished.connect(lambda r=reply, u=result["thumbnail"]: self.thumbnail_loaded(r, u))
        except (json.JSONDecodeError, TypeError, ValueError) as exc:
            self.status.setText(f"Format hasil tidak dikenali: {exc}")
            return
        self.status.setText(f"{len(self.results)} hasil ditemukan.")
        if self.results:
            self.list.setCurrentRow(0)
            self.list.setFocus()

    def thumbnail_loaded(self, reply, url):
        item = self.thumbnail_items.get(url)
        if item is not None and reply.error() == reply.NetworkError.NoError:
            pixmap = QPixmap()
            if pixmap.loadFromData(reply.readAll()):
                item.setIcon(QIcon(pixmap.scaled(112, 64, Qt.KeepAspectRatio, Qt.SmoothTransformation)))
        reply.deleteLater()

    def play_selected(self):
        item = self.list.currentItem()
        if item is None:
            self.status.setText("Pilih video terlebih dahulu.")
            return
        video = self.results[item.data(Qt.UserRole)]
        if not shutil.which(MPV):
            QMessageBox.critical(self, APP_NAME, f"mpv tidak ditemukan: {MPV}")
            return
        if self.player_process and self.player_process.state() != QProcess.NotRunning:
            self.player_process.terminate()
        fmt = QUALITY_FORMATS[self.quality.currentText()]
        process = QProcess(self)
        self.player_process = process
        process.setProgram(MPV)
        process.setArguments(["--force-window=yes", f"--ytdl-format={fmt}", video["url"]])
        process.started.connect(lambda p=process: self.player_started(p, video["title"]))
        process.finished.connect(lambda code, _status, p=process: self.player_finished(p, code))
        process.errorOccurred.connect(lambda _err, p=process: self.player_error(p))
        process.start()
        self.status.setText(f"Menyiapkan: {video['title']}")

    def player_started(self, process, title):
        if process is self.player_process:
            self.stop_button.setEnabled(True)
            self.status.setText(f"Sedang diputar: {title} • Tutup jendela MPV atau tekan STOP untuk kembali.")

    def player_finished(self, process, exit_code):
        if process is self.player_process:
            self.stop_button.setEnabled(False)
            self.status.setText("Pemutaran selesai. Daftar video siap.")
        process.deleteLater()

    def player_error(self, process):
        if process is self.player_process:
            self.stop_button.setEnabled(False)
            self.status.setText("MPV tidak dapat dijalankan. Periksa instalasi MPV.")

    def stop_player(self):
        if self.player_process and self.player_process.state() != QProcess.NotRunning:
            self.status.setText("Menghentikan pemutaran…")
            self.player_process.terminate()
            self.stop_button.setEnabled(False)

    def closeEvent(self, event):
        for process in (self.search_process, self.player_process):
            if process and process.state() != QProcess.NotRunning:
                process.terminate()
        super().closeEvent(event)

    def eventFilter(self, watched, event):
        # Central D-pad routing keeps navigation predictable across child widgets.
        if event.type() != QEvent.KeyPress or not self.isActiveWindow():
            return super().eventFilter(watched, event)
        focus = QApplication.focusWidget()
        if focus is None:
            return super().eventFilter(watched, event)
        key = event.key()

        if focus is self.query:
            if key == Qt.Key_Down:
                self.quality.setFocus()
                return True
            if key == Qt.Key_Right and self.query.cursorPosition() >= len(self.query.text()):
                self.keyboard_button.setFocus()
                return True
        elif focus is self.keyboard_button:
            if key == Qt.Key_Left:
                self.query.setFocus()
                return True
            if key == Qt.Key_Right:
                self.search_button.setFocus()
                return True
            if key == Qt.Key_Down:
                self.quality.setFocus()
                return True
        elif focus is self.search_button:
            if key == Qt.Key_Left:
                self.keyboard_button.setFocus()
                return True
            if key == Qt.Key_Down:
                self.quality.setFocus()
                return True
        elif focus is self.quality:
            if key == Qt.Key_Up:
                self.search_button.setFocus()
                return True
            if key == Qt.Key_Down and self.list.count():
                self.list.setFocus()
                if self.list.currentRow() < 0:
                    self.list.setCurrentRow(0)
                return True
            if key == Qt.Key_Right:
                self.play_button.setFocus()
                return True
        elif focus is self.list:
            if key == Qt.Key_Up and self.list.currentRow() <= 0:
                self.quality.setFocus()
                return True
            if key == Qt.Key_Down and self.list.currentRow() >= self.list.count() - 1:
                self.play_button.setFocus()
                return True
            if key == Qt.Key_Right:
                self.play_button.setFocus()
                return True
        elif focus is self.play_button:
            if key == Qt.Key_Left:
                self.quality.setFocus()
                return True
            if key == Qt.Key_Right and self.stop_button.isEnabled():
                self.stop_button.setFocus()
                return True
            if key == Qt.Key_Up and self.list.count():
                self.list.setFocus()
                if self.list.currentRow() < 0:
                    self.list.setCurrentRow(0)
                return True
        elif focus is self.stop_button:
            if key == Qt.Key_Left:
                self.play_button.setFocus()
                return True
            if key == Qt.Key_Up and self.list.count():
                self.list.setFocus()
                return True
        return super().eventFilter(watched, event)

    def keyPressEvent(self, event):
        key = event.key()
        if key == Qt.Key_Escape:
            self.query.setFocus()
            return
        if key == Qt.Key_Down and self.query.hasFocus():
            self.list.setFocus()
            if self.list.count() and self.list.currentRow() < 0:
                self.list.setCurrentRow(0)
            return
        if key == Qt.Key_Up and self.list.hasFocus() and self.list.currentRow() == 0:
            self.quality.setFocus()
            return
        if key == Qt.Key_Down and self.quality.hasFocus():
            self.list.setFocus()
            if self.list.count():
                self.list.setCurrentRow(0)
            return
        if key == Qt.Key_Right and self.query.hasFocus():
            self.search_button.setFocus()
            return
        if key == Qt.Key_Left and self.search_button.hasFocus():
            self.query.setFocus()
            return
        if key == Qt.Key_Right and self.quality.hasFocus():
            self.play_button.setFocus()
            return
        if key == Qt.Key_Left and self.play_button.hasFocus():
            self.quality.setFocus()
            return
        super().keyPressEvent(event)


def main():
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
