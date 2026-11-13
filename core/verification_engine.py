from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class VerificationResult:
    """Result of an independent verification check."""

    action: str
    passed: bool
    detail: str
    evidence: dict[str, Any] = None


class VerificationEngine:
    """Independent verification for important actions.

    Every significant action should be verified by a separate check, not merely
    by trusting the tool that performed it. This engine provides the common
    verification interface.
    """

    def __init__(self) -> None:
        self.results: list[VerificationResult] = []

    def record(self, result: VerificationResult) -> None:
        self.results.append(result)

    def verify_file_exists(self, path: str, action: str = "file_create") -> VerificationResult:
        import os

        exists = os.path.exists(path)
        return VerificationResult(
            action=action,
            passed=exists,
            detail="File exists" if exists else f"File not found: {path}",
            evidence={"path": path, "exists": exists},
        )

    def verify_file_contains(self, path: str, expected: str, action: str = "file_create") -> VerificationResult:
        import os

        if not os.path.exists(path):
            return VerificationResult(
                action=action,
                passed=False,
                detail=f"File does not exist: {path}",
                evidence={"path": path},
            )
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
        match = expected in content
        return VerificationResult(
            action=action,
            passed=match,
            detail="File content verified" if match else "Expected content not found",
            evidence={"path": path, "contains_expected": match},
        )

    def verify_process_running(self, process_name: str, action: str = "open_application") -> VerificationResult:
        import psutil

        running = any(proc.info["name"] and process_name.lower() in str(proc.info["name"]).lower() for proc in psutil.process_iter(["name"]))
        return VerificationResult(
            action=action,
            passed=running,
            detail=f"Process '{process_name}' running" if running else f"Process '{process_name}' not running",
            evidence={"process": process_name, "running": running},
        )

    def verify_window_visible(self, window_title: str, action: str = "window_focus") -> VerificationResult:
        """Best-effort window visibility check using UI automation."""
        try:
            import win32gui
        except Exception:
            return VerificationResult(
                action=action,
                passed=False,
                detail="UI automation unavailable",
                evidence={"error": "ui_automation_unavailable"},
            )

        found = False
        def callback(hwnd: int, _data: Any) -> None:
            nonlocal found
            if win32gui.IsWindowVisible(hwnd):
                title = win32gui.GetWindowText(hwnd)
                if window_title.lower() in title.lower():
                    found = True
            return True

        win32gui.EnumWindows(callback, None)
        return VerificationResult(
            action=action,
            passed=found,
            detail="Window visible" if found else f"Window not visible: {window_title}",
            evidence={"window_title": window_title, "visible": found},
        )
