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
PROGRESS_RE = re.compile(r"\[download\]\s+([\d.]+)%")

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
    return {"avc1": "H.264", "h264": "H.264", "av01": "AV1", "vp09": "VP9", "mp4a": "AAC"}.get(raw, raw.upper())


def duration(value: object) -> str:
    if not isinstance(value, (int, float)):
        return ""
    total = int(value)
    hours, total = divmod(total, 3600)
    minutes, seconds = divmod(total, 60)
    return f"{hours}:{minutes:02d}:{seconds:02d}" if hours else f"{minutes}:{seconds:02d}"


class App(ctk.CTk):
    def __init__(self) -> None:
        super().__init__()
        self.title(APP_NAME)
        self.geometry("760x170")
        self.minsize(620, 150)
        self.configure(fg_color=("#f6f6f4", "#181818"))

        self.events: queue.Queue[tuple[str, object]] = queue.Queue()
        self.process: subprocess.Popen[str] | None = None
        self.analysis_timer: str | None = None
        self.analyzed_url = ""
        self.video_formats: dict[str, dict[str, Any]] = {}
        self.audio_formats: dict[str, dict[str, Any]] = {}
        self.quality_buttons: list[ctk.CTkButton] = []
        self.selected_video = ""
        self.selected_audio = ""
        self.revealed = False
        self.log_open = False

        self.url_var = ctk.StringVar()
        self.mode_var = ctk.StringVar(value="Видео")
        self.output_var = ctk.StringVar(value=str(downloads_dir()))
        self.audio_output_var = ctk.StringVar(value="Оригинал")
        self.playlist_var = ctk.BooleanVar(value=False)
        self.separate_var = ctk.BooleanVar(value=False)
        self.status_var = ctk.StringVar(value="")
        self.title_var = ctk.StringVar(value="")
        self.meta_var = ctk.StringVar(value="")

        self._build()
        self.after(100, self._poll)
        self.protocol("WM_DELETE_WINDOW", self._close)

    def _build(self) -> None:
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        search = ctk.CTkFrame(self, fg_color="transparent")
        search.grid(row=0, column=0, sticky="ew", padx=34, pady=34)
        search.grid_columnconfigure(0, weight=1)
        self.url_entry = ctk.CTkEntry(
            search,
            textvariable=self.url_var,
            height=54,
            corner_radius=14,
            border_width=1,
            placeholder_text="Вставьте ссылку на видео",
            font=ctk.CTkFont(size=16),
        )
        self.url_entry.grid(row=0, column=0, sticky="ew")
        self.url_entry.bind("<KeyRelease>", self._url_changed)
        self.url_entry.bind("<<Paste>>", lambda _event: self.after(50, self._url_changed))
        self.url_entry.bind("<Return>", lambda _event: self._analyze_now())
        self.url_entry.focus_set()

        self.loading = ctk.CTkProgressBar(search, width=70, height=3, mode="indeterminate")

        self.content = ctk.CTkFrame(self, fg_color="transparent")
        self.content.grid_columnconfigure(0, weight=1)

        info = ctk.CTkFrame(self.content, fg_color="transparent")
        info.grid(row=0, column=0, sticky="ew", padx=34)
        info.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            info, textvariable=self.title_var, anchor="w", justify="left",
            font=ctk.CTkFont(size=21, weight="bold"), wraplength=690,
        ).grid(row=0, column=0, sticky="ew")
        ctk.CTkLabel(
            info, textvariable=self.meta_var, anchor="w",
            text_color=("#747474", "#a5a5a5"), font=ctk.CTkFont(size=13),
        ).grid(row=1, column=0, sticky="ew", pady=(4, 0))

        self.mode = ctk.CTkSegmentedButton(
            self.content, values=["Видео", "Аудио"], variable=self.mode_var,
            command=self._mode_changed, height=38, corner_radius=10,
        )
        self.mode.grid(row=1, column=0, sticky="ew", padx=34, pady=(22, 0))

        self.quality_frame = ctk.CTkFrame(self.content, fg_color="transparent")
        self.quality_frame.grid(row=2, column=0, sticky="ew", padx=34, pady=(18, 0))
        for column in range(4):
            self.quality_frame.grid_columnconfigure(column, weight=1, uniform="quality")

        self.audio_options = ctk.CTkFrame(self.content, fg_color="transparent")
        self.audio_options.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            self.audio_options, text="Формат файла", anchor="w",
            text_color=("#747474", "#a5a5a5"),
        ).grid(row=0, column=0, sticky="w", pady=(0, 6))
        self.audio_output = ctk.CTkOptionMenu(
            self.audio_options,
            values=["Оригинал", "mp3", "m4a", "opus", "wav", "flac"],
            variable=self.audio_output_var,
            height=36,
        )
        self.audio_output.grid(row=1, column=0, sticky="ew")

        options = ctk.CTkFrame(self.content, fg_color="transparent")
        options.grid(row=4, column=0, sticky="ew", padx=34, pady=(20, 0))
        options.grid_columnconfigure(1, weight=1)
        self.separate_check = ctk.CTkCheckBox(
            options, text="Скачать видео и аудио отдельно", variable=self.separate_var,
            checkbox_width=20, checkbox_height=20,
        )
        self.separate_check.grid(row=0, column=0, sticky="w")
        self.playlist_check = ctk.CTkCheckBox(
            options, text="Скачать весь плейлист", variable=self.playlist_var,
            checkbox_width=20, checkbox_height=20,
        )
        self.playlist_check.grid(row=0, column=1, sticky="e")

        destination = ctk.CTkFrame(self.content, fg_color="transparent")
        destination.grid(row=5, column=0, sticky="ew", padx=34, pady=(16, 0))
        destination.grid_columnconfigure(0, weight=1)
        self.folder_button = ctk.CTkButton(
            destination, text=self._folder_label(), anchor="w", height=36,
            fg_color="transparent", border_width=1,
            text_color=("#555555", "#c7c7c7"), command=self._choose_folder,
        )
        self.folder_button.grid(row=0, column=0, sticky="ew")

        actions = ctk.CTkFrame(self.content, fg_color="transparent")
        actions.grid(row=6, column=0, sticky="ew", padx=34, pady=(20, 0))
        actions.grid_columnconfigure(0, weight=1)
        self.download_button = ctk.CTkButton(
            actions, text="Скачать", height=48, corner_radius=12,
            font=ctk.CTkFont(size=15, weight="bold"), command=self._download,
        )
        self.download_button.grid(row=0, column=0, sticky="ew")
        self.cancel_button = ctk.CTkButton(
            actions, text="Отмена", width=90, height=48, corner_radius=12,
            fg_color="transparent", border_width=1,
            text_color=("#555555", "#d0d0d0"), command=self._cancel,
        )
        self.status = ctk.CTkLabel(
            actions, textvariable=self.status_var, anchor="w",
            text_color=("#747474", "#a5a5a5"),
        )
        self.status.grid(row=1, column=0, sticky="ew", pady=(8, 0))
        self.progress = ctk.CTkProgressBar(actions, height=7)
        self.progress.set(0)

        footer = ctk.CTkFrame(self.content, fg_color="transparent")
        footer.grid(row=7, column=0, sticky="ew", padx=34, pady=(10, 22))
        footer.grid_columnconfigure(1, weight=1)
        self.log_button = ctk.CTkButton(
            footer, text="Подробности", width=100, height=28,
            fg_color="transparent", text_color=("#666666", "#aaaaaa"),
            hover_color=("#e9e9e6", "#252525"), command=self._toggle_log,
        )
        self.log_button.grid(row=0, column=0, sticky="w")
        self.open_button = ctk.CTkButton(
            footer, text="Открыть папку", width=110, height=28,
            fg_color="transparent", text_color=("#666666", "#aaaaaa"),
            hover_color=("#e9e9e6", "#252525"), command=self._open_folder,
        )

        self.log = ctk.CTkTextbox(
            self.content, height=170, corner_radius=10, wrap="word", font=("Consolas", 11)
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
            messagebox.showerror(APP_NAME, "yt-dlp не найден рядом с программой.")
            return
        self._hide_content()
        self.loading.grid(row=1, column=0, sticky="ew", pady=(7, 0))
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
            self.events.put(("error", stderr.strip() or f"yt-dlp: код {code}"))

    def _apply_analysis(self, url: str, data: dict[str, Any]) -> None:
        if url != self.url_var.get().strip():
            return
        self.analyzed_url = url
        self.title_var.set(str(data.get("title") or "Видео"))
        author = str(data.get("channel") or data.get("uploader") or "")
        length = duration(data.get("duration"))
        self.meta_var.set("  ·  ".join(value for value in (author, length) if value))
        self._prepare_formats(data.get("formats") or [])
        self._reveal_content()
        self._mode_changed(self.mode_var.get())
        self.status_var.set("Готово к скачиванию")

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

        best_video: dict[tuple[int, int], dict[str, Any]] = {}
        for item in video_candidates:
            key = (int(item.get("height") or 0), int(item.get("fps") or 0))
            old = best_video.get(key)
            score = (str(item.get("acodec") or "none") == "none", float(item.get("tbr") or 0))
            old_score = (-1, -1.0) if old is None else (
                str(old.get("acodec") or "none") == "none", float(old.get("tbr") or 0)
            )
            if score > old_score:
                best_video[key] = item

        videos = sorted(best_video.values(), key=lambda x: (int(x.get("height") or 0), float(x.get("fps") or 0)), reverse=True)[:8]
        audios = sorted(audio_candidates, key=lambda x: (float(x.get("abr") or x.get("tbr") or 0), float(x.get("filesize") or 0)), reverse=True)[:8]

        self.video_formats.clear()
        for item in videos:
            height = int(item.get("height") or 0)
            fps = int(item.get("fps") or 0)
            detail = f"{fps} FPS · {codec(item.get('vcodec'))}" if fps else codec(item.get("vcodec"))
            label = f"{height}p\n{detail}"
            self.video_formats[label] = item

        self.audio_formats.clear()
        for item in audios:
            abr = int(float(item.get("abr") or item.get("tbr") or 0))
            label = f"{abr or '?'} кбит/с\n{codec(item.get('acodec'))} · {str(item.get('ext') or '').upper()}"
            if label not in self.audio_formats:
                self.audio_formats[label] = item

        self.selected_video = next(iter(self.video_formats), "")
        self.selected_audio = next(iter(self.audio_formats), "")

    def _render_quality_buttons(self, source: dict[str, dict[str, Any]], selected: str) -> None:
        for button in self.quality_buttons:
            button.destroy()
        self.quality_buttons.clear()
        for index, label in enumerate(source):
            active = label == selected
            button = ctk.CTkButton(
                self.quality_frame,
                text=label,
                height=58,
                corner_radius=10,
                fg_color=("#2783de", "#3b8ed0") if active else ("#ffffff", "#242424"),
                text_color="#ffffff" if active else ("#333333", "#eeeeee"),
                border_width=0 if active else 1,
                border_color=("#dededb", "#3a3a3a"),
                hover_color=("#1f75c5", "#367baa") if active else ("#eeeeeb", "#303030"),
                command=lambda value=label: self._select_quality(value),
            )
            button.grid(row=index // 4, column=index % 4, sticky="ew", padx=4, pady=4)
            self.quality_buttons.append(button)

    def _select_quality(self, label: str) -> None:
        if self.mode_var.get() == "Видео":
            self.selected_video = label
            self._render_quality_buttons(self.video_formats, label)
        else:
            self.selected_audio = label
            self._render_quality_buttons(self.audio_formats, label)

    def _mode_changed(self, mode: str) -> None:
        if not self.revealed:
            return
        if mode == "Видео":
            self.audio_options.grid_remove()
            self.separate_check.grid()
            self._render_quality_buttons(self.video_formats, self.selected_video)
        else:
            self.separate_check.grid_remove()
            self.audio_options.grid(row=3, column=0, sticky="ew", padx=34, pady=(14, 0))
            self._render_quality_buttons(self.audio_formats, self.selected_audio)

    def _reveal_content(self) -> None:
        self.loading.stop()
        self.loading.grid_remove()
        self.content.grid(row=1, column=0, sticky="nsew")
        self.revealed = True
        self.geometry("820x700")
        self.minsize(700, 630)

    def _hide_content(self) -> None:
        self.content.grid_remove()
        self.revealed = False
        self.geometry("760x170")
        self.minsize(620, 150)

    def _download(self) -> None:
        if self.process or self.analyzed_url != self.url_var.get().strip():
            return
        executable = find_tool("yt-dlp")
        if not executable:
            messagebox.showerror(APP_NAME, "yt-dlp не найден рядом с программой.")
            return
        folder = Path(self.output_var.get()).expanduser()
        folder.mkdir(parents=True, exist_ok=True)
        command = self._download_command(executable, folder)
        self.status_var.set("Подготовка…")
        self.progress.set(0)
        self.progress.grid(row=2, column=0, sticky="ew", pady=(10, 0))
        self.download_button.grid_remove()
        self.cancel_button.grid(row=0, column=0, sticky="ew")
        self._log("\nЗапуск загрузки…\n")
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
        separate = self.separate_var.get() and self.mode_var.get() == "Видео"
        template = "%(title)s [%(format_id)s].%(ext)s" if separate else "%(title)s.%(ext)s"
        command = [
            executable,
            self.analyzed_url,
            "--newline",
            "--progress",
            "--windows-filenames",
            "--ffmpeg-location",
            str(app_dir()),
            "--output",
            str(folder / template),
            "--yes-playlist" if self.playlist_var.get() else "--no-playlist",
        ]
        if self.mode_var.get() == "Видео":
            item = self.video_formats.get(self.selected_video, {})
            video_id = str(item.get("format_id") or "bestvideo")
            has_audio = str(item.get("acodec") or "none") != "none"
            if separate:
                selector = f"{video_id},bestaudio" if not has_audio else f"{video_id},bestaudio"
            else:
                selector = video_id if has_audio else f"{video_id}+bestaudio/best"
            command.extend(["--format", selector])
            if not separate:
                command.extend(["--merge-output-format", "mp4"])
        else:
            item = self.audio_formats.get(self.selected_audio, {})
            command.extend(["--format", str(item.get("format_id") or "bestaudio/best")])
            output = self.audio_output_var.get()
            if output != "Оригинал":
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
                    self.status_var.set("Не удалось прочитать ссылку")
                    messagebox.showerror(APP_NAME, str(payload))
                elif event == "line":
                    self._log(str(payload))
                elif event == "progress":
                    value = float(payload)
                    self.progress.set(value / 100)
                    self.status_var.set(f"Скачивание · {value:.1f}%")
                elif event == "finished":
                    self.cancel_button.grid_remove()
                    self.download_button.grid()
                    if int(payload) == 0:
                        self.progress.set(1)
                        self.status_var.set("Готово")
                        self.open_button.grid(row=0, column=2, sticky="e")
                        self._log("Готово.\n")
                    else:
                        self.status_var.set("Ошибка загрузки — откройте подробности")
        except queue.Empty:
            pass
        self.after(100, self._poll)

    def _choose_folder(self) -> None:
        selected = filedialog.askdirectory(initialdir=self.output_var.get())
        if selected:
            self.output_var.set(selected)
            self.folder_button.configure(text=self._folder_label())

    def _folder_label(self) -> str:
        return f"Сохранить в  ·  {self.output_var.get()}"

    def _toggle_log(self) -> None:
        self.log_open = not self.log_open
        if self.log_open:
            self.log.grid(row=8, column=0, sticky="nsew", padx=34, pady=(0, 24))
            self.content.grid_rowconfigure(8, weight=1)
            self.geometry("820x850")
            self.log_button.configure(text="Скрыть подробности")
        else:
            self.log.grid_remove()
            self.content.grid_rowconfigure(8, weight=0)
            self.geometry("820x700")
            self.log_button.configure(text="Подробности")

    def _log(self, text: str) -> None:
        self.log.configure(state="normal")
        self.log.insert("end", text)
        self.log.see("end")
        self.log.configure(state="disabled")

    def _cancel(self) -> None:
        if self.process and self.process.poll() is None:
            self.process.terminate()
            self.status_var.set("Отмена…")

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
