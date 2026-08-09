"""PyInstaller runtime hook exposing the physical Windows screen size to Tk.

At 200% Windows scaling Tk may report the 3840x2160 desktop as 1920x1080.
The application then mistakes those logical values for physical pixels and
shrinks CustomTkinter back to almost 100%.  The UI scaling code is explicitly
written in physical pixels, so make Tk's screen metrics match that contract.
"""

from __future__ import annotations

import ctypes
import os
import tkinter


def _physical_primary_screen() -> tuple[int, int]:
    user32 = ctypes.windll.user32
    gdi32 = ctypes.windll.gdi32
    desktop_horzres = 118
    desktop_vertres = 117
    device_context = user32.GetDC(0)
    if not device_context:
        return (0, 0)
    try:
        return (
            int(gdi32.GetDeviceCaps(device_context, desktop_horzres)),
            int(gdi32.GetDeviceCaps(device_context, desktop_vertres)),
        )
    finally:
        user32.ReleaseDC(0, device_context)


if os.name == "nt":
    try:
        physical_width, physical_height = _physical_primary_screen()
        if physical_width > 0 and physical_height > 0:
            tkinter.Misc.winfo_screenwidth = lambda _self: physical_width
            tkinter.Misc.winfo_screenheight = lambda _self: physical_height
    except Exception:
        # Keep Tk's native metrics if the graphics device is unavailable.
        pass
