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
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

APP_NAME = "yt-dlp GUI"
SETTINGS_DIR = Path(os.getenv("APPDATA", Path.home())) / "yt-dlp-gui"
SETTINGS_FILE = SETTINGS_DIR / "settings.json"
PROGRESS_RE = re.compile(r"\[download\]\s+([\d.]+)%")


def app_directory() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def default_download_directory() -> Path:
    downloads = Path.home() / "Downloads"
    return downloads if downloads.exists() else Path.home()


class YtDlpGui(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title(APP_NAME)
        self.geometry("780x650")
        self.minsize(700, 580)
        self.configure(background="#f7f7f5")

        self.process: subprocess.Popen[str] | None = None
        self.events: queue.Queue[tuple[str, object]] = queue.Queue()
        self.settings = self._load_settings()

        detected_executable = self._detect_yt_dlp()
        self.url_var = tk.StringVar()
        self.output_var = tk.StringVar(
            value=self.settings.get("output_dir", str(default_download_directory()))
        )
        self.executable_var = tk.StringVar(
            value=self.settings.get("yt_dlp_path", detected_executable)
        )
        self.mode_var = tk.StringVar(value=self.settings.get("mode", "video"))
        self.quality_var = tk.StringVar(value=self.settings.get("quality", "Лучшее"))
        self.audio_format_var = tk.StringVar(
            value=self.settings.get("audio_format", "mp3")
        )
        self.playlist_var = tk.BooleanVar(value=self.settings.get("playlist", False))
        self.overwrite_var = tk.BooleanVar(value=False)
        self.status_var = tk.StringVar(value="Готово к работе")
        self.progress_var = tk.DoubleVar(value=0)

        self._configure_styles()
        self._build_ui()
        self._update_mode_controls()
        self.after(100, self._poll_events)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _configure_styles(self) -> None:
        style = ttk.Style(self)
        if "clam" in style.theme_names():
            style.theme_use("clam")
        style.configure("App.TFrame", background="#f7f7f5")
        style.configure("Card.TFrame", background="#ffffff")
        style.configure(
            "Title.TLabel",
            background="#f7f7f5",
            foreground="#2c2c2b",
            font=("Segoe UI", 20, "bold"),
        )
        style.configure(
            "Subtitle.TLabel",
            background="#f7f7f5",
            foreground="#6f6e69",
            font=("Segoe UI", 10),
        )
        style.configure(
            "Card.TLabel",
            background="#ffffff",
            foreground="#2c2c2b",
            font=("Segoe UI", 10),
        )
        style.configure("Card.TRadiobutton", background="#ffffff")
        style.configure("Card.TCheckbutton", background="#ffffff")
        style.configure(
            "Primary.TButton",
            font=("Segoe UI", 10, "bold"),
            padding=(18, 10),
            foreground="#ffffff",
            background="#2783de",
        )
        style.map(
            "Primary.TButton",
            background=[("active", "#1f6fbd"), ("disabled", "#a9c9e8")],
        )
        style.configure("Secondary.TButton", padding=(12, 8))
        style.configure(
            "Horizontal.TProgressbar",
            troughcolor="#e6e5e3",
            background="#2783de",
        )

    def _build_ui(self) -> None:
        root = ttk.Frame(self, style="App.TFrame", padding=(28, 24))
        root.pack(fill="both", expand=True)
        root.columnconfigure(0, weight=1)
        root.rowconfigure(3, weight=1)

        ttk.Label(root, text="yt-dlp GUI", style="Title.TLabel").grid(
            row=0, column=0, sticky="w"
        )
        ttk.Label(
            root,
            text="Скачивайте видео и аудио без командной строки",
            style="Subtitle.TLabel",
        ).grid(row=1, column=0, sticky="w", pady=(2, 18))

        card = ttk.Frame(root, style="Card.TFrame", padding=20)
        card.grid(row=2, column=0, sticky="ew")
        card.columnconfigure(0, weight=1)

        ttk.Label(card, text="Ссылка", style="Card.TLabel").grid(
            row=0, column=0, sticky="w"
        )
        self.url_entry = ttk.Entry(card, textvariable=self.url_var)
        self.url_entry.grid(row=1, column=0, columnspan=4, sticky="ew", pady=(6, 14))
        self.url_entry.focus_set()

        ttk.Label(card, text="Что скачать", style="Card.TLabel").grid(
            row=2, column=0, sticky="w"
        )
        mode_frame = ttk.Frame(card, style="Card.TFrame")
        mode_frame.grid(row=3, column=0, columnspan=2, sticky="w", pady=(6, 14))
        ttk.Radiobutton(
            mode_frame,
            text="Видео",
            variable=self.mode_var,
            value="video",
            command=self._update_mode_controls,
            style="Card.TRadiobutton",
        ).pack(side="left")
        ttk.Radiobutton(
            mode_frame,
            text="Только аудио",
            variable=self.mode_var,
            value="audio",
            command=self._update_mode_controls,
            style="Card.TRadiobutton",
        ).pack(side="left", padx=(18, 0))

        ttk.Label(card, text="Качество видео", style="Card.TLabel").grid(
            row=2, column=2, sticky="w", padx=(18, 0)
        )
        self.quality_box = ttk.Combobox(
            card,
            textvariable=self.quality_var,
            values=("Лучшее", "2160p", "1440p", "1080p", "720p", "480p"),
            state="readonly",
            width=13,
        )
        self.quality_box.grid(row=3, column=2, sticky="w", padx=(18, 0), pady=(6, 14))

        ttk.Label(card, text="Формат аудио", style="Card.TLabel").grid(
            row=2, column=3, sticky="w", padx=(12, 0)
        )
        self.audio_box = ttk.Combobox(
            card,
            textvariable=self.audio_format_var,
            values=("mp3", "m4a", "opus", "wav", "flac"),
            state="readonly",
            width=10,
        )
        self.audio_box.grid(row=3, column=3, sticky="w", padx=(12, 0), pady=(6, 14))

        ttk.Label(card, text="Папка сохранения", style="Card.TLabel").grid(
            row=4, column=0, sticky="w"
        )
        ttk.Entry(card, textvariable=self.output_var).grid(
            row=5, column=0, columnspan=3, sticky="ew", pady=(6, 12)
        )
        ttk.Button(
            card,
            text="Выбрать…",
            command=self._choose_output,
            style="Secondary.TButton",
        ).grid(row=5, column=3, sticky="e", padx=(10, 0), pady=(6, 12))

        ttk.Label(card, text="Путь к yt-dlp", style="Card.TLabel").grid(
            row=6, column=0, sticky="w"
        )
        ttk.Entry(card, textvariable=self.executable_var).grid(
            row=7, column=0, columnspan=3, sticky="ew", pady=(6, 12)
        )
        ttk.Button(
            card,
            text="Выбрать…",
            command=self._choose_executable,
            style="Secondary.TButton",
        ).grid(row=7, column=3, sticky="e", padx=(10, 0), pady=(6, 12))

        options = ttk.Frame(card, style="Card.TFrame")
        options.grid(row=8, column=0, columnspan=4, sticky="w")
        ttk.Checkbutton(
            options,
            text="Скачать плейлист целиком",
            variable=self.playlist_var,
            style="Card.TCheckbutton",
        ).pack(side="left")
        ttk.Checkbutton(
            options,
            text="Перезаписывать существующие файлы",
            variable=self.overwrite_var,
            style="Card.TCheckbutton",
        ).pack(side="left", padx=(20, 0))

        activity = ttk.Frame(root, style="App.TFrame")
        activity.grid(row=3, column=0, sticky="nsew", pady=(18, 0))
        activity.columnconfigure(0, weight=1)
        activity.rowconfigure(3, weight=1)

        ttk.Label(activity, textvariable=self.status_var, style="Subtitle.TLabel").grid(
            row=0, column=0, sticky="w"
        )
        self.progress = ttk.Progressbar(
            activity,
            variable=self.progress_var,
            maximum=100,
            mode="determinate",
        )
        self.progress.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(7, 12))

        button_frame = ttk.Frame(activity, style="App.TFrame")
        button_frame.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(0, 12))
        self.download_button = ttk.Button(
            button_frame,
            text="Скачать",
            command=self._start_download,
            style="Primary.TButton",
        )
        self.download_button.pack(side="left")
        self.cancel_button = ttk.Button(
            button_frame,
            text="Отмена",
            command=self._cancel_download,
            style="Secondary.TButton",
            state="disabled",
        )
        self.cancel_button.pack(side="left", padx=(10, 0))
        ttk.Button(
            button_frame,
            text="Открыть папку",
            command=self._open_output,
            style="Secondary.TButton",
        ).pack(side="right")

        log_frame = ttk.Frame(activity, style="Card.TFrame", padding=1)
        log_frame.grid(row=3, column=0, columnspan=2, sticky="nsew")
        log_frame.columnconfigure(0, weight=1)
        log_frame.rowconfigure(0, weight=1)
        self.log = tk.Text(
            log_frame,
            height=9,
            wrap="word",
            relief="flat",
            borderwidth=0,
            padx=12,
            pady=10,
            background="#ffffff",
            foreground="#4b4a47",
            insertbackground="#2c2c2b",
            font=("Consolas", 9),
            state="disabled",
        )
        self.log.grid(row=0, column=0, sticky="nsew")
        scrollbar = ttk.Scrollbar(log_frame, orient="vertical", command=self.log.yview)
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.log.configure(yscrollcommand=scrollbar.set)

    def _detect_yt_dlp(self) -> str:
        candidates = [
            app_directory() / "yt-dlp.exe",
            app_directory() / "yt-dlp",
        ]
        for candidate in candidates:
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
            "quality": self.quality_var.get(),
            "audio_format": self.audio_format_var.get(),
            "playlist": self.playlist_var.get(),
        }
        try:
            SETTINGS_DIR.mkdir(parents=True, exist_ok=True)
            SETTINGS_FILE.write_text(
                json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        except OSError:
            pass

    def _update_mode_controls(self) -> None:
        is_video = self.mode_var.get() == "video"
        self.quality_box.configure(state="readonly" if is_video else "disabled")
        self.audio_box.configure(state="disabled" if is_video else "readonly")

    def _choose_output(self) -> None:
        selected = filedialog.askdirectory(
            title="Выберите папку для загрузок",
            initialdir=self.output_var.get() or str(default_download_directory()),
        )
        if selected:
            self.output_var.set(selected)

    def _choose_executable(self) -> None:
        selected = filedialog.askopenfilename(
            title="Выберите yt-dlp",
            filetypes=(("yt-dlp", "yt-dlp.exe yt-dlp"), ("Все файлы", "*.*")),
        )
        if selected:
            self.executable_var.set(selected)

    def _validate(self) -> tuple[str, Path] | None:
        url = self.url_var.get().strip()
        if not url.startswith(("http://", "https://")):
            messagebox.showwarning(APP_NAME, "Введите корректную ссылку на видео.")
            self.url_entry.focus_set()
            return None

        executable = self.executable_var.get().strip()
        resolved_executable = executable if Path(executable).is_file() else shutil.which(executable)
        if not resolved_executable:
            messagebox.showerror(
                APP_NAME,
                "Файл yt-dlp не найден. Укажите путь к yt-dlp.exe.",
            )
            return None

        output_dir = Path(self.output_var.get().strip()).expanduser()
        try:
            output_dir.mkdir(parents=True, exist_ok=True)
        except OSError as error:
            messagebox.showerror(APP_NAME, f"Не удалось открыть папку:\n{error}")
            return None
        return str(resolved_executable), output_dir

    def _build_command(self, executable: str, output_dir: Path) -> list[str]:
        output_template = str(output_dir / "%(title)s.%(ext)s")
        command = [
            executable,
            self.url_var.get().strip(),
            "--newline",
            "--progress",
            "--windows-filenames",
            "--output",
            output_template,
        ]

        command.append("--yes-playlist" if self.playlist_var.get() else "--no-playlist")
        command.append("--force-overwrites" if self.overwrite_var.get() else "--no-overwrites")

        if self.mode_var.get() == "audio":
            command.extend(
                [
                    "--extract-audio",
                    "--audio-format",
                    self.audio_format_var.get(),
                    "--audio-quality",
                    "0",
                ]
            )
        else:
            quality = self.quality_var.get()
            if quality == "Лучшее":
                format_selector = "bestvideo*+bestaudio/best"
            else:
                height = quality.removesuffix("p")
                format_selector = (
                    f"bestvideo*[height<={height}]+bestaudio/"
                    f"best[height<={height}]"
                )
            command.extend(["--format", format_selector, "--merge-output-format", "mp4"])
        return command

    def _start_download(self) -> None:
        validated = self._validate()
        if not validated:
            return
        executable, output_dir = validated
        command = self._build_command(executable, output_dir)
        self._save_settings()
        self._set_running(True)
        self.progress_var.set(0)
        self.status_var.set("Подготовка загрузки…")
        self._clear_log()
        self._append_log("Запуск yt-dlp…\n")
        threading.Thread(
            target=self._run_download,
            args=(command,),
            daemon=True,
        ).start()

    def _run_download(self, command: list[str]) -> None:
        try:
            creation_flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
            self.process = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                creationflags=creation_flags,
            )
            assert self.process.stdout is not None
            for line in self.process.stdout:
                self.events.put(("line", line))
                match = PROGRESS_RE.search(line)
                if match:
                    self.events.put(("progress", float(match.group(1))))
            return_code = self.process.wait()
            self.events.put(("finished", return_code))
        except OSError as error:
            self.events.put(("error", str(error)))
        finally:
            self.process = None

    def _poll_events(self) -> None:
        try:
            while True:
                event, payload = self.events.get_nowait()
                if event == "line":
                    self._append_log(str(payload))
                elif event == "progress":
                    self.progress_var.set(float(payload))
                    self.status_var.set(f"Загрузка: {float(payload):.1f}%")
                elif event == "finished":
                    self._set_running(False)
                    if int(payload) == 0:
                        self.progress_var.set(100)
                        self.status_var.set("Загрузка завершена")
                        self._append_log("\nГотово.\n")
                    else:
                        self.status_var.set("Загрузка завершилась с ошибкой")
                        self._append_log(f"\nyt-dlp завершился с кодом {payload}.\n")
                elif event == "error":
                    self._set_running(False)
                    self.status_var.set("Не удалось запустить yt-dlp")
                    self._append_log(f"\nОшибка запуска: {payload}\n")
                    messagebox.showerror(APP_NAME, f"Не удалось запустить yt-dlp:\n{payload}")
        except queue.Empty:
            pass
        self.after(100, self._poll_events)

    def _cancel_download(self) -> None:
        process = self.process
        if process and process.poll() is None:
            process.terminate()
            self.status_var.set("Отмена загрузки…")
            self._append_log("\nЗагрузка отменена пользователем.\n")

    def _set_running(self, running: bool) -> None:
        self.download_button.configure(state="disabled" if running else "normal")
        self.cancel_button.configure(state="normal" if running else "disabled")

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
            if not messagebox.askyesno(
                APP_NAME,
                "Загрузка ещё выполняется. Остановить её и закрыть программу?",
            ):
                return
            self.process.terminate()
        self.destroy()


if __name__ == "__main__":
    YtDlpGui().mainloop()
