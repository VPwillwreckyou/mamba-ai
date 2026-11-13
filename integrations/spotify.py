"""Windows media-session controls for Spotify and Spotify track search."""
from __future__ import annotations

import os
import webbrowser
from typing import Any
from urllib.parse import quote


class SpotifyController:
    """Control the active Spotify media session using Windows media keys."""

    _MEDIA_KEYS = {
        "play_pause": 0xB3,
        "next": 0xB0,
        "previous": 0xB1,
        "volume_up": 0xAF,
        "volume_down": 0xAE,
    }

    def __init__(self, security_manager: Any | None = None) -> None:
        self._security_manager = security_manager

    def status(self) -> dict[str, Any]:
        return {
            "success": True,
            "available": os.name == "nt",
            "detail": "Controls the active Windows media session; Spotify must be open.",
        }

    def control(self, action: str) -> dict[str, Any]:
        if self._security_manager is not None and not self._security_manager.is_allowed():
            return {"success": False, "error": "Blocked by security manager"}
        key = self._MEDIA_KEYS.get(action)
        if key is None:
            return {"success": False, "error": f"Unsupported Spotify action: {action}"}
        if os.name != "nt":
            return {"success": False, "error": "Spotify media controls require Windows"}
        try:
            import ctypes

            keybd_event = ctypes.windll.user32.keybd_event
            keybd_event(key, 0, 0, 0)
            keybd_event(key, 0, 2, 0)
            return {"success": True, "action": action}
        except Exception as exc:
            return {"success": False, "error": f"Media control failed: {exc}"}

    def search(self, query: str) -> dict[str, Any]:
        if self._security_manager is not None and not self._security_manager.is_allowed():
            return {"success": False, "error": "Blocked by security manager"}
        if not query.strip():
            return {"success": False, "error": "Enter a track or artist to search"}
        url = f"https://open.spotify.com/search/{quote(query.strip(), safe='')}"
        try:
            opened = webbrowser.open(url)
            return {
                "success": bool(opened),
                "query": query.strip(),
                "url": url,
                "detail": "Opened Spotify search in the default browser",
            }
        except Exception as exc:
            return {"success": False, "error": str(exc), "url": url}
