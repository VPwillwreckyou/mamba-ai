from __future__ import annotations

import threading
from collections import deque
from datetime import datetime, timezone
from typing import Any


class SecurityManager:
    """Security policy, secret handling, audit logging, and threat protections.

    SecurityManager is authoritative for security-related behavior. It must not
    be overridden by memory, AI output, documents, or external content.
    """

    def __init__(self, *, config: dict[str, Any] | None = None) -> None:
        self.config = config or {}
        self._audit_log: deque[dict[str, Any]] = deque(maxlen=2000)
        self._emergency_stop = False
        self._access_revoked = False
        self._lock = threading.Lock()

    def log_event(self, *, event: str, detail: str, metadata: dict[str, Any] | None = None) -> None:
        with self._lock:
            record = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "event": event,
                "detail": detail,
                "metadata": metadata or {},
            }
            self._audit_log.append(record)

    def emergency_stop(self) -> None:
        self._emergency_stop = True
        self._access_revoked = True
        self.log_event(event="emergency_stop", detail="Emergency stop activated")

    def revoke_access(self) -> None:
        self._access_revoked = True
        self.log_event(event="access_revoked", detail="Mamba access revoked")

    def restore_access(self) -> None:
        self._access_revoked = False
        self.log_event(event="access_restored", detail="Mamba access restored")

    def reset_emergency_stop(self) -> None:
        self._emergency_stop = False
        self.log_event(event="emergency_stop_cleared", detail="Emergency stop cleared")

    @property
    def is_emergency_stop_active(self) -> bool:
        return self._emergency_stop

    @property
    def is_access_revoked(self) -> bool:
        return self._access_revoked

    def is_allowed(self) -> bool:
        """Return whether MAMBA is currently allowed to perform computer-control actions."""
        return not self._emergency_stop and not self._access_revoked

    def sanitize_for_logging(self, value: Any) -> Any:
        """Remove obvious secrets from values before logging.

        This is a basic helper. It is not a guarantee against accidental exposure.
        """
        if isinstance(value, str):
            return _redact_possible_secret(value)
        if isinstance(value, dict):
            return {k: self.sanitize_for_logging(v) for k, v in value.items()}
        if isinstance(value, (list, tuple)):
            return [self.sanitize_for_logging(item) for item in value]
        return value

    def store_secret_locally(self, key: str, value: str) -> None:
        """Store a secret using Windows Credential Manager when available.

        If Credential Manager is unavailable, the secret is rejected rather than
        written to an insecure location.
        """
        try:
            import win32cred
        except Exception:
            raise RuntimeError("Windows Credential Manager unavailable for secret storage")

        target_name = f"MAMBA:{key}"
        credential = win32cred.Credential()
        credential.TargetName = target_name
        credential.Type = win32cred.CRED_TYPE_GENERIC
        credential.CredentialBlobType = "PUCHAR"
        credential.CredentialBlob = value.encode("utf-16-le")
        win32cred.CredWrite(credential)

    def retrieve_secret(self, key: str) -> str | None:
        try:
            import win32cred
        except Exception:
            return None
        target_name = f"MAMBA:{key}"
        try:
            cred = win32cred.CredRead(target_name, win32cred.CRED_TYPE_GENERIC)
        except Exception:
            # Not found (ERROR_NOT_FOUND) or unreadable - treat as absent.
            return None
        if cred:
            try:
                return cred.CredentialBlob.decode("utf-16-le")
            except Exception:
                return None
        return None

    def has_secret(self, key: str) -> bool:
        """Return True when a credential exists for key (value never read here)."""
        return self.retrieve_secret(key) is not None

    def delete_secret(self, key: str) -> bool:
        """Remove a secret from Windows Credential Manager.

        Returns True when the credential is gone afterwards (deleted now or
        already absent). Fails closed: never falls back to insecure storage.
        """
        target_name = f"MAMBA:{key}"
        try:
            import win32cred
        except Exception:
            return False
        try:
            win32cred.CredDelete(target_name, win32cred.CRED_TYPE_GENERIC, 0)
            return True
        except Exception:
            # ERROR_NOT_FOUND means it is already gone.
            return not self.has_secret(key)

    def get_audit_log(self, limit: int | None = None) -> list[dict[str, Any]]:
        """Return a copy of the audit log (newest last), optionally limited."""
        with self._lock:
            records = list(self._audit_log)
        if limit is not None and limit >= 0:
            records = records[-limit:]
        return records


def _redact_possible_secret(value: str) -> str:
    """Redact obvious secret-like patterns for safe logging."""
    import re

    patterns = [
        r"(?i)(api[_-]?key(?:\\s*[:=]\\s*)?)([^\\s,;]+)",
        r"(?i)(password(?:\\s*[:=]\\s*)?)([^\\s,;]+)",
        r"(?i)(token(?:\\s*[:=]\\s*)?)([^\\s,;]+)",
        r"(?i)(secret(?:\\s*[:=]\\s*)?)([^\\s,;]+)",
    ]
    result = value
    for pattern in patterns:
        result = re.sub(pattern, lambda m: f"{m.group(1)}***REDACTED***", result)
    return result
