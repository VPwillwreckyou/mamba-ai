"""Win32 window enumeration, lookup, and focus helpers."""
from __future__ import annotations

import time
from typing import Any

try:
    import win32con
    import win32gui

    WIN32_AVAILABLE = True
except Exception:  # pragma: no cover - non-Windows
    win32con = None  # type: ignore
    win32gui = None  # type: ignore
    WIN32_AVAILABLE = False


class WindowManager:
    """Enumerate and focus top-level windows using the Win32 API."""

    def __init__(self, security_manager: Any | None = None) -> None:
        self._security_manager = security_manager

    def _allowed(self) -> bool:
        if self._security_manager is None:
            return True
        return bool(self._security_manager.is_allowed())

    def list_windows(self) -> list[dict[str, Any]]:
        """Return visible top-level windows with title and geometry."""
        if not WIN32_AVAILABLE:
            return []
        windows: list[dict[str, Any]] = []

        def callback(hwnd: int, _data: Any) -> None:
            if win32gui.IsWindowVisible(hwnd):
                title = win32gui.GetWindowText(hwnd)
                if title:
                    try:
                        rect = win32gui.GetWindowRect(hwnd)
                    except Exception:
                        rect = None
                    windows.append({"hwnd": hwnd, "title": title, "rect": rect})
            return True

        win32gui.EnumWindows(callback, None)
        return windows

    def find_window(self, title_substring: str) -> dict[str, Any] | None:
        """Find the first visible window whose title contains the substring."""
        needle = title_substring.lower()
        for win in self.list_windows():
            if needle in win["title"].lower():
                return win
        return None

    def is_window_visible(self, title_substring: str) -> bool:
        return self.find_window(title_substring) is not None

    def focus_window(self, title_substring: str) -> dict[str, Any]:
        """Bring a window matching the title substring to the foreground."""
        if not self._allowed():
            return {"success": False, "error": "Blocked: security manager disallows control actions"}
        if not WIN32_AVAILABLE:
            return {"success": False, "error": "Win32 API unavailable on this platform"}
        target = self.find_window(title_substring)
        if target is None:
            return {"success": False, "error": f"No visible window matching {title_substring!r}"}
        hwnd = target["hwnd"]
        try:
            win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
            # Attaching to the foreground thread is the reliable way to focus
            # a window when the caller is not already the foreground process.
            foreground = win32gui.GetForegroundWindow()
            if foreground != hwnd:
                win32gui.SetForegroundWindow(hwnd)
            time.sleep(0.2)
            now_foreground = win32gui.GetForegroundWindow() == hwnd
            return {
                "success": now_foreground,
                "hwnd": hwnd,
                "title": target["title"],
                "rect": target["rect"],
                "detail": "Window focused" if now_foreground else "Window raised but not foreground",
            }
        except Exception as exc:
            return {"success": False, "error": str(exc), "hwnd": hwnd, "title": target["title"]}
