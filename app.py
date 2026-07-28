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
from typing import Any

import customtkinter as ctk
from tkinter import TclError, filedialog, messagebox

APP_NAME = "yt-dlp GUI"
PROGRESS_RE = re.compile(r"\[download\]\s+([\d.]+)%")
LANGUAGES = {
    "ru": {
        "url_hint": "Вставьте сюда ссылку на видео",
        "url_placeholder": "https://www.youtube.com/watch?v=…",
        "mode_video": "Видео",
        "mode_audio": "Аудио",
        "codec": "Кодек",
        "audio_format": "Формат файла",
        "audio_original": "Оригинал",
        "separate": "Скачать видео и аудио отдельно",
        "playlist": "Скачать весь плейлист",
        "download_video_audio": "Скачать видео с аудио",
        "download_audio": "Скачать аудио",
        "cancel": "Отмена",
        "details": "Подробности",
        "hide_details": "Скрыть подробности",
        "open_folder": "Открыть папку",
        "save_to": "Сохранить в",
        "status_choose": "Выберите качество и кодек",
        "status_prepare": "Подготовка…",
        "status_cannot_read": "Не удалось прочитать ссылку",
        "status_downloading": "Скачивание · {value:.1f}%",
        "status_done_merged": "Готово · видео и аудио объединены",
        "status_done": "Готово",
        "status_error": "Ошибка — откройте подробности",
        "status_cancel": "Отмена…",
        "yt_dlp_not_found": "yt-dlp не найден рядом с программой.",
        "ffmpeg_not_found": "FFmpeg не найден. Без него невозможно объединить видео и аудио.",
        "yt_dlp_code": "yt-dlp: код {code}",
        "log_start": "\nЗапуск загрузки:\n",
        "log_done": "Готово.\n",
        "default_title": "Видео",
        "size_unknown": "размер неизвестен",
        "size_total_file": "Примерный размер готового файла: {size}",
        "size_total": "Примерный размер: {size} · {suffix}",
        "size_suffix_separate": "суммарно для двух файлов",
        "size_suffix_merge": "после объединения с аудио",
        "kbps": "кбит/с",
    },
    "en": {
        "url_hint": "Paste a video link here",
        "url_placeholder": "https://www.youtube.com/watch?v=…",
        "mode_video": "Video",
        "mode_audio": "Audio",
        "codec": "Codec",
        "audio_format": "File format",
        "audio_original": "Original",
        "separate": "Download video and audio separately",
        "playlist": "Download entire playlist",
        "download_video_audio": "Download video with audio",
        "download_audio": "Download audio",
        "cancel": "Cancel",
        "details": "Details",
        "hide_details": "Hide details",
        "open_folder": "Open folder",
        "save_to": "Save to",
        "status_choose": "Choose quality and codec",
        "status_prepare": "Preparing…",
        "status_cannot_read": "Failed to read link",
        "status_downloading": "Downloading · {value:.1f}%",
        "status_done_merged": "Done · video and audio merged",
        "status_done": "Done",
        "status_error": "Error — open details",
        "status_cancel": "Cancelling…",
        "yt_dlp_not_found": "yt-dlp was not found next to the application.",
        "ffmpeg_not_found": "FFmpeg was not found. It is required to merge video and audio.",
        "yt_dlp_code": "yt-dlp: code {code}",
        "log_start": "\nStarting download:\n",
        "log_done": "Done.\n",
        "default_title": "Video",
        "size_unknown": "size unknown",
        "size_total_file": "Approximate final file size: {size}",
        "size_total": "Approximate size: {size} · {suffix}",
        "size_suffix_separate": "total for two files",
        "size_suffix_merge": "after merging with audio",
        "kbps": "kbps",
    },
}

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


def human_size(size: float) -> str:
    if size <= 0:
        return "размер неизвестен"
    value = size
    for unit in ("Б", "КБ", "МБ", "ГБ"):
        if value < 1024 or unit == "ГБ":
            return f"≈ {value:.1f} {unit}"
        value /= 1024
    return "размер неизвестен"


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
        self._apply_language()
        self.after(100, self._poll)
        self.protocol("WM_DELETE_WINDOW", self._close)

    def tr(self, key: str, **kwargs: Any) -> str:
        text = LANGUAGES[self.language].get(key, key)
        return text.format(**kwargs) if kwargs else text

    def _mode_key_from_value(self, value: str) -> str:
        if value in {LANGUAGES["ru"]["mode_video"], LANGUAGES["en"]["mode_video"]}:
            return "video"
        if value in {LANGUAGES["ru"]["mode_audio"], LANGUAGES["en"]["mode_audio"]}:
            return "audio"
        return "video"

    def _mode_key(self) -> str:
        return self._mode_key_from_value(self.mode_var.get())

    def _is_original_audio_output(self, value: str | None = None) -> bool:
        selected = self.audio_output_var.get() if value is None else value
        return selected in {LANGUAGES["ru"]["audio_original"], LANGUAGES["en"]["audio_original"]}

    def _human_size(self, size: float) -> str:
        if size <= 0:
            return self.tr("size_unknown")
        value = size
        units = ("B", "KB", "MB", "GB") if self.language == "en" else ("Б", "КБ", "МБ", "ГБ")
        for unit in units:
            if value < 1024 or unit == units[-1]:
                return f"≈ {value:.1f} {unit}"
            value /= 1024
        return self.tr("size_unknown")

    def _apply_language(self) -> None:
        mode = self._mode_key()
        original_audio = self._is_original_audio_output()
        status_key = self._status_key()
        self.url_label.configure(text=self.tr("url_hint"))
        self.url_entry.configure(placeholder_text=self.tr("url_placeholder"))
        self.mode.configure(values=[self.tr("mode_video"), self.tr("mode_audio")])
        self.mode_var.set(self.tr("mode_video") if mode == "video" else self.tr("mode_audio"))
        self.codec_label.configure(text=self.tr("codec"))
        self.audio_format_label.configure(text=self.tr("audio_format"))
        self.audio_output.configure(values=[self.tr("audio_original"), "mp3", "m4a", "opus", "wav", "flac"])
        if original_audio:
            self.audio_output_var.set(self.tr("audio_original"))
        self.separate_check.configure(text=self.tr("separate"))
        self.playlist_check.configure(text=self.tr("playlist"))
        self.cancel_button.configure(text=self.tr("cancel"))
        self.open_button.configure(text=self.tr("open_folder"))
        self.log_button.configure(text=self.tr("hide_details") if self.log_open else self.tr("details"))
        self.folder_button.configure(text=self._folder_label())
        if status_key:
            self.status_var.set(self.tr(status_key))
        self._mode_changed(self.mode_var.get())
        self._update_size_summary()

    def _change_language(self, choice: str) -> None:
        self.language = "en" if choice == "EN" else "ru"
        self._apply_language()

    def _status_key(self) -> str | None:
        current = self.status_var.get()
        for key in (
            "status_choose",
            "status_prepare",
            "status_cannot_read",
            "status_done_merged",
            "status_done",
            "status_error",
            "status_cancel",
        ):
            if current in {LANGUAGES["ru"][key], LANGUAGES["en"][key]}:
                return key
        return None

    def _handle_non_english_ctrl_v(self, event: object) -> str | None:
        if os.name != "nt":
            return None
        key_event = event
        keycode = int(getattr(key_event, "keycode", -1))
        state = int(getattr(key_event, "state", 0))
        keysym = str(getattr(key_event, "keysym", ""))
        if not (state & 0x4) or keycode != 86:
            return None
        if keysym.lower() == "v":
            return None
        try:
            text = self.clipboard_get()
        except TclError:
            return "break"
        if text:
            try:
                self.url_entry.delete("sel.first", "sel.last")
            except TclError:
                pass
            self.url_entry.insert("insert", text)
            self.after(50, self._url_changed)
        return "break"

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
        self.url_label.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 9))
        self.url_entry = ctk.CTkEntry(
            search,
            textvariable=self.url_var,
            height=54,
            corner_radius=14,
            border_width=1,
            placeholder_text=self.tr("url_placeholder"),
            font=ctk.CTkFont(size=15),
        )
        self.url_entry.grid(row=1, column=0, sticky="ew")
        self.url_entry.bind("<KeyRelease>", self._url_changed)
        self.url_entry.bind("<<Paste>>", lambda _event: self.after(50, self._url_changed))
        self.url_entry.bind("<KeyPress>", self._handle_non_english_ctrl_v, add="+")
        self.url_entry.bind("<Return>", lambda _event: self._analyze_now())
        self.language_switch = ctk.CTkSegmentedButton(
            search,
            values=["RU", "EN"],
            variable=self.language_var,
            command=self._change_language,
            width=82,
            height=34,
            corner_radius=10,
        )
        self.language_switch.grid(row=1, column=1, sticky="e", padx=(10, 0))
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

        self.mode = ctk.CTkSegmentedButton(
            self.content,
            values=[self.tr("mode_video"), self.tr("mode_audio")],
            variable=self.mode_var,
            command=self._mode_changed,
            height=38,
            corner_radius=10,
        )
        self.mode.grid(row=1, column=0, sticky="ew", padx=34, pady=(20, 0))

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
            values=[self.tr("audio_original"), "mp3", "m4a", "opus", "wav", "flac"],
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
            text=self.tr("download_video_audio"),
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
            messagebox.showerror(APP_NAME, self.tr("yt_dlp_not_found"))
            return
        self._hide_content()
        self.loading.grid(row=2, column=0, sticky="ew", pady=(7, 0))
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
            self.events.put(("error", stderr.strip() or self.tr("yt_dlp_code", code=code)))

    def _apply_analysis(self, url: str, data: dict[str, Any]) -> None:
        if url != self.url_var.get().strip():
            return
        self.analyzed_url = url
        self.media_duration = float(data.get("duration") or 0)
        self.title_var.set(str(data.get("title") or self.tr("default_title")))
        author = str(data.get("channel") or data.get("uploader") or "")
        length = duration(data.get("duration"))
        self.meta_var.set("  ·  ".join(value for value in (author, length) if value))
        self._prepare_formats(data.get("formats") or [])
        self._reveal_content()
        self._mode_changed(self.mode_var.get())
        self.status_var.set(self.tr("status_choose"))

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

        preferred_audio = [item for item in audio_candidates if str(item.get("ext") or "").lower() == "m4a"]
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
            quality_label = f"{height}p\n{fps} FPS" if fps else f"{height}p"
            displayed_codecs: dict[str, dict[str, Any]] = {}
            for codec_label, item in codecs.items():
                video_size = format_size(item, self.media_duration)
                has_audio = str(item.get("acodec") or "none") != "none"
                total_size = video_size if has_audio else video_size + self.merge_audio_size
                displayed_codecs[f"{codec_label}\n{self._human_size(total_size)}"] = item
            self.video_groups[quality_label] = displayed_codecs

        audios = sorted(
            audio_candidates,
            key=lambda item: (
                float(item.get("abr") or item.get("tbr") or 0),
                float(item.get("filesize") or 0),
            ),
            reverse=True,
        )[:8]
        self.audio_formats.clear()
        for item in audios:
            abr = int(float(item.get("abr") or item.get("tbr") or 0))
            size = self._human_size(format_size(item, self.media_duration))
            label = (
                f"{abr or '?'} {self.tr('kbps')}\n"
                f"{codec(item.get('acodec'))} · {str(item.get('ext') or '').upper()} · {size}"
            )
            if label not in self.audio_formats:
                self.audio_formats[label] = item

        self.selected_quality = next(iter(self.video_groups), "")
        codecs = self.video_groups.get(self.selected_quality, {})
        self.selected_codec = next(iter(codecs), "")
        self.selected_audio = next(iter(self.audio_formats), "")
        self._update_size_summary()

    def _render_quality_buttons(self) -> None:
        for button in self.quality_buttons:
            button.destroy()
        self.quality_buttons.clear()
        video_mode = self._mode_key() == "video"
        source = self.video_groups if video_mode else self.audio_formats
        selected = self.selected_quality if video_mode else self.selected_audio
        for index, label in enumerate(source):
            active = label == selected
            button = self._choice_button(
                self.quality_frame,
                label,
                active,
                lambda value=label: self._select_quality(value),
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
        for index, label in enumerate(source):
            active = label == self.selected_codec
            button = self._choice_button(
                self.codec_frame,
                label,
                active,
                lambda value=label: self._select_codec(value),
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

    def _select_quality(self, label: str) -> None:
        if self._mode_key() == "video":
            self.selected_quality = label
            self.selected_codec = next(iter(self.video_groups.get(label, {})), "")
            self._render_quality_buttons()
            self._render_codec_buttons()
        else:
            self.selected_audio = label
            self._render_quality_buttons()

    def _select_codec(self, label: str) -> None:
        self.selected_codec = label
        self._render_codec_buttons()

    def _update_size_summary(self) -> None:
        item = self.video_groups.get(self.selected_quality, {}).get(self.selected_codec, {})
        video_size = format_size(item, self.media_duration)
        has_audio = str(item.get("acodec") or "none") != "none"
        if has_audio:
            self.size_var.set(self.tr("size_total_file", size=self._human_size(video_size)))
        else:
            total = video_size + self.merge_audio_size
            suffix = self.tr("size_suffix_separate") if self.separate_var.get() else self.tr("size_suffix_merge")
            self.size_var.set(self.tr("size_total", size=self._human_size(total), suffix=suffix))

    def _mode_changed(self, mode: str) -> None:
        if not self.revealed:
            return
        mode_key = self._mode_key_from_value(mode)
        if mode_key == "video":
            self.audio_options.grid_remove()
            self.codec_section.grid(row=3, column=0, sticky="ew", padx=34, pady=(13, 0))
            self.separate_check.grid()
            self.download_button.configure(text=self.tr("download_video_audio"))
        else:
            self.codec_section.grid_remove()
            self.separate_check.grid_remove()
            self.audio_options.grid(row=3, column=0, sticky="ew", padx=34, pady=(13, 0))
            self.download_button.configure(text=self.tr("download_audio"))
        self._render_quality_buttons()
        if mode_key == "video":
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

    def _download(self) -> None:
        if self.process or self.analyzed_url != self.url_var.get().strip():
            return
        executable = find_tool("yt-dlp")
        if not executable:
            messagebox.showerror(APP_NAME, self.tr("yt_dlp_not_found"))
            return
        video_mode = self._mode_key() == "video"
        separate = self.separate_var.get() and video_mode
        if video_mode and not separate and not find_tool("ffmpeg"):
            messagebox.showerror(
                APP_NAME,
                self.tr("ffmpeg_not_found"),
            )
            return
        folder = Path(self.output_var.get()).expanduser()
        folder.mkdir(parents=True, exist_ok=True)
        command = self._download_command(executable, folder)
        self.status_var.set(self.tr("status_prepare"))
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
        separate = self.separate_var.get() and self._mode_key() == "video"
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
        if self._mode_key() == "video":
            item = self.video_groups.get(self.selected_quality, {}).get(self.selected_codec, {})
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
            output = self.audio_output_var.get()
            if not self._is_original_audio_output(output):
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
                    self.status_var.set(self.tr("status_cannot_read"))
                    messagebox.showerror(APP_NAME, str(payload))
                elif event == "line":
                    self._log(str(payload))
                elif event == "progress":
                    value = float(payload)
                    self.progress.set(value / 100)
                    self.status_var.set(self.tr("status_downloading", value=value))
                elif event == "finished":
                    self.cancel_button.grid_remove()
                    self.download_button.grid()
                    if int(payload) == 0:
                        self.progress.set(1)
                        if self._mode_key() == "video" and not self.separate_var.get():
                            self.status_var.set(self.tr("status_done_merged"))
                        else:
                            self.status_var.set(self.tr("status_done"))
                        self.open_button.grid(row=0, column=2, sticky="e")
                        self._log(self.tr("log_done"))
                    else:
                        self.status_var.set(self.tr("status_error"))
        except queue.Empty:
            pass
        self.after(100, self._poll)

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
            self.status_var.set(self.tr("status_cancel"))

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
