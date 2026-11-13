"""Mouse control via pyautogui with security gating."""
from __future__ import annotations

from typing import Any

import pyautogui

pyautogui.FAILSAFE = True


class MouseController:
    """Move and click the mouse; all actions gated by the security manager."""

    def __init__(self, security_manager: Any | None = None) -> None:
        self._security_manager = security_manager

    def _allowed(self) -> bool:
        if self._security_manager is None:
            return True
        return bool(self._security_manager.is_allowed())

    def position(self) -> dict[str, Any]:
        x, y = pyautogui.position()
        return {"success": True, "x": int(x), "y": int(y)}

    def move_to(self, x: int, y: int, duration: float = 0.2) -> dict[str, Any]:
        if not self._allowed():
            return {"success": False, "error": "Blocked: security manager disallows control actions"}
        try:
            pyautogui.moveTo(int(x), int(y), duration=duration)
            nx, ny = pyautogui.position()
            return {
                "success": (int(nx), int(ny)) == (int(x), int(y)),
                "requested": {"x": int(x), "y": int(y)},
                "actual": {"x": int(nx), "y": int(ny)},
            }
        except Exception as exc:
            return {"success": False, "error": str(exc)}

    def click(
        self,
        x: int | None = None,
        y: int | None = None,
        button: str = "left",
        clicks: int = 1,
    ) -> dict[str, Any]:
        if not self._allowed():
            return {"success": False, "error": "Blocked: security manager disallows control actions"}
        try:
            if x is None or y is None:
                pyautogui.click(button=button, clicks=clicks)
                nx, ny = pyautogui.position()
            else:
                pyautogui.click(int(x), int(y), button=button, clicks=clicks)
                nx, ny = int(x), int(y)
            return {"success": True, "button": button, "clicks": clicks, "at": {"x": nx, "y": ny}}
        except Exception as exc:
            return {"success": False, "error": str(exc)}

    def scroll(
        self,
        direction: str = "down",
        amount: int = 3,
        x: int | None = None,
        y: int | None = None,
    ) -> dict[str, Any]:
        """Scroll the wheel; amount is clamped to a sane range."""
        if not self._allowed():
            return {"success": False, "error": "Blocked: security manager disallows control actions"}
        direction = str(direction).lower()
        if direction not in ("up", "down"):
            return {"success": False, "error": f"Invalid scroll direction: {direction}"}
        clicks = max(1, min(int(amount), 20)) * (1 if direction == "up" else -1)
        try:
            if x is None or y is None:
                pyautogui.scroll(clicks)
            else:
                pyautogui.scroll(clicks, int(x), int(y))
            return {"success": True, "direction": direction, "clicks": int(clicks)}
        except Exception as exc:
            return {"success": False, "error": str(exc)}
