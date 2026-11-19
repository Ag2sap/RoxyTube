#!/usr/bin/env python3
"""Roxy YouTube TV - single-layer TV interface for yt-dlp + mpv."""
from __future__ import annotations
import json, os, shutil, sys
from pathlib import Path
from PySide6.QtCore import Qt, QEvent, QProcess, QPropertyAnimation, QEasingCurve, QUrl
from PySide6.QtGui import QPixmap
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkRequest
from PySide6.QtWidgets import (
    QApplication, QComboBox, QFrame, QGridLayout, QHBoxLayout, QLabel,
    QLineEdit, QMainWindow, QMessageBox, QPushButton, QScrollArea,
    QSizePolicy, QVBoxLayout, QWidget,
)

APP_NAME = "Roxy YouTube TV"
CONFIG_DIR = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
SAFE_AREA_FILE = CONFIG_DIR / "roxy-display" / "safe-area.json"
YTDLP = os.environ.get("ROXY_YT_DLP", "yt-dlp")
MPV = os.environ.get("ROXY_MPV", "mpv")
QUALITY_FORMATS = {"Auto": "best", "360p": "best[height<=360]",
                   "480p": "best[height<=480]", "720p": "best[height<=720]"}


def safe_area_margins():
    values = {"margin_left": 4, "margin_right": 4, "margin_top": 4, "margin_bottom": 4}
    try:
        data = json.loads(SAFE_AREA_FILE.read_text(encoding="utf-8"))
        for key in values:
            values[key] = max(0.0, min(15.0, float(data.get(key, values[key]))))
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        pass
    return values


def video_url(entry):
    candidate, video_id = entry.get("webpage_url") or entry.get("url"), entry.get("id")
    if candidate and candidate.startswith(("http://", "https://")):
        return candidate
    if video_id:
        return f"https://www.youtube.com/watch?v={video_id}"
    if candidate and len(candidate) >= 8 and "/" not in candidate:
        return f"https://www.youtube.com/watch?v={candidate}"
    return None


class VideoCard(QFrame):
    def __init__(self, index, title, channel, duration, parent=None):
        super().__init__(parent)
        self.index = index
        self.on_activate = None
        self.setObjectName("videoCard")
        self.setFocusPolicy(Qt.StrongFocus)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setStyleSheet("""
            QFrame#videoCard { background:#1a202a; border:2px solid #303b4a; border-radius:9px; }
            QFrame#videoCard:focus { border:3px solid #ffd166; background:#29384b; }
        """)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(7, 7, 7, 7)
        layout.setSpacing(4)
        self.image = QLabel("Memuat thumbnail…")
        self.image.setAlignment(Qt.AlignCenter)
        self.image.setMinimumHeight(90)
        self.image.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.image.setStyleSheet("background:#252e3b;color:#9ba8b8;border:0;font-size:12px;")
        layout.addWidget(self.image, 1)
        self.title_label = QLabel(title)
        self.title_label.setWordWrap(True)
        self.title_label.setMaximumHeight(38)
        self.title_label.setStyleSheet("font-size:14px;font-weight:700;color:#f4f6f8;border:0;")
        layout.addWidget(self.title_label)
        self.meta_label = QLabel(f"{channel}  •  {duration}" if duration else channel)
        self.meta_label.setStyleSheet("font-size:11px;color:#aeb8c5;border:0;")
        layout.addWidget(self.meta_label)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.image.setFixedHeight(max(90, int((self.width() - 24) * 9 / 16)))

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton and callable(self.on_activate):
            self.on_activate(self.index)
        super().mousePressEvent(event)

    def set_thumbnail(self, pixmap):
        if pixmap.isNull():
            return
        self.image.setText("")
        self.image.setPixmap(pixmap.scaled(max(1, self.image.width()),
            max(1, self.image.height()), Qt.KeepAspectRatio, Qt.SmoothTransformation))


class TvKeyboard(QWidget):
    def __init__(self, target, on_finish, parent=None):
        super().__init__(parent)
        self.target, self.on_finish = target, on_finish
        self.caps_locked, self.shift_once, self.symbol_mode = False, False, False
        self.buttons = []
        self.setObjectName("keyboardPanel")
        self.setStyleSheet("""
            QWidget#keyboardPanel { background:#151c26; border:1px solid #354253; border-radius:9px; }
            QPushButton { background:#303d4e; color:#f7f8fa; border:2px solid #536176;
                border-radius:6px; padding:3px 2px; font-size:14px; font-weight:700; min-height:27px; }
            QPushButton:focus { background:#526781; border:3px solid #ffd166; }
        """)
        self.box = QVBoxLayout(self)
        self.box.setContentsMargins(7, 7, 7, 7)
        self.box.setSpacing(4)
        self.build_keys()

    def build_keys(self):
        while self.box.count():
            item = self.box.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self.buttons = []
        grid = QGridLayout()
        grid.setSpacing(4)
        for c in range(10):
            grid.setColumnStretch(c, 1)

        def key(label, row, col, span=1, callback=None):
            button = QPushButton(label)
            button.setFocusPolicy(Qt.StrongFocus)
            button.clicked.connect(callback or (lambda checked=False, v=label: self.insert(v)))
            grid.addWidget(button, row, col, 1, span)
            self.buttons.append(button)
            return button

        if not self.symbol_mode:
            for r, chars in enumerate(("1234567890", "QWERTYUIOP", "ASDFGHJKL")):
                offset = 1 if r == 2 else 0
                for c, char in enumerate(chars):
                    shown = char.upper() if self.caps_locked or self.shift_once else char.lower()
                    key(shown, r, c + offset)
            key("SHIFT", 3, 0, 2, self.toggle_shift)
            for c, char in enumerate("ZXCVBNM"):
                shown = char.upper() if self.caps_locked or self.shift_once else char.lower()
                key(shown, 3, c + 2)
            key("⌫", 3, 9, callback=self.backspace)
            key("?123", 4, 0, 2, self.toggle_symbols)
            key(",", 4, 2)
            key("SPASI", 4, 3, 4, lambda: self.insert(" "))
            key(".", 4, 7)
            key("CAPS", 4, 8, callback=self.toggle_caps)
            key("SELESAI", 4, 9, callback=self.finish)
        else:
            for r, chars in enumerate(("1234567890", "!@#$%^&*()", "[]{}<>?/+=")):
                for c, char in enumerate(chars):
                    key(char, r, c)
            key("ABC", 3, 0, 2, self.toggle_symbols)
            key("-", 3, 2)
            key("_", 3, 3)
            key(":", 3, 4)
            key(";", 3, 5)
            key("'", 3, 6)
            key('"', 3, 7)
            key("⌫", 3, 8, 2, self.backspace)
            key("KOSONGKAN", 4, 0, 2, self.clear_text)
            key(",", 4, 2)
            key("SPASI", 4, 3, 3, lambda: self.insert(" "))
            key(".", 4, 6)
            key("CAPS", 4, 7, callback=self.toggle_caps)
            key("SELESAI", 4, 8, 2, self.finish)
        self.box.addLayout(grid)
        if self.buttons:
            self.buttons[0].setFocus()

    def insert(self, value):
        if len(value) == 1 and value.isalpha():
            value = value.upper() if (self.caps_locked or self.shift_once) else value.lower()
            self.shift_once = False
            self.build_keys()
        pos = self.target.cursorPosition()
        self.target.setText(self.target.text()[:pos] + value + self.target.text()[pos:])
        self.target.setCursorPosition(pos + len(value))

    def backspace(self):
        pos = self.target.cursorPosition()
        if pos:
            self.target.setText(self.target.text()[:pos - 1] + self.target.text()[pos:])
            self.target.setCursorPosition(pos - 1)

    def clear_text(self):
        self.target.clear()

    def toggle_caps(self):
        self.caps_locked = not self.caps_locked
        self.build_keys()

    def toggle_shift(self):
        self.shift_once = not self.shift_once
        self.build_keys()

    def toggle_symbols(self):
        self.symbol_mode = not self.symbol_mode
        self.build_keys()

    def finish(self):
        self.on_finish()


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.resize(700, 525)
        self.setMinimumSize(560, 420)
        self.setMaximumSize(900, 675)
        self.results, self.cards = [], []
        self.search_process = self.player_process = None
        self.network = QNetworkAccessManager(self)
        self.thumbnail_cards = {}
        self.safe_margins = safe_area_margins()
        self.keyboard_open = False
        self.keyboard_animation = None
        self.setStyleSheet("""
            QMainWindow, QWidget { background:#101318; color:#f4f6f8; font-family:Sans; }
            QLabel#brand { color:#ff4545; font-size:21px; font-weight:800; }
            QLabel#hint { color:#aeb8c5; font-size:11px; }
            QLineEdit,QComboBox { background:#202733; color:white; border:2px solid #465366;
                border-radius:7px; padding:6px 8px; font-size:14px; min-height:25px; }
            QPushButton { background:#d92727; color:white; border:2px solid transparent;
                border-radius:7px; padding:6px 11px; font-size:13px; font-weight:700; }
            QPushButton:focus,QLineEdit:focus,QComboBox:focus { border:3px solid #ffd166; }
            QScrollArea { border:0; background:transparent; }
            QScrollBar:vertical { width:12px; background:#171d26; }
            QScrollBar::handle:vertical { background:#526176; border-radius:5px; min-height:24px; }
        """)
        root = QWidget()
        self.root_layout = QVBoxLayout(root)
        self.root_layout.setSpacing(7)
        self.setCentralWidget(root)

        header = QHBoxLayout()
        brand = QLabel("ROXY  /  YouTube")
        brand.setObjectName("brand")
        header.addWidget(brand)
        header.addStretch(1)
        self.quality = QComboBox()
        self.quality.addItems(list(QUALITY_FORMATS))
        self.quality.setMaximumWidth(100)
        header.addWidget(QLabel("Kualitas"))
        header.addWidget(self.quality)
        self.root_layout.addLayout(header)

        search_row = QHBoxLayout()
        self.query = QLineEdit()
        self.query.setPlaceholderText("Cari video atau tempel URL YouTube…")
        self.query.returnPressed.connect(self.search)
        self.keyboard_button = QPushButton("⌨ KEYBOARD")
        self.keyboard_button.clicked.connect(self.toggle_keyboard)
        self.search_button = QPushButton("CARI")
        self.search_button.clicked.connect(self.search)
        search_row.addWidget(self.query, 1)
        search_row.addWidget(self.keyboard_button)
        search_row.addWidget(self.search_button)
        self.root_layout.addLayout(search_row)

        self.keyboard = TvKeyboard(self.query, self.finish_keyboard, self)
        self.keyboard.setVisible(False)
        self.keyboard.setMaximumHeight(0)
        self.root_layout.addWidget(self.keyboard)

        self.results_heading = QLabel("HASIL VIDEO")
        self.results_heading.setObjectName("hint")
        self.root_layout.addWidget(self.results_heading)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.cards_host = QWidget()
        self.cards_grid = QGridLayout(self.cards_host)
        self.cards_grid.setContentsMargins(2, 2, 2, 2)
        self.cards_grid.setSpacing(9)
        self.scroll.setWidget(self.cards_host)
        self.root_layout.addWidget(self.scroll, 1)

        footer = QHBoxLayout()
        self.play_button = QPushButton("PUTAR")
        self.play_button.clicked.connect(self.play_selected)
        self.play_button.setEnabled(False)
        self.stop_button = QPushButton("STOP")
        self.stop_button.clicked.connect(self.stop_player)
        self.stop_button.setEnabled(False)
        self.status = QLabel("Siap. Cari video menggunakan remote.")
        self.status.setObjectName("hint")
        self.status.setWordWrap(True)
        footer.addWidget(self.play_button)
        footer.addWidget(self.stop_button)
        footer.addWidget(self.status, 1)
        self.root_layout.addLayout(footer)

        self.apply_safe_area()
        self.query.setFocus()
        QApplication.instance().installEventFilter(self)
        self.setTabOrder(self.query, self.keyboard_button)
        self.setTabOrder(self.keyboard_button, self.search_button)
        self.setTabOrder(self.search_button, self.quality)
        self.setTabOrder(self.quality, self.play_button)
        self.setTabOrder(self.play_button, self.stop_button)

    def apply_safe_area(self):
        m, w, h = self.safe_margins, max(1, self.width()), max(1, self.height())
        self.root_layout.setContentsMargins(round(w*m["margin_left"]/100),
            round(h*m["margin_top"]/100), round(w*m["margin_right"]/100),
            round(h*m["margin_bottom"]/100))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.apply_safe_area()
        self.refresh_card_columns()

    def refresh_card_columns(self):
        columns = 2 if self.scroll.viewport().width() < 980 else 3
        for i, card in enumerate(self.cards):
            self.cards_grid.removeWidget(card)
            self.cards_grid.addWidget(card, i // columns, i % columns)

    def set_keyboard_visible(self, visible):
        visible = bool(visible)
        if visible == self.keyboard_open:
            return
        self.keyboard_open = visible
        self.keyboard_button.setText("⌨ TUTUP" if visible else "⌨ KEYBOARD")
        self.keyboard.setVisible(True)
        animation = QPropertyAnimation(self.keyboard, b"maximumHeight", self)
        animation.setDuration(220)
        animation.setStartValue(self.keyboard.maximumHeight())
        animation.setEndValue(205 if visible else 0)
        animation.setEasingCurve(QEasingCurve.OutCubic if visible else QEasingCurve.InCubic)
        if not visible:
            animation.finished.connect(lambda: self.keyboard.setVisible(False))
        self.keyboard_animation = animation
        animation.start()

    def finish_keyboard(self):
        self.set_keyboard_visible(False)
        self.query.setFocus()

    def toggle_keyboard(self):
        self.set_keyboard_visible(not self.keyboard_open)
        if self.keyboard_open and self.keyboard.buttons:
            self.keyboard.buttons[0].setFocus()
        else:
            self.query.setFocus()

    def clear_cards(self):
        for card in self.cards:
            self.cards_grid.removeWidget(card)
            card.deleteLater()
        self.cards.clear()
        self.thumbnail_cards.clear()

    def search(self):
        term = self.query.text().strip()
        if not term:
            self.status.setText("Masukkan kata pencarian atau URL.")
            self.query.setFocus()
            return
        if not shutil.which(YTDLP):
            QMessageBox.critical(self, APP_NAME, f"yt-dlp tidak ditemukan: {YTDLP}")
            return
        if self.keyboard_open:
            self.set_keyboard_visible(False)
        if self.search_process and self.search_process.state() != QProcess.NotRunning:
            self.search_process.kill()
        self.search_button.setEnabled(False)
        self.clear_cards()
        self.results = []
        self.play_button.setEnabled(False)
        self.status.setText("Mencari video YouTube…")
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
                QMessageBox.warning(self, APP_NAME, err[-1400:])
            return
        try:
            data = json.loads(raw)
            for entry in (data.get("entries") or [data]):
                if not entry:
                    continue
                url = video_url(entry)
                if not url:
                    continue
                title = entry.get("title") or "Video tanpa judul"
                channel = entry.get("channel") or entry.get("uploader") or entry.get("artist") or "YouTube"
                duration = entry.get("duration")
                duration_text = f"{int(duration)//60}:{int(duration)%60:02d}" if duration else ""
                result = {"url": url, "title": title, "channel": channel,
                          "thumbnail": entry.get("thumbnail"), "duration": duration_text}
                self.results.append(result)
                card = VideoCard(len(self.results)-1, title, channel, duration_text, self.cards_host)
                card.setMinimumHeight(245)
                card.on_activate = self.play_selected
                card.installEventFilter(self)
                self.cards.append(card)
                if result["thumbnail"]:
                    self.thumbnail_cards[result["thumbnail"]] = card
                    request = QNetworkRequest(QUrl(result["thumbnail"]))
                    request.setTransferTimeout(12000)
                    reply = self.network.get(request)
                    reply.finished.connect(lambda r=reply, u=result["thumbnail"]: self.thumbnail_loaded(r, u))
            self.refresh_card_columns()
        except (json.JSONDecodeError, TypeError, ValueError) as exc:
            self.status.setText(f"Format hasil tidak dikenali: {exc}")
            return
        self.status.setText(f"{len(self.results)} hasil ditemukan. Pilih thumbnail untuk memutar.")
        self.play_button.setEnabled(bool(self.results))
        if self.cards:
            self.cards[0].setFocus()

    def thumbnail_loaded(self, reply, url):
        card = self.thumbnail_cards.get(url)
        if card is not None and reply.error() == reply.NetworkError.NoError:
            pixmap = QPixmap()
            if pixmap.loadFromData(reply.readAll()):
                card.set_thumbnail(pixmap)
        reply.deleteLater()

    def play_selected(self, index=None):
        if not self.results:
            self.status.setText("Cari dan pilih video terlebih dahulu.")
            return
        if index is None:
            focus = QApplication.focusWidget()
            index = getattr(focus, "index", 0)
        index = max(0, min(int(index), len(self.results)-1))
        video = self.results[index]
        if not shutil.which(MPV):
            QMessageBox.critical(self, APP_NAME, f"mpv tidak ditemukan: {MPV}")
            return
        if self.player_process and self.player_process.state() != QProcess.NotRunning:
            self.player_process.terminate()
        process = QProcess(self)
        self.player_process = process
        process.setProgram(MPV)
        process.setArguments(["--force-window=yes",
            f"--ytdl-format={QUALITY_FORMATS[self.quality.currentText()]}", video["url"]])
        process.started.connect(lambda p=process: self.player_started(p, video["title"]))
        process.finished.connect(lambda code, _status, p=process: self.player_finished(p, code))
        process.errorOccurred.connect(lambda _err, p=process: self.player_error(p))
        process.start()
        self.status.setText(f"Menyiapkan: {video['title']}")

    def player_started(self, process, title):
        if process is self.player_process:
            self.stop_button.setEnabled(True)
            self.status.setText(f"Sedang diputar: {title} • STOP untuk kembali.")

    def player_finished(self, process, exit_code):
        if process is self.player_process:
            self.stop_button.setEnabled(False)
            self.status.setText("Pemutaran selesai. Hasil pencarian tetap tersedia.")
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

    def eventFilter(self, watched, event):
        if event.type() == QEvent.KeyPress and self.isActiveWindow():
            key, focus = event.key(), QApplication.focusWidget()
            if key in (Qt.Key_Escape, Qt.Key_Back):
                if self.keyboard_open:
                    self.set_keyboard_visible(False)
                self.query.setFocus()
                return True
            if focus in self.cards:
                idx = self.cards.index(focus)
                cols = 2 if self.scroll.viewport().width() < 980 else 3
                if key == Qt.Key_Right and idx + 1 < len(self.cards):
                    self.cards[idx+1].setFocus(); return True
                if key == Qt.Key_Left:
                    (self.cards[idx-1] if idx % cols else self.query).setFocus(); return True
                if key == Qt.Key_Down and idx + cols < len(self.cards):
                    self.cards[idx+cols].setFocus(); return True
                if key == Qt.Key_Up:
                    (self.cards[idx-cols] if idx >= cols else self.query).setFocus(); return True
                if key in (Qt.Key_Return, Qt.Key_Enter, Qt.Key_Select):
                    self.play_selected(idx); return True
            if focus is self.query and key == Qt.Key_Down:
                target = self.keyboard.buttons[0] if self.keyboard_open and self.keyboard.buttons else (
                    self.cards[0] if self.cards else self.quality)
                target.setFocus(); return True
            if focus is self.keyboard_button and key == Qt.Key_Left:
                self.query.setFocus(); return True
            if focus is self.keyboard_button and key == Qt.Key_Right:
                self.search_button.setFocus(); return True
            if focus is self.search_button and key == Qt.Key_Left:
                self.keyboard_button.setFocus(); return True
            if focus is self.search_button and key == Qt.Key_Down and self.cards:
                self.cards[0].setFocus(); return True
        return super().eventFilter(watched, event)

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key_Escape, Qt.Key_Back):
            if self.keyboard_open:
                self.set_keyboard_visible(False)
            self.query.setFocus()
            return
        super().keyPressEvent(event)

    def closeEvent(self, event):
        for process in (self.search_process, self.player_process):
            if process and process.state() != QProcess.NotRunning:
                process.terminate()
        super().closeEvent(event)


def main():
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
