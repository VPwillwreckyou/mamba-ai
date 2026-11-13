"""Secret storage for MAMBA.

Single source of truth for storing API keys and other secrets:

1. Windows Credential Manager (via SecurityManager's credential helpers,
   target prefix ``MAMBA:``) - the preferred, OS-protected backend.
2. Read-only fallback to environment variables (``.env`` / process env) for
   keys the user configured outside the UI (e.g. ``GEMINI_API_KEY``).

There is deliberately NO plaintext-file fallback: if the Credential Manager
is unavailable, storing fails closed rather than degrading security.

Values returned here are secrets: never log them, never put them into audit
events, never render them unmasked in the UI, and never send them anywhere
except to the configured AI provider as the ``x-goog-api-key`` auth header
(that is done inside GeminiProvider).
"""
from __future__ import annotations

import os
from typing import Any


class SecretStore:
    """Facade over Windows Credential Manager + environment fallback."""

    ENV_PREFIX = "MAMBA_SECRET_ENV_"  # reserved for future env-backed secrets

    def __init__(self, security_manager: Any) -> None:
        self._sm = security_manager

    # --------------------------------------------------------------- state --
    @property
    def backend(self) -> str:
        """Human-readable backend name for diagnostics (never a secret)."""
        try:
            import win32cred  # noqa: F401
            return "windows_credential_manager"
        except Exception:
            return "unavailable"

    @property
    def available(self) -> bool:
        return self.backend == "windows_credential_manager"

    # ----------------------------------------------------------------- api --
    def store(self, name: str, value: str) -> None:
        """Persist a secret. Raises RuntimeError when no secure backend exists."""
        if not value:
            raise ValueError("Refusing to store an empty secret")
        if not self.available:
            raise RuntimeError(
                "Windows Credential Manager unavailable; refusing to store the "
                "secret in an insecure location"
            )
        self._sm.store_secret_locally(name, value)

    def retrieve(self, name: str, *, env_fallback: str | None = None) -> str | None:
        """Read a secret: Credential Manager first, then an env var (read-only).

        ``env_fallback`` names an environment variable consulted only when the
        credential is absent. Returns None when nothing is configured.
        """
        value = self._sm.retrieve_secret(name)
        if value:
            return value
        if env_fallback:
            env_value = os.getenv(env_fallback)
            if env_value and env_value.strip():
                return env_value.strip()
        return None

    def exists(self, name: str, *, env_fallback: str | None = None) -> bool:
        """True when a secret is configured (value is not read for env checks)."""
        if self._sm.has_secret(name):
            return True
        if env_fallback:
            env_value = os.getenv(env_fallback)
            return bool(env_value and env_value.strip())
        return False

    def delete(self, name: str) -> bool:
        """Remove the stored credential. Env vars cannot be deleted from here."""
        return bool(self._sm.delete_secret(name))


def mask_secret(value: str | None) -> str:
    """Return a display-safe mask: never reveals more than the last 4 chars."""
    if not value:
        return ""
    if len(value) <= 4:
        return "•" * 8
    return "•" * 8 + value[-4:]
