"""Bring a window matching the given title to the foreground and print its rect."""
import sys
import time

import win32con
import win32gui

title_substr = sys.argv[1] if len(sys.argv) > 1 else "MAMBA"

found = []


def cb(hwnd, _):
    if win32gui.IsWindowVisible(hwnd):
        title = win32gui.GetWindowText(hwnd)
        if title_substr.lower() in title.lower():
            found.append((hwnd, title))


win32gui.EnumWindows(cb, None)
for hwnd, title in found:
    print(f"found hwnd={hwnd} title={title!r}")
    try:
        win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
        win32gui.SetForegroundWindow(hwnd)
        time.sleep(0.3)
        rect = win32gui.GetWindowRect(hwnd)
        print(f"  rect={rect}")
    except Exception as e:
        print(f"  error: {e}")
if not found:
    print(f"no window matching {title_substr!r}")
