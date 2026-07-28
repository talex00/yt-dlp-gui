from __future__ import annotations

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

SIZE_UNITS = {
    "ru": ("\u0411", "\u041a\u0411", "\u041c\u0411", "\u0413\u0411"),
    "en": ("B", "KB", "MB", "GB"),
}

TEXTS: dict[str, dict[str, str]] = {
    "ru": {
        "url_hint": "\u0412\u0441\u0442\u0430\u0432\u044c\u0442\u0435 \u0441\u044e\u0434\u0430 \u0441\u0441\u044b\u043b\u043a\u0443 \u043d\u0430 \u0432\u0438\u0434\u0435\u043e",
        "mode_video": "\u0412\u0438\u0434\u0435\u043e",
        "mode_audio": "\u0410\u0443\u0434\u0438\u043e",
        "codec": "\u041a\u043e\u0434\u0435\u043a",
        "audio_format": "\u0424\u043e\u0440\u043c\u0430\u0442 \u0444\u0430\u0439\u043b\u0430",
        "audio_original": "\u041e\u0440\u0438\u0433\u0438\u043d\u0430\u043b",
        "separate": "\u0421\u043a\u0430\u0447\u0430\u0442\u044c \u0432\u0438\u0434\u0435\u043e \u0438 \u0430\u0443\u0434\u0438\u043e \u043e\u0442\u0434\u0435\u043b\u044c\u043d\u043e",
        "playlist": "\u0421\u043a\u0430\u0447\u0430\u0442\u044c \u0432\u0435\u0441\u044c \u043f\u043b\u0435\u0439\u043b\u0438\u0441\u0442",
        "save_to": "\u0421\u043e\u0445\u0440\u0430\u043d\u0438\u0442\u044c \u0432",
        "download_video": "\u0421\u043a\u0430\u0447\u0430\u0442\u044c \u0432\u0438\u0434\u0435\u043e \u0441 \u0430\u0443\u0434\u0438\u043e",
        "download_audio": "\u0421\u043a\u0430\u0447\u0430\u0442\u044c \u0430\u0443\u0434\u0438\u043e",
        "cancel": "\u041e\u0442\u043c\u0435\u043d\u0430",
        "details": "\u041f\u043e\u0434\u0440\u043e\u0431\u043d\u043e\u0441\u0442\u0438",
        "hide_details": "\u0421\u043a\u0440\u044b\u0442\u044c \u043f\u043e\u0434\u0440\u043e\u0431\u043d\u043e\u0441\u0442\u0438",
        "open_folder": "\u041e\u0442\u043a\u0440\u044b\u0442\u044c \u043f\u0430\u043f\u043a\u0443",
        "default_title": "\u0412\u0438\u0434\u0435\u043e",
        "kbps": "\u043a\u0431\u0438\u0442/\u0441",
        "size_unknown": "\u0440\u0430\u0437\u043c\u0435\u0440 \u043d\u0435\u0438\u0437\u0432\u0435\u0441\u0442\u0435\u043d",
        "size_ready": "\u041f\u0440\u0438\u043c\u0435\u0440\u043d\u044b\u0439 \u0440\u0430\u0437\u043c\u0435\u0440 \u0433\u043e\u0442\u043e\u0432\u043e\u0433\u043e \u0444\u0430\u0439\u043b\u0430: {size}",
        "size_total": "\u041f\u0440\u0438\u043c\u0435\u0440\u043d\u044b\u0439 \u0440\u0430\u0437\u043c\u0435\u0440: {size} \u00b7 {suffix}",
        "size_suffix_separate": "\u0441\u0443\u043c\u043c\u0430\u0440\u043d\u043e \u0434\u043b\u044f \u0434\u0432\u0443\u0445 \u0444\u0430\u0439\u043b\u043e\u0432",
        "size_suffix_merge": "\u043f\u043e\u0441\u043b\u0435 \u043e\u0431\u044a\u0435\u0434\u0438\u043d\u0435\u043d\u0438\u044f \u0441 \u0430\u0443\u0434\u0438\u043e",
        "status_choose": "\u0412\u044b\u0431\u0435\u0440\u0438\u0442\u0435 \u043a\u0430\u0447\u0435\u0441\u0442\u0432\u043e \u0438 \u043a\u043e\u0434\u0435\u043a",
        "status_prepare": "\u041f\u043e\u0434\u0433\u043e\u0442\u043e\u0432\u043a\u0430\u2026",
        "status_progress": "\u0421\u043a\u0430\u0447\u0438\u0432\u0430\u043d\u0438\u0435 \u00b7 {value:.1f}%",
        "status_done_merged": "\u0413\u043e\u0442\u043e\u0432\u043e \u00b7 \u0432\u0438\u0434\u0435\u043e \u0438 \u0430\u0443\u0434\u0438\u043e \u043e\u0431\u044a\u0435\u0434\u0438\u043d\u0435\u043d\u044b",
        "status_done": "\u0413\u043e\u0442\u043e\u0432\u043e",
        "status_failed": "\u041e\u0448\u0438\u0431\u043a\u0430 \u2014 \u043e\u0442\u043a\u0440\u043e\u0439\u0442\u0435 \u043f\u043e\u0434\u0440\u043e\u0431\u043d\u043e\u0441\u0442\u0438",
        "status_cancelling": "\u041e\u0442\u043c\u0435\u043d\u0430\u2026",
        "status_bad_link": "\u041d\u0435 \u0443\u0434\u0430\u043b\u043e\u0441\u044c \u043f\u0440\u043e\u0447\u0438\u0442\u0430\u0442\u044c \u0441\u0441\u044b\u043b\u043a\u0443",
        "error_yt_dlp": "yt-dlp \u043d\u0435 \u043d\u0430\u0439\u0434\u0435\u043d \u0440\u044f\u0434\u043e\u043c \u0441 \u043f\u0440\u043e\u0433\u0440\u0430\u043c\u043c\u043e\u0439.",
        "error_ffmpeg": "FFmpeg \u043d\u0435 \u043d\u0430\u0439\u0434\u0435\u043d. \u0411\u0435\u0437 \u043d\u0435\u0433\u043e \u043d\u0435\u0432\u043e\u0437\u043c\u043e\u0436\u043d\u043e \u043e\u0431\u044a\u0435\u0434\u0438\u043d\u0438\u0442\u044c \u0432\u0438\u0434\u0435\u043e \u0438 \u0430\u0443\u0434\u0438\u043e.",
        "error_code": "yt-dlp: \u043a\u043e\u0434 {code}",
        "log_start": "\n\u0417\u0430\u043f\u0443\u0441\u043a \u0437\u0430\u0433\u0440\u0443\u0437\u043a\u0438:\n",
        "log_done": "\u0413\u043e\u0442\u043e\u0432\u043e.\n",
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
        "size_total": "Estimated size: {size} \u00b7 {suffix}",
        "size_suffix_separate": "total for two files",
        "size_suffix_merge": "after merging with audio",
        "status_choose": "Pick quality and codec",
        "status_prepare": "Preparing\u2026",
        "status_progress": "Downloading \u00b7 {value:.1f}%",
        "status_done_merged": "Done \u00b7 video and audio merged",
        "status_done": "Done",
        "status_failed": "Failed \u2014 open the details",
        "status_cancelling": "Cancelling\u2026",
        "status_bad_link": "Could not read this link",
        "error_yt_dlp": "yt-dlp was not found next to the app.",
        "error_ffmpeg": "FFmpeg was not found. It is required to merge video and audio.",
        "error_code": "yt-dlp: exit code {code}",
        "log_start": "\nStarting download:\n",
        "log_done": "Done.\n",
    },
}

URL_PLACEHOLDER = "https://www.youtube.com/watch?v=\u2026"
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
        self.title(APP_NAME)
        self.geometry("760x210")
        self.minsize(620, 190)
        self.configure(fg_color=("#f6f6f4", "#181818"))

        self.events: queue.Queue[tuple[str, object]] = queue.Queue()
        self.process: subprocess.Popen[str] | None = None
        self.analysis_timer: str | None = None
        self.analyzed_url = ""
        self.media_duration = 0.0
        self.merge_audio_size = 0.0

        # Keys are stable ids, never localized text.
        self.video_groups: dict[str, dict[str, dict[str, Any]]] = {}
        self.audio_formats: dict[str, dict[str, Any]] = {}
        self.quality_buttons: list[ctk.CTkButton] = []
        self.codec_buttons: list[ctk.CTkButton] = []
        self.selected_quality = ""
        self.selected_codec = ""
        self.selected_audio = ""

        self.revealed = False
        self.log_open = False
        self.language = "ru"
        self.mode = "video"
        self.status_key: str | None = None
        self.status_args: dict[str, Any] = {}

        self.language_var = ctk.StringVar(value="RU")
        self.url_var = ctk.StringVar()
        self.mode_var = ctk.StringVar(value=self.tr("mode_video"))
        self.output_var = ctk.StringVar(value=str(downloads_dir()))
        self.audio_output_var = ctk.StringVar(value=self.tr("audio_original"))
        self.playlist_var = ctk.BooleanVar(value=False)
        self.separate_var = ctk.BooleanVar(value=False)
        self.status_var = ctk.StringVar(value="")
        self.title_var = ctk.StringVar(value="")
        self.meta_var = ctk.StringVar(value="")
        self.size_var = ctk.StringVar(value="")

        self._build()
        self.after(100, self._poll)
        self.protocol("WM_DELETE_WINDOW", self._close)

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
                return f"\u2248 {value:.1f} {unit}"
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
        self.folder_button.configure(text=self._folder_label())
        self.cancel_button.configure(text=self.tr("cancel"))
        self.open_button.configure(text=self.tr("open_folder"))
        self.log_button.configure(text=self.tr("hide_details" if self.log_open else "details"))
        self.download_button.configure(
            text=self.tr("download_video" if self.mode == "video" else "download_audio")
        )
        self._set_status(self.status_key, **self.status_args)
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
            width=76,
            height=26,
            corner_radius=8,
            font=ctk.CTkFont(size=12),
        )
        self.language_switch.grid(row=0, column=1, sticky="e", pady=(0, 9))
        self.url_entry = ctk.CTkEntry(
            search,
            textvariable=self.url_var,
            height=54,
            corner_radius=14,
            border_width=1,
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

        self.content = ctk.CTkFrame(self, fg_color="transparent")
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
            text_color=("#747474", "#a5a5a5"),
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
            text_color=("#747474", "#a5a5a5"),
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
            text_color=("#747474", "#a5a5a5"),
            font=ctk.CTkFont(size=12),
        ).grid(row=2, column=0, sticky="ew", pady=(7, 0))

        self.audio_options = ctk.CTkFrame(self.content, fg_color="transparent")
        self.audio_options.grid_columnconfigure(0, weight=1)
        self.audio_format_label = ctk.CTkLabel(
            self.audio_options,
            text=self.tr("audio_format"),
            anchor="w",
            text_color=("#747474", "#a5a5a5"),
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
        options.grid_columnconfigure(1, weight=1)
        self.separate_check = ctk.CTkCheckBox(
            options,
            text=self.tr("separate"),
            variable=self.separate_var,
            checkbox_width=20,
            checkbox_height=20,
            command=self._update_size_summary,
        )
        self.separate_check.grid(row=0, column=0, sticky="w")
        self.playlist_check = ctk.CTkCheckBox(
            options,
            text=self.tr("playlist"),
            variable=self.playlist_var,
            checkbox_width=20,
            checkbox_height=20,
        )
        self.playlist_check.grid(row=0, column=1, sticky="e")

        destination = ctk.CTkFrame(self.content, fg_color="transparent")
        destination.grid(row=5, column=0, sticky="ew", padx=34, pady=(15, 0))
        destination.grid_columnconfigure(0, weight=1)
        self.folder_button = ctk.CTkButton(
            destination,
            text=self._folder_label(),
            anchor="w",
            height=36,
            fg_color="transparent",
            border_width=1,
            text_color=("#555555", "#c7c7c7"),
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
            border_width=1,
            text_color=("#555555", "#d0d0d0"),
            command=self._cancel,
        )
        self.status = ctk.CTkLabel(
            actions,
            textvariable=self.status_var,
            anchor="w",
            text_color=("#747474", "#a5a5a5"),
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
            text_color=("#666666", "#aaaaaa"),
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
            text_color=("#666666", "#aaaaaa"),
            hover_color=("#e9e9e6", "#252525"),
            command=self._open_folder,
        )
        self.log = ctk.CTkTextbox(
            self.content,
            height=170,
            corner_radius=10,
            wrap="word",
            font=("Consolas", 11),
        )
        self.log.configure(state="disabled")

    # ---------- paste / url ----------

    def _layout_agnostic_paste(self, event: Any) -> str | None:
        """Paste on Ctrl+V even when the active keyboard layout is not Latin.

        Tk resolves Ctrl+V through the keysym, so with a Cyrillic layout the
        stroke arrives as Ctrl+\u043c and the built-in <<Paste>> never fires.
        The physical key is still reported in event.keycode, so we use that.
        Latin layouts keep using the built-in binding, so nothing is pasted twice.
        """
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
        executable = find_tool("yt-dlp")
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
        self.meta_var.set("  \u00b7  ".join(value for value in (author, length) if value))
        self._prepare_formats(data.get("formats") or [])
        self._reveal_content()
        self._refresh_mode_views()
        self._set_status("status_choose")

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
            codec_key = f"{codec(item.get('vcodec'))} \u00b7 {str(item.get('ext') or '?').upper()}"
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
            f"{codec(item.get('acodec'))} \u00b7 {extension} \u00b7 {size}"
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
            fg_color=("#2783de", "#3b8ed0") if active else ("#ffffff", "#242424"),
            text_color="#ffffff" if active else ("#333333", "#eeeeee"),
            border_width=0 if active else 1,
            border_color=("#dededb", "#3a3a3a"),
            hover_color=("#1f75c5", "#367baa") if active else ("#eeeeeb", "#303030"),
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
            self.download_button.configure(text=self.tr("download_video"))
        else:
            self.codec_section.grid_remove()
            self.separate_check.grid_remove()
            self.audio_options.grid(row=3, column=0, sticky="ew", padx=34, pady=(13, 0))
            self.download_button.configure(text=self.tr("download_audio"))
        self._render_quality_buttons()
        if self.mode == "video":
            self._render_codec_buttons()

    def _reveal_content(self) -> None:
        self.loading.stop()
        self.loading.grid_remove()
        self.content.grid(row=1, column=0, sticky="nsew")
        self.revealed = True
        self.geometry("840x820")
        self.minsize(720, 720)

    def _hide_content(self) -> None:
        self.content.grid_remove()
        self.revealed = False
        self.geometry("760x210")
        self.minsize(620, 190)

    # ---------- download ----------

    def _download(self) -> None:
        if self.process or self.analyzed_url != self.url_var.get().strip():
            return
        executable = find_tool("yt-dlp")
        if not executable:
            messagebox.showerror(APP_NAME, self.tr("error_yt_dlp"))
            return
        separate = self.separate_var.get() and self.mode == "video"
        if self.mode == "video" and not separate and not find_tool("ffmpeg"):
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
        ffmpeg = find_tool("ffmpeg")
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
        return f"{self.tr('save_to')}  \u00b7  {self.output_var.get()}"

    def _toggle_log(self) -> None:
        self.log_open = not self.log_open
        if self.log_open:
            self.log.grid(row=8, column=0, sticky="nsew", padx=34, pady=(0, 24))
            self.content.grid_rowconfigure(8, weight=1)
            self.geometry("840x970")
            self.log_button.configure(text=self.tr("hide_details"))
        else:
            self.log.grid_remove()
            self.content.grid_rowconfigure(8, weight=0)
            self.geometry("840x820")
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
