"""Terminal execution with real output capture and failure detection."""
from __future__ import annotations

import re
import subprocess
import time
from pathlib import Path
from typing import Any

# Commands that are never executed autonomously (would need explicit user
# confirmation through a trusted channel instead).
DANGEROUS_PATTERNS: list[str] = [
    r"\brm\s+-rf\b",
    r"\b(?:del|erase)\s+/[sfq]\b",
    r"\bformat\s+[a-z]:",
    r"\bdiskpart\b",
    r"\bshutdown\b",
    r"\bRemove-Item\b.*(-Recurse\s+-Force|-Force\s+-Recurse)",
    r"\b(?:rmdir|rd)\s+/s\b",
    r"\b(?:clear-disk|format-volume|remove-partition)\b",
    r"\bmkfs\b",
    r"\bdd\s+if=",
    r":\(\)\s*\{.*\|.*&\s*\}",  # fork bomb
]

FAILURE_MARKERS = [
    "traceback (most recent call last)",
    "syntaxerror",
    "nameerror",
    "importerror",
    "modulenotfounderror",
    "assertionerror",
    "failed",
    "fatal error",
    "build failed",
    "tests failed",
    "nok:",
    "error:",
]


class Terminal:
    """Run shell commands and return *real* captured output.

    Returns success strictly from the process exit code and flags likely
    failures in the output text so callers can diagnose builds/tests.
    """

    def __init__(
        self,
        cwd: str | Path | None = None,
        security_manager: Any | None = None,
        default_timeout: int = 60,
    ) -> None:
        self.cwd = str(cwd) if cwd else None
        self._security_manager = security_manager
        self.default_timeout = default_timeout

    def _allowed(self) -> bool:
        if self._security_manager is None:
            return True
        return bool(self._security_manager.is_allowed())

    @staticmethod
    def is_dangerous(command: str) -> bool:
        return any(re.search(p, command, re.IGNORECASE) for p in DANGEROUS_PATTERNS)

    def run(self, command: str, timeout: int | None = None,
            allow_dangerous: bool = False) -> dict[str, Any]:
        """Run a shell command.

        ``allow_dangerous`` may only be set by the trusted confirmation path
        (user clicked Yes in the confirmation dialog); it is never derived from
        AI output alone.
        """
        if not self._allowed():
            return {"success": False, "error": "Blocked: security manager disallows control actions"}
        if not command or not command.strip():
            return {"success": False, "error": "Empty command"}
        if self.is_dangerous(command) and not allow_dangerous:
            return {
                "success": False,
                "blocked": True,
                "error": "Dangerous command refused (requires explicit user confirmation)",
                "command": command,
            }
        timeout = timeout or self.default_timeout
        start = time.time()
        try:
            proc = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                errors="replace",
                timeout=timeout,
                cwd=self.cwd,
                check=False,
            )
            duration = round(time.time() - start, 3)
            stdout = proc.stdout or ""
            stderr = proc.stderr or ""
            combined = (stdout + "\n" + stderr).lower()
            markers = [m for m in FAILURE_MARKERS if m in combined]
            return {
                "success": proc.returncode == 0,
                "command": command,
                "returncode": proc.returncode,
                "stdout": stdout,
                "stderr": stderr,
                "duration_s": duration,
                "failure_markers": markers,
                "detected_failure": proc.returncode != 0 or bool(markers),
            }
        except subprocess.TimeoutExpired:
            return {
                "success": False,
                "command": command,
                "error": f"Command timed out after {timeout}s",
            }
        except (OSError, subprocess.SubprocessError, TypeError, ValueError) as exc:
            return {"success": False, "command": command, "error": str(exc)}
