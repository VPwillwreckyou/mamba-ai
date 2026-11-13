"""MAMBA application settings.

Persists user configuration (AI provider/model, voice, language, wake words,
autonomy) as JSON in ``data/settings.json``. Defaults are seeded from the
existing environment/.env system so both configuration paths stay compatible.

The API key itself is NEVER stored here - it belongs in Windows Credential
Manager (see core/secret_store.py).
"""
from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Any


def _env_str(name: str, default: str) -> str:
    value = os.getenv(name)
    return value.strip() if value and value.strip() else default


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None or not value.strip():
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _env_float(name: str, default: float) -> float:
    value = os.getenv(name)
    try:
        return float(value) if value and value.strip() else default
    except ValueError:
        return default


def default_settings() -> dict[str, Any]:
    """Build the default settings dict, seeded from environment variables."""
    wake_words = _env_str("WAKE_WORDS", "Mamba,Hey Mamba")
    return {
        "ai": {
            "provider": _env_str("AI_PROVIDER", "gemini"),
            "model": _env_str("GEMINI_MODEL", ""),
            # Provider routing mode: local | cloud | auto (cloud online,
            # local Ollama offline).
            "mode": _env_str("AI_MODE", "auto"),
            # Local Ollama model, kept separate from the cloud model.
            "ollama_model": _env_str("OLLAMA_MODEL", "qwen2.5:7b"),
            "fallback_provider": _env_str("AI_FALLBACK_PROVIDER", "groq"),
            "timeout_s": _env_float("AI_TIMEOUT_S", 30.0),
            "retries": 1,
            "retry_backoff_s": 1.0,
        },
        "voice": {
            "enabled": _env_bool("VOICE_ENABLED", True),
            "speech_rate": _env_float("SPEECH_RATE", 1.0),
            "speech_volume": _env_float("SPEECH_VOLUME", 1.0),
            "push_to_talk": _env_bool("PUSH_TO_TALK", False),
            "microphone_index": _env_str("MICROPHONE_INDEX", ""),
        },
        "language": _env_str("DEFAULT_LANGUAGE", "en"),
        "wake_words": [w.strip() for w in wake_words.split(",") if w.strip()],
        "autonomy_mode": _env_str("AUTONOMY_MODE", "maximum"),
    }


class SettingsManager:
    """Load/save MAMBA settings with environment-seeded defaults."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self._lock = threading.Lock()
        self._data: dict[str, Any] = {}
        self.load()

    # ------------------------------------------------------------------ io --
    def load(self) -> dict[str, Any]:
        """Load settings from disk, merged over defaults. Never raises."""
        data = default_settings()
        try:
            if self.path.exists():
                on_disk = json.loads(self.path.read_text(encoding="utf-8"))
                if isinstance(on_disk, dict):
                    data = _deep_merge(data, on_disk)
        except (OSError, ValueError):
            # Corrupt file: fall back to defaults; a later save repairs it.
            pass
        with self._lock:
            self._data = data
        return self._data

    def save(self) -> None:
        """Persist settings to disk. Never writes secrets."""
        with self._lock:
            data = json.loads(json.dumps(self._data))
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
            tmp.replace(self.path)
        except OSError:
            # Saving is best-effort; in-memory settings remain usable.
            pass

    # ----------------------------------------------------------------- api --
    @property
    def data(self) -> dict[str, Any]:
        with self._lock:
            return json.loads(json.dumps(self._data))

    def get(self, dotted: str, default: Any = None) -> Any:
        node: Any = self._data
        for part in dotted.split("."):
            if not isinstance(node, dict) or part not in node:
                return default
            node = node[part]
        return node

    def set(self, dotted: str, value: Any, *, save: bool = True) -> None:
        parts = dotted.split(".")
        with self._lock:
            node = self._data
            for part in parts[:-1]:
                nxt = node.get(part)
                if not isinstance(nxt, dict):
                    nxt = {}
                    node[part] = nxt
                node = nxt
            node[parts[-1]] = value
        if save:
            self.save()


def _deep_merge(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = dict(base)
    for key, value in overlay.items():
        if key in out and isinstance(out[key], dict) and isinstance(value, dict):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = value
    return out
