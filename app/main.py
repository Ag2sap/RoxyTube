#!/usr/bin/env python3
"""YouTube Roxy TV - embedded player, paged search and remote-friendly controls."""
from __future__ import annotations
import json, os, shutil, sys
from pathlib import Path
from PySide6.QtCore import Qt, QEvent, QProcess, QUrl, QTimer, QPropertyAnimation, QEasingCurve
from PySide6.QtGui import QPixmap
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkRequest, QNetworkDiskCache, QLocalSocket, QLocalServer
from PySide6.QtWidgets import (
    QApplication, QComboBox, QFrame, QGridLayout, QHBoxLayout, QLabel,
    QLineEdit, QMainWindow, QMessageBox, QPushButton, QScrollArea,
    QProgressBar, QSizePolicy, QSlider, QStackedWidget, QStyle, QVBoxLayout, QWidget,
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
                ("CAPS" if not self.caps_locked else "CAPS ON", 1, self.toggle_caps, self.caps_locked),
                ("SPASI", 3, lambda: self.insert(" "), False),
                ("DEL", 1, self.backspace, False),
                ("SELESAI", 2, self.finish, False),
            ]
        else:
            special = [
                ("ABC", 2, self.toggle_symbols, False),
                ("CAPS" if not self.caps_locked else "CAPS ON", 1, self.toggle_caps, self.caps_locked),
                ("SPASI", 4, lambda: self.insert(" "), False),
                ("DEL", 1, self.backspace, False),
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
        self.playback_queue = []
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
        self.duration_seconds = 0.0
        self.slider_dragging = False
        self.playback_paused = False
        self.playback_started = False
        self.manual_stop = False
        self.selected_subtitle_track = None
        self.subtitle_applied_process = None
        self.subtitle_applied_track = None
        self.is_playback_fullscreen = False
        self.fullscreen_controls_visible = False
        self.fullscreen_hide_timer = QTimer(self)
        self.fullscreen_hide_timer.setSingleShot(True)
        self.fullscreen_hide_timer.timeout.connect(self.hide_fullscreen_controls)
        self.fallback_qualities = []
        self.background_playback = False
        self.playlist_items = []
        self.mini_title_text = ""
        self.mini_title_offset = 0
        self.mini_title_timer = QTimer(self)
        self.mini_title_timer.setInterval(280)
        self.mini_title_timer.timeout.connect(self.advance_mini_title)
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
        self.nav_buttons, self.nav_modes, self.nav_labels = [], [], []
        nav_items = (
            ("Beranda", "home", QStyle.SP_DirHomeIcon),
            ("Cari", "search", QStyle.SP_FileDialogContentsView),
            ("Trending", "trending", QStyle.SP_BrowserReload),
            ("Video", "videos", QStyle.SP_MediaPlay),
            ("Riwayat", "history", QStyle.SP_FileDialogInfoView),
            ("Favorit", "favorites", QStyle.SP_DialogApplyButton),
            ("Playlist", "playlists", QStyle.SP_FileDialogListView),
            ("Pengaturan", "settings", QStyle.SP_FileDialogDetailedView),
        )
        for label, mode, icon_type in nav_items:
            button = QPushButton(label)
            button.setIcon(self.style().standardIcon(icon_type))
            button.setMinimumHeight(34)
            button.setFocusPolicy(Qt.StrongFocus)
            button.setStyleSheet("text-align:left;padding:5px 7px;font-size:12px;")
            button.setToolTip(label)
            button.clicked.connect(lambda checked=False, m=mode: self.select_section(m))
            sidebar_layout.addWidget(button)
            self.nav_buttons.append(button)
            self.nav_modes.append(mode)
            self.nav_labels.append(label)
        sidebar_layout.addStretch(1)
        search_shell.addWidget(self.sidebar)
        content = QWidget()
        self.root_layout = QVBoxLayout(content)
        self.root_layout.setContentsMargins(3, 3, 3, 3)
        self.root_layout.setSpacing(6)
        search_shell.addWidget(content, 1)
        self.feed_mode = "home"
        header = QHBoxLayout()
        logo = QLabel()
        logo.setPixmap(self.style().standardIcon(QStyle.SP_MediaPlay).pixmap(22, 22))
        brand = QLabel("YouTube Roxy")
        brand.setObjectName("brand")
        brand.setMaximumWidth(112)
        header.addWidget(logo)
        header.addWidget(brand)

        self.mini_player = QFrame()
        self.mini_player.setFixedWidth(278)
        self.mini_player.setStyleSheet(
            "QFrame{background:#171e28;border:1px solid #65758b;border-radius:6px;}"
        )
        mini_layout = QVBoxLayout(self.mini_player)
        mini_layout.setContentsMargins(4, 3, 4, 3)
        mini_layout.setSpacing(2)
        self.mini_title_button = QPushButton("Tidak ada playback")
        self.mini_title_button.setFixedHeight(22)
        self.mini_title_button.setToolTip("Kembali ke video yang sedang diputar")
        self.mini_title_button.setStyleSheet(
            "text-align:left;padding:1px 4px;font-size:11px;border:0;"
        )
        self.mini_title_button.clicked.connect(self.return_to_playback)
        mini_layout.addWidget(self.mini_title_button)
        mini_controls = QHBoxLayout()
        mini_controls.setSpacing(3)
        self.mini_progress = QProgressBar()
        self.mini_progress.setRange(0, 1000)
        self.mini_progress.setValue(0)
        self.mini_progress.setTextVisible(False)
        self.mini_progress.setFixedWidth(76)
        self.mini_progress.setFixedHeight(9)
        self.mini_progress.setStyleSheet(
            "QProgressBar{background:#394657;border:0;border-radius:3px;}"
            "QProgressBar::chunk{background:#ff334f;border-radius:3px;}"
        )
        mini_controls.addWidget(self.mini_progress)
        self.mini_rewind_button = QPushButton("-10")
        self.mini_rewind_button.setFixedWidth(38)
        self.mini_rewind_button.setToolTip("Mundur 10 detik")
        self.mini_rewind_button.clicked.connect(lambda: self.seek_relative(-10))
        self.mini_play_pause_button = QPushButton()
        self.mini_play_pause_button.setIcon(self.style().standardIcon(QStyle.SP_MediaPause))
        self.mini_play_pause_button.setFixedWidth(34)
        self.mini_play_pause_button.setToolTip("Jeda / lanjut")
        self.mini_play_pause_button.clicked.connect(self.toggle_play_pause)
        self.mini_fast_forward_button = QPushButton("+10")
        self.mini_fast_forward_button.setFixedWidth(38)
        self.mini_fast_forward_button.setToolTip("Maju 10 detik")
        self.mini_fast_forward_button.clicked.connect(lambda: self.seek_relative(10))
        self.mini_stop_button = QPushButton()
        self.mini_stop_button.setIcon(self.style().standardIcon(QStyle.SP_MediaStop))
        self.mini_stop_button.setFixedWidth(30)
        self.mini_stop_button.setToolTip("Stop playback")
        self.mini_stop_button.clicked.connect(self.stop_playback)
        for widget in (self.mini_rewind_button, self.mini_play_pause_button,
                       self.mini_fast_forward_button, self.mini_stop_button):
            widget.setFixedHeight(23)
            widget.setFocusPolicy(Qt.StrongFocus)
            mini_controls.addWidget(widget)
        mini_layout.addLayout(mini_controls)
        header.addWidget(self.mini_player)
        self.mini_player.hide()

        self.window_controls_widget = QWidget()
        window_controls = QHBoxLayout(self.window_controls_widget)
        window_controls.setContentsMargins(0, 0, 0, 0)
        window_controls.setSpacing(3)
        self.minimize_button = QPushButton()
        self.minimize_button.setIcon(self.style().standardIcon(QStyle.SP_TitleBarMinButton))
        self.minimize_button.setFixedSize(30, 28)
        self.minimize_button.setToolTip("Minimize aplikasi")
        self.minimize_button.clicked.connect(self.showMinimized)
        self.close_button = QPushButton()
        self.close_button.setIcon(self.style().standardIcon(QStyle.SP_TitleBarCloseButton))
        self.close_button.setFixedSize(30, 28)
        self.close_button.setToolTip("Tutup aplikasi dan hentikan playback")
        self.close_button.clicked.connect(self.close)
        window_controls.addWidget(self.minimize_button)
        window_controls.addWidget(self.close_button)
        header.addWidget(self.window_controls_widget)
        self.root_layout.addLayout(header)

        search_row = QHBoxLayout()
        self.query = QLineEdit()
        self.query.setPlaceholderText("Cari video atau tempel URL YouTube…")
        self.query.returnPressed.connect(self.search)
        self.keyboard_button = QPushButton("KEY")
        self.keyboard_button.setToolTip("Buka keyboard layar")
        self.keyboard_button.clicked.connect(self.toggle_keyboard)
        self.search_button = QPushButton("Search")
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
        self.prev_page_button = QPushButton("Prev")
        self.prev_page_button.setToolTip("Halaman sebelumnya")
        self.prev_page_button.clicked.connect(lambda: self.change_page(-1))
        self.page_label = QLabel("0 / 0")
        self.page_label.setAlignment(Qt.AlignCenter)
        self.page_label.setObjectName("hint")
        self.next_page_button = QPushButton("Next")
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
        self.player_page.setFocusPolicy(Qt.StrongFocus)
        self.player_page.setMouseTracking(True)
        player_layout = QVBoxLayout(self.player_page)
        player_layout.setContentsMargins(2, 2, 2, 2)
        player_layout.setSpacing(5)
        self.player_header_widget = QWidget()
        player_header = QHBoxLayout(self.player_header_widget)
        self.player_title = QLabel("Pemutar YouTube")
        self.player_title.setObjectName("brand")
        self.player_title.setWordWrap(True)
        self.back_button = QPushButton("Back")
        self.back_button.setToolTip("Kembali ke hasil")
        self.back_button.clicked.connect(self.back_to_results)
        player_header.addWidget(self.back_button)
        player_header.addWidget(self.player_title, 1)
        player_layout.addWidget(self.player_header_widget)

        # PlasmaTube-inspired watch page: wide video first, queue/details below.
        # A vertical flow is better suited to the device's 4:3 PAL display.
        body = QVBoxLayout()
        body.setSpacing(5)
        self.video_surface = QWidget()
        # MPV --wid must target a real child X11 window owned by this Qt page.
        self.video_surface.setAttribute(Qt.WA_NativeWindow, True)
        # The embedded MPV child must never become the Qt focus target.
        # Roxy owns remote/D-pad navigation; playback is controlled via IPC.
        self.video_surface.setFocusPolicy(Qt.NoFocus)
        self.video_surface.setMouseTracking(True)
        self.video_surface.setMinimumSize(300, 170)
        self.video_surface.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.video_surface.setStyleSheet("background:#000000;border:1px solid #384354;")
        body.addWidget(self.video_surface, 5)
        self.player_meta = QLabel("")
        self.player_meta.setObjectName("hint")
        self.player_meta.setWordWrap(False)
        self.player_meta.setStyleSheet(
            "color:#b9c5d3;font-size:11px;padding:2px 4px;border:0;")
        body.addWidget(self.player_meta)
        self.side_panel = QFrame()
        self.side_panel.setMinimumWidth(0)
        self.side_panel.setMaximumWidth(16777215)
        self.side_panel.setMaximumHeight(112)
        self.side_panel.setStyleSheet("QFrame{background:#171e28;border:1px solid #354253;border-radius:7px;}")
        side_layout = QVBoxLayout(self.side_panel)
        side_layout.setContentsMargins(5, 4, 5, 4)
        side_layout.setSpacing(3)
        side_buttons = QHBoxLayout()
        self.playlist_button = QPushButton("Queue")
        self.playlist_button.setToolTip("Antrean video")
        self.playlist_button.clicked.connect(lambda: self.show_side_panel("playlist"))
        self.description_button = QPushButton("Description")
        self.description_button.setToolTip("Deskripsi video")
        self.description_button.clicked.connect(lambda: self.show_side_panel("description"))
        side_buttons.addWidget(self.playlist_button)
        side_buttons.addWidget(self.description_button)
        side_layout.addLayout(side_buttons)
        self.side_content = QScrollArea()
        self.side_content.setWidgetResizable(True)
        self.side_content.setFocusPolicy(Qt.StrongFocus)
        self.side_content.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.side_text_host = QWidget()
        self.side_text_layout = QVBoxLayout(self.side_text_host)
        self.side_text_layout.setContentsMargins(2, 2, 2, 2)
        self.side_text_layout.setSpacing(2)
        self.side_content.setWidget(self.side_text_host)
        side_layout.addWidget(self.side_content, 1)
        self.timeline_widget = QWidget()
        self.timeline_widget.setMouseTracking(True)
        timeline = QHBoxLayout(self.timeline_widget)
        timeline.setContentsMargins(0, 0, 0, 0)
        timeline.setSpacing(5)
        self.elapsed_label = QLabel("0:00")
        self.elapsed_label.setObjectName("hint")
        self.elapsed_label.setMinimumWidth(35)
        self.elapsed_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.seek_slider = QSlider(Qt.Horizontal)
        self.seek_slider.setObjectName("playbackSlider")
        self.seek_slider.setRange(0, 0)
        self.seek_slider.setSingleStep(5)
        self.seek_slider.setPageStep(15)
        self.seek_slider.setFocusPolicy(Qt.StrongFocus)
        self.seek_slider.setToolTip("Geser untuk mencari posisi video; kiri/kanan untuk maju atau mundur 5 detik")
        self.seek_slider.setStyleSheet("""
            QSlider#playbackSlider { min-height:22px; }
            QSlider#playbackSlider::groove:horizontal { height:5px; background:#455365; border-radius:2px; }
            QSlider#playbackSlider::sub-page:horizontal { background:#ff334f; border-radius:2px; }
            QSlider#playbackSlider::handle:horizontal { background:#ffd166; width:13px; margin:-5px 0; border-radius:6px; }
        """)
        self.duration_label = QLabel("0:00")
        self.duration_label.setObjectName("hint")
        self.duration_label.setMinimumWidth(35)
        self.seek_slider.sliderPressed.connect(self.seek_started)
        self.seek_slider.sliderReleased.connect(self.seek_finished)
        self.seek_slider.valueChanged.connect(self.seek_preview)
        timeline.addWidget(self.elapsed_label)
        timeline.addWidget(self.seek_slider, 1)
        timeline.addWidget(self.duration_label)
        body.addWidget(self.timeline_widget)

        self.controls_widget = QWidget()
        self.controls_widget.setMouseTracking(True)
        controls = QHBoxLayout(self.controls_widget)
        controls.setContentsMargins(0, 0, 0, 0)
        self.previous_video_button = QPushButton()
        self.previous_video_button.setIcon(self.style().standardIcon(QStyle.SP_MediaSkipBackward))
        self.previous_video_button.setToolTip("Video sebelumnya")
        self.previous_video_button.clicked.connect(
            lambda: self.play_index(self.current_index - 1, queue=self.playback_queue)
        )
        self.rewind_button = QPushButton("-10")
        self.rewind_button.setFixedWidth(46)
        self.rewind_button.setToolTip("Mundur 10 detik")
        self.rewind_button.clicked.connect(lambda: self.seek_relative(-10))
        self.play_pause_button = QPushButton()
        self.play_pause_button.setIcon(self.style().standardIcon(QStyle.SP_MediaPause))
        self.play_pause_button.setToolTip("Jeda / lanjut")
        self.play_pause_button.clicked.connect(self.toggle_play_pause)
        self.play_pause_button.setFocusPolicy(Qt.StrongFocus)
        self.fast_forward_button = QPushButton("+10")
        self.fast_forward_button.setFixedWidth(46)
        self.fast_forward_button.setToolTip("Maju 10 detik")
        self.fast_forward_button.clicked.connect(lambda: self.seek_relative(10))
        self.next_video_button = QPushButton()
        self.next_video_button.setIcon(self.style().standardIcon(QStyle.SP_MediaSkipForward))
        self.next_video_button.setToolTip("Video berikutnya")
        self.next_video_button.clicked.connect(
            lambda: self.play_index(self.current_index + 1, queue=self.playback_queue)
        )
        self.stop_button = QPushButton()
        self.stop_button.setIcon(self.style().standardIcon(QStyle.SP_MediaStop))
        self.stop_button.setToolTip("Stop playback")
        self.stop_button.clicked.connect(self.stop_playback)
        self.subtitle_box = QComboBox()
        self.subtitle_box.setMinimumWidth(105)
        self.subtitle_box.addItem("Subtitle: Off", None)
        self.subtitle_box.currentIndexChanged.connect(self.select_subtitle)
        self.fullscreen_button = QPushButton("Maximize")
        self.fullscreen_button.setToolTip("Fullscreen playback")
        self.fullscreen_button.clicked.connect(self.toggle_playback_fullscreen)
        self.quality = QComboBox()
        self.quality.addItems(list(QUALITY_FORMATS))
        self.quality.setCurrentText("720p")
        self.quality.setMinimumWidth(75)
        self.quality.currentTextChanged.connect(self.change_quality)
        controls.addWidget(self.previous_video_button)
        controls.addWidget(self.rewind_button)
        controls.addWidget(self.play_pause_button)
        controls.addWidget(self.fast_forward_button)
        controls.addWidget(self.next_video_button)
        controls.addWidget(self.stop_button)
        self.volume_slider = QSlider(Qt.Horizontal)
        self.volume_slider.setRange(0, 100)
        self.volume_slider.setValue(100)
        self.volume_slider.setFixedWidth(72)
        self.volume_slider.setFocusPolicy(Qt.StrongFocus)
        self.volume_slider.setToolTip("Volume")
        self.volume_slider.valueChanged.connect(self.change_volume)
        controls.addWidget(QLabel("VOL"))
        controls.addWidget(self.volume_slider)
        controls.addStretch(1)
        controls.addWidget(QLabel("Kualitas"))
        controls.addWidget(self.quality)
        controls.addWidget(QLabel("CC"))
        controls.addWidget(self.subtitle_box)
        controls.addWidget(self.fullscreen_button)
        body.addWidget(self.controls_widget)
        body.addWidget(self.side_panel, 2)
        player_layout.addLayout(body, 1)
        self.player_status = QLabel("Menyiapkan pemutar…")
        self.player_status.setObjectName("hint")
        player_layout.addWidget(self.player_status)
        self.pages.addWidget(self.player_page)
        self.set_playback_controls_enabled(False)

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
        # Recommended/Home uses the same two-column grid as Search.
        columns = 2
        for i, card in enumerate(self.cards):
            self.cards_grid.removeWidget(card)
            self.cards_grid.addWidget(card, i // columns, i % columns)

    def set_keyboard_visible(self, visible):
        visible = bool(visible)
        if visible == self.keyboard_open:
            return
        self.keyboard_open = visible
        self.keyboard_button.setText("KEY CLOSE" if visible else "KEY")
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
        for button, label in zip(self.nav_buttons, self.nav_labels):
            button.setText("")
            button.setToolTip(label)
            button.setStyleSheet("padding:5px 2px;")

    def expand_sidebar(self):
        self.sidebar.setFixedWidth(150)
        for button, label in zip(self.nav_buttons, self.nav_labels):
            button.setText(label)
            button.setStyleSheet("text-align:left;padding:5px 7px;font-size:12px;")

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
        if self.process_is_running(self.search_process):
            self.search_process.kill()
        self.set_active_nav(mode)
        self.clear_cards()
        self.results = []
        self.current_page = 0
        self.search_button.setEnabled(False)
        if mode == "home":
            # Public search is available without a signed-in YouTube account.
            target = "ytsearch30:video populer Indonesia"
            self.results_heading.setText("BERANDA  •  PILIHAN VIDEO INDONESIA")
            self.status.setText("Memuat pilihan video publik…")
        else:
            # YouTube retired the old /feed/trending endpoint. Use a public
            # relevance search instead of relying on that obsolete playlist.
            target = "ytsearch30:video trending Indonesia terbaru"
            self.results_heading.setText("TRENDING  •  POPULER DI INDONESIA")
            self.status.setText("Mencari video populer di Indonesia…")
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
        if self.process_is_running(self.search_process):
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
                self.status.setText("Beranda belum mendapat hasil pencarian publik. Periksa koneksi atau yt-dlp.")
            elif self.feed_mode == "trending":
                self.status.setText("Pencarian video populer Indonesia gagal. Periksa koneksi atau yt-dlp.")
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
                    "duration_seconds": float(duration or 0),
                    "description": entry.get("description") or "",
                })
            if not self.results:
                if self.feed_mode == "home":
                    self.status.setText("Belum ada video publik untuk ditampilkan di Beranda.")
                elif self.feed_mode == "trending":
                    self.status.setText("Belum ada hasil video populer Indonesia saat ini.")
                else:
                    self.status.setText("Tidak ada video yang ditemukan.")
                return
            self.render_page()
            if self.feed_mode == "home":
                self.results_heading.setText("BERANDA  •  PILIHAN VIDEO INDONESIA")
                self.status.setText(f"{len(self.results)} rekomendasi publik.")
            elif self.feed_mode == "trending":
                self.results_heading.setText("TRENDING  •  POPULER DI INDONESIA")
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
        # Keep Recommended, Trending, and Search visually consistent.
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

    @staticmethod
    def process_is_running(process):
        """Return process state safely even if Qt has already deleted its C++ object."""
        if process is None:
            return False
        try:
            return process.state() != QProcess.NotRunning
        except RuntimeError:
            return False

    def quality_fallbacks(self, quality):
        if quality == "720p":
            return ["480p", "Auto"]
        if quality == "480p":
            return ["Auto"]
        if quality == "360p":
            return ["Auto"]
        return []

    def play_index(self, index, start_position=0.0, background=False, queue=None):
        if queue is None:
            queue = list(self.results)
        else:
            queue = list(queue)
        if not queue:
            return
        self.playback_queue = queue
        index = max(0, min(int(index), len(self.playback_queue) - 1))
        self.background_playback = bool(background)
        self.mini_player.setVisible(self.background_playback)
        self.window_controls_widget.setVisible(self.background_playback)
        self.current_index = index
        self.set_mini_controls_enabled(False)
        self.manual_stop = False
        self.selected_subtitle_track = None
        self.subtitle_applied_process = None
        self.subtitle_applied_track = None
        self.current_time_pos = max(0.0, float(start_position or 0.0))
        self.duration_seconds = float(self.playback_queue[index].get("duration_seconds") or 0)
        self.update_timeline(self.current_time_pos, self.duration_seconds)
        self.set_playback_controls_enabled(False)
        self.playback_paused = False
        self.update_play_pause_icons()
        self.fallback_qualities = self.quality_fallbacks(self.quality.currentText())
        self.metadata_requested_index = None
        video = self.playback_queue[index]
        self.player_title.setText(video["title"])
        self.set_mini_title(video["title"])
        channel = video.get("channel") or "YouTube"
        duration = video.get("duration") or ""
        self.player_meta.setText(f"{channel}  •  {duration}" if duration else channel)
        self.player_status.setText("Menghubungkan ke YouTube…")
        self.subtitle_box.blockSignals(True)
        self.subtitle_box.clear()
        self.subtitle_box.addItem("Subtitle: Off", None)
        self.subtitle_box.blockSignals(False)
        self.show_side_panel("playlist")
        self.populate_playlist()
        if self.background_playback:
            self.pages.setCurrentWidget(self.search_page)
            self.mini_player.show()
            self.window_controls_widget.show()
        else:
            self.pages.setCurrentWidget(self.player_page)
            self.mini_player.hide()
            self.window_controls_widget.hide()
        self.video_surface.winId()
        # Keep keyboard focus in Roxy when MPV is embedded in the native surface.
        self.play_pause_button.setFocus(Qt.OtherFocusReason)
        self._launch_player()

    def _launch_player(self):
        if not shutil.which(MPV):
            QMessageBox.critical(self, APP_NAME, f"mpv tidak ditemukan: {MPV}")
            self.back_to_results()
            return
        old_process = self.player_process
        self.player_process = None
        self.dispose_mpv_event_socket()
        if self.process_is_running(old_process):
            old_process.kill()
        self.ipc_path = f"/tmp/roxy-youtube-tv-{os.getpid()}-{self.current_index}.sock"
        try:
            Path(self.ipc_path).unlink(missing_ok=True)
        except OSError:
            pass
        process = QProcess(self)
        self.player_process = process
        # Attach MPV to the native Qt child window; do not create a separate
        # top-level MPV window. HG680P's verified audible ALSA route is dmix.
        args = ["--no-osc", "--vo=x11", f"--wid={int(self.video_surface.winId())}",
                # Never let MPV consume the TV remote; Roxy handles D-pad keys
                # and sends explicit playback commands over MPV IPC.
                "--input-vo-keyboard=no", "--input-default-bindings=no",
                f"--volume={self.volume_slider.value()}",
                "--ao=alsa",
                "--audio-device=alsa/dmix:CARD=S905XP212,DEV=0",
                f"--input-ipc-server={self.ipc_path}",
                f"--ytdl-format={QUALITY_FORMATS[self.quality.currentText()]}",
                # Keep subtitle enumeration out of the startup path; metadata is fetched later.
                "--ytdl-raw-options=sub-langs=none",
                "--keep-open=no"]
        if self.current_time_pos > 0.5:
            args.append(f"--start={self.current_time_pos:.2f}")
        if self.playback_paused:
            args.append("--pause")
        args.append(self.playback_queue[self.current_index]["url"])
        process.setProgram(MPV)
        process.setArguments(args)
        process.started.connect(lambda p=process: self.player_started(p))
        process.finished.connect(lambda code, _status, p=process: self.player_finished(p, code))
        process.errorOccurred.connect(lambda _err, p=process: self.player_error(p))
        self.playback_started = False
        process.start()
        self.player_status.setText(f"Mencoba kualitas {self.quality.currentText()}…")

    def change_quality(self, quality):
        if self.pages.currentWidget() != self.player_page or not self.playback_queue:
            return
        if not self.process_is_running(self.player_process):
            return
        self.fallback_qualities = self.quality_fallbacks(quality)
        self.player_status.setText(f"Mengganti kualitas ke {quality}…")
        self._launch_player()

    def player_started(self, process):
        if process is self.player_process:
            self.player_status.setText("Mengambil stream video…")
            self.set_playback_controls_enabled(True)
            self.set_mini_controls_enabled(True)
            self.mpv_event_attempts = 0
            QTimer.singleShot(250, lambda i=self.current_index, p=process:
                              self.connect_mpv_events(i, p))

    def dispose_mpv_event_socket(self, sock=None):
        """Detach an IPC socket before scheduling Qt object deletion."""
        target = sock if sock is not None else self.mpv_event_socket
        if target is None:
            return
        if target is self.mpv_event_socket:
            self.mpv_event_socket = None
        try:
            target.abort()
        except RuntimeError:
            pass
        try:
            target.deleteLater()
        except RuntimeError:
            pass

    def connect_mpv_events(self, index, process):
        """Connect to MPV IPC so metadata work starts only after playback begins."""
        if (process is not self.player_process or index != self.current_index or
                not self.process_is_running(process)):
            return
        self.dispose_mpv_event_socket()
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
            # Clear the member reference before deleteLater(); otherwise the
            # next retry can see a Python wrapper for an already-deleted C++ socket.
            self.dispose_mpv_event_socket(sock)
            QTimer.singleShot(250, lambda i=index, p=process:
                              self.connect_mpv_events(i, p))

    def mpv_event_connected(self, sock):
        if sock is not self.mpv_event_socket:
            return
        # Observe time-pos as a fallback if the initial playback event was missed.
        for command in (
            ["observe_property", 1, "time-pos"],
            ["observe_property", 2, "duration"],
            ["observe_property", 3, "pause"],
        ):
            sock.write(json.dumps({"command": command}).encode("utf-8") + b"\n")
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
                if (self.selected_subtitle_track and
                        self.subtitle_applied_process is not process):
                    QTimer.singleShot(300, self.apply_selected_subtitle)
            elif event == "property-change":
                name, value = message.get("name"), message.get("data")
                if name == "time-pos" and isinstance(value, (int, float)):
                    self.current_time_pos = max(0.0, float(value))
                    self.playback_started = True
                    self.update_timeline(self.current_time_pos, self.duration_seconds)
                    self.schedule_metadata_after_start(index, process, 1200)
                    if (self.selected_subtitle_track and
                            self.subtitle_applied_process is not process):
                        QTimer.singleShot(300, self.apply_selected_subtitle)
                elif name == "duration" and isinstance(value, (int, float)):
                    self.duration_seconds = max(0.0, float(value))
                    self.update_timeline(self.current_time_pos, self.duration_seconds)
                elif name == "pause" and isinstance(value, bool):
                    self.playback_paused = value
                    self.update_play_pause_icons()

    def schedule_metadata_after_start(self, index, process, delay_ms):
        if self.metadata_requested_index == index:
            return
        self.metadata_requested_index = index
        QTimer.singleShot(
            delay_ms,
            lambda i=index, p=process:
                self.fetch_metadata(i)
                if p is self.player_process and i == self.current_index and self.process_is_running(p)
                else None,
        )

    def retry_lower_quality(self, process, reason):
        if (process is not self.player_process or self.playback_started or
                not self.fallback_qualities):
            return False
        next_quality = self.fallback_qualities.pop(0)
        self.set_mini_controls_enabled(False)
        self.player_process = None
        self.quality.blockSignals(True)
        self.quality.setCurrentText(next_quality)
        self.quality.blockSignals(False)
        self.player_status.setText(f"{reason} Mencoba {next_quality}…")
        try:
            process.deleteLater()
        except RuntimeError:
            pass
        QTimer.singleShot(450, self._launch_player)
        return True

    def player_finished(self, process, exit_code):
        if process is self.player_process:
            if self.retry_lower_quality(process, "Stream gagal dibuka."):
                return
            finished_naturally = (
                exit_code == 0 and self.playback_started and not self.manual_stop
            )
            finished_index = self.current_index
            self.player_process = None
            self.set_playback_controls_enabled(False)
            self.set_mini_controls_enabled(False)
            if finished_naturally and finished_index + 1 < len(self.playback_queue):
                self.player_status.setText("Video selesai. Memutar video berikutnya…")
                keep_background = self.background_playback
                QTimer.singleShot(250, lambda i=finished_index + 1, bg=keep_background:
                                  self.play_index(i, background=bg, queue=self.playback_queue)
                                  if self.current_index == finished_index
                                  and self.player_process is None else None)
            else:
                self.background_playback = False
                self.mini_player.hide()
                self.window_controls_widget.setVisible(
                    self.pages.currentWidget() == self.search_page
                )
                if self.pages.currentWidget() == self.player_page:
                    self.player_status.setText(
                        "Pemutaran selesai." if finished_naturally
                        else "Pemutaran selesai atau stream terputus."
                    )
        try:
            process.deleteLater()
        except RuntimeError:
            pass

    def player_error(self, process):
        if process is self.player_process:
            if self.retry_lower_quality(process, "MPV gagal membuka stream."):
                return
            self.player_process = None
            self.background_playback = False
            self.mini_player.hide()
            self.window_controls_widget.setVisible(
                self.pages.currentWidget() == self.search_page
            )
            self.set_playback_controls_enabled(False)
            self.set_mini_controls_enabled(False)
            self.player_status.setText("MPV gagal dijalankan.")
        try:
            process.deleteLater()
        except RuntimeError:
            pass

    def fetch_metadata(self, index):
        if self.process_is_running(self.metadata_process):
            self.metadata_process.kill()
        process = QProcess(self)
        self.metadata_process = process
        process.setProgram(YTDLP)
        process.setArguments(["--no-warnings", "--skip-download", "--no-playlist",
                              "--dump-single-json", self.playback_queue[index]["url"]])
        process.finished.connect(lambda code, _status, p=process, i=index: self.metadata_finished(p, i, code))
        process.start()

    def metadata_finished(self, process, index, exit_code):
        if process is not self.metadata_process or index != self.current_index or exit_code != 0:
            return
        try:
            data = json.loads(bytes(process.readAllStandardOutput()).decode("utf-8", "replace"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            return
        if data.get("duration") is not None:
            self.duration_seconds = max(0.0, float(data["duration"]))
            self.playback_queue[index]["duration_seconds"] = self.duration_seconds
            self.update_timeline(self.current_time_pos, self.duration_seconds)
        description = data.get("description") or self.playback_queue[index].get("description") or "Deskripsi tidak tersedia."
        self.playback_queue[index]["description"] = description
        self.show_side_panel("description", description)
        tracks = []
        for source, label in ((data.get("subtitles") or {}, "Tersedia"),
                              (data.get("automatic_captions") or {}, "Otomatis")):
            for lang, entries in source.items():
                # Prefer WebVTT when YouTube exposes several encodings for one language.
                item = next((entry for entry in entries
                             if entry.get("url") and entry.get("ext") == "vtt"), None)
                if item is None:
                    item = next((entry for entry in entries
                                 if entry.get("url") and entry.get("ext") in
                                 ("srt", "ass", "srv3", "ttml", "json3")), None)
                if item:
                    tracks.append({"lang": lang, "name": item.get("name") or lang,
                                   "source": label, "url": item["url"]})
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
            self.selected_subtitle_track = None
            self.player_status.setText("Subtitle tidak tersedia untuk video ini.")

    @staticmethod
    def format_time(seconds):
        seconds = max(0, int(seconds or 0))
        hours, remainder = divmod(seconds, 3600)
        minutes, secs = divmod(remainder, 60)
        return f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes}:{secs:02d}"

    def update_timeline(self, position, duration):
        duration = max(0.0, float(duration or 0))
        position = max(0.0, float(position or 0))
        self.elapsed_label.setText(self.format_time(position))
        self.duration_label.setText(self.format_time(duration))
        self.mini_progress.setValue(
            int(min(1.0, position / duration) * 1000) if duration > 0 else 0
        )
        if not self.slider_dragging:
            self.seek_slider.blockSignals(True)
            self.seek_slider.setRange(0, max(0, int(duration)))
            self.seek_slider.setValue(min(int(position), int(duration)) if duration else 0)
            self.seek_slider.blockSignals(False)
        self.seek_slider.setEnabled(duration > 0 and self.player_process is not None and
                                    self.process_is_running(self.player_process))

    def seek_started(self):
        self.slider_dragging = True

    def seek_preview(self, value):
        if self.slider_dragging:
            self.elapsed_label.setText(self.format_time(value))

    def seek_finished(self):
        value = self.seek_slider.value()
        self.slider_dragging = False
        if self.duration_seconds > 0:
            self.current_time_pos = float(value)
            self.mpv_command(["seek", value, "absolute+exact"])
            self.update_timeline(self.current_time_pos, self.duration_seconds)

    def seek_relative(self, seconds):
        """Seek the active MPV session by a fixed relative offset."""
        if not self.process_is_running(self.player_process):
            return
        if not self.mpv_command(["seek", int(seconds), "relative+exact"]):
            return
        target = max(0.0, self.current_time_pos + float(seconds))
        if self.duration_seconds > 0:
            target = min(target, self.duration_seconds)
        self.current_time_pos = target
        self.update_timeline(target, self.duration_seconds)

    def update_play_pause_icons(self):
        icon_type = QStyle.SP_MediaPlay if self.playback_paused else QStyle.SP_MediaPause
        icon = self.style().standardIcon(icon_type)
        self.play_pause_button.setIcon(icon)
        self.mini_play_pause_button.setIcon(icon)

    def toggle_play_pause(self):
        if not self.process_is_running(self.player_process):
            return
        self.mpv_command(["cycle", "pause"])
        self.playback_paused = not self.playback_paused
        self.update_play_pause_icons()

    def set_mini_controls_enabled(self, enabled):
        for widget in (self.mini_rewind_button, self.mini_play_pause_button,
                       self.mini_fast_forward_button, self.mini_stop_button):
            widget.setEnabled(bool(enabled))

    def set_playback_controls_enabled(self, enabled):
        for widget in (self.rewind_button, self.play_pause_button, self.fast_forward_button,
                       self.seek_slider, self.volume_slider, self.quality, self.subtitle_box,
                       self.fullscreen_button):
            widget.setEnabled(bool(enabled))
        self.previous_video_button.setEnabled(bool(enabled) and self.current_index > 0)
        self.next_video_button.setEnabled(
            bool(enabled) and self.current_index + 1 < len(self.playback_queue)
        )
        self.stop_button.setEnabled(bool(enabled))

    def change_volume(self, value):
        if self.process_is_running(self.player_process):
            self.mpv_command(["set_property", "volume", int(value)])

    def select_subtitle(self, index):
        track = self.subtitle_box.itemData(index)
        self.selected_subtitle_track = track
        self.subtitle_applied_process = None
        self.subtitle_applied_track = None
        if not track:
            self.mpv_command(["set_property", "sid", "no"])
            self.mpv_command(["set_property", "sub-visibility", False])
            return
        self.apply_selected_subtitle()

    def apply_selected_subtitle(self):
        """Apply the chosen external track to the currently active MPV session."""
        track = self.selected_subtitle_track
        process = self.player_process
        if not track or not self.process_is_running(process):
            return
        if self.subtitle_applied_process is process and self.subtitle_applied_track == track:
            return
        if not self.mpv_command([
            "sub-add", track["url"], "select", track["name"], track["lang"]
        ]):
            self.player_status.setText("Subtitle belum dapat diterapkan ke MPV.")
            return
        self.mpv_command(["set_property", "sub-visibility", True])
        self.subtitle_applied_process = process
        self.subtitle_applied_track = track
        self.player_status.setText(f"Subtitle aktif: {track['name']}")

    def mpv_command(self, command):
        if not self.process_is_running(self.player_process):
            return False
        payload = json.dumps({"command": command}).encode("utf-8") + b"\n"
        # Reuse the live event channel whenever possible. This avoids racing
        # MPV's IPC socket creation and keeps remote controls responsive.
        event_socket = self.mpv_event_socket
        if event_socket is not None:
            try:
                connected = event_socket.state() == QLocalSocket.ConnectedState
            except RuntimeError:
                # Qt may have destroyed the C++ socket while its Python wrapper
                # is still referenced; discard it and use a fresh IPC connection.
                if event_socket is self.mpv_event_socket:
                    self.mpv_event_socket = None
                connected = False
            if connected:
                try:
                    if event_socket.write(payload) < 0:
                        return False
                    event_socket.flush()
                    return True
                except RuntimeError:
                    if event_socket is self.mpv_event_socket:
                        self.mpv_event_socket = None
        socket = QLocalSocket(self)
        socket.connectToServer(self.ipc_path)
        if not socket.waitForConnected(1000):
            socket.deleteLater()
            return False
        if socket.write(payload) < 0 or not socket.waitForBytesWritten(750):
            socket.abort()
            socket.deleteLater()
            return False
        socket.disconnectFromServer()
        socket.deleteLater()
        return True

    def populate_playlist(self):
        self.clear_side_content()
        self.playlist_items = []
        for idx, item in enumerate(self.playback_queue):
            button = QPushButton((">  " if idx == self.current_index else "") + item["title"])
            button.setToolTip(item["title"])
            button.setFocusPolicy(Qt.StrongFocus)
            button.setStyleSheet("text-align:left;padding:6px;font-size:11px;")
            button.clicked.connect(
                lambda checked=False, i=idx: self.play_index(i, queue=self.playback_queue)
            )
            self.side_text_layout.addWidget(button)
            self.playlist_items.append(button)
        self.side_text_layout.addStretch(1)

    def show_side_panel(self, mode, description=None):
        self.clear_side_content()
        if mode == "description":
            text = description if description is not None else (
                self.playback_queue[self.current_index].get("description", "") if self.playback_queue else "")
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
        self.playlist_items = []
        while self.side_text_layout.count():
            item = self.side_text_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

    def stop_playback(self):
        if self.is_playback_fullscreen:
            self.exit_playback_fullscreen()
        self.manual_stop = True
        self.set_mini_controls_enabled(False)
        self.background_playback = False
        self.mini_player.hide()
        self.window_controls_widget.show()
        self.fallback_qualities.clear()
        process = self.player_process
        self.player_process = None
        if self.process_is_running(process):
            process.terminate()
            QTimer.singleShot(700, lambda p=process: p.kill()
                              if self.process_is_running(p) else None)
        self.selected_subtitle_track = None
        self.subtitle_applied_process = None
        self.subtitle_applied_track = None
        self.current_time_pos = 0.0
        self.playback_started = False
        self.set_playback_controls_enabled(False)
        self.slider_dragging = False
        self.pages.setCurrentWidget(self.search_page)
        if self.cards:
            self.cards[0].setFocus()
        else:
            self.query.setFocus()

    def back_to_results(self):
        self.background_playback = self.process_is_running(self.player_process)
        if not self.background_playback:
            self.fallback_qualities.clear()
        self.mini_player.setVisible(self.background_playback)
        self.window_controls_widget.show()
        self.set_playback_controls_enabled(False)
        self.slider_dragging = False
        self.pages.setCurrentWidget(self.search_page)
        if self.cards:
            self.cards[0].setFocus()
        else:
            self.query.setFocus()

    def toggle_playback_fullscreen(self):
        if self.is_playback_fullscreen:
            self.exit_playback_fullscreen()
            return
        self.is_playback_fullscreen = True
        self.showFullScreen()
        self.player_header_widget.hide()
        self.player_meta.hide()
        self.side_panel.hide()
        self.player_status.hide()
        self.timeline_widget.hide()
        self.controls_widget.hide()
        self.fullscreen_button.setText("Minimize")
        self.fullscreen_button.setToolTip("Kembali ke tampilan normal")
        self.fullscreen_controls_visible = False
        self.player_page.setFocus()

    def exit_playback_fullscreen(self):
        self.fullscreen_hide_timer.stop()
        self.is_playback_fullscreen = False
        self.fullscreen_controls_visible = True
        self.showNormal()
        self.player_header_widget.show()
        self.player_meta.show()
        self.side_panel.show()
        self.player_status.show()
        self.timeline_widget.show()
        self.controls_widget.show()
        self.fullscreen_button.setText("Maximize")
        self.fullscreen_button.setToolTip("Fullscreen playback")
        self.play_pause_button.setFocus(Qt.OtherFocusReason)

    def show_fullscreen_controls(self, focus_slider=False):
        if not self.is_playback_fullscreen:
            return
        self.timeline_widget.show()
        self.controls_widget.show()
        self.fullscreen_controls_visible = True
        if focus_slider:
            self.seek_slider.setFocus(Qt.OtherFocusReason)
        self.fullscreen_hide_timer.start(1000)

    def hide_fullscreen_controls(self):
        if not self.is_playback_fullscreen:
            return
        self.timeline_widget.hide()
        self.controls_widget.hide()
        self.fullscreen_controls_visible = False
        self.player_page.setFocus(Qt.OtherFocusReason)

    def set_mini_title(self, title):
        self.mini_title_text = str(title or "Video tanpa judul")
        self.mini_title_offset = 0
        self.mini_title_button.setToolTip(self.mini_title_text)
        self.advance_mini_title()
        text_width = self.mini_title_button.fontMetrics().horizontalAdvance(self.mini_title_text)
        if text_width > self.mini_title_button.width() - 22:
            self.mini_title_timer.start()
        else:
            self.mini_title_timer.stop()
            self.mini_title_button.setText(self.mini_title_text)

    def advance_mini_title(self):
        text = self.mini_title_text
        if not text:
            return
        char_width = max(1, self.mini_title_button.fontMetrics().horizontalAdvance("M"))
        visible = max(8, int((self.mini_title_button.width() - 22) / char_width))
        if len(text) <= visible:
            self.mini_title_button.setText(text)
            return
        cycle = text + "   "
        doubled = cycle + cycle
        start = self.mini_title_offset
        self.mini_title_button.setText(doubled[start:start + visible])
        self.mini_title_offset = (start + 1) % len(cycle)

    def return_to_playback(self):
        if not self.process_is_running(self.player_process):
            self.mini_player.hide()
            return
        self.background_playback = False
        self.mini_player.hide()
        self.window_controls_widget.hide()
        self.pages.setCurrentWidget(self.player_page)
        self.set_playback_controls_enabled(True)
        self.play_pause_button.setFocus(Qt.OtherFocusReason)

    def eventFilter(self, watched, event):
        if self.is_playback_fullscreen and event.type() == QEvent.MouseMove:
            try:
                point = watched.mapTo(self.player_page, event.position().toPoint())
                if point.y() >= int(self.player_page.height() * 0.68):
                    self.show_fullscreen_controls()
                elif self.fullscreen_controls_visible:
                    self.fullscreen_hide_timer.start(1000)
            except (AttributeError, RuntimeError, TypeError):
                pass
        if event.type() == QEvent.KeyPress and self.isActiveWindow():
            key, focus = event.key(), QApplication.focusWidget()
            if self.is_playback_fullscreen:
                if key in (Qt.Key_Escape, Qt.Key_Back):
                    self.exit_playback_fullscreen()
                    return True
                if self.fullscreen_controls_visible:
                    self.fullscreen_hide_timer.start(1000)
                    if key == Qt.Key_Down and focus is self.player_page:
                        self.seek_slider.setFocus(Qt.OtherFocusReason)
                        return True
                    if key == Qt.Key_Up and focus is self.seek_slider:
                        self.hide_fullscreen_controls()
                        return True
                    if key == Qt.Key_Down and focus in (
                        self.previous_video_button, self.rewind_button, self.play_pause_button,
                        self.fast_forward_button, self.next_video_button, self.stop_button,
                        self.quality, self.subtitle_box, self.fullscreen_button
                    ):
                        self.hide_fullscreen_controls()
                        return True
                elif key == Qt.Key_Down:
                    self.show_fullscreen_controls(focus_slider=True)
                    return True
                if focus is self.player_page and key in (Qt.Key_Return, Qt.Key_Enter, Qt.Key_Select):
                    self.toggle_play_pause()
                    return True
            if self.pages.currentWidget() == self.player_page:
                if key in (Qt.Key_Escape, Qt.Key_Back):
                    self.back_to_results()
                    return True
                if focus in (self.seek_slider, self.volume_slider):
                    if key in (Qt.Key_Left, Qt.Key_Right):
                        if focus is self.seek_slider:
                            step = 10 if QApplication.keyboardModifiers() & Qt.ShiftModifier else 5
                            target = self.seek_slider.value() + (step if key == Qt.Key_Right else -step)
                            target = max(0, min(int(self.duration_seconds), target))
                            self.seek_slider.setValue(target)
                            self.current_time_pos = float(target)
                            self.mpv_command(["seek", target, "absolute+exact"])
                            self.elapsed_label.setText(self.format_time(target))
                        else:
                            step = 5
                            self.volume_slider.setValue(max(0, min(100,
                                self.volume_slider.value() + (step if key == Qt.Key_Right else -step))))
                        return True
                    if key == Qt.Key_Down:
                        (self.quality if focus is self.volume_slider else self.previous_video_button).setFocus()
                        return True
                    if key == Qt.Key_Up:
                        if focus is self.volume_slider:
                            self.seek_slider.setFocus()
                        else:
                            self.back_button.setFocus()
                        return True
                if focus in (self.previous_video_button, self.rewind_button,
                             self.play_pause_button, self.fast_forward_button,
                             self.next_video_button, self.stop_button):
                    row = [self.previous_video_button, self.rewind_button,
                           self.play_pause_button, self.fast_forward_button,
                           self.next_video_button, self.stop_button, self.volume_slider]
                    pos = row.index(focus)
                    if key == Qt.Key_Left and pos > 0:
                        row[pos - 1].setFocus(); return True
                    if key == Qt.Key_Right and pos < len(row) - 1:
                        row[pos + 1].setFocus(); return True
                    if key == Qt.Key_Up:
                        self.seek_slider.setFocus(); return True
                    if key == Qt.Key_Down:
                        self.playlist_button.setFocus(); return True
                if focus is self.quality:
                    if key == Qt.Key_Left:
                        self.stop_button.setFocus(); return True
                    if key == Qt.Key_Right:
                        self.subtitle_box.setFocus(); return True
                    if key == Qt.Key_Up:
                        self.seek_slider.setFocus(); return True
                    if key == Qt.Key_Down:
                        self.playlist_button.setFocus(); return True
                if focus is self.subtitle_box:
                    if key == Qt.Key_Left:
                        self.quality.setFocus(); return True
                    if key == Qt.Key_Right:
                        self.fullscreen_button.setFocus(); return True
                    if key == Qt.Key_Up:
                        self.seek_slider.setFocus(); return True
                    if key == Qt.Key_Down:
                        self.playlist_button.setFocus(); return True
                if focus is self.fullscreen_button:
                    if key == Qt.Key_Left:
                        self.subtitle_box.setFocus(); return True
                    if key == Qt.Key_Up:
                        self.seek_slider.setFocus(); return True
                    if key == Qt.Key_Down:
                        self.playlist_button.setFocus(); return True
                if focus in self.playlist_items:
                    item_index = self.playlist_items.index(focus)
                    if key == Qt.Key_Up:
                        if item_index > 0:
                            self.playlist_items[item_index - 1].setFocus()
                        else:
                            self.playlist_button.setFocus()
                        return True
                    if key == Qt.Key_Down:
                        if item_index + 1 < len(self.playlist_items):
                            self.playlist_items[item_index + 1].setFocus()
                        else:
                            self.side_content.setFocus()
                        return True
                    if key == Qt.Key_Left:
                        self.playlist_button.setFocus(); return True
                    if key == Qt.Key_Right:
                        self.description_button.setFocus(); return True
                if focus in (self.side_content, self.side_content.viewport()):
                    scroll_bar = self.side_content.verticalScrollBar()
                    if key == Qt.Key_Up:
                        if scroll_bar.value() <= scroll_bar.minimum():
                            self.subtitle_box.setFocus(); return True
                        scroll_bar.setValue(max(scroll_bar.minimum(),
                                                scroll_bar.value() - scroll_bar.singleStep()))
                        return True
                    if key == Qt.Key_Down:
                        if scroll_bar.value() >= scroll_bar.maximum():
                            self.description_button.setFocus(); return True
                        scroll_bar.setValue(min(scroll_bar.maximum(),
                                                scroll_bar.value() + scroll_bar.singleStep()))
                        return True
                if focus in (self.playlist_button, self.description_button):
                    if key == Qt.Key_Left:
                        self.playlist_button.setFocus(); return True
                    if key == Qt.Key_Right:
                        self.description_button.setFocus(); return True
                    if key == Qt.Key_Up:
                        self.subtitle_box.setFocus(); return True
                    if key == Qt.Key_Down:
                        self.side_content.setFocus(); return True
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
                mini_buttons = (self.mini_rewind_button, self.mini_play_pause_button,
                                self.mini_fast_forward_button, self.mini_stop_button)
                if focus is self.mini_title_button and self.mini_player.isVisible():
                    if key == Qt.Key_Down:
                        self.mini_rewind_button.setFocus(); return True
                    if key == Qt.Key_Right:
                        self.minimize_button.setFocus(); return True
                    if key in (Qt.Key_Return, Qt.Key_Enter, Qt.Key_Select):
                        self.return_to_playback(); return True
                if focus in mini_buttons:
                    pos = mini_buttons.index(focus)
                    if key == Qt.Key_Left and pos > 0:
                        mini_buttons[pos - 1].setFocus(); return True
                    if key == Qt.Key_Right and pos < len(mini_buttons) - 1:
                        mini_buttons[pos + 1].setFocus(); return True
                    if key == Qt.Key_Up:
                        self.mini_title_button.setFocus(); return True
                    if key == Qt.Key_Down:
                        if self.cards:
                            self.cards[0].setFocus()
                        else:
                            self.query.setFocus()
                        return True
                if focus is self.minimize_button:
                    if key == Qt.Key_Right:
                        self.close_button.setFocus(); return True
                    if key == Qt.Key_Left:
                        (self.mini_title_button if self.mini_player.isVisible()
                         else self.query).setFocus(); return True
                    if key == Qt.Key_Down:
                        self.query.setFocus(); return True
                if focus is self.close_button:
                    if key == Qt.Key_Left:
                        self.minimize_button.setFocus(); return True
                    if key == Qt.Key_Down:
                        self.query.setFocus(); return True
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
                    if key == Qt.Key_Right and cols == 2 and idx + 1 < len(self.cards):
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
                if focus is self.query and key == Qt.Key_Up:
                    (self.mini_title_button if self.mini_player.isVisible()
                     else self.minimize_button).setFocus()
                    return True
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
        if self.process_is_running(self.player_process):
            answer = QMessageBox.question(
                self, APP_NAME,
                "Playback masih berjalan. Tutup Roxy dan hentikan playback?",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No
            )
            if answer != QMessageBox.Yes:
                event.ignore()
                return
        self.mini_title_timer.stop()
        self.fullscreen_hide_timer.stop()
        for process in (self.search_process, self.player_process, self.metadata_process):
            if self.process_is_running(process):
                process.terminate()
        try:
            Path(self.ipc_path).unlink(missing_ok=True)
        except OSError:
            pass
        super().closeEvent(event)


def main():
    app = QApplication(sys.argv)
    # LauncherTV may start the application again after its window was minimized.
    # Reuse the existing process and restore its window instead of opening a
    # second copy behind the launcher.
    server_name = f"roxy-youtube-tv-{os.getuid()}"
    probe = QLocalSocket()
    probe.connectToServer(server_name)
    if probe.waitForConnected(500):
        probe.write(b"activate")
        probe.waitForBytesWritten(500)
        probe.disconnectFromServer()
        return 0

    QLocalServer.removeServer(server_name)
    server = QLocalServer(app)
    if not server.listen(server_name):
        print(f"Unable to create single-instance server: {server.errorString()}", file=sys.stderr)
        return 1

    window = MainWindow()

    def activate_existing_window():
        while server.hasPendingConnections():
            client = server.nextPendingConnection()
            if client is None:
                continue
            client.waitForReadyRead(250)
            command = bytes(client.readAll()).strip()
            if command == b"activate":
                if window.isMinimized():
                    window.showNormal()
                else:
                    window.show()
                window.raise_()
                window.activateWindow()
            client.disconnectFromServer()
            client.deleteLater()

    server.newConnection.connect(activate_existing_window)
    app._roxy_single_instance_server = server
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()