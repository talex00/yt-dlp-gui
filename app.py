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
from tkinter import filedialog, messagebox

APP_NAME = "yt-dlp GUI"
SETTINGS_DIR = Path(os.getenv("APPDATA", Path.home())) / "yt-dlp-gui"
SETTINGS_FILE = SETTINGS_DIR / "settings.json"
PROGRESS_RE = re.compile(r"\[download\]\s+([\d.]+)%")
AUTO_VIDEO = "Лучшее доступное качество (авто)"
AUTO_AUDIO = "Лучший аудиопоток (авто)"

ctk.set_appearance_mode("System")
ctk.set_default_color_theme("blue")


def app_directory() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def default_download_directory() -> Path:
    downloads = Path.home() / "Downloads"
    return downloads if downloads.exists() else Path.home()


def human_size(value: object) -> str:
    if not isinstance(value, (int, float)) or value <= 0:
        return "размер неизвестен"
    size = float(value)
    for unit in ("Б", "КБ", "МБ", "ГБ"):
        if size < 1024 or unit == "ГБ":
            return f"{size:.1f} {unit}"
        size /= 1024
    return "размер неизвестен"


def human_duration(value: object) -> str:
    if not isinstance(value, (int, float)):
        return ""
    seconds = int(value)
    hours, seconds = divmod(seconds, 3600)
    minutes, seconds = divmod(seconds, 60)
    return f"{hours}:{minutes:02d}:{seconds:02d}" if hours else f"{minutes}:{seconds:02d}"


def codec_name(value: object) -> str:
    text = str(value or "?").split(".", 1)[0]
    aliases = {"avc1": "H.264", "h264": "H.264", "av01": "AV1", "vp09": "VP9", "mp4a": "AAC"}
    return aliases.get(text.lower(), text.upper())


class YtDlpGui(ctk.CTk):
    def __init__(self) -> None:
        super().__init__()
        self.title(APP_NAME)
        self.geometry("1100x820")
        self.minsize(900, 720)

        self.process: subprocess.Popen[str] | None = None
        self.current_action: str | None = None
        self.events: queue.Queue[tuple[str, object]] = queue.Queue()
        self.settings = self._load_settings()
        self.video_formats: dict[str, tuple[str, bool]] = {}
        self.audio_formats: dict[str, str] = {}

        detected_executable = self._detect_yt_dlp()
        self.url_var = ctk.StringVar()
        self.output_var = ctk.StringVar(value=str(self.settings.get("output_dir", default_download_directory())))
        self.executable_var = ctk.StringVar(value=str(self.settings.get("yt_dlp_path", detected_executable)))
        self.mode_var = ctk.StringVar(value=str(self.settings.get("mode", "Видео")))
        self.video_format_var = ctk.StringVar(value=AUTO_VIDEO)
        self.audio_source_var = ctk.StringVar(value=AUTO_AUDIO)
        self.audio_output_var = ctk.StringVar(value=str(self.settings.get("audio_output", "mp3")))
        self.playlist_var = ctk.BooleanVar(value=bool(self.settings.get("playlist", False)))
        self.overwrite_var = ctk.BooleanVar(value=False)
        self.status_var = ctk.StringVar(value="Готово к работе")
        self.media_title_var = ctk.StringVar(value="Вставьте ссылку и нажмите «Анализировать»")
        self.media_details_var = ctk.StringVar(value="Будут показаны реальные форматы, разрешения, FPS и битрейты")

        self._build_ui()
        self._update_mode_controls(self.mode_var.get())
        self.after(100, self._poll_events)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _build_ui(self) -> None:
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(4, weight=1)

        header = ctk.CTkFrame(self, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", padx=32, pady=(24, 16))
        header.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(header, text="yt-dlp GUI", font=ctk.CTkFont(size=28, weight="bold")).grid(row=0, column=0, sticky="w")
        ctk.CTkLabel(
            header,
            text="Видео и аудио — с понятным выбором реального качества",
            text_color=("#666666", "#a9a9a9"),
            font=ctk.CTkFont(size=14),
        ).grid(row=1, column=0, sticky="w", pady=(3, 0))
        self.theme_button = ctk.CTkButton(
            header, text="◐  Тема", width=96, fg_color="transparent", border_width=1,
            text_color=("#333333", "#eeeeee"), command=self._toggle_theme,
        )
        self.theme_button.grid(row=0, column=1, rowspan=2, sticky="e")

        url_card = ctk.CTkFrame(self, corner_radius=14)
        url_card.grid(row=1, column=0, sticky="ew", padx=32, pady=(0, 14))
        url_card.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(url_card, text="Ссылка на видео или плейлист", font=ctk.CTkFont(size=13, weight="bold")).grid(
            row=0, column=0, columnspan=2, sticky="w", padx=20, pady=(16, 7)
        )
        self.url_entry = ctk.CTkEntry(
            url_card, textvariable=self.url_var, height=42,
            placeholder_text="https://www.youtube.com/watch?v=…",
        )
        self.url_entry.grid(row=1, column=0, sticky="ew", padx=(20, 10), pady=(0, 16))
        self.url_entry.bind("<Return>", lambda _event: self._start_analysis())
        self.analyze_button = ctk.CTkButton(
            url_card, text="Анализировать", width=150, height=42, command=self._start_analysis,
        )
        self.analyze_button.grid(row=1, column=1, padx=(0, 20), pady=(0, 16))

        content = ctk.CTkFrame(self, fg_color="transparent")
        content.grid(row=2, column=0, sticky="ew", padx=32)
        content.grid_columnconfigure(0, weight=3, uniform="cards")
        content.grid_columnconfigure(1, weight=2, uniform="cards")

        media_card = ctk.CTkFrame(content, corner_radius=14)
        media_card.grid(row=0, column=0, sticky="nsew", padx=(0, 7))
        media_card.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(media_card, textvariable=self.media_title_var, anchor="w", justify="left", wraplength=570,
                     font=ctk.CTkFont(size=16, weight="bold")).grid(row=0, column=0, sticky="ew", padx=20, pady=(17, 3))
        ctk.CTkLabel(media_card, textvariable=self.media_details_var, anchor="w", justify="left",
                     text_color=("#666666", "#a9a9a9")).grid(row=1, column=0, sticky="ew", padx=20, pady=(0, 14))

        self.mode_switch = ctk.CTkSegmentedButton(
            media_card, values=["Видео", "Аудио"], variable=self.mode_var,
            command=self._update_mode_controls, height=36,
        )
        self.mode_switch.grid(row=2, column=0, sticky="ew", padx=20, pady=(0, 14))

        self.video_panel = ctk.CTkFrame(media_card, fg_color="transparent")
        self.video_panel.grid(row=3, column=0, sticky="ew", padx=20, pady=(0, 18))
        self.video_panel.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(self.video_panel, text="Доступное качество", anchor="w").grid(row=0, column=0, sticky="ew", pady=(0, 6))
        self.video_menu = ctk.CTkOptionMenu(
            self.video_panel, variable=self.video_format_var, values=[AUTO_VIDEO],
            height=38, dynamic_resizing=False,
        )
        self.video_menu.grid(row=1, column=0, sticky="ew")

        self.audio_panel = ctk.CTkFrame(media_card, fg_color="transparent")
        self.audio_panel.grid(row=3, column=0, sticky="ew", padx=20, pady=(0, 18))
        self.audio_panel.grid_columnconfigure(0, weight=2)
        self.audio_panel.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(self.audio_panel, text="Исходный аудиопоток", anchor="w").grid(row=0, column=0, sticky="ew", pady=(0, 6))
        ctk.CTkLabel(self.audio_panel, text="Сохранить как", anchor="w").grid(row=0, column=1, sticky="ew", padx=(10, 0), pady=(0, 6))
        self.audio_source_menu = ctk.CTkOptionMenu(
            self.audio_panel, variable=self.audio_source_var, values=[AUTO_AUDIO],
            height=38, dynamic_resizing=False,
        )
        self.audio_source_menu.grid(row=1, column=0, sticky="ew")
        self.audio_output_menu = ctk.CTkOptionMenu(
            self.audio_panel, variable=self.audio_output_var,
            values=["Оригинал", "mp3", "m4a", "opus", "wav", "flac"], height=38,
        )
        self.audio_output_menu.grid(row=1, column=1, sticky="ew", padx=(10, 0))

        settings_card = ctk.CTkFrame(content, corner_radius=14)
        settings_card.grid(row=0, column=1, sticky="nsew", padx=(7, 0))
        settings_card.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(settings_card, text="Сохранение", font=ctk.CTkFont(size=16, weight="bold")).grid(
            row=0, column=0, sticky="w", padx=20, pady=(17, 12)
        )
        self.output_entry = ctk.CTkEntry(settings_card, textvariable=self.output_var, height=38)
        self.output_entry.grid(row=1, column=0, sticky="ew", padx=(20, 8))
        ctk.CTkButton(settings_card, text="…", width=42, height=38, command=self._choose_output).grid(
            row=1, column=1, padx=(0, 20)
        )
        ctk.CTkLabel(settings_card, text="Путь к yt-dlp", anchor="w").grid(
            row=2, column=0, columnspan=2, sticky="ew", padx=20, pady=(13, 6)
        )
        self.executable_entry = ctk.CTkEntry(settings_card, textvariable=self.executable_var, height=38)
        self.executable_entry.grid(row=3, column=0, sticky="ew", padx=(20, 8))
        ctk.CTkButton(settings_card, text="…", width=42, height=38, command=self._choose_executable).grid(
            row=3, column=1, padx=(0, 20)
        )
        self.playlist_check = ctk.CTkCheckBox(settings_card, text="Скачать плейлист целиком", variable=self.playlist_var)
        self.playlist_check.grid(row=4, column=0, columnspan=2, sticky="w", padx=20, pady=(15, 8))
        self.overwrite_check = ctk.CTkCheckBox(settings_card, text="Перезаписывать файлы", variable=self.overwrite_var)
        self.overwrite_check.grid(row=5, column=0, columnspan=2, sticky="w", padx=20, pady=(0, 17))

        action = ctk.CTkFrame(self, fg_color="transparent")
        action.grid(row=3, column=0, sticky="ew", padx=32, pady=14)
        action.grid_columnconfigure(1, weight=1)
        self.download_button = ctk.CTkButton(
            action, text="Скачать", width=150, height=42, font=ctk.CTkFont(weight="bold"), command=self._start_download,
        )
        self.download_button.grid(row=0, column=0, rowspan=2, sticky="w")
        self.progress = ctk.CTkProgressBar(action, height=10)
        self.progress.grid(row=0, column=1, sticky="ew", padx=16)
        self.progress.set(0)
        ctk.CTkLabel(action, textvariable=self.status_var, anchor="w", text_color=("#666666", "#a9a9a9")).grid(
            row=1, column=1, sticky="ew", padx=16, pady=(4, 0)
        )
        self.cancel_button = ctk.CTkButton(
            action, text="Отмена", width=100, height=42, fg_color="transparent", border_width=1,
            text_color=("#333333", "#eeeeee"), command=self._cancel_operation, state="disabled",
        )
        self.cancel_button.grid(row=0, column=2, rowspan=2)
        ctk.CTkButton(
            action, text="Открыть папку", width=125, height=42, fg_color="transparent", border_width=1,
            text_color=("#333333", "#eeeeee"), command=self._open_output,
        ).grid(row=0, column=3, rowspan=2, padx=(10, 0))

        log_card = ctk.CTkFrame(self, corner_radius=14)
        log_card.grid(row=4, column=0, sticky="nsew", padx=32, pady=(0, 26))
        log_card.grid_columnconfigure(0, weight=1)
        log_card.grid_rowconfigure(1, weight=1, minsize=210)
        ctk.CTkLabel(log_card, text="Журнал", font=ctk.CTkFont(size=15, weight="bold")).grid(
            row=0, column=0, sticky="w", padx=18, pady=(13, 7)
        )
        ctk.CTkButton(
            log_card, text="Очистить", width=80, height=28, fg_color="transparent",
            text_color=("#555555", "#bbbbbb"), command=self._clear_log,
        ).grid(row=0, column=1, sticky="e", padx=12, pady=(10, 5))
        self.log = ctk.CTkTextbox(log_card, wrap="word", font=("Consolas", 12), corner_radius=8)
        self.log.grid(row=1, column=0, columnspan=2, sticky="nsew", padx=12, pady=(0, 12))
        self.log.configure(state="disabled")
        self.url_entry.focus_set()

    def _toggle_theme(self) -> None:
        current = ctk.get_appearance_mode()
        ctk.set_appearance_mode("Light" if current == "Dark" else "Dark")

    def _detect_yt_dlp(self) -> str:
        for candidate in (app_directory() / "yt-dlp.exe", app_directory() / "yt-dlp"):
            if candidate.is_file():
                return str(candidate)
        return shutil.which("yt-dlp") or "yt-dlp.exe"

    def _load_settings(self) -> dict[str, object]:
        try:
            return json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            return {}

    def _save_settings(self) -> None:
        data = {
            "output_dir": self.output_var.get().strip(),
            "yt_dlp_path": self.executable_var.get().strip(),
            "mode": self.mode_var.get(),
            "audio_output": self.audio_output_var.get(),
            "playlist": self.playlist_var.get(),
        }
        try:
            SETTINGS_DIR.mkdir(parents=True, exist_ok=True)
            SETTINGS_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        except OSError:
            pass

    def _resolve_executable(self) -> str | None:
        value = self.executable_var.get().strip()
        if Path(value).is_file():
            return value
        return shutil.which(value)

    def _validate_url_and_executable(self) -> tuple[str, str] | None:
        url = self.url_var.get().strip()
        if not url.startswith(("http://", "https://")):
            messagebox.showwarning(APP_NAME, "Введите корректную ссылку на видео.")
            self.url_entry.focus_set()
            return None
        executable = self._resolve_executable()
        if not executable:
            messagebox.showerror(APP_NAME, "Файл yt-dlp не найден. Укажите путь к yt-dlp.exe.")
            return None
        return url, executable

    def _start_analysis(self) -> None:
        if self.process:
            return
        validated = self._validate_url_and_executable()
        if not validated:
            return
        url, executable = validated
        self._set_busy(True, "analysis")
        self.status_var.set("Получаем сведения о видео…")
        self.media_title_var.set("Анализ ссылки…")
        self.media_details_var.set("yt-dlp запрашивает список доступных потоков")
        self._append_log(f"\nАнализ: {url}\n")
        threading.Thread(target=self._run_analysis, args=(executable, url), daemon=True).start()

    def _run_analysis(self, executable: str, url: str) -> None:
        try:
            flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
            self.process = subprocess.Popen(
                [executable, "--dump-single-json", "--no-playlist", "--no-warnings", url],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                encoding="utf-8", errors="replace", creationflags=flags,
            )
            stdout, stderr = self.process.communicate()
            code = self.process.returncode
            if code != 0:
                self.events.put(("analysis_error", stderr.strip() or f"yt-dlp завершился с кодом {code}"))
            else:
                self.events.put(("analysis_result", json.loads(stdout)))
        except (OSError, ValueError, json.JSONDecodeError) as error:
            self.events.put(("analysis_error", str(error)))
        finally:
            self.process = None

    def _apply_analysis(self, data: dict[str, Any]) -> None:
        if data.get("_type") == "playlist" and data.get("entries"):
            data = next((entry for entry in data["entries"] if entry), data)
        title = str(data.get("title") or "Без названия")
        uploader = str(data.get("uploader") or data.get("channel") or "Автор неизвестен")
        duration = human_duration(data.get("duration"))
        self.media_title_var.set(title)
        self.media_details_var.set(" · ".join(part for part in (uploader, duration) if part))

        videos: list[tuple[tuple[int, float, float], str, str, bool]] = []
        audios: list[tuple[tuple[float, float], str, str]] = []
        for fmt in data.get("formats") or []:
            format_id = str(fmt.get("format_id") or "")
            if not format_id:
                continue
            vcodec = str(fmt.get("vcodec") or "none")
            acodec = str(fmt.get("acodec") or "none")
            extension = str(fmt.get("ext") or "?").upper()
            size = human_size(fmt.get("filesize") or fmt.get("filesize_approx"))
            if vcodec != "none" and fmt.get("height"):
                height = int(fmt.get("height") or 0)
                fps = float(fmt.get("fps") or 0)
                bitrate = float(fmt.get("tbr") or 0)
                audio_note = "с аудио" if acodec != "none" else "+ лучшее аудио"
                fps_text = f" · {fps:g} FPS" if fps else ""
                label = f"{height}p{fps_text} · {codec_name(vcodec)} · {extension} · {audio_note} · {size}  [{format_id}]"
                videos.append(((height, fps, bitrate), label, format_id, acodec != "none"))
            elif vcodec == "none" and acodec != "none":
                abr = float(fmt.get("abr") or fmt.get("tbr") or 0)
                bitrate_text = f"{abr:.0f} кбит/с" if abr else "битрейт неизвестен"
                sample_rate = fmt.get("asr")
                sample_text = f" · {int(sample_rate) / 1000:g} кГц" if isinstance(sample_rate, (int, float)) else ""
                label = f"{codec_name(acodec)} · {bitrate_text}{sample_text} · {extension} · {size}  [{format_id}]"
                audios.append(((abr, float(fmt.get("filesize") or 0)), label, format_id))

        videos.sort(key=lambda item: item[0], reverse=True)
        audios.sort(key=lambda item: item[0], reverse=True)
        self.video_formats = {label: (format_id, has_audio) for _, label, format_id, has_audio in videos}
        self.audio_formats = {label: format_id for _, label, format_id in audios}
        video_values = [AUTO_VIDEO, *self.video_formats.keys()]
        audio_values = [AUTO_AUDIO, *self.audio_formats.keys()]
        self.video_menu.configure(values=video_values)
        self.audio_source_menu.configure(values=audio_values)
        self.video_format_var.set(video_values[1] if len(video_values) > 1 else AUTO_VIDEO)
        self.audio_source_var.set(audio_values[1] if len(audio_values) > 1 else AUTO_AUDIO)
        self.status_var.set(f"Найдено: {len(videos)} видеоформатов и {len(audios)} аудиоформатов")
        self._append_log(f"Найдено видеоформатов: {len(videos)}, аудиоформатов: {len(audios)}.\n")

    def _update_mode_controls(self, selected: str) -> None:
        if selected == "Видео":
            self.audio_panel.grid_remove()
            self.video_panel.grid()
        else:
            self.video_panel.grid_remove()
            self.audio_panel.grid()

    def _choose_output(self) -> None:
        selected = filedialog.askdirectory(title="Выберите папку", initialdir=self.output_var.get() or str(default_download_directory()))
        if selected:
            self.output_var.set(selected)

    def _choose_executable(self) -> None:
        selected = filedialog.askopenfilename(
            title="Выберите yt-dlp", filetypes=(("yt-dlp", "yt-dlp.exe yt-dlp"), ("Все файлы", "*.*"))
        )
        if selected:
            self.executable_var.set(selected)

    def _build_download_command(self, executable: str, url: str, output_dir: Path) -> list[str]:
        command = [
            executable, url, "--newline", "--progress", "--windows-filenames",
            "--output", str(output_dir / "%(title)s.%(ext)s"),
            "--yes-playlist" if self.playlist_var.get() else "--no-playlist",
            "--force-overwrites" if self.overwrite_var.get() else "--no-overwrites",
        ]
        if self.mode_var.get() == "Видео":
            selected = self.video_format_var.get()
            if selected in self.video_formats:
                format_id, has_audio = self.video_formats[selected]
                selector = format_id if has_audio else f"{format_id}+bestaudio/best"
            else:
                selector = "bestvideo*+bestaudio/best"
            command.extend(["--format", selector, "--merge-output-format", "mp4"])
        else:
            selected = self.audio_source_var.get()
            selector = self.audio_formats.get(selected, "bestaudio/best")
            command.extend(["--format", selector])
            output_format = self.audio_output_var.get()
            if output_format != "Оригинал":
                command.extend(["--extract-audio", "--audio-format", output_format, "--audio-quality", "0"])
        return command

    def _start_download(self) -> None:
        if self.process:
            return
        validated = self._validate_url_and_executable()
        if not validated:
            return
        url, executable = validated
        output_dir = Path(self.output_var.get().strip()).expanduser()
        try:
            output_dir.mkdir(parents=True, exist_ok=True)
        except OSError as error:
            messagebox.showerror(APP_NAME, f"Не удалось открыть папку:\n{error}")
            return
        self._save_settings()
        self.progress.set(0)
        self._set_busy(True, "download")
        self.status_var.set("Подготовка загрузки…")
        self._append_log("\nЗапуск загрузки…\n")
        command = self._build_download_command(executable, url, output_dir)
        threading.Thread(target=self._run_download, args=(command,), daemon=True).start()

    def _run_download(self, command: list[str]) -> None:
        try:
            flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
            self.process = subprocess.Popen(
                command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                encoding="utf-8", errors="replace", bufsize=1, creationflags=flags,
            )
            assert self.process.stdout is not None
            for line in self.process.stdout:
                self.events.put(("line", line))
                match = PROGRESS_RE.search(line)
                if match:
                    self.events.put(("progress", float(match.group(1))))
            self.events.put(("finished", self.process.wait()))
        except OSError as error:
            self.events.put(("operation_error", str(error)))
        finally:
            self.process = None

    def _poll_events(self) -> None:
        try:
            while True:
                event, payload = self.events.get_nowait()
                if event == "line":
                    self._append_log(str(payload))
                elif event == "progress":
                    value = float(payload)
                    self.progress.set(value / 100)
                    self.status_var.set(f"Загрузка: {value:.1f}%")
                elif event == "analysis_result":
                    self._set_busy(False)
                    self._apply_analysis(payload if isinstance(payload, dict) else {})
                elif event == "analysis_error":
                    self._set_busy(False)
                    self.media_title_var.set("Не удалось проанализировать ссылку")
                    self.media_details_var.set(str(payload))
                    self.status_var.set("Ошибка анализа")
                    self._append_log(f"Ошибка анализа: {payload}\n")
                elif event == "finished":
                    self._set_busy(False)
                    if int(payload) == 0:
                        self.progress.set(1)
                        self.status_var.set("Загрузка завершена")
                        self._append_log("Готово.\n")
                    else:
                        self.status_var.set("Загрузка завершилась с ошибкой")
                        self._append_log(f"yt-dlp завершился с кодом {payload}.\n")
                elif event == "operation_error":
                    self._set_busy(False)
                    self.status_var.set("Не удалось запустить yt-dlp")
                    self._append_log(f"Ошибка запуска: {payload}\n")
        except queue.Empty:
            pass
        self.after(100, self._poll_events)

    def _set_busy(self, busy: bool, action: str | None = None) -> None:
        self.current_action = action if busy else None
        state = "disabled" if busy else "normal"
        self.download_button.configure(state=state)
        self.analyze_button.configure(state=state)
        self.cancel_button.configure(state="normal" if busy else "disabled")

    def _cancel_operation(self) -> None:
        process = self.process
        if process and process.poll() is None:
            process.terminate()
            self.status_var.set("Операция отменяется…")
            self._append_log("Операция отменена пользователем.\n")

    def _append_log(self, text: str) -> None:
        self.log.configure(state="normal")
        self.log.insert("end", text)
        self.log.see("end")
        self.log.configure(state="disabled")

    def _clear_log(self) -> None:
        self.log.configure(state="normal")
        self.log.delete("1.0", "end")
        self.log.configure(state="disabled")

    def _open_output(self) -> None:
        output_dir = Path(self.output_var.get().strip()).expanduser()
        if not output_dir.exists():
            messagebox.showwarning(APP_NAME, "Папка сохранения пока не существует.")
            return
        try:
            if os.name == "nt":
                os.startfile(output_dir)  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(output_dir)])
            else:
                subprocess.Popen(["xdg-open", str(output_dir)])
        except OSError as error:
            messagebox.showerror(APP_NAME, f"Не удалось открыть папку:\n{error}")

    def _on_close(self) -> None:
        self._save_settings()
        if self.process and self.process.poll() is None:
            if not messagebox.askyesno(APP_NAME, "Операция ещё выполняется. Остановить её и закрыть программу?"):
                return
            self.process.terminate()
        self.destroy()


if __name__ == "__main__":
    YtDlpGui().mainloop()
