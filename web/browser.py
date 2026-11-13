"""Open URLs in the system default browser."""
from __future__ import annotations

import re
import webbrowser
from typing import Any


class BrowserController:
    """Navigate the default web browser to a URL."""

    def __init__(self, security_manager: Any | None = None) -> None:
        self._security_manager = security_manager

    def _allowed(self) -> bool:
        if self._security_manager is None:
            return True
        return bool(self._security_manager.is_allowed())

    @staticmethod
    def normalize_url(target: str) -> str:
        target = target.strip()
        if re.match(r"^https?://", target, re.IGNORECASE):
            return target
        if re.match(r"^[\w-]+(\.[\w-]+)+(/.*)?$", target):
            return "https://" + target
        return target

    def open(self, url: str) -> dict[str, Any]:
        if not self._allowed():
            return {"success": False, "error": "Blocked: security manager disallows control actions"}
        normalized = self.normalize_url(url)
        if not re.match(r"^https?://", normalized, re.IGNORECASE):
            return {"success": False, "error": f"Not a valid URL: {url}"}
        try:
            opened = webbrowser.open(normalized)
            return {
                "success": bool(opened),
                "url": normalized,
                "detail": "Opened in default browser" if opened else "browser.open() returned False",
            }
        except Exception as exc:
            return {"success": False, "error": str(exc), "url": normalized}
