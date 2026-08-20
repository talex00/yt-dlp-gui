from __future__ import annotations

import ctypes
import json
import os
import queue
import re
import shutil
import subprocess
import sys
import threading
from pathlib import Path
from tkinter import TclError, filedialog, messagebox
from typing import Any

import customtkinter as ctk

APP_NAME = "yt-dlp GUI"
PROGRESS_RE = re.compile(r"\[download\]\s+([\d.]+)%")

# Physical "V" key: 86 on Windows, 55 on X11. Independent of the active layout.
PASTE_KEYCODES = {86, 55}
# Keysym reported for the same physical key under a Cyrillic layout.
PASTE_KEYSYMS = {"cyrillic_em"}

# The layout is authored for these logical sizes. Actual pixels are derived
# from them by the scaling factor computed in App._init_scaling.
BASE_WIDTH = 840
BASE_HEIGHT = 900
# Room reserved for the taskbar and the window frame.
CHROME_MARGIN = 110
MIN_SCALING = 0.62
MAX_AUTO_SCALING = 2.0

WINDOW_BG = ("#f6f6f4", "#181818")
CONTROL_BG = ("#ffffff", "#242424")
# Two logical pixels and higher contrast keep rounded outlines crisp at
# fractional Windows scales such as 125% and 150%.
CONTROL_BORDER = ("#9b9b96", "#666666")

SIZE_UNITS = {
    "ru": ("Б", "КБ", "МБ", "ГБ"),
    "en": ("B", "KB", "MB", "GB"),
}

TEXTS: dict[str, dict[str, str]] = {
    "ru": {
        "url_hint": "Вставьте сюда ссылку на видео",
        "mode_video": "Видео",
        "mode_audio": "Аудио",
        "codec": "Кодек",
        "audio_format": "Формат файла",
        "audio_original": "Оригинал",
        "separate": "Скачать видео и аудио отдельно",
        "playlist": "Скачать весь плейлист",
        "subtitles": "Встроить субтитры",
        "subtitles_unavailable": "Субтитры недоступны",
        "subtitle_auto": "авто",
        "save_to": "Сохранить в",
        "download_video": "Скачать видео с аудио",
        "download_audio": "Скачать аудио",
        "cancel": "Отмена",
        "details": "Подробности",
        "hide_details": "Скрыть подробности",
        "open_folder": "Открыть папку",
        "default_title": "Видео",
        "kbps": "кбит/с",
        "size_unknown": "размер неизвестен",
        "size_ready": "Примерный размер готового файла: {size}",
        "size_total": "Примерный размер: {size} · {suffix}",
        "size_suffix_separate": "суммарно для двух файлов",
        "size_suffix_merge": "после объединения с аудио",
        "status_choose": "Выберите качество и кодек",
        "status_prepare": "Подготовка…",
        "status_progress": "Скачивание · {value:.1f}%",
        "status_done_merged": "Готово · видео и аудио объединены",
        "status_done": "Готово",
        "status_failed": "Ошибка — откройте подробности",
        "status_cancelling": "Отмена…",
        "status_bad_link": "Не удалось прочитать ссылку",
        "error_yt_dlp": "yt-dlp не найден рядом с программой.",
        "error_ffmpeg": "FFmpeg не найден. Он нужен для объединения видео, аудио и субтитров.",
        "error_code": "yt-dlp: код {code}",
        "tool_checking": "yt-dlp: проверка обновлений…",
        "tool_updated": "yt-dlp обновлён до {version}",
        "tool_updated_unknown": "yt-dlp обновлён",
        "tool_up_to_date": "yt-dlp: установлена последняя версия ({version})",
        "tool_up_to_date_unknown": "yt-dlp: установлена последняя версия",
        "tool_update_failed": "Не удалось проверить обновление yt-dlp · нажмите, чтобы повторить",
        "log_start": "\nЗапуск загрузки:\n",
        "log_done": "Готово.\n",
    },
    "en": {
        "url_hint": "Paste a video link here",
        "mode_video": "Video",
        "mode_audio": "Audio",
        "codec": "Codec",
        "audio_format": "File format",
        "audio_original": "Original",
        "separate": "Download video and audio separately",
        "playlist": "Download the whole playlist",
        "subtitles": "Embed subtitles",
        "subtitles_unavailable": "Subtitles unavailable",
        "subtitle_auto": "auto",
        "save_to": "Save to",
        "download_video": "Download video with audio",
        "download_audio": "Download audio",
        "cancel": "Cancel",
        "details": "Details",
        "hide_details": "Hide details",
        "open_folder": "Open folder",
        "default_title": "Video",
        "kbps": "kbps",
        "size_unknown": "size unknown",
        "size_ready": "Estimated file size: {size}",
        "size_total": "Estimated size: {size} · {suffix}",
        "size_suffix_separate": "total for two files",
        "size_suffix_merge": "after merging with audio",
        "status_choose": "Pick quality and codec",
        "status_prepare": "Preparing…",
        "status_progress": "Downloading · {value:.1f}%",
        "status_done_merged": "Done · video and audio merged",
        "status_done": "Done",
        "status_failed": "Failed — open the details",
        "status_cancelling": "Cancelling…",
        "status_bad_link": "Could not read this link",
        "error_yt_dlp": "yt-dlp was not found next to the app.",
        "error_ffmpeg": "FFmpeg was not found. It is required to merge video, audio and subtitles.",
        "error_code": "yt-dlp: exit code {code}",
        "tool_checking": "yt-dlp: checking for updates…",
        "tool_updated": "yt-dlp updated to {version}",
        "tool_updated_unknown": "yt-dlp updated",
        "tool_up_to_date": "yt-dlp: up to date ({version})",
        "tool_up_to_date_unknown": "yt-dlp: up to date",
        "tool_update_failed": "Could not check yt-dlp updates · click to retry",
        "log_start": "\nStarting download:\n",
        "log_done": "Done.\n",
    },
}

URL_PLACEHOLDER = "https://www.youtube.com/watch?v=…"
AUDIO_OUTPUTS = ("mp3", "m4a", "opus", "wav", "flac")
ORIGINAL_LABELS = {texts["audio_original"] for texts in TEXTS.values()}

ctk.set_appearance_mode("System")
ctk.set_default_color_theme("blue")


def app_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def downloads_dir() -> Path:
    path = Path.home() / "Downloads"
    return path if path.exists() else Path.home()


def find_tool(name: str) -> str | None:
    executable = f"{name}.exe" if os.name == "nt" else name
    local = app_dir() / executable
    return str(local) if local.is_file() else shutil.which(name)


def local_tools_dir() -> Path:
    """Writable, persistent location for embedded tools.

    The bundled yt-dlp/ffmpeg binaries live inside a PyInstaller temp folder
    that is recreated (and can be wiped) on every launch, so yt-dlp's own
    self-update would have nothing durable to write to. A copy here survives
    between runs and can be updated in place.
    """
    base = Path(os.environ.get("LOCALAPPDATA") or Path.home())
    directory = base / "yt-dlp-gui" / "tools"
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def ensure_local_copy(name: str) -> str | None:
    """Return a persistent, writable path to an embedded tool.

    On first use, the bundled binary (from the app folder or PATH) is copied
    into `local_tools_dir()`. Later calls reuse that copy directly, which is
    what lets yt-dlp's `--update` replace its own executable across runs.
    """
    executable = f"{name}.exe" if os.name == "nt" else name
    target = local_tools_dir() / executable
    if target.is_file():
        return str(target)
    bundled = find_tool(name)
    if not bundled:
        return None
    bundled_path = Path(bundled)
    try:
        if bundled_path.resolve() == target.resolve():
            return str(target)
        shutil.copy2(bundled_path, target)
        if name == "ffmpeg":
            for dll in bundled_path.parent.glob("*.dll"):
                shutil.copy2(dll, target.parent / dll.name)
    except OSError:
        return str(bundled_path)
    return str(target)


def codec(value: object) -> str:
    raw = str(value or "?").split(".", 1)[0].lower()
    aliases = {
        "avc1": "H.264",
        "h264": "H.264",
        "av01": "AV1",
        "vp09": "VP9",
        "vp9": "VP9",
        "mp4a": "AAC",
    }
    return aliases.get(raw, raw.upper())


def duration(value: object) -> str:
    if not isinstance(value, (int, float)):
        return ""
    total = int(value)
    hours, total = divmod(total, 3600)
    minutes, seconds = divmod(total, 60)
    return f"{hours}:{minutes:02d}:{seconds:02d}" if hours else f"{minutes}:{seconds:02d}"


def format_size(item: dict[str, Any], media_duration: float) -> float:
    exact = item.get("filesize") or item.get("filesize_approx")
    if isinstance(exact, (int, float)) and exact > 0:
        return float(exact)
    bitrate = item.get("tbr") or item.get("vbr") or item.get("abr")
    if isinstance(bitrate, (int, float)) and bitrate > 0 and media_duration > 0:
        return float(bitrate) * 1000 * media_duration / 8
    return 0.0


class App(ctk.CTk):
    def __init__(self) -> None:
        super().__init__()
        # Must run before any widget is created: it sets the global scaling.
        self.ui_scaling = self._init_scaling()
        self.title(APP_NAME)
        self._apply_geometry(760, 210)
        self._apply_minsize(620, 190)
        self.resizable(True, True)
        self.configure(fg_color=WINDOW_BG)

        self.events: queue.Queue[tuple[str, object]] = queue.Queue()
        self.process: subprocess.Popen[str] | None = None
        self.analysis_timer: str | None = None
        self.analyzed_url = ""
        self.media_duration = 0.0
        self.merge_audio_size = 0.0

        # Keys are stable ids, never localized text.
        self.video_groups: dict[str, dict[str, dict[str, Any]]] = {}
        self.audio_formats: dict[str, dict[str, Any]] = {}
        self.subtitle_tracks: list[dict[str, Any]] = []
        self.subtitle_display_to_code: dict[str, str] = {}
        self.quality_buttons: list[ctk.CTkButton] = []
        self.codec_buttons: list[ctk.CTkButton] = []
        self.selected_quality = ""
        self.selected_codec = ""
        self.selected_audio = ""
        self.selected_subtitle_code = ""

        self.revealed = False
        self.log_open = False
        self.language = "ru"
        self.mode = "video"
        self.status_key: str | None = None
        self.status_args: dict[str, Any] = {}
        self.tool_status_key: str | None = None
        self.tool_status_args: dict[str, Any] = {}

        self.language_var = ctk.StringVar(value="RU")
        self.url_var = ctk.StringVar()
        self.mode_var = ctk.StringVar(value=self.tr("mode_video"))
        self.output_var = ctk.StringVar(value=str(downloads_dir()))
        self.audio_output_var = ctk.StringVar(value=self.tr("audio_original"))
        self.playlist_var = ctk.BooleanVar(value=False)
        self.separate_var = ctk.BooleanVar(value=False)
        self.subtitle_var = ctk.BooleanVar(value=False)
        self.subtitle_choice_var = ctk.StringVar(value="—")
        self.status_var = ctk.StringVar(value="")
        self.title_var = ctk.StringVar(value="")
        self.meta_var = ctk.StringVar(value="")
        self.size_var = ctk.StringVar(value="")
        self.tool_status_var = ctk.StringVar(value="")

        self._build()
        self._set_tool_status("tool_checking")
        self.after(80, self._style_title_bar)
        self.after(100, self._poll)
        self.after(300, self._start_yt_dlp_update)
        self.protocol("WM_DELETE_WINDOW", self._close)

    # ---------- scaling / native window ----------

    def _dpi_scaling(self) -> float:
        """System scaling factor: 1.0 at 100%, 1.5 at 150%, and so on."""
        try:
            return float(ctk.ScalingTracker.get_window_scaling(self))
        except Exception:
            try:
                return max(1.0, float(self.winfo_fpixels("1i")) / 96.0)
            except Exception:
                return 1.0

    def _init_scaling(self) -> float:
        """Pick a scaling factor that fits the layout and remains readable.

        Fractionally scaled Full HD screens are constrained by available height.
        A 4K screen receives a small readability boost over raw Windows DPI,
        while a 4K screen at 100% still grows the UI automatically.
        """
        dpi = max(self._dpi_scaling(), 0.5)
        screen_width = max(int(self.winfo_screenwidth()), 800)
        screen_height = max(int(self.winfo_screenheight()), 600)
        if dpi > 1.05:
            four_k_boost = min(screen_height / 1234.0, MAX_AUTO_SCALING)
            suggested = max(dpi, four_k_boost)
        else:
            suggested = min(max(screen_height / 1080.0, 1.0), MAX_AUTO_SCALING)
        fits = min(
            screen_width * 0.92 / BASE_WIDTH,
            (screen_height - CHROME_MARGIN) / BASE_HEIGHT,
        )
        total = max(min(suggested, fits), MIN_SCALING)
        # CustomTkinter already multiplies by DPI, so set only the correction.
        factor = total / dpi
        ctk.set_widget_scaling(factor)
        ctk.set_window_scaling(factor)
        return total

    def _screen_limits(self) -> tuple[int, int]:
        scaling = max(self.ui_scaling, 0.1)
        max_width = int(self.winfo_screenwidth() * 0.96 / scaling)
        max_height = int((self.winfo_screenheight() - CHROME_MARGIN) / scaling)
        return max(max_width, 480), max(max_height, 320)

    def _apply_geometry(self, width: int, height: int) -> None:
        max_width, max_height = self._screen_limits()
        self.geometry(f"{min(width, max_width)}x{min(height, max_height)}")

    def _apply_minsize(self, width: int, height: int) -> None:
        max_width, max_height = self._screen_limits()
        self.minsize(min(width, max_width), min(height, max_height))

    @staticmethod
    def _colorref(hex_color: str) -> int:
        value = hex_color.lstrip("#")
        red, green, blue = (int(value[index:index + 2], 16) for index in (0, 2, 4))
        return red | (green << 8) | (blue << 16)

    def _style_title_bar(self) -> None:
        """Blend the native Windows caption into the application surface."""
        if os.name != "nt":
            return
        try:
            self.update_idletasks()
            child = int(self.winfo_id())
            hwnd = int(ctypes.windll.user32.GetParent(child) or child)
            dark = ctk.get_appearance_mode().lower() == "dark"
            background = WINDOW_BG[1 if dark else 0]
            text = "#ffffff" if dark else "#111111"
            dwm = ctypes.windll.dwmapi

            dark_mode = ctypes.c_int(1 if dark else 0)
            dwm.DwmSetWindowAttribute(
                hwnd, 20, ctypes.byref(dark_mode), ctypes.sizeof(dark_mode)
            )
            for attribute, color in (
                (34, background),  # DWMWA_BORDER_COLOR
                (35, background),  # DWMWA_CAPTION_COLOR
                (36, text),        # DWMWA_TEXT_COLOR
            ):
                value = ctypes.c_int(self._colorref(color))
                dwm.DwmSetWindowAttribute(
                    hwnd, attribute, ctypes.byref(value), ctypes.sizeof(value)
                )
        except Exception:
            # Older Windows versions do not expose the color attributes.
            pass

    # ---------- localization ----------

    def tr(self, key: str, **kwargs: Any) -> str:
        text = TEXTS[self.language].get(key, TEXTS["en"].get(key, key))
        return text.format(**kwargs) if kwargs else text

    def _human_size(self, size: float) -> str:
        if size <= 0:
            return self.tr("size_unknown")
        units = SIZE_UNITS[self.language]
        value = size
        for unit in units:
            if value < 1024 or unit == units[-1]:
                return f"≈ {value:.1f} {unit}"
            value /= 1024
        return self.tr("size_unknown")

    def _change_language(self, choice: str) -> None:
        language = "en" if choice == "EN" else "ru"
        if language == self.language:
            return
        keep_original_audio = self._audio_output() == "original"
        self.language = language
        self._apply_language(keep_original_audio)

    def _apply_language(self, keep_original_audio: bool) -> None:
        self.url_label.configure(text=self.tr("url_hint"))
        self.mode_switch.configure(values=[self.tr("mode_video"), self.tr("mode_audio")])
        self.mode_var.set(self.tr("mode_video") if self.mode == "video" else self.tr("mode_audio"))
        self.codec_label.configure(text=self.tr("codec"))
        self.audio_format_label.configure(text=self.tr("audio_format"))
        self.audio_output.configure(values=[self.tr("audio_original"), *AUDIO_OUTPUTS])
        if keep_original_audio:
            self.audio_output_var.set(self.tr("audio_original"))
        self.separate_check.configure(text=self.tr("separate"))
        self.playlist_check.configure(text=self.tr("playlist"))
        self._render_subtitle_choices()
        self.folder_button.configure(text=self._folder_label())
        self.cancel_button.configure(text=self.tr("cancel"))
        self.open_button.configure(text=self.tr("open_folder"))
        self.log_button.configure(text=self.tr("hide_details" if self.log_open else "details"))
        self.download_button.configure(
            text=self.tr("download_video" if self.mode == "video" else "download_audio")
        )
        self._set_status(self.status_key, **self.status_args)
        if self.tool_status_key:
            self.tool_status_var.set(self.tr(self.tool_status_key, **self.tool_status_args))
        if self.revealed:
            self._render_quality_buttons()
            if self.mode == "video":
                self._render_codec_buttons()
            else:
                self._update_size_summary()

    def _set_status(self, key: str | None, **kwargs: Any) -> None:
        self.status_key = key
        self.status_args = kwargs
        self.status_var.set(self.tr(key, **kwargs) if key else "")

    def _set_tool_status(self, key: str, **kwargs: Any) -> None:
        self.tool_status_key = key
        self.tool_status_args = kwargs
        self.tool_status_var.set(self.tr(key, **kwargs))

    def _audio_output(self) -> str:
        value = self.audio_output_var.get()
        return "original" if value in ORIGINAL_LABELS else value

    # ---------- layout ----------

    def _build(self) -> None:
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        search = ctk.CTkFrame(self, fg_color="transparent")
        search.grid(row=0, column=0, sticky="ew", padx=34, pady=30)
        search.grid_columnconfigure(0, weight=1)
        self.url_label = ctk.CTkLabel(
            search,
            text=self.tr("url_hint"),
            anchor="w",
            font=ctk.CTkFont(size=17, weight="bold"),
        )
        self.url_label.grid(row=0, column=0, sticky="ew", pady=(0, 9))
        self.language_switch = ctk.CTkSegmentedButton(
            search,
            values=["RU", "EN"],
            variable=self.language_var,
            command=self._change_language,
            width=80,
            height=28,
            corner_radius=8,
            font=ctk.CTkFont(size=12),
        )
        self.language_switch.grid(row=0, column=1, sticky="e", pady=(0, 9))
        self.url_entry = ctk.CTkEntry(
            search,
            textvariable=self.url_var,
            height=54,
            corner_radius=14,
            border_width=2,
            border_color=CONTROL_BORDER,
            fg_color=CONTROL_BG,
            placeholder_text=URL_PLACEHOLDER,
            font=ctk.CTkFont(size=15),
        )
        self.url_entry.grid(row=1, column=0, columnspan=2, sticky="ew")
        self.url_entry.bind("<KeyRelease>", self._url_changed)
        self.url_entry.bind("<<Paste>>", lambda _event: self.after(50, self._url_changed))
        self.url_entry.bind("<Control-KeyPress>", self._layout_agnostic_paste, add="+")
        self.url_entry.bind("<Return>", lambda _event: self._analyze_now())
        self.url_entry.focus_set()
        self.loading = ctk.CTkProgressBar(search, height=3, mode="indeterminate")

        # A scrollable frame keeps every option reachable (via the scrollbar or
        # the mouse wheel) once the window is resized smaller than the content.
        self.content = ctk.CTkScrollableFrame(self, fg_color="transparent")
        self.content.grid_columnconfigure(0, weight=1)

        info = ctk.CTkFrame(self.content, fg_color="transparent")
        info.grid(row=0, column=0, sticky="ew", padx=34)
        info.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            info,
            textvariable=self.title_var,
            anchor="w",
            justify="left",
            font=ctk.CTkFont(size=21, weight="bold"),
            wraplength=750,
        ).grid(row=0, column=0, sticky="ew")
        ctk.CTkLabel(
            info,
            textvariable=self.meta_var,
            anchor="w",
            text_color=("#686868", "#b0b0b0"),
            font=ctk.CTkFont(size=13),
        ).grid(row=1, column=0, sticky="ew", pady=(4, 0))

        self.mode_switch = ctk.CTkSegmentedButton(
            self.content,
            values=[self.tr("mode_video"), self.tr("mode_audio")],
            variable=self.mode_var,
            command=self._mode_changed,
            height=38,
            corner_radius=10,
        )
        self.mode_switch.grid(row=1, column=0, sticky="ew", padx=34, pady=(20, 0))

        self.quality_frame = ctk.CTkFrame(self.content, fg_color="transparent")
        self.quality_frame.grid(row=2, column=0, sticky="ew", padx=30, pady=(14, 0))
        for column in range(4):
            self.quality_frame.grid_columnconfigure(column, weight=1, uniform="quality")

        self.codec_section = ctk.CTkFrame(self.content, fg_color="transparent")
        self.codec_section.grid_columnconfigure(0, weight=1)
        self.codec_label = ctk.CTkLabel(
            self.codec_section,
            text=self.tr("codec"),
            anchor="w",
            text_color=("#686868", "#b0b0b0"),
        )
        self.codec_label.grid(row=0, column=0, sticky="w", pady=(0, 6))
        self.codec_frame = ctk.CTkFrame(self.codec_section, fg_color="transparent")
        self.codec_frame.grid(row=1, column=0, sticky="ew")
        for column in range(4):
            self.codec_frame.grid_columnconfigure(column, weight=1, uniform="codec")
        ctk.CTkLabel(
            self.codec_section,
            textvariable=self.size_var,
            anchor="w",
            text_color=("#686868", "#b0b0b0"),
            font=ctk.CTkFont(size=12),
        ).grid(row=2, column=0, sticky="ew", pady=(7, 0))

        self.audio_options = ctk.CTkFrame(self.content, fg_color="transparent")
        self.audio_options.grid_columnconfigure(0, weight=1)
        self.audio_format_label = ctk.CTkLabel(
            self.audio_options,
            text=self.tr("audio_format"),
            anchor="w",
            text_color=("#686868", "#b0b0b0"),
        )
        self.audio_format_label.grid(row=0, column=0, sticky="w", pady=(0, 6))
        self.audio_output = ctk.CTkOptionMenu(
            self.audio_options,
            values=[self.tr("audio_original"), *AUDIO_OUTPUTS],
            variable=self.audio_output_var,
            height=36,
        )
        self.audio_output.grid(row=1, column=0, sticky="ew")

        options = ctk.CTkFrame(self.content, fg_color="transparent")
        options.grid(row=4, column=0, sticky="ew", padx=34, pady=(18, 0))
        options.grid_columnconfigure(0, weight=1)
        options.grid_columnconfigure(1, weight=1)
        self.separate_check = ctk.CTkCheckBox(
            options,
            text=self.tr("separate"),
            variable=self.separate_var,
            checkbox_width=21,
            checkbox_height=21,
            border_width=2,
            border_color=CONTROL_BORDER,
            command=self._separate_toggled,
        )
        self.separate_check.grid(row=0, column=0, sticky="w")
        self.playlist_check = ctk.CTkCheckBox(
            options,
            text=self.tr("playlist"),
            variable=self.playlist_var,
            checkbox_width=21,
            checkbox_height=21,
            border_width=2,
            border_color=CONTROL_BORDER,
        )
        self.playlist_check.grid(row=0, column=1, sticky="e")
        self.subtitle_check = ctk.CTkCheckBox(
            options,
            text=self.tr("subtitles_unavailable"),
            variable=self.subtitle_var,
            checkbox_width=21,
            checkbox_height=21,
            border_width=2,
            border_color=CONTROL_BORDER,
            state="disabled",
            command=self._subtitle_toggled,
        )
        self.subtitle_check.grid(row=1, column=0, sticky="w", pady=(14, 0))
        self.subtitle_menu = ctk.CTkOptionMenu(
            options,
            values=["—"],
            variable=self.subtitle_choice_var,
            command=self._subtitle_selected,
            width=260,
            height=34,
            dynamic_resizing=False,
            state="disabled",
        )
        self.subtitle_menu.grid(row=1, column=1, sticky="e", pady=(14, 0))

        destination = ctk.CTkFrame(self.content, fg_color="transparent")
        destination.grid(row=5, column=0, sticky="ew", padx=34, pady=(15, 0))
        destination.grid_columnconfigure(0, weight=1)
        self.folder_button = ctk.CTkButton(
            destination,
            text=self._folder_label(),
            anchor="w",
            height=38,
            fg_color="transparent",
            border_width=2,
            border_color=CONTROL_BORDER,
            text_color=("#4b4b4b", "#d0d0d0"),
            command=self._choose_folder,
        )
        self.folder_button.grid(row=0, column=0, sticky="ew")

        actions = ctk.CTkFrame(self.content, fg_color="transparent")
        actions.grid(row=6, column=0, sticky="ew", padx=34, pady=(18, 0))
        actions.grid_columnconfigure(0, weight=1)
        self.download_button = ctk.CTkButton(
            actions,
            text=self.tr("download_video"),
            height=48,
            corner_radius=12,
            font=ctk.CTkFont(size=15, weight="bold"),
            command=self._download,
        )
        self.download_button.grid(row=0, column=0, sticky="ew")
        self.cancel_button = ctk.CTkButton(
            actions,
            text=self.tr("cancel"),
            height=48,
            corner_radius=12,
            fg_color="transparent",
            border_width=2,
            border_color=CONTROL_BORDER,
            text_color=("#4b4b4b", "#d0d0d0"),
            command=self._cancel,
        )
        self.status = ctk.CTkLabel(
            actions,
            textvariable=self.status_var,
            anchor="w",
            text_color=("#686868", "#b0b0b0"),
        )
        self.status.grid(row=1, column=0, sticky="ew", pady=(7, 0))
        self.progress = ctk.CTkProgressBar(actions, height=7)
        self.progress.set(0)

        footer = ctk.CTkFrame(self.content, fg_color="transparent")
        footer.grid(row=7, column=0, sticky="ew", padx=34, pady=(8, 20))
        footer.grid_columnconfigure(1, weight=1)
        self.log_button = ctk.CTkButton(
            footer,
            text=self.tr("details"),
            width=100,
            height=28,
            fg_color="transparent",
            text_color=("#5b5b5b", "#b8b8b8"),
            hover_color=("#e9e9e6", "#252525"),
            command=self._toggle_log,
        )
        self.log_button.grid(row=0, column=0, sticky="w")
        self.open_button = ctk.CTkButton(
            footer,
            text=self.tr("open_folder"),
            width=110,
            height=28,
            fg_color="transparent",
            text_color=("#5b5b5b", "#b8b8b8"),
            hover_color=("#e9e9e6", "#252525"),
            command=self._open_folder,
        )
        self.tool_status_label = ctk.CTkLabel(
            footer,
            textvariable=self.tool_status_var,
            anchor="w",
            text_color=("#8f8f89", "#8c8c8c"),
            font=ctk.CTkFont(size=11),
            cursor="hand2",
        )
        self.tool_status_label.grid(row=1, column=0, columnspan=3, sticky="ew", pady=(6, 0))
        self.tool_status_label.bind("<Button-1>", lambda _event: self._start_yt_dlp_update())
        self.log = ctk.CTkTextbox(
            self.content,
            height=170,
            corner_radius=10,
            border_width=2,
            border_color=CONTROL_BORDER,
            wrap="word",
            font=ctk.CTkFont(family="Consolas", size=11),
        )
        self.log.configure(state="disabled")

    # ---------- paste / url ----------

    def _layout_agnostic_paste(self, event: Any) -> str | None:
        """Paste on Ctrl+V even when the active keyboard layout is not Latin."""
        keysym = str(getattr(event, "keysym", "")).lower()
        if keysym in {"v", "insert"}:
            return None
        keycode = int(getattr(event, "keycode", -1) or -1)
        if keysym not in PASTE_KEYSYMS and keycode not in PASTE_KEYCODES:
            return None
        self._paste_clipboard()
        return "break"

    def _paste_clipboard(self) -> None:
        try:
            clipboard = str(self.clipboard_get())
        except TclError:
            return
        text = clipboard.strip()
        if not text:
            return
        try:
            self.url_entry.delete("sel.first", "sel.last")
        except TclError:
            pass
        self.url_entry.insert("insert", text)
        self._url_changed()

    def _url_changed(self, _event: object = None) -> None:
        if self.analysis_timer:
            self.after_cancel(self.analysis_timer)
        url = self.url_var.get().strip()
        if url.startswith(("http://", "https://")):
            self.analysis_timer = self.after(700, self._analyze_now)

    def _analyze_now(self) -> None:
        self.analysis_timer = None
        url = self.url_var.get().strip()
        if not url.startswith(("http://", "https://")) or self.process:
            return
        executable = ensure_local_copy("yt-dlp")
        if not executable:
            messagebox.showerror(APP_NAME, self.tr("error_yt_dlp"))
            return
        self._hide_content()
        self.loading.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(7, 0))
        self.loading.start()
        self.process = subprocess.Popen(
            [executable, "--dump-single-json", "--no-playlist", "--no-warnings", url],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        threading.Thread(target=self._collect_analysis, args=(url,), daemon=True).start()

    def _collect_analysis(self, url: str) -> None:
        assert self.process is not None
        stdout, stderr = self.process.communicate()
        code = self.process.returncode
        self.process = None
        if code == 0:
            try:
                self.events.put(("analysis", (url, json.loads(stdout))))
            except json.JSONDecodeError as error:
                self.events.put(("error", str(error)))
        else:
            self.events.put(("error", stderr.strip() or self.tr("error_code", code=code)))

    def _apply_analysis(self, url: str, data: dict[str, Any]) -> None:
        if url != self.url_var.get().strip():
            return
        self.analyzed_url = url
        self.media_duration = float(data.get("duration") or 0)
        self.title_var.set(str(data.get("title") or self.tr("default_title")))
        author = str(data.get("channel") or data.get("uploader") or "")
        length = duration(data.get("duration"))
        self.meta_var.set("  ·  ".join(value for value in (author, length) if value))
        self._prepare_subtitles(data)
        self._prepare_formats(data.get("formats") or [])
        self._reveal_content()
        self._refresh_mode_views()
        self._set_status("status_choose")

    # ---------- subtitles ----------

    def _prepare_subtitles(self, data: dict[str, Any]) -> None:
        previous = self.selected_subtitle_code
        tracks: list[dict[str, Any]] = []
        manual = data.get("subtitles") or {}
        automatic = data.get("automatic_captions") or {}
        manual_codes = {
            str(code) for code, variants in manual.items() if isinstance(variants, list) and variants
        }

        def add(source: object, is_automatic: bool) -> None:
            if not isinstance(source, dict):
                return
            for raw_code, variants in source.items():
                code = str(raw_code)
                if is_automatic and code in manual_codes:
                    continue
                if not isinstance(variants, list) or not variants:
                    continue
                first = next((item for item in variants if isinstance(item, dict)), {})
                name = str(first.get("name") or code)
                tracks.append({"code": code, "name": name, "automatic": is_automatic})

        add(manual, False)
        add(automatic, True)

        def priority(track: dict[str, Any]) -> tuple[int, int, str]:
            code = str(track["code"]).lower()
            preferred = (self.language, "en", "ru")
            language_rank = len(preferred) + 1
            for index, language in enumerate(preferred):
                if code == language or code.startswith(f"{language}-"):
                    language_rank = index
                    break
            return (1 if track["automatic"] else 0, language_rank, code)

        self.subtitle_tracks = sorted(tracks, key=priority)
        available_codes = {str(track["code"]) for track in self.subtitle_tracks}
        self.selected_subtitle_code = previous if previous in available_codes else ""
        if not self.selected_subtitle_code and self.subtitle_tracks:
            self.selected_subtitle_code = str(self.subtitle_tracks[0]["code"])
        if not self.subtitle_tracks:
            self.subtitle_var.set(False)
        self._render_subtitle_choices()

    def _subtitle_label(self, track: dict[str, Any]) -> str:
        code = str(track["code"])
        name = str(track.get("name") or code).strip()
        label = code if name.lower() == code.lower() else f"{name} · {code}"
        if track.get("automatic"):
            label += f" · {self.tr('subtitle_auto')}"
        return label

    def _render_subtitle_choices(self) -> None:
        self.subtitle_display_to_code.clear()
        labels: list[str] = []
        selected_label = "—"
        for track in self.subtitle_tracks:
            label = self._subtitle_label(track)
            if label in self.subtitle_display_to_code:
                label = f"{label} ({len(labels) + 1})"
            code = str(track["code"])
            self.subtitle_display_to_code[label] = code
            labels.append(label)
            if code == self.selected_subtitle_code:
                selected_label = label

        available = bool(labels)
        self.subtitle_menu.configure(values=labels or ["—"])
        self.subtitle_choice_var.set(selected_label if available else "—")
        self.subtitle_check.configure(
            text=self.tr("subtitles" if available else "subtitles_unavailable"),
            state="normal" if available else "disabled",
        )
        if not available:
            self.subtitle_var.set(False)
        self._sync_subtitle_controls()

    def _sync_subtitle_controls(self) -> None:
        enabled = bool(self.subtitle_tracks) and self.mode == "video"
        self.subtitle_check.configure(state="normal" if enabled else "disabled")
        menu_enabled = enabled and self.subtitle_var.get()
        self.subtitle_menu.configure(state="normal" if menu_enabled else "disabled")

    def _subtitle_selected(self, label: str) -> None:
        code = self.subtitle_display_to_code.get(label)
        if code:
            self.selected_subtitle_code = code

    def _subtitle_toggled(self) -> None:
        if self.subtitle_var.get():
            # Separate video/audio output has no single final container in which
            # subtitles can be embedded, so the options are mutually exclusive.
            self.separate_var.set(False)
        self._sync_subtitle_controls()
        self._update_size_summary()

    def _separate_toggled(self) -> None:
        if self.separate_var.get():
            self.subtitle_var.set(False)
        self._sync_subtitle_controls()
        self._update_size_summary()

    # ---------- formats ----------

    def _prepare_formats(self, formats: list[dict[str, Any]]) -> None:
        video_candidates: list[dict[str, Any]] = []
        audio_candidates: list[dict[str, Any]] = []
        for item in formats:
            if not item.get("format_id"):
                continue
            vcodec = str(item.get("vcodec") or "none")
            acodec = str(item.get("acodec") or "none")
            if vcodec != "none" and item.get("height"):
                video_candidates.append(item)
            elif vcodec == "none" and acodec != "none":
                audio_candidates.append(item)

        preferred_audio = [
            item for item in audio_candidates if str(item.get("ext") or "").lower() == "m4a"
        ]
        merge_audio = max(
            preferred_audio or audio_candidates,
            key=lambda item: float(item.get("abr") or item.get("tbr") or 0),
            default={},
        )
        self.merge_audio_size = format_size(merge_audio, self.media_duration)

        grouped: dict[tuple[int, int], dict[str, dict[str, Any]]] = {}
        for item in video_candidates:
            height = int(item.get("height") or 0)
            fps = int(item.get("fps") or 0)
            quality_key = (height, fps)
            codec_key = f"{codec(item.get('vcodec'))} · {str(item.get('ext') or '?').upper()}"
            previous = grouped.setdefault(quality_key, {}).get(codec_key)
            score = (
                str(item.get("acodec") or "none") == "none",
                float(item.get("tbr") or 0),
            )
            previous_score = (-1, -1.0) if previous is None else (
                str(previous.get("acodec") or "none") == "none",
                float(previous.get("tbr") or 0),
            )
            if score > previous_score:
                grouped[quality_key][codec_key] = item

        self.video_groups.clear()
        for (height, fps), codecs in sorted(grouped.items(), reverse=True)[:8]:
            quality_id = f"{height}p\n{fps} FPS" if fps else f"{height}p"
            self.video_groups[quality_id] = dict(codecs)

        audios = sorted(
            audio_candidates,
            key=lambda item: (
                float(item.get("abr") or item.get("tbr") or 0),
                float(item.get("filesize") or 0),
            ),
            reverse=True,
        )[:8]
        self.audio_formats.clear()
        seen: set[tuple[int, str, str]] = set()
        for item in audios:
            abr = int(float(item.get("abr") or item.get("tbr") or 0))
            signature = (
                abr,
                codec(item.get("acodec")),
                str(item.get("ext") or "").upper(),
            )
            if signature in seen:
                continue
            seen.add(signature)
            self.audio_formats[str(item.get("format_id"))] = item

        self.selected_quality = next(iter(self.video_groups), "")
        codecs_for_quality = self.video_groups.get(self.selected_quality, {})
        self.selected_codec = next(iter(codecs_for_quality), "")
        self.selected_audio = next(iter(self.audio_formats), "")
        self._update_size_summary()

    def _codec_label(self, codec_id: str, item: dict[str, Any]) -> str:
        video_size = format_size(item, self.media_duration)
        has_audio = str(item.get("acodec") or "none") != "none"
        total = video_size if has_audio else video_size + self.merge_audio_size
        return f"{codec_id}\n{self._human_size(total)}"

    def _audio_label(self, item: dict[str, Any]) -> str:
        abr = int(float(item.get("abr") or item.get("tbr") or 0))
        size = self._human_size(format_size(item, self.media_duration))
        extension = str(item.get("ext") or "").upper()
        return (
            f"{abr or '?'} {self.tr('kbps')}\n"
            f"{codec(item.get('acodec'))} · {extension} · {size}"
        )

    def _render_quality_buttons(self) -> None:
        for button in self.quality_buttons:
            button.destroy()
        self.quality_buttons.clear()
        if self.mode == "video":
            entries = [(quality_id, quality_id) for quality_id in self.video_groups]
            selected = self.selected_quality
        else:
            entries = [
                (format_id, self._audio_label(item))
                for format_id, item in self.audio_formats.items()
            ]
            selected = self.selected_audio
        for index, (key, label) in enumerate(entries):
            button = self._choice_button(
                self.quality_frame,
                label,
                key == selected,
                lambda value=key: self._select_quality(value),
                height=58,
            )
            button.grid(row=index // 4, column=index % 4, sticky="ew", padx=4, pady=4)
            self.quality_buttons.append(button)

    def _render_codec_buttons(self) -> None:
        for button in self.codec_buttons:
            button.destroy()
        self.codec_buttons.clear()
        source = self.video_groups.get(self.selected_quality, {})
        if self.selected_codec not in source:
            self.selected_codec = next(iter(source), "")
        for index, (codec_id, item) in enumerate(source.items()):
            button = self._choice_button(
                self.codec_frame,
                self._codec_label(codec_id, item),
                codec_id == self.selected_codec,
                lambda value=codec_id: self._select_codec(value),
                height=54,
            )
            button.grid(row=index // 4, column=index % 4, sticky="ew", padx=4, pady=4)
            self.codec_buttons.append(button)
        self._update_size_summary()

    def _choice_button(
        self,
        parent: ctk.CTkFrame,
        text: str,
        active: bool,
        command: Any,
        height: int,
    ) -> ctk.CTkButton:
        return ctk.CTkButton(
            parent,
            text=text,
            height=height,
            corner_radius=10,
            fg_color=("#2783de", "#3b8ed0") if active else CONTROL_BG,
            text_color="#ffffff" if active else ("#2d2d2d", "#eeeeee"),
            border_width=0 if active else 2,
            border_color=CONTROL_BORDER,
            hover_color=("#1f75c5", "#367baa") if active else ("#e8e8e5", "#303030"),
            command=command,
        )

    def _select_quality(self, key: str) -> None:
        if self.mode == "video":
            self.selected_quality = key
            self.selected_codec = next(iter(self.video_groups.get(key, {})), "")
            self._render_quality_buttons()
            self._render_codec_buttons()
        else:
            self.selected_audio = key
            self._render_quality_buttons()

    def _select_codec(self, key: str) -> None:
        self.selected_codec = key
        self._render_codec_buttons()

    def _selected_video_format(self) -> dict[str, Any]:
        return self.video_groups.get(self.selected_quality, {}).get(self.selected_codec, {})

    def _update_size_summary(self) -> None:
        item = self._selected_video_format()
        video_size = format_size(item, self.media_duration)
        has_audio = str(item.get("acodec") or "none") != "none"
        if has_audio:
            self.size_var.set(self.tr("size_ready", size=self._human_size(video_size)))
            return
        total = video_size + self.merge_audio_size
        suffix = self.tr(
            "size_suffix_separate" if self.separate_var.get() else "size_suffix_merge"
        )
        self.size_var.set(self.tr("size_total", size=self._human_size(total), suffix=suffix))

    # ---------- modes ----------

    def _mode_changed(self, value: str) -> None:
        self.mode = "audio" if value == self.tr("mode_audio") else "video"
        self._refresh_mode_views()

    def _refresh_mode_views(self) -> None:
        if not self.revealed:
            return
        if self.mode == "video":
            self.audio_options.grid_remove()
            self.codec_section.grid(row=3, column=0, sticky="ew", padx=34, pady=(13, 0))
            self.separate_check.grid()
            self.subtitle_check.grid()
            self.subtitle_menu.grid()
            self.download_button.configure(text=self.tr("download_video"))
        else:
            self.codec_section.grid_remove()
            self.separate_check.grid_remove()
            self.subtitle_check.grid_remove()
            self.subtitle_menu.grid_remove()
            self.audio_options.grid(row=3, column=0, sticky="ew", padx=34, pady=(13, 0))
            self.download_button.configure(text=self.tr("download_audio"))
        self._sync_subtitle_controls()
        self._render_quality_buttons()
        if self.mode == "video":
            self._render_codec_buttons()

    def _reveal_content(self) -> None:
        self.loading.stop()
        self.loading.grid_remove()
        self.content.grid(row=1, column=0, sticky="nsew")
        self.revealed = True
        self._apply_geometry(840, 870)
        # Content now scrolls, so the window can shrink well below its natural
        # height/width without hiding any option from the user.
        self._apply_minsize(620, 400)

    def _hide_content(self) -> None:
        self.content.grid_remove()
        self.revealed = False
        self._apply_minsize(620, 190)
        self._apply_geometry(760, 210)

    # ---------- download ----------

    def _download(self) -> None:
        if self.process or self.analyzed_url != self.url_var.get().strip():
            return
        executable = ensure_local_copy("yt-dlp")
        if not executable:
            messagebox.showerror(APP_NAME, self.tr("error_yt_dlp"))
            return
        separate = self.separate_var.get() and self.mode == "video"
        subtitles = (
            self.mode == "video"
            and self.subtitle_var.get()
            and bool(self.selected_subtitle_code)
        )
        if self.mode == "video" and (not separate or subtitles) and not ensure_local_copy("ffmpeg"):
            messagebox.showerror(APP_NAME, self.tr("error_ffmpeg"))
            return
        folder = Path(self.output_var.get()).expanduser()
        folder.mkdir(parents=True, exist_ok=True)
        command = self._download_command(executable, folder)
        self._set_status("status_prepare")
        self.progress.set(0)
        self.progress.grid(row=2, column=0, sticky="ew", pady=(10, 0))
        self.download_button.grid_remove()
        self.cancel_button.grid(row=0, column=0, sticky="ew")
        self._log(self.tr("log_start") + subprocess.list2cmdline(command) + "\n\n")
        self.process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        threading.Thread(target=self._collect_download, daemon=True).start()

    def _download_command(self, executable: str, folder: Path) -> list[str]:
        separate = self.separate_var.get() and self.mode == "video"
        template = "%(title)s [%(format_id)s].%(ext)s" if separate else "%(title)s [%(id)s].%(ext)s"
        ffmpeg = ensure_local_copy("ffmpeg")
        ffmpeg_location = str(Path(ffmpeg).parent) if ffmpeg else str(app_dir())
        command = [
            executable,
            self.analyzed_url,
            "--newline",
            "--progress",
            "--windows-filenames",
            "--ffmpeg-location",
            ffmpeg_location,
            "--output",
            str(folder / template),
            "--yes-playlist" if self.playlist_var.get() else "--no-playlist",
        ]
        if self.mode == "video":
            item = self._selected_video_format()
            video_id = str(item.get("format_id") or "bestvideo")
            has_audio = str(item.get("acodec") or "none") != "none"
            if separate:
                selector = f"{video_id},bestaudio"
            elif has_audio:
                selector = video_id
            else:
                selector = f"{video_id}+bestaudio[ext=m4a]/{video_id}+bestaudio/{video_id}+best"
            command.extend(["--format", selector])
            if not separate:
                command.extend(["--merge-output-format", "mp4", "--remux-video", "mp4"])
            if self.subtitle_var.get() and self.selected_subtitle_code:
                command.extend([
                    "--write-subs",
                    "--sub-langs",
                    self.selected_subtitle_code,
                    "--sub-format",
                    "vtt/best",
                    "--convert-subs",
                    "srt",
                    "--embed-subs",
                ])
        else:
            item = self.audio_formats.get(self.selected_audio, {})
            command.extend(["--format", str(item.get("format_id") or "bestaudio/best")])
            output = self._audio_output()
            if output != "original":
                command.extend(["--extract-audio", "--audio-format", output, "--audio-quality", "0"])
        return command

    def _collect_download(self) -> None:
        assert self.process is not None and self.process.stdout is not None
        for line in self.process.stdout:
            self.events.put(("line", line))
            match = PROGRESS_RE.search(line)
            if match:
                self.events.put(("progress", float(match.group(1))))
        code = self.process.wait()
        self.process = None
        self.events.put(("finished", code))

    # ---------- yt-dlp self-update ----------

    def _start_yt_dlp_update(self) -> None:
        """Refresh the persistent yt-dlp copy so it stays current between runs.

        yt-dlp ships new releases far more often than this wrapper does, so
        relying only on the bundled binary would leave users stuck on
        whatever version was current when they downloaded the app.
        """
        self._set_tool_status("tool_checking")
        threading.Thread(target=self._run_yt_dlp_update, daemon=True).start()

    def _run_yt_dlp_update(self) -> None:
        executable = ensure_local_copy("yt-dlp")
        if not executable:
            self.events.put(("tool_update", ("error", "")))
            return
        creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        try:
            result = subprocess.run(
                [executable, "--update"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=90,
                creationflags=creationflags,
            )
        except Exception:
            self.events.put(("tool_update", ("error", "")))
            return
        output = f"{result.stdout or ''}\n{result.stderr or ''}".lower()
        version = ""
        try:
            version_result = subprocess.run(
                [executable, "--version"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=20,
                creationflags=creationflags,
            )
            if version_result.stdout:
                version = version_result.stdout.strip().splitlines()[0]
        except Exception:
            version = ""
        if result.returncode != 0:
            self.events.put(("tool_update", ("error", version)))
        elif "updated yt-dlp" in output or "has been updated" in output:
            self.events.put(("tool_update", ("updated", version)))
        else:
            self.events.put(("tool_update", ("current", version)))

    def _poll(self) -> None:
        try:
            while True:
                event, payload = self.events.get_nowait()
                if event == "analysis":
                    url, data = payload
                    self._apply_analysis(str(url), data)
                elif event == "error":
                    self.loading.stop()
                    self.loading.grid_remove()
                    self._set_status("status_bad_link")
                    messagebox.showerror(APP_NAME, str(payload))
                elif event == "line":
                    self._log(str(payload))
                elif event == "progress":
                    value = float(payload)
                    self.progress.set(value / 100)
                    self._set_status("status_progress", value=value)
                elif event == "tool_update":
                    status, version = payload
                    if status == "error":
                        self._set_tool_status("tool_update_failed")
                    elif status == "updated":
                        if version:
                            self._set_tool_status("tool_updated", version=version)
                        else:
                            self._set_tool_status("tool_updated_unknown")
                    else:
                        if version:
                            self._set_tool_status("tool_up_to_date", version=version)
                        else:
                            self._set_tool_status("tool_up_to_date_unknown")
                elif event == "finished":
                    self.cancel_button.grid_remove()
                    self.download_button.grid()
                    if int(payload) == 0:
                        self.progress.set(1)
                        merged = self.mode == "video" and not self.separate_var.get()
                        self._set_status("status_done_merged" if merged else "status_done")
                        self.open_button.grid(row=0, column=2, sticky="e")
                        self._log(self.tr("log_done"))
                    else:
                        self._set_status("status_failed")
        except queue.Empty:
            pass
        self.after(100, self._poll)

    # ---------- misc ----------

    def _choose_folder(self) -> None:
        selected = filedialog.askdirectory(initialdir=self.output_var.get())
        if selected:
            self.output_var.set(selected)
            self.folder_button.configure(text=self._folder_label())

    def _folder_label(self) -> str:
        return f"{self.tr('save_to')}  ·  {self.output_var.get()}"

    def _toggle_log(self) -> None:
        self.log_open = not self.log_open
        if self.log_open:
            self.log.grid(row=8, column=0, sticky="nsew", padx=34, pady=(0, 24))
            self.content.grid_rowconfigure(8, weight=1)
            self._apply_geometry(840, 1020)
            self.log_button.configure(text=self.tr("hide_details"))
        else:
            self.log.grid_remove()
            self.content.grid_rowconfigure(8, weight=0)
            self._apply_geometry(840, 870)
            self.log_button.configure(text=self.tr("details"))

    def _log(self, text: str) -> None:
        self.log.configure(state="normal")
        self.log.insert("end", text)
        self.log.see("end")
        self.log.configure(state="disabled")

    def _cancel(self) -> None:
        if self.process and self.process.poll() is None:
            self.process.terminate()
            self._set_status("status_cancelling")

    def _open_folder(self) -> None:
        folder = Path(self.output_var.get())
        if os.name == "nt":
            os.startfile(folder)  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(folder)])
        else:
            subprocess.Popen(["xdg-open", str(folder)])

    def _close(self) -> None:
        if self.process and self.process.poll() is None:
            self.process.terminate()
        self.destroy()


if __name__ == "__main__":
    App().mainloop()
