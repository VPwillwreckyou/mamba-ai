"""Connectivity detection: internet vs Wi-Fi, bounded probes, cached state.

Distinguishes:
- local Wi-Fi/link presence (best-effort) from real internet reachability,
- cloud provider reachability from generic internet reachability.

All probes are bounded (timeouts), cached (no spam), and never raise.
Used by the AI router to decide ONLINE vs OFFLINE routing.
"""
from __future__ import annotations

import socket
import threading
import time

# Lightweight, highly-available HTTPS endpoints used only for
# reachability probes (no data is sent - just TCP connect).
PROBE_HOSTS: tuple[tuple[str, int], ...] = (
    ("8.8.8.8", 53),          # Google DNS - UDP/TCP 53, very reliable
    ("1.1.1.1", 443),         # Cloudflare - HTTPS
    ("www.google.com", 443),
)

# Cloud AI endpoints probed to decide provider-specific availability.
PROVIDER_HOSTS: dict[str, tuple[str, int]] = {
    "gemini": ("generativelanguage.googleapis.com", 443),
    "openai": ("api.openai.com", 443),
    "anthropic": ("api.anthropic.com", 443),
    "groq": ("api.groq.com", 443),
    "deepseek": ("api.deepseek.com", 443),
    "openrouter": ("openrouter.ai", 443),
    "ollama": ("127.0.0.1", 11434),
}


def tcp_reachable(host: str, port: int, timeout: float = 3.0) -> bool:
    """Bounded TCP connect probe. Never raises."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except Exception:
        return False


def internet_reachable(*, timeout: float = 3.0) -> bool:
    """True when at least one public probe host is reachable."""
    for host, port in PROBE_HOSTS:
        if tcp_reachable(host, port, timeout=timeout):
            return True
    return False


class ConnectivityManager:
    """Cached connectivity state: internet + per-provider reachability.

    - Probes are bounded and cached (default TTL 15s) to avoid spam.
    - Never raises; failures degrade to "unreachable".
    - Thread-safe.
    """

    def __init__(self, *, ttl: float = 15.0, timeout: float = 3.0) -> None:
        self.ttl = ttl
        self.timeout = timeout
        self._lock = threading.Lock()
        self._internet: tuple[float, bool] | None = None
        self._providers: dict[str, tuple[float, bool]] = {}
        self._last_change_ts: float = 0.0
        self._last_internet: bool | None = None

    def _fresh(self, cached: tuple[float, bool] | None) -> bool:
        return cached is not None and (time.monotonic() - cached[0]) < self.ttl

    def has_internet(self, *, force: bool = False) -> bool:
        with self._lock:
            cached = self._internet
            if not force and self._fresh(cached):
                assert cached is not None
                return cached[1]
        reachable = internet_reachable(timeout=self.timeout)
        with self._lock:
            if self._last_internet is not None and self._last_internet != reachable:
                self._last_change_ts = time.monotonic()
            self._last_internet = reachable
            self._internet = (time.monotonic(), reachable)
        return reachable

    def provider_reachable(self, provider_id: str, *, force: bool = False) -> bool:
        pid = (provider_id or "").strip().lower()
        host = PROVIDER_HOSTS.get(pid)
        if host is None:
            # Unknown provider: fall back to generic internet state.
            return self.has_internet(force=force)
        with self._lock:
            cached = self._providers.get(pid)
            if not force and self._fresh(cached):
                assert cached is not None
                return cached[1]
        reachable = tcp_reachable(host[0], host[1], timeout=self.timeout)
        with self._lock:
            self._providers[pid] = (time.monotonic(), reachable)
        return reachable

    def snapshot(self) -> dict:
        """UI-safe snapshot (no secrets)."""
        internet = self.has_internet()
        return {
            "internet": internet,
            "last_change_s_ago": round(time.monotonic() - self._last_change_ts, 1)
            if self._last_change_ts else None,
            "ttl_s": self.ttl,
        }
