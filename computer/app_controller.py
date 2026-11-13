"""Open, verify, and close desktop applications on Windows."""
from __future__ import annotations

import shutil
import subprocess
import time
from typing import Any

import psutil

try:
    import win32gui

    WIN32_AVAILABLE = True
except Exception:  # pragma: no cover - non-Windows
    win32gui = None  # type: ignore
    WIN32_AVAILABLE = False

# Common friendly names -> executables resolvable on a stock Windows install.
KNOWN_APPS: dict[str, str] = {
    "notepad": "notepad.exe",
    "calculator": "calc.exe",
    "calc": "calc.exe",
    "explorer": "explorer.exe",
    "file explorer": "explorer.exe",
    "command prompt": "cmd.exe",
    "cmd": "cmd.exe",
    "terminal": "cmd.exe",
    "paint": "mspaint.exe",
    "wordpad": "wordpad.exe",
}


class AppController:
    """Open/close applications and independently verify the result."""

    def __init__(self, security_manager: Any | None = None) -> None:
        self._security_manager = security_manager

    def _allowed(self) -> bool:
        if self._security_manager is None:
            return True
        return bool(self._security_manager.is_allowed())

    def _resolve_executable(self, name: str) -> str | None:
        clean = name.strip().lower().removesuffix(".exe")
        if clean in KNOWN_APPS:
            candidate = KNOWN_APPS[clean]
            if shutil.which(candidate):
                return candidate
        if shutil.which(clean + ".exe"):
            return clean + ".exe"
        if shutil.which(clean):
            return clean
        return None

    def _find_processes(self, exe_name: str) -> list[psutil.Process]:
        matches = []
        for proc in psutil.process_iter(["name", "pid"]):
            try:
                if proc.info["name"] and proc.info["name"].lower() == exe_name.lower():
                    matches.append(proc)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        return matches

    def open_application(self, name: str) -> dict[str, Any]:
        """Launch an application and verify its process/window actually appeared."""
        if not self._allowed():
            return {"success": False, "error": "Blocked: security manager disallows control actions"}

        exe = self._resolve_executable(name)
        if exe is None:
            return {
                "success": False,
                "error": f"Could not resolve application {name!r} to an executable",
            }

        before = {p.pid for p in self._find_processes(exe)}
        try:
            subprocess.Popen(exe, shell=False)
        except Exception as exc:
            return {"success": False, "error": f"Failed to launch {exe}: {exc}", "executable": exe}

        # Wait up to 5 s for a new process to appear.
        new_pid: int | None = None
        for _ in range(25):
            time.sleep(0.2)
            fresh = [p for p in self._find_processes(exe) if p.pid not in before]
            if fresh:
                new_pid = fresh[0].pid
                break
        if new_pid is None:
            return {
                "success": False,
                "error": f"Process {exe} did not appear within 5 s",
                "executable": exe,
            }

        # Independent verification: process is alive.
        try:
            proc_alive = psutil.Process(new_pid).is_running()
        except psutil.Error:
            proc_alive = False

        # Best-effort: a visible window whose title mentions the app.
        window_title = None
        if WIN32_AVAILABLE:
            for _ in range(10):
                window_title = self._find_window_title(exe)
                if window_title:
                    break
                time.sleep(0.2)

        return {
            "success": proc_alive,
            "application": name,
            "executable": exe,
            "pid": new_pid,
            "process_alive": proc_alive,
            "window_title": window_title,
            "verified_by": "psutil process check" + (" + window check" if window_title else ""),
        }

    def _find_window_title(self, exe: str) -> str | None:
        if not WIN32_AVAILABLE:
            return None
        stem = exe.lower().removesuffix(".exe")
        aliases = {"notepad": "notepad", "calc": "calculator", "mspaint": "paint"}
        needles = {stem, aliases.get(stem, stem)}
        found: str | None = None

        def callback(hwnd: int, _data: Any) -> None:
            nonlocal found
            if found or not win32gui.IsWindowVisible(hwnd):
                return
            title = win32gui.GetWindowText(hwnd)
            if not title:
                return
            low = title.lower()
            if any(n in low for n in needles) or stem == "notepad" and "untitled" in low:
                found = title

        win32gui.EnumWindows(callback, None)
        return found

    def close_application(self, name: str) -> dict[str, Any]:
        """Terminate an application by name and verify it is gone."""
        if not self._allowed():
            return {"success": False, "error": "Blocked: security manager disallows control actions"}
        exe = name.strip().lower().removesuffix(".exe") + ".exe"
        victims = self._find_processes(exe)
        if not victims:
            return {"success": False, "error": f"No running process named {exe}"}
        terminated = 0
        for proc in victims:
            try:
                proc.terminate()
                terminated += 1
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        _gone, alive = psutil.wait_procs(victims, timeout=5)
        return {
            "success": len(alive) == 0,
            "application": name,
            "terminated": terminated,
            "still_running": [p.pid for p in alive],
        }

