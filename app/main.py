#!/usr/bin/env python3
"""YouTube Roxy TV - embedded player, paged search and remote-friendly controls."""
from __future__ import annotations
import json, os, shutil, sys
from pathlib import Path
from PySide6.QtCore import Qt, QEvent, QProcess, QUrl, QTimer, QPropertyAnimation, QEasingCurve
from PySide6.QtGui import QPixmap
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkRequest, QNetworkDiskCache, QLocalSocket
from PySide6.QtWidgets import (
    QApplication, QComboBox, QFrame, QGridLayout, QHBoxLayout, QLabel,
    QLineEdit, QMainWindow, QMessageBox, QPushButton, QScrollArea,
    QSizePolicy, QStackedWidget, QVBoxLayout, QWidget,
)

APP_NAME = "YouTube Roxy"
CONFIG_DIR = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
SAFE_AREA_FILE = CONFIG_DIR / "roxy-display" / "safe-area.json"
CACHE_DIR = Path.home() / ".cache" / "roxy-youtube-tv" / "thumbnails"
YTDLP = os.environ.get("ROXY_YT_DLP", "yt-dlp")
MPV = os.environ.get("ROXY_MPV", "mpv")
QUALITY_FORMATS = {
    "Auto": "bestvideo+bestaudio/best",
    "360p": "bestvideo[height<=360]+bestaudio/best[height<=360]",
    "480p": "bestvideo[height<=480]+bestaudio/best[height<=480]",
    "720p": "bestvideo[height<=720]+bestaudio/best[height<=720]",
}


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
    return None


def thumbnail_url(entry):
    items = entry.get("thumbnails") or []
    usable = [x for x in items if x.get("url")]
    if usable:
        # Prefer a modest 320-480 px image; avoid downloading full-size artwork.
        usable.sort(key=lambda x: (0 if 240 <= (x.get("width") or 0) <= 480 else 1,
                                   abs((x.get("width") or 320) - 320)))
        return usable[0]["url"]
    return entry.get("thumbnail")


class TvKeyboard(QWidget):
    """CatTube-style 10-unit remote keyboard, adapted for YouTube search."""
    ROW_UNITS = 10

    def __init__(self, target, on_finish, parent=None):
        super().__init__(parent)
        self.target, self.on_finish = target, on_finish
        self.caps_locked = False
        self.shift_once = False
        self.symbol_mode = False
        self.buttons = []
        self.key_items = []
        self.setObjectName("keyboardPanel")
        self.setStyleSheet("""
            QWidget#keyboardPanel { background:#151c26; border:1px solid #354253; border-radius:9px; }
            QPushButton { background:#303d4e; color:#f7f8fa; border:2px solid #536176;
                border-radius:6px; padding:2px 1px; font-size:13px; font-weight:650; min-height:26px; }
            QPushButton:focus { background:#526781; border:3px solid #ffd166; }
            QPushButton[keyRole="special"] { background:#25364a; }
            QPushButton[keyRole="active"] { background:#6b5525; border-color:#ffd166; }
        """)
        self.box = QVBoxLayout(self)
        self.box.setContentsMargins(7, 6, 7, 6)
        self.box.setSpacing(4)
        self.build_keys()

    def build_keys(self, focus_position=None):
        while self.box.count():
            item = self.box.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
            elif item.layout():
                child = item.layout()
                while child.count():
                    sub = child.takeAt(0)
                    if sub.widget():
                        sub.widget().deleteLater()

        self.buttons = []
        self.key_items = []

        utility = QHBoxLayout()
        utility.addStretch(1)
        clear_button = QPushButton("KOSONGKAN")
        clear_button.setFocusPolicy(Qt.StrongFocus)
        clear_button.setProperty("keyRole", "special")
        clear_button.clicked.connect(self.clear_text)
        clear_button.installEventFilter(self)
        utility.addWidget(clear_button)
        self.box.addLayout(utility)
        self.buttons.append(clear_button)
        self.key_items.append({
            "button": clear_button, "row": -1, "col": 8,
            "span": 2, "center": 9.0,
        })

        grid = QGridLayout()
        grid.setSpacing(4)
        for col in range(self.ROW_UNITS):
            grid.setColumnStretch(col, 1)

        def add_key(label, row, col, span=1, callback=None, value=None, active=False):
            button = QPushButton(label)
            button.setFocusPolicy(Qt.StrongFocus)
            button.setProperty("keyRole", "active" if active else "special" if callback else "normal")
            if callback is not None:
                button.clicked.connect(callback)
            else:
                button.clicked.connect(lambda checked=False, v=value: self.insert(v))
            button.installEventFilter(self)
            grid.addWidget(button, row, col, 1, span)
            self.buttons.append(button)
            self.key_items.append({
                "button": button, "row": row, "col": col,
                "span": span, "center": col + span / 2,
            })
            return button

        if not self.symbol_mode:
            rows = ("1234567890", "qwertyuiop", "asdfghjkl@", "zxcvbnm-_.")
        else:
            rows = ("1234567890", "!@#$%^&*()", "-_=+[]{};:", "'\",./?\\|~^")

        for row, chars in enumerate(rows):
            for col, char in enumerate(chars):
                shown = char
                if char.isalpha() and not self.symbol_mode:
                    upper = self.caps_locked ^ self.shift_once
                    shown = char.upper() if upper else char.lower()
                add_key(shown, row, col, value=char)

        if not self.symbol_mode:
            special = [
                ("SHIFT", 2, self.toggle_shift, self.shift_once),
                ("?123", 1, self.toggle_symbols, False),
                ("CAPS" if not self.caps_locked else "CAPS ✓", 1, self.toggle_caps, self.caps_locked),
                ("SPASI", 3, lambda: self.insert(" "), False),
                ("⌫", 1, self.backspace, False),
                ("SELESAI", 2, self.finish, False),
            ]
        else:
            special = [
                ("ABC", 2, self.toggle_symbols, False),
                ("CAPS" if not self.caps_locked else "CAPS ✓", 1, self.toggle_caps, self.caps_locked),
                ("SPASI", 4, lambda: self.insert(" "), False),
                ("⌫", 1, self.backspace, False),
                ("SELESAI", 2, self.finish, False),
            ]

        col = 0
        for label, span, callback, active in special:
            add_key(label, 4, col, span, callback=callback, active=active)
            col += span
        if col != self.ROW_UNITS:
            raise RuntimeError(f"Keyboard special row uses {col} units, expected {self.ROW_UNITS}")

        self.box.addLayout(grid)
        if focus_position:
            row, col = focus_position
            candidates = [x for x in self.key_items if x["row"] == row]
            if candidates:
                min(candidates, key=lambda x: abs(x["center"] - col))["button"].setFocus()
        elif self.buttons:
            self.buttons[0].setFocus()

    def eventFilter(self, watched, event):
        if event.type() == QEvent.KeyPress:
            key = event.key()
            item = next((x for x in self.key_items if x["button"] is watched), None)
            if item:
                if key in (Qt.Key_Left, Qt.Key_Right):
                    row_items = sorted(
                        (x for x in self.key_items if x["row"] == item["row"]),
                        key=lambda x: x["col"]
                    )
                    index = row_items.index(item)
                    next_index = index + (1 if key == Qt.Key_Right else -1)
                    if 0 <= next_index < len(row_items):
                        row_items[next_index]["button"].setFocus()
                        event.accept()
                        return True
                elif key in (Qt.Key_Up, Qt.Key_Down):
                    next_row = item["row"] + (-1 if key == Qt.Key_Up else 1)
                    if next_row < -1:
                        self.target.setFocus()
                        event.accept()
                        return True
                    if next_row <= 4:
                        candidates = [x for x in self.key_items if x["row"] == next_row]
                        if candidates:
                            nearest = min(candidates, key=lambda x: abs(x["center"] - item["center"]))
                            nearest["button"].setFocus()
                            event.accept()
                            return True
        return super().eventFilter(watched, event)

    def insert(self, value):
        if value is None:
            return
        pos = self.target.cursorPosition()
        self.target.setText(self.target.text()[:pos] + value + self.target.text()[pos:])
        self.target.setCursorPosition(pos + len(value))
        current = next(
            (x for x in self.key_items if x["button"] is self.focusWidget()),
            {"row": 1, "col": 0},
        )
        if value and value[-1:].isalpha() and not self.symbol_mode and self.shift_once:
            self.shift_once = False
            self.build_keys((current["row"], current["col"]))

    def backspace(self):
        pos = self.target.cursorPosition()
        if pos:
            self.target.setText(self.target.text()[:pos - 1] + self.target.text()[pos:])
            self.target.setCursorPosition(pos - 1)

    def clear_text(self):
        self.target.clear()

    def toggle_caps(self):
        self.caps_locked = not self.caps_locked
        self.shift_once = False
        self.build_keys((4, 3))

    def toggle_shift(self):
        self.shift_once = not self.shift_once
        self.build_keys((4, 0))

    def toggle_symbols(self):
        self.symbol_mode = not self.symbol_mode
        self.shift_once = False
        self.build_keys((4, 0))

    def finish(self):
        self.on_finish()


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

        # Large 16:9 thumbnail with duration overlaid in its bottom-right corner.
        self.thumbnail_frame = QFrame()
        self.thumbnail_frame.setObjectName("thumbnailFrame")
        self.thumbnail_frame.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.thumbnail_frame.setStyleSheet(
            "QFrame#thumbnailFrame { background:#252e3b; border:0; border-radius:5px; }")
        thumb_layout = QGridLayout(self.thumbnail_frame)
        thumb_layout.setContentsMargins(0, 0, 5, 5)
        self.image = QLabel(" ")
        self.image.setAlignment(Qt.AlignCenter)
        self.image.setMinimumHeight(70)
        self.image.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.image.setStyleSheet("background:transparent;color:#9ba8b8;border:0;font-size:11px;")
        thumb_layout.addWidget(self.image, 0, 0)
        self.duration_label = QLabel(duration or "")
        self.duration_label.setAlignment(Qt.AlignCenter)
        self.duration_label.setStyleSheet(
            "QLabel { background:rgba(0,0,0,220); color:white; border-radius:3px;"
            " padding:2px 5px; font-size:10px; font-weight:700; }")
        self.duration_label.setVisible(bool(duration))
        thumb_layout.addWidget(self.duration_label, 0, 0, Qt.AlignRight | Qt.AlignBottom)
        layout.addWidget(self.thumbnail_frame)

        self.title_label = QLabel(title)
        self.title_label.setWordWrap(True)
        self.title_label.setMaximumHeight(38)
        self.title_label.setStyleSheet("font-size:13px;font-weight:700;color:#f4f6f8;border:0;")
        layout.addWidget(self.title_label)
        self.meta_label = QLabel(channel)
        self.meta_label.setWordWrap(False)
        self.meta_label.setStyleSheet("font-size:10px;color:#aeb8c5;border:0;")
        layout.addWidget(self.meta_label)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        height = max(70, int((self.width() - 20) * 9 / 16))
        self.thumbnail_frame.setFixedHeight(height)
        self.image.setFixedHeight(height)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton and callable(self.on_activate):
            self.on_activate(self.index)
        super().mousePressEvent(event)

    def set_thumbnail(self, pixmap):
        if pixmap.isNull():
            return
        self.image.setText("")
        self.image.setPixmap(pixmap.scaled(max(1, self.image.width()),
            max(1, self.image.height()), Qt.KeepAspectRatio, Qt.FastTransformation))


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.resize(700, 525)
        self.setMinimumSize(560, 420)
        self.setMaximumSize(900, 675)
        self.results, self.cards = [], []
        self.search_process = self.player_process = self.metadata_process = None
        self.current_index = 0
        self.current_page = 0
        self.page_size = 8
        self.thumbnail_queue = []
        self.thumbnail_active = 0
        self.thumbnail_cards = {}
        self.thumbnail_replies = set()
        self.network = QNetworkAccessManager(self)
        self.cache = QNetworkDiskCache(self)
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        self.cache.setCacheDirectory(str(CACHE_DIR))
        self.cache.setMaximumCacheSize(32 * 1024 * 1024)
        self.network.setCache(self.cache)
        self.safe_margins = safe_area_margins()
        self.ipc_path = f"/tmp/roxy-youtube-tv-{os.getpid()}.sock"
        self.mpv_socket = None
        self.mpv_event_socket = None
        self.mpv_event_attempts = 0
        self.mpv_event_buffer = ""
        self.metadata_requested_index = None
        self.current_time_pos = 0.0
        self.playback_started = False
        self.fallback_qualities = []
        self.setStyleSheet("""
            QMainWindow, QWidget { background:#101318; color:#f4f6f8; font-family:Sans; }
            QLabel#brand { color:#ffffff; font-size:17px; font-weight:750; }
            QLabel#hint { color:#aeb8c5; font-size:11px; }
            QLineEdit,QComboBox { background:#202733; color:white; border:2px solid #465366;
                border-radius:7px; padding:5px 7px; font-size:13px; min-height:23px; }
            QPushButton { background:#293443; color:white; border:2px solid #465366;
                border-radius:7px; padding:5px 8px; font-size:12px; font-weight:700; }
            QPushButton:focus,QLineEdit:focus,QComboBox:focus { border:3px solid #ffd166; background:#3a4b60; }
            QPushButton:disabled { color:#718096; background:#202733; }
            QScrollArea { border:0; background:transparent; }
            QScrollBar:vertical { width:11px; background:#171d26; }
            QScrollBar::handle:vertical { background:#526176; border-radius:5px; min-height:24px; }
        """)
        root = QWidget()
        outer = QVBoxLayout(root)
        outer.setContentsMargins(0, 0, 0, 0)
        self.setCentralWidget(root)
        self.pages = QStackedWidget()
        outer.addWidget(self.pages)

        # Search/results page
        self.search_page = QWidget()
        search_shell = QHBoxLayout(self.search_page)
        search_shell.setContentsMargins(0, 0, 0, 0)
        search_shell.setSpacing(5)
        self.sidebar = QFrame()
        self.sidebar.setObjectName("sidebar")
        self.sidebar.setFixedWidth(150)
        self.sidebar.setStyleSheet("QFrame#sidebar{background:#171e28;border:1px solid #354253;border-radius:7px;}")
        sidebar_layout = QVBoxLayout(self.sidebar)
        sidebar_layout.setContentsMargins(4, 7, 4, 7)
        sidebar_layout.setSpacing(5)
        self.nav_buttons, self.nav_modes = [], []
        for icon, label, mode in (
            ("⌂", "Beranda", "home"), ("⌕", "Cari", "search"),
            ("🔥", "Trending", "trending"), ("▣", "Video", "videos"),
            ("◷", "Riwayat", "history"), ("♡", "Favorit", "favorites"),
            ("☷", "Playlist", "playlists"), ("⚙", "Pengaturan", "settings"),
        ):
            button = QPushButton(f"{icon}  {label}")
            button.setMinimumHeight(34)
            button.setFocusPolicy(Qt.StrongFocus)
            button.setStyleSheet("text-align:left;padding:5px 7px;font-size:12px;")
            button.clicked.connect(lambda checked=False, m=mode: self.select_section(m))
            sidebar_layout.addWidget(button)
            self.nav_buttons.append(button)
            self.nav_modes.append(mode)
        sidebar_layout.addStretch(1)
        search_shell.addWidget(self.sidebar)
        content = QWidget()
        self.root_layout = QVBoxLayout(content)
        self.root_layout.setContentsMargins(3, 3, 3, 3)
        self.root_layout.setSpacing(6)
        search_shell.addWidget(content, 1)
        self.feed_mode = "home"
        header = QHBoxLayout()
        logo = QLabel("▶")
        logo.setStyleSheet("color:#ff0033;font-size:22px;font-weight:900;")
        brand = QLabel("YouTube Roxy")
        brand.setObjectName("brand")
        header.addWidget(logo)
        header.addWidget(brand)
        header.addStretch(1)
        self.root_layout.addLayout(header)

        search_row = QHBoxLayout()
        self.query = QLineEdit()
        self.query.setPlaceholderText("Cari video atau tempel URL YouTube…")
        self.query.returnPressed.connect(self.search)
        self.keyboard_button = QPushButton("⌨")
        self.keyboard_button.setToolTip("Buka keyboard layar")
        self.keyboard_button.clicked.connect(self.toggle_keyboard)
        self.search_button = QPushButton("⌕")
        self.search_button.setToolTip("Cari video")
        self.search_button.clicked.connect(self.search)
        search_row.addWidget(self.query, 1)
        search_row.addWidget(self.keyboard_button)
        search_row.addWidget(self.search_button)
        self.root_layout.addLayout(search_row)

        self.keyboard_open = False
        self.keyboard_animation = None
        self.keyboard = TvKeyboard(self.query, self.finish_keyboard, self)
        self.keyboard_widget = self.keyboard
        self.keyboard.setVisible(False)
        self.keyboard.setMaximumHeight(0)
        self.root_layout.addWidget(self.keyboard)

        options = QHBoxLayout()
        options.addWidget(QLabel("Video per halaman"))
        self.page_size_box = QComboBox()
        self.page_size_box.addItems(["6", "8", "12"])
        self.page_size_box.setCurrentText("8")
        self.page_size_box.currentTextChanged.connect(self.change_page_size)
        options.addWidget(self.page_size_box)
        options.addStretch(1)
        self.root_layout.addLayout(options)

        self.results_heading = QLabel("HASIL VIDEO")
        self.results_heading.setObjectName("hint")
        self.root_layout.addWidget(self.results_heading)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.cards_host = QWidget()
        self.cards_grid = QGridLayout(self.cards_host)
        self.cards_grid.setContentsMargins(2, 2, 2, 2)
        self.cards_grid.setSpacing(8)
        self.scroll.setWidget(self.cards_host)
        self.root_layout.addWidget(self.scroll, 1)

        page_nav = QHBoxLayout()
        self.prev_page_button = QPushButton("‹")
        self.prev_page_button.setToolTip("Halaman sebelumnya")
        self.prev_page_button.clicked.connect(lambda: self.change_page(-1))
        self.page_label = QLabel("0 / 0")
        self.page_label.setAlignment(Qt.AlignCenter)
        self.page_label.setObjectName("hint")
        self.next_page_button = QPushButton("›")
        self.next_page_button.setToolTip("Halaman berikutnya")
        self.next_page_button.clicked.connect(lambda: self.change_page(1))
        page_nav.addWidget(self.prev_page_button)
        page_nav.addWidget(self.page_label, 1)
        page_nav.addWidget(self.next_page_button)
        self.root_layout.addLayout(page_nav)
        self.status = QLabel("Siap. Cari video menggunakan remote.")
        self.status.setObjectName("hint")
        self.status.setWordWrap(True)
        self.root_layout.addWidget(self.status)
        self.pages.addWidget(self.search_page)

        # Embedded player page
        self.player_page = QWidget()
        player_layout = QVBoxLayout(self.player_page)
        player_layout.setContentsMargins(2, 2, 2, 2)
        player_layout.setSpacing(5)
        player_header = QHBoxLayout()
        self.player_title = QLabel("Pemutar YouTube")
        self.player_title.setObjectName("brand")
        self.player_title.setWordWrap(True)
        self.back_button = QPushButton("‹")
        self.back_button.setToolTip("Kembali ke hasil")
        self.back_button.clicked.connect(self.back_to_results)
        player_header.addWidget(self.back_button)
        player_header.addWidget(self.player_title, 1)
        player_layout.addLayout(player_header)

        body = QHBoxLayout()
        self.video_surface = QWidget()
        self.video_surface.setMinimumSize(300, 170)
        self.video_surface.setStyleSheet("background:#000000;border:1px solid #384354;")
        body.addWidget(self.video_surface, 3)
        self.side_panel = QFrame()
        self.side_panel.setMinimumWidth(150)
        self.side_panel.setMaximumWidth(235)
        self.side_panel.setStyleSheet("QFrame{background:#171e28;border:1px solid #354253;border-radius:7px;}")
        side_layout = QVBoxLayout(self.side_panel)
        side_layout.setContentsMargins(6, 6, 6, 6)
        side_buttons = QHBoxLayout()
        self.playlist_button = QPushButton("☷")
        self.playlist_button.setToolTip("Playlist")
        self.playlist_button.clicked.connect(lambda: self.show_side_panel("playlist"))
        self.description_button = QPushButton("≡")
        self.description_button.setToolTip("Deskripsi")
        self.description_button.clicked.connect(lambda: self.show_side_panel("description"))
        side_buttons.addWidget(self.playlist_button)
        side_buttons.addWidget(self.description_button)
        side_layout.addLayout(side_buttons)
        self.side_content = QScrollArea()
        self.side_content.setWidgetResizable(True)
        self.side_content.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.side_text_host = QWidget()
        self.side_text_layout = QVBoxLayout(self.side_text_host)
        self.side_text_layout.setContentsMargins(2, 2, 2, 2)
        self.side_content.setWidget(self.side_text_host)
        side_layout.addWidget(self.side_content, 1)
        body.addWidget(self.side_panel, 1)
        player_layout.addLayout(body, 1)

        controls = QHBoxLayout()
        self.previous_video_button = QPushButton("⏮")
        self.previous_video_button.setToolTip("Video sebelumnya")
        self.previous_video_button.clicked.connect(lambda: self.play_index(self.current_index - 1))
        self.play_pause_button = QPushButton("Ⅱ")
        self.play_pause_button.setToolTip("Jeda / lanjut")
        self.play_pause_button.clicked.connect(lambda: self.mpv_command(["cycle", "pause"]))
        self.next_video_button = QPushButton("⏭")
        self.next_video_button.setToolTip("Video berikutnya")
        self.next_video_button.clicked.connect(lambda: self.play_index(self.current_index + 1))
        self.stop_button = QPushButton("■")
        self.stop_button.setToolTip("Stop dan kembali")
        self.stop_button.clicked.connect(self.back_to_results)
        self.subtitle_box = QComboBox()
        self.subtitle_box.setMinimumWidth(105)
        self.subtitle_box.addItem("Subtitle: Off", None)
        self.subtitle_box.currentIndexChanged.connect(self.select_subtitle)
        self.quality = QComboBox()
        self.quality.addItems(list(QUALITY_FORMATS))
        self.quality.setCurrentText("720p")
        self.quality.setMinimumWidth(75)
        self.quality.currentTextChanged.connect(self.change_quality)
        controls.addWidget(self.previous_video_button)
        controls.addWidget(self.play_pause_button)
        controls.addWidget(self.next_video_button)
        controls.addWidget(self.stop_button)
        controls.addStretch(1)
        controls.addWidget(QLabel("Kualitas"))
        controls.addWidget(self.quality)
        controls.addWidget(QLabel("CC"))
        controls.addWidget(self.subtitle_box)
        player_layout.addLayout(controls)
        self.player_status = QLabel("Menyiapkan pemutar…")
        self.player_status.setObjectName("hint")
        player_layout.addWidget(self.player_status)
        self.pages.addWidget(self.player_page)

        self.apply_safe_area()
        self.query.setFocus()
        QApplication.instance().installEventFilter(self)
        self.show_side_panel("playlist")
        self.set_active_nav("home")
        QTimer.singleShot(700, lambda: self.load_feed("home"))

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
        if not hasattr(self, "scroll"):
            return
        columns = 2
        for i, card in enumerate(self.cards):
            self.cards_grid.removeWidget(card)
            self.cards_grid.addWidget(card, i // columns, i % columns)

    def set_keyboard_visible(self, visible):
        visible = bool(visible)
        if visible == self.keyboard_open:
            return
        self.keyboard_open = visible
        self.keyboard_button.setText("⌨ TUTUP" if visible else "⌨")
        if self.keyboard_animation is not None:
            self.keyboard_animation.stop()
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
        self.thumbnail_queue.clear()

    def set_active_nav(self, mode):
        for button, button_mode in zip(self.nav_buttons, self.nav_modes):
            active = button_mode == mode
            button.setStyleSheet("text-align:left;padding:5px 7px;font-size:12px;" +
                                 ("background:#40536b;border:2px solid #ffd166;" if active else ""))
        self.feed_mode = mode

    def collapse_sidebar(self):
        self.sidebar.setFixedWidth(48)
        for button, icon in zip(self.nav_buttons, ("⌂", "⌕", "🔥", "▣", "◷", "♡", "☷", "⚙")):
            button.setText(icon)

    def expand_sidebar(self):
        self.sidebar.setFixedWidth(150)
        for button, icon, label in zip(self.nav_buttons, ("⌂", "⌕", "🔥", "▣", "◷", "♡", "☷", "⚙"),
                                       ("Beranda", "Cari", "Trending", "Video", "Riwayat", "Favorit", "Playlist", "Pengaturan")):
            button.setText(f"{icon}  {label}")

    def select_section(self, mode):
        self.set_active_nav(mode)
        self.collapse_sidebar()
        if mode == "search":
            self.query.setFocus()
            self.status.setText("Masukkan kata pencarian atau URL YouTube.")
        elif mode in ("home", "trending"):
            self.load_feed(mode)
        else:
            self.results_heading.setText(mode.upper())
            self.status.setText(f"Bagian {mode} belum tersedia.")

    def load_feed(self, mode):
        if mode not in ("home", "trending"):
            return
        if not shutil.which(YTDLP):
            self.status.setText(f"yt-dlp tidak ditemukan: {YTDLP}")
            return
        if self.search_process and self.search_process.state() != QProcess.NotRunning:
            self.search_process.kill()
        self.set_active_nav(mode)
        self.clear_cards()
        self.results = []
        self.current_page = 0
        self.search_button.setEnabled(False)
        if mode == "home":
            target = "https://www.youtube.com/feed/recommended"
            self.results_heading.setText("BERANDA  •  REKOMENDASI YOUTUBE")
            self.status.setText("Memuat rekomendasi publik YouTube…")
        else:
            target = "https://www.youtube.com/feed/trending?gl=ID"
            self.results_heading.setText("TRENDING 🔥  •  INDONESIA")
            self.status.setText("Memuat video Trending Indonesia…")
        process = QProcess(self)
        self.search_process = process
        process.setProgram(YTDLP)
        process.setArguments(["--no-warnings", "--flat-playlist", "--dump-single-json", target])
        process.finished.connect(lambda code, status, p=process: self.search_finished(p, code, status))
        process.errorOccurred.connect(lambda _err, p=process: self.search_error(p))
        process.start()

    def search(self):
        self.set_active_nav("search")
        self.collapse_sidebar()
        term = self.query.text().strip()
        if not term:
            self.status.setText("Masukkan kata pencarian atau URL.")
            self.query.setFocus()
            return
        if not shutil.which(YTDLP):
            QMessageBox.critical(self, APP_NAME, f"yt-dlp tidak ditemukan: {YTDLP}")
            return
        if self.search_process and self.search_process.state() != QProcess.NotRunning:
            self.search_process.kill()
        self.search_button.setEnabled(False)
        self.clear_cards()
        self.results = []
        self.current_page = 0
        self.status.setText("Mencari video YouTube…")
        self.results_heading.setText("HASIL PENCARIAN")
        target = term if term.startswith(("http://", "https://")) else f"ytsearch60:{term}"
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
            if self.feed_mode == "home":
                self.status.setText("Rekomendasi publik tidak dapat dimuat. Periksa koneksi atau dukungan yt-dlp.")
            elif self.feed_mode == "trending":
                self.status.setText("Trending YouTube Indonesia tidak tersedia dari sumber publik saat ini.")
            else:
                self.status.setText("Pencarian gagal. Periksa koneksi / yt-dlp.")
                if err.strip():
                    QMessageBox.warning(self, APP_NAME, err[-1200:])
            self.search_button.setEnabled(True)
            return
        try:
            data = json.loads(raw)
            for entry in (data.get("entries") or [data]):
                if not entry:
                    continue
                url = video_url(entry)
                if not url:
                    continue
                duration = entry.get("duration")
                duration_text = f"{int(duration)//60}:{int(duration)%60:02d}" if duration else ""
                self.results.append({
                    "url": url, "title": entry.get("title") or "Video tanpa judul",
                    "channel": entry.get("channel") or entry.get("uploader") or "YouTube",
                    "thumbnail": thumbnail_url(entry), "duration": duration_text,
                    "description": entry.get("description") or "",
                })
            if not self.results:
                if self.feed_mode == "home":
                    self.status.setText("Belum ada rekomendasi publik yang dapat ditampilkan.")
                elif self.feed_mode == "trending":
                    self.status.setText("Daftar Trending Indonesia kosong atau tidak didukung YouTube.")
                else:
                    self.status.setText("Tidak ada video yang ditemukan.")
                return
            self.render_page()
            if self.feed_mode == "home":
                self.results_heading.setText("BERANDA  •  REKOMENDASI YOUTUBE")
                self.status.setText(f"{len(self.results)} rekomendasi publik.")
            elif self.feed_mode == "trending":
                self.results_heading.setText("TRENDING 🔥  •  INDONESIA")
                self.status.setText(f"{len(self.results)} video Trending.")
            else:
                self.status.setText(f"{len(self.results)} video ditemukan.")
        except (json.JSONDecodeError, TypeError, ValueError) as exc:
            self.status.setText(f"Format hasil tidak dikenali: {exc}")

    def render_page(self):
        self.clear_cards()
        total_pages = max(1, (len(self.results) + self.page_size - 1) // self.page_size)
        self.current_page = max(0, min(self.current_page, total_pages - 1))
        start = self.current_page * self.page_size
        end = min(len(self.results), start + self.page_size)
        columns = 2
        for idx in range(start, end):
            result = self.results[idx]
            card = VideoCard(idx, result["title"], result["channel"], result["duration"], self.cards_host)
            card.setMinimumHeight(250)
            card.on_activate = self.play_index
            card.installEventFilter(self)
            self.cards.append(card)
            self.cards_grid.addWidget(card, (idx-start)//columns, (idx-start)%columns)
            if result["thumbnail"]:
                self.thumbnail_cards[result["thumbnail"]] = card
                self.thumbnail_queue.append((result["thumbnail"], card))
        self.page_label.setText(f"{self.current_page + 1} / {total_pages}")
        self.prev_page_button.setEnabled(self.current_page > 0)
        self.next_page_button.setEnabled(self.current_page + 1 < total_pages)
        self.results_heading.setText(f"HASIL VIDEO  •  {start + 1 if end else 0}–{end} dari {len(self.results)}")
        self.refresh_card_columns()
        self.load_next_thumbnail()
        if self.cards:
            self.cards[0].setFocus()

    def load_next_thumbnail(self):
        while self.thumbnail_active < 3 and self.thumbnail_queue:
            url, card = self.thumbnail_queue.pop(0)
            if card is None:
                continue
            request = QNetworkRequest(QUrl(url))
            request.setTransferTimeout(6000)
            reply = self.network.get(request)
            self.thumbnail_active += 1
            self.thumbnail_replies.add(reply)
            reply.finished.connect(lambda r=reply, u=url, c=card: self.thumbnail_loaded(r, u, c))

    def thumbnail_loaded(self, reply, url, card):
        self.thumbnail_active = max(0, self.thumbnail_active - 1)
        self.thumbnail_replies.discard(reply)
        if card in self.cards and reply.error() == reply.NetworkError.NoError:
            pixmap = QPixmap()
            if pixmap.loadFromData(reply.readAll()):
                card.set_thumbnail(pixmap)
        reply.deleteLater()
        self.load_next_thumbnail()

    def change_page_size(self, value):
        self.page_size = int(value)
        self.current_page = 0
        if self.results:
            self.render_page()

    def change_page(self, delta):
        target = self.current_page + delta
        total = max(1, (len(self.results) + self.page_size - 1) // self.page_size)
        if 0 <= target < total:
            self.current_page = target
            self.render_page()

    def quality_fallbacks(self, quality):
        if quality == "720p":
            return ["480p", "Auto"]
        if quality == "480p":
            return ["Auto"]
        if quality == "360p":
            return ["Auto"]
        return []

    def play_index(self, index, start_position=0.0):
        if not self.results:
            return
        index = max(0, min(int(index), len(self.results) - 1))
        self.current_index = index
        self.current_time_pos = max(0.0, float(start_position or 0.0))
        self.fallback_qualities = self.quality_fallbacks(self.quality.currentText())
        self.metadata_requested_index = None
        video = self.results[index]
        self.player_title.setText(video["title"])
        self.player_status.setText("Menghubungkan ke YouTube…")
        self.subtitle_box.blockSignals(True)
        self.subtitle_box.clear()
        self.subtitle_box.addItem("Subtitle: Off", None)
        self.subtitle_box.blockSignals(False)
        self.show_side_panel("playlist")
        self.populate_playlist()
        self.pages.setCurrentWidget(self.player_page)
        self.video_surface.winId()
        self._launch_player()

    def _launch_player(self):
        if not shutil.which(MPV):
            QMessageBox.critical(self, APP_NAME, f"mpv tidak ditemukan: {MPV}")
            self.back_to_results()
            return
        old_process = self.player_process
        self.player_process = None
        if old_process and old_process.state() != QProcess.NotRunning:
            old_process.kill()
        self.ipc_path = f"/tmp/roxy-youtube-tv-{os.getpid()}-{self.current_index}.sock"
        try:
            Path(self.ipc_path).unlink(missing_ok=True)
        except OSError:
            pass
        process = QProcess(self)
        self.player_process = process
        args = ["--no-osc", "--force-window=yes", f"--wid={int(self.video_surface.winId())}",
                f"--input-ipc-server={self.ipc_path}",
                f"--ytdl-format={QUALITY_FORMATS[self.quality.currentText()]}",
                # Keep subtitle enumeration out of the startup path; metadata is fetched later.
                "--ytdl-raw-options=sub-langs=none",
                "--keep-open=no"]
        if self.current_time_pos > 0.5:
            args.append(f"--start={self.current_time_pos:.2f}")
        args.append(self.results[self.current_index]["url"])
        process.setProgram(MPV)
        process.setArguments(args)
        process.started.connect(lambda p=process: self.player_started(p))
        process.finished.connect(lambda code, _status, p=process: self.player_finished(p, code))
        process.errorOccurred.connect(lambda _err, p=process: self.player_error(p))
        self.playback_started = False
        process.start()
        self.player_status.setText(f"Mencoba kualitas {self.quality.currentText()}…")

    def change_quality(self, quality):
        if self.pages.currentWidget() != self.player_page or not self.results:
            return
        if not self.player_process or self.player_process.state() == QProcess.NotRunning:
            return
        self.fallback_qualities = self.quality_fallbacks(quality)
        self.player_status.setText(f"Mengganti kualitas ke {quality}…")
        self._launch_player()

    def player_started(self, process):
        if process is self.player_process:
            self.player_status.setText("Mengambil stream video…")
            self.stop_button.setEnabled(True)
            self.mpv_event_attempts = 0
            QTimer.singleShot(250, lambda i=self.current_index, p=process:
                              self.connect_mpv_events(i, p))

    def connect_mpv_events(self, index, process):
        """Connect to MPV IPC so metadata work starts only after playback begins."""
        if (process is not self.player_process or index != self.current_index or
                process.state() == QProcess.NotRunning):
            return
        if self.mpv_event_socket:
            self.mpv_event_socket.abort()
            self.mpv_event_socket.deleteLater()
        sock = QLocalSocket(self)
        self.mpv_event_socket = sock
        self.mpv_event_buffer = ""
        sock.readyRead.connect(lambda s=sock, i=index, p=process:
                               self.read_mpv_events(s, i, p))
        sock.connected.connect(lambda s=sock: self.mpv_event_connected(s))
        sock.connectToServer(self.ipc_path)
        QTimer.singleShot(350, lambda s=sock, i=index, p=process:
                          self.retry_mpv_event_connection(s, i, p))
        # Keep IPC connection asynchronous; never block the TV UI waiting for MPV.

    def retry_mpv_event_connection(self, sock, index, process):
        if (sock is not self.mpv_event_socket or process is not self.player_process or
                index != self.current_index):
            return
        if sock.state() == QLocalSocket.ConnectedState:
            self.mpv_event_connected(sock)
            return
        self.mpv_event_attempts += 1
        if self.mpv_event_attempts >= 20:
            return
        if sock.state() == QLocalSocket.ConnectingState:
            QTimer.singleShot(250, lambda s=sock, i=index, p=process:
                              self.retry_mpv_event_connection(s, i, p))
        else:
            sock.abort()
            sock.deleteLater()
            QTimer.singleShot(250, lambda i=index, p=process:
                              self.connect_mpv_events(i, p))

    def mpv_event_connected(self, sock):
        if sock is not self.mpv_event_socket:
            return
        # Observe time-pos as a fallback if the initial playback event was missed.
        sock.write(b'{"command":["observe_property",1,"time-pos"]}\n')
        sock.flush()

    def read_mpv_events(self, sock, index, process):
        if sock is not self.mpv_event_socket:
            return
        self.mpv_event_buffer += bytes(sock.readAll()).decode("utf-8", "replace")
        while "\n" in self.mpv_event_buffer:
            line, self.mpv_event_buffer = self.mpv_event_buffer.split("\n", 1)
            try:
                message = json.loads(line)
            except json.JSONDecodeError:
                continue
            event = message.get("event")
            if event == "playback-restart":
                self.playback_started = True
                self.schedule_metadata_after_start(index, process, 1200)
            elif event == "property-change" and message.get("name") == "time-pos":
                value = message.get("data")
                if isinstance(value, (int, float)):
                    self.current_time_pos = max(0.0, float(value))
                    self.playback_started = True
                self.schedule_metadata_after_start(index, process, 1200)

    def schedule_metadata_after_start(self, index, process, delay_ms):
        if self.metadata_requested_index == index:
            return
        self.metadata_requested_index = index
        QTimer.singleShot(delay_ms, lambda i=index, p=process:
            self.fetch_metadata(i) if (                p is self.player_process and i == self.current_index and
                p.state() != QProcess.NotRunning) else None)

    def retry_lower_quality(self, process, reason):
        if (process is not self.player_process or self.playback_started or
                not self.fallback_qualities or self.pages.currentWidget() != self.player_page):
            return False
        next_quality = self.fallback_qualities.pop(0)
        self.player_process = None
        self.quality.blockSignals(True)
        self.quality.setCurrentText(next_quality)
        self.quality.blockSignals(False)
        self.player_status.setText(f"{reason} Mencoba {next_quality}…")
        process.deleteLater()
        QTimer.singleShot(450, self._launch_player)
        return True

    def player_finished(self, process, exit_code):
        if process is self.player_process:
            if self.retry_lower_quality(process, "Stream gagal dibuka."):
                return
            self.stop_button.setEnabled(False)
            if self.pages.currentWidget() == self.player_page:
                self.player_status.setText("Pemutaran selesai atau stream terputus.")
        process.deleteLater()

    def player_error(self, process):
        if process is self.player_process:
            if self.retry_lower_quality(process, "MPV gagal membuka stream."):
                return
            self.stop_button.setEnabled(False)
            self.player_status.setText("MPV gagal dijalankan.")

    def fetch_metadata(self, index):
        if self.metadata_process and self.metadata_process.state() != QProcess.NotRunning:
            self.metadata_process.kill()
        process = QProcess(self)
        self.metadata_process = process
        process.setProgram(YTDLP)
        process.setArguments(["--no-warnings", "--skip-download", "--no-playlist",
                              "--dump-single-json", self.results[index]["url"]])
        process.finished.connect(lambda code, _status, p=process, i=index: self.metadata_finished(p, i, code))
        process.start()

    def metadata_finished(self, process, index, exit_code):
        if process is not self.metadata_process or index != self.current_index or exit_code != 0:
            return
        try:
            data = json.loads(bytes(process.readAllStandardOutput()).decode("utf-8", "replace"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            return
        description = data.get("description") or self.results[index].get("description") or "Deskripsi tidak tersedia."
        self.results[index]["description"] = description
        self.show_side_panel("description", description)
        tracks = []
        for source, label in ((data.get("subtitles") or {}, "Tersedia"),
                              (data.get("automatic_captions") or {}, "Otomatis")):
            for lang, entries in source.items():
                for item in entries:
                    url = item.get("url")
                    ext = item.get("ext", "")
                    if url and ext in ("vtt", "srv3", "ttml", "json3"):
                        tracks.append({"lang": lang, "name": item.get("name") or lang,
                                       "source": label, "url": url})
                        break
        self.subtitle_box.blockSignals(True)
        self.subtitle_box.clear()
        self.subtitle_box.addItem("Subtitle: Off", None)
        # Indonesian first, then other languages.
        tracks.sort(key=lambda x: (0 if x["lang"] == "id" or x["lang"].startswith("id-") else 1,
                                   x["source"] != "Tersedia", x["lang"]))
        for track in tracks:
            self.subtitle_box.addItem(f"{track['name']} ({track['source']})", track)
        self.subtitle_box.blockSignals(False)
        if tracks:
            self.player_status.setText("Subtitle tersedia. Pilih bahasa melalui CC.")
        else:
            self.player_status.setText("Subtitle tidak tersedia untuk video ini.")

    def select_subtitle(self, index):
        track = self.subtitle_box.itemData(index)
        if not track:
            self.mpv_command(["set_property", "sid", "no"])
            return
        self.mpv_command(["sub-add", track["url"], "select", track["name"]])

    def mpv_command(self, command):
        socket = QLocalSocket(self)
        socket.connectToServer(self.ipc_path)
        if socket.waitForConnected(250):
            payload = json.dumps({"command": command}).encode("utf-8") + b"\n"
            socket.write(payload)
            socket.flush()
            socket.disconnectFromServer()
        socket.deleteLater()

    def populate_playlist(self):
        self.clear_side_content()
        for idx, item in enumerate(self.results):
            button = QPushButton(("▶  " if idx == self.current_index else "") + item["title"])
            button.setToolTip(item["title"])
            button.setStyleSheet("text-align:left;padding:6px;font-size:11px;")
            button.clicked.connect(lambda checked=False, i=idx: self.play_index(i))
            self.side_text_layout.addWidget(button)
        self.side_text_layout.addStretch(1)

    def show_side_panel(self, mode, description=None):
        self.clear_side_content()
        if mode == "description":
            text = description if description is not None else (
                self.results[self.current_index].get("description", "") if self.results else "")
            label = QLabel(text or "Memuat deskripsi…")
            label.setWordWrap(True)
            label.setTextInteractionFlags(Qt.TextSelectableByMouse)
            label.setStyleSheet("font-size:11px;color:#e4e9ef;border:0;")
            self.side_text_layout.addWidget(label)
        else:
            self.populate_playlist()
        self.playlist_button.setStyleSheet("background:#40536b;" if mode == "playlist" else "")
        self.description_button.setStyleSheet("background:#40536b;" if mode == "description" else "")

    def clear_side_content(self):
        while self.side_text_layout.count():
            item = self.side_text_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

    def back_to_results(self):
        self.fallback_qualities.clear()
        if self.player_process and self.player_process.state() != QProcess.NotRunning:
            self.player_process.terminate()
            QTimer.singleShot(700, lambda p=self.player_process: p.kill()
                              if p and p.state() != QProcess.NotRunning else None)
        self.stop_button.setEnabled(False)
        self.pages.setCurrentWidget(self.search_page)
        if self.cards:
            self.cards[0].setFocus()
        else:
            self.query.setFocus()

    def eventFilter(self, watched, event):
        if event.type() == QEvent.KeyPress and self.isActiveWindow():
            key, focus = event.key(), QApplication.focusWidget()
            if self.pages.currentWidget() == self.player_page:
                if key in (Qt.Key_Escape, Qt.Key_Back):
                    self.back_to_results()
                    return True
                if key == Qt.Key_Left and focus is self.subtitle_box:
                    self.quality.setFocus()
                    return True
                if key == Qt.Key_Right and focus is self.quality:
                    self.subtitle_box.setFocus()
                    return True
                if key == Qt.Key_Left and focus is self.quality:
                    self.stop_button.setFocus()
                    return True
                if key == Qt.Key_Right and focus is self.stop_button:
                    self.quality.setFocus()
                    return True
                if key in (Qt.Key_Return, Qt.Key_Enter, Qt.Key_Select) and focus is self.video_surface:
                    self.mpv_command(["cycle", "pause"])
                    return True
            elif self.pages.currentWidget() == self.search_page:
                if key in (Qt.Key_Escape, Qt.Key_Back):
                    if self.keyboard_open:
                        self.set_keyboard_visible(False)
                    self.query.setFocus()
                    return True
                if focus in self.nav_buttons:
                    nav_index = self.nav_buttons.index(focus)
                    if key == Qt.Key_Down and nav_index + 1 < len(self.nav_buttons):
                        self.nav_buttons[nav_index + 1].setFocus(); return True
                    if key == Qt.Key_Up and nav_index > 0:
                        self.nav_buttons[nav_index - 1].setFocus(); return True
                    if key == Qt.Key_Right:
                        self.collapse_sidebar()
                        if self.feed_mode == "search":
                            self.query.setFocus()
                        elif self.cards:
                            self.cards[0].setFocus()
                        return True
                    if key in (Qt.Key_Return, Qt.Key_Enter, Qt.Key_Select):
                        self.select_section(self.nav_modes[nav_index]); return True
                if focus in self.cards:
                    idx = self.cards.index(focus)
                    cols = 2
                    if key == Qt.Key_Left and idx % cols == 0:
                        self.expand_sidebar()
                        active = self.nav_modes.index(self.feed_mode) if self.feed_mode in self.nav_modes else 0
                        self.nav_buttons[active].setFocus()
                        return True
                    if key == Qt.Key_Right and idx + 1 < len(self.cards):
                        self.cards[idx+1].setFocus(); return True
                    if key == Qt.Key_Left and idx % cols:
                        self.cards[idx-1].setFocus(); return True
                    if key == Qt.Key_Down and idx + cols < len(self.cards):
                        self.cards[idx+cols].setFocus(); return True
                    if key == Qt.Key_Up and idx >= cols:
                        self.cards[idx-cols].setFocus(); return True
                    if key == Qt.Key_Up and idx < cols:
                        self.query.setFocus(); return True
                    if key in (Qt.Key_Return, Qt.Key_Enter, Qt.Key_Select):
                        self.play_index(idx); return True
                if focus is self.query and key == Qt.Key_Left:
                    self.expand_sidebar()
                    self.nav_buttons[1].setFocus()
                    return True
                if focus is self.query and key == Qt.Key_Down:
                    if self.keyboard_open and self.keyboard.buttons:
                        self.keyboard.buttons[0].setFocus()
                        return True
                    if self.cards:
                        self.cards[0].setFocus()
                        return True
        return super().eventFilter(watched, event)

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key_Escape, Qt.Key_Back) and self.pages.currentWidget() == self.player_page:
            self.back_to_results()
            return
        if event.key() in (Qt.Key_Escape, Qt.Key_Back) and self.keyboard_open:
            self.set_keyboard_visible(False)
            self.query.setFocus()
            return
        super().keyPressEvent(event)

    def closeEvent(self, event):
        for process in (self.search_process, self.player_process, self.metadata_process):
            if process and process.state() != QProcess.NotRunning:
                process.terminate()
        try:
            Path(self.ipc_path).unlink(missing_ok=True)
        except OSError:
            pass
        super().closeEvent(event)


def main():
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()