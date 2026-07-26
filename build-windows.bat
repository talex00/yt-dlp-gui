@echo off
setlocal
cd /d "%~dp0"

echo Installing build dependencies...
py -m pip install -r requirements.txt pyinstaller || goto :error

echo Building yt-dlp-gui.exe...
py -m PyInstaller --noconfirm --clean --onefile --windowed --name yt-dlp-gui --collect-all customtkinter app.py || goto :error

echo.
echo Build completed: dist\yt-dlp-gui.exe
echo Copy yt-dlp.exe, ffmpeg.exe and ffprobe.exe into the dist folder.
pause
exit /b 0

:error
echo.
echo Build failed.
pause
exit /b 1
