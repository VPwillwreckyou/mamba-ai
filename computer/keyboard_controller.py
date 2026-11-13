"""Keyboard control via pyautogui with a Win32 clipboard fallback for Unicode."""
from __future__ import annotations

import time
from typing import Any

import pyautogui

pyautogui.FAILSAFE = True


class KeyboardController:
    """Type text and press key combinations with security gating."""

    def __init__(self, security_manager: Any | None = None) -> None:
        self._security_manager = security_manager

    def _allowed(self) -> bool:
        if self._security_manager is None:
            return True
        return bool(self._security_manager.is_allowed())

    def type_text(self, text: str, interval: float = 0.02) -> dict[str, Any]:
        """Type text into the currently focused window.

        ASCII text is typed key-by-key. Text containing non-ASCII characters is
        pasted through the clipboard (restored afterwards) because pyautogui
        cannot type arbitrary Unicode characters.
        """
        if not self._allowed():
            return {"success": False, "error": "Blocked: security manager disallows control actions"}
        if not text:
            return {"success": False, "error": "No text provided"}
        try:
            if text.isascii():
                pyautogui.write(text, interval=interval)
                method = "keystroke injection"
            else:
                method = self._paste_via_clipboard(text)
            return {
                "success": True,
                "characters": len(text),
                "method": method,
                "typed_text_preview": text[:60],
            }
        except Exception as exc:
            return {"success": False, "error": str(exc)}

    @staticmethod
    def _paste_via_clipboard(text: str) -> str:
        import win32clipboard
        import win32con

        win32clipboard.OpenClipboard()
        try:
            previous = None
            try:
                previous = win32clipboard.GetClipboardData(win32con.CF_UNICODETEXT)
            except Exception:
                previous = None
            win32clipboard.EmptyClipboard()
            win32clipboard.SetClipboardData(win32con.CF_UNICODETEXT, text)
        finally:
            win32clipboard.CloseClipboard()
        time.sleep(0.05)
        pyautogui.hotkey("ctrl", "v")
        time.sleep(0.1)
        if previous is not None:
            win32clipboard.OpenClipboard()
            try:
                win32clipboard.EmptyClipboard()
                win32clipboard.SetClipboardData(win32con.CF_UNICODETEXT, previous)
            finally:
                win32clipboard.CloseClipboard()
        return "clipboard paste"

    def press(self, *keys: str) -> dict[str, Any]:
        """Press keys in sequence, e.g. press('enter') or press('ctrl','s')."""
        if not self._allowed():
            return {"success": False, "error": "Blocked: security manager disallows control actions"}
        if not keys:
            return {"success": False, "error": "No keys provided"}
        try:
            if len(keys) == 1:
                pyautogui.press(keys[0])
            else:
                pyautogui.hotkey(*keys)
            return {"success": True, "keys": list(keys)}
        except Exception as exc:
            return {"success": False, "error": str(exc)}
