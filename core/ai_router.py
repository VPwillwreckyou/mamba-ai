"""Central AI router: ONLINE/OFFLINE states, fallback, loop protection."""
from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Any

ONLINE_READY = "ONLINE_READY"
ONLINE_PROVIDER_ERROR = "ONLINE_PROVIDER_ERROR"
OFFLINE_LOCAL_READY = "OFFLINE_LOCAL_READY"
OFFLINE_LOCAL_UNAVAILABLE = "OFFLINE_LOCAL_UNAVAILABLE"
SWITCHING_PROVIDER = "SWITCHING_PROVIDER"
MANUAL_LOCAL_MODE = "MANUAL_LOCAL_MODE"

STATE_LABELS = {
    ONLINE_READY: "Online - ready",
    ONLINE_PROVIDER_ERROR: "Online - provider error",
    OFFLINE_LOCAL_READY: "Offline - local ready",
    OFFLINE_LOCAL_UNAVAILABLE: "Offline - local unavailable",
    SWITCHING_PROVIDER: "Switching provider",
    MANUAL_LOCAL_MODE: "Manual local mode",
}


@dataclass
class RouteDecision:
    state: str
    provider_id: str
    model: str
    reason: str
    internet: bool
    ollama_reachable: bool


class AIRouter:
    """Decide which provider serves the next request."""

    def __init__(self, ai_service: Any, connectivity: Any = None,
                 *, switch_cooldown_s: float = 30.0) -> None:
        self.ai_service = ai_service
        if connectivity is None:
            from core.connectivity import ConnectivityManager
            connectivity = ConnectivityManager()
        self.connectivity = connectivity
        self.switch_cooldown_s = switch_cooldown_s
        self._lock = threading.Lock()
        self._state = ONLINE_READY
        self._last_switch_ts = 0.0
        self._consecutive_failures = 0
        self._last_error_code: str | None = None

    @property
    def state(self) -> str:
        with self._lock:
            return self._state

    def decide(self, *, force_refresh: bool = False) -> RouteDecision:
        svc = self.ai_service
        mode = svc.mode
        internet = bool(self.connectivity.has_internet(force=force_refresh))
        try:
            ollama_up = bool(svc.ollama_reachable(force=force_refresh))
        except Exception:
            ollama_up = False
        eff_id = svc.effective_provider_id
        eff_model = svc.effective_model
        if mode == "local":
            st = MANUAL_LOCAL_MODE if internet else (
                OFFLINE_LOCAL_READY if ollama_up else OFFLINE_LOCAL_UNAVAILABLE)
            with self._lock:
                self._state = st
            return RouteDecision(st, "ollama", svc.ollama_model,
                                 "Manual local mode: on-device model.",
                                 internet, ollama_up)
        if not internet:
            if ollama_up or eff_id == "ollama":
                st, reason = OFFLINE_LOCAL_READY, "No internet - local model."
            else:
                st = OFFLINE_LOCAL_UNAVAILABLE
                reason = ("No internet and no local model. Start Ollama or "
                          f"run 'ollama pull {svc.ollama_model}'.")
            with self._lock:
                self._state = st
            return RouteDecision(st, eff_id, eff_model, reason, False, ollama_up)
        if eff_id == "ollama":
            with self._lock:
                self._state = ONLINE_READY
            return RouteDecision(ONLINE_READY, "ollama", eff_model,
                                 "Local model preferred and reachable.",
                                 True, ollama_up)
        cloud_ok = bool(self.connectivity.provider_reachable(eff_id))
        if cloud_ok and self._consecutive_failures == 0:
            with self._lock:
                self._state = ONLINE_READY
            return RouteDecision(ONLINE_READY, eff_id, eff_model,
                                 f"Online via {eff_id}.", True, ollama_up)
        with self._lock:
            self._state = ONLINE_PROVIDER_ERROR
        return RouteDecision(ONLINE_PROVIDER_ERROR, eff_id, eff_model,
                             f"Provider '{eff_id}' issue "
                             f"({self._last_error_code or 'probe failed'}).",
                             True, ollama_up)

    def report_result(self, ok: bool, code: str | None = None) -> None:
        with self._lock:
            if ok:
                self._consecutive_failures = 0
                self._last_error_code = None
            else:
                self._consecutive_failures += 1
                self._last_error_code = code

    def status(self) -> dict:
        d = self.decide()
        return {"state": d.state, "provider": d.provider_id,
                "model": d.model, "reason": d.reason,
                "internet": d.internet, "ollama": d.ollama_reachable,
                "failures": self._consecutive_failures,
                "last_error": self._last_error_code}

