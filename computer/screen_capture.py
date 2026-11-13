"""Screen capture using mss + Pillow."""
from __future__ import annotations

import time
from pathlib import Path
from typing import Any


class ScreenCapture:
    """Capture the screen (full or region) to a real PNG file."""

    def __init__(self, output_dir: str | Path, security_manager: Any | None = None) -> None:
        self.output_dir = Path(output_dir)
        self._security_manager = security_manager

    def _allowed(self) -> bool:
        if self._security_manager is None:
            return True
        return bool(self._security_manager.is_allowed())

    def _grab(self, monitor: dict, path: str | None) -> dict[str, Any]:
        from mss import mss
        from PIL import Image

        self.output_dir.mkdir(parents=True, exist_ok=True)
        if path is None:
            path = str(self.output_dir / f"screenshot_{int(time.time() * 1000)}.png")
        target = Path(path)
        if not target.is_absolute():
            target = self.output_dir / target
        with mss() as sct:
            shot = sct.grab(monitor)
            img = Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")
        img.save(target)
        # Independent verification: file exists and is a readable image.
        verify = Image.open(target)
        verify.verify()
        size_on_disk = target.stat().st_size
        return {
            "success": True,
            "path": str(target),
            "width": img.width,
            "height": img.height,
            "bytes": size_on_disk,
        }

    def capture_full(self, path: str | None = None, monitor_index: int = 1) -> dict[str, Any]:
        if not self._allowed():
            return {"success": False, "error": "Blocked: security manager disallows control actions"}
        from mss import mss

        with mss() as sct:
            if monitor_index < 1 or monitor_index > len(sct.monitors):
                return {"success": False, "error": f"Invalid monitor index: {monitor_index}"}
            monitor = sct.monitors[monitor_index]
            monitor = dict(monitor)
        return self._grab(monitor, path)


    def capture_region(self, x: int, y: int, width: int, height: int, path: str | None = None) -> dict[str, Any]:
        if not self._allowed():
            return {"success": False, "error": "Blocked: security manager disallows control actions"}
        monitor = {"left": int(x), "top": int(y), "width": int(width), "height": int(height)}
        return self._grab(monitor, path)
