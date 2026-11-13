"""AI service: provider registry, secure key resolution, real connection tests.

This module owns the bridge between MAMBA's brain and its configured AI
provider. It never fakes success: ``test_connection()`` performs an actual
minimal API request and classifies the real outcome.

Provider architecture (extensible without touching the AI brain):

    AIProvider (core/ai_provider.py)
      -> GeminiProvider           (registered below as "gemini")
      -> future providers         (add one ProviderSpec to PROVIDER_REGISTRY)

Secrets handling rules enforced here:
  * the API key is read from Windows Credential Manager first, then from the
    environment (``GEMINI_API_KEY``) as a read-only fallback;
  * every error message leaving this module is passed through ``redact()``
    so the key can never appear in UI text, logs, or audit events;
  * the key is only ever handed to the provider object that needs it for
    authentication - it is never included in prompts.
"""
from __future__ import annotations

import asyncio
import hashlib
import os
import re
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import httpx

from core.ai_provider import (
    AIProvider,
    AnthropicProvider,
    GeminiProvider,
    OllamaModelMissingError,
    OllamaNotRunningError,
    OllamaProvider,
    OpenAICompatibleProvider,
)
from core.connectivity import ConnectivityManager
from core.secret_store import SecretStore, mask_secret

# ------------------------------------------------------------ status codes --
CONNECTED = "connected"
INVALID_KEY = "invalid_key"
NETWORK_ERROR = "network_error"
PROVIDER_ERROR = "provider_error"
CONFIG_ERROR = "config_error"
RATE_LIMITED = "rate_limited"

# Rate-limit signals live outside _NETWORK_PATTERNS on purpose: a 429 means
# "back off and optionally fall back", not "the network is down". Retrying
# immediately or rerouting as a network failure would make throttling worse.

# ----------------------------------------------------------- routing modes --
# The AI "mode" is the top-level Local/Cloud/Automatic selector. It decides
# which provider actually serves requests, independent of the granular
# per-provider choice used for the cloud fallback.
MODE_LOCAL = "local"      # always the local Ollama server (offline)
MODE_CLOUD = "cloud"      # always the configured cloud provider (Groq)
MODE_AUTO = "auto"        # prefer configured cloud online, Ollama offline
AI_MODES = (MODE_LOCAL, MODE_CLOUD, MODE_AUTO)

MODE_LABELS = {
    MODE_LOCAL: "Local (Ollama)",
    MODE_CLOUD: "Cloud (Groq)",
    MODE_AUTO: "Automatic",
}

# The cloud provider used by Cloud and Automatic modes when no other cloud
# provider has been explicitly configured.
DEFAULT_CLOUD_PROVIDER = "groq"

OLLAMA_BASE_URL = "http://localhost:11434"

# Sidebar/status states
STATE_NOT_CONFIGURED = "not_configured"
STATE_UNVERIFIED = "configured_unverified"
STATE_ONLINE = "online"
STATE_ERROR = "error"

STATE_LABELS = {
    STATE_NOT_CONFIGURED: "AI PROVIDER NOT CONFIGURED",
    STATE_UNVERIFIED: "AI PROVIDER CONFIGURED - NOT VERIFIED",
    STATE_ONLINE: "AI ONLINE",
    STATE_ERROR: "AI PROVIDER ERROR",
}

RESULT_LABELS = {
    CONNECTED: "Connected",
    INVALID_KEY: "Invalid API key",
    NETWORK_ERROR: "Network error",
    PROVIDER_ERROR: "Provider error",
    CONFIG_ERROR: "Configuration error",
    RATE_LIMITED: "Rate limited",
}


class AIServiceError(RuntimeError):
    """AI failure with a classified, safe-to-display code and message."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class ProviderSpec:
    """Static description of one AI provider implementation."""

    id: str
    label: str
    default_model: str
    models: tuple[str, ...]
    key_credential: str   # Windows Credential Manager name (MAMBA:<name>)
    key_env: str          # env/.env variable read-only fallback
    factory: Callable[..., AIProvider]
    requires_api_key: bool = True

    def build(self, api_key: str, model: str | None,
              timeout: float | None = None) -> AIProvider:
        try:
            if timeout is None:
                return self.factory(api_key, model or self.default_model or None)
            return self.factory(api_key, model or self.default_model or None,
                                timeout=timeout)
        except TypeError:
            return self.factory(api_key, model or self.default_model or None)


GEMINI_MODELS: tuple[str, ...] = (
    "gemini-1.5-flash",
    "gemini-1.5-pro",
    "gemini-2.0-flash",
    "gemini-2.5-flash",
    "gemini-2.5-pro",
)


def _compatible_factory(base_url: str) -> Callable[..., AIProvider]:
    def _build(api_key: str, model: str | None = None,
               timeout: float = 30.0) -> OpenAICompatibleProvider:
        return OpenAICompatibleProvider(
            api_key, model=model or "", base_url=base_url, timeout=timeout)
    return _build


def _ollama_factory(api_key: str, model: str | None = None,
                    timeout: float = 120.0) -> OllamaProvider:
    """Build a native local Ollama provider (no API key, offline)."""
    return OllamaProvider(model or OllamaProvider.DEFAULT_MODEL,
                          base_url=OLLAMA_BASE_URL, timeout=timeout)

PROVIDER_REGISTRY: dict[str, ProviderSpec] = {
    "gemini": ProviderSpec(
        id="gemini",
        label="Google Gemini",
        default_model="gemini-1.5-flash",
        models=GEMINI_MODELS,
        key_credential="GEMINI_API_KEY",
        key_env="GEMINI_API_KEY",
        factory=lambda api_key, model=None: GeminiProvider(api_key, model=model),
    ),
    "openai": ProviderSpec(
        id="openai", label="OpenAI", default_model="gpt-4o-mini",
        models=("gpt-4o-mini", "gpt-4o", "gpt-4.1-mini"),
        key_credential="OPENAI_API_KEY", key_env="OPENAI_API_KEY",
        factory=_compatible_factory("https://api.openai.com/v1"),
    ),
    "anthropic": ProviderSpec(
        id="anthropic", label="Anthropic Claude",
        default_model="claude-3-5-haiku-latest",
        models=("claude-3-5-haiku-latest", "claude-3-7-sonnet-latest",
                "claude-sonnet-4-20250514"),
        key_credential="ANTHROPIC_API_KEY", key_env="ANTHROPIC_API_KEY",
        factory=lambda api_key, model=None: AnthropicProvider(
            api_key, model=model or "claude-3-5-haiku-latest"
        ),
    ),
    "groq": ProviderSpec(
        id="groq", label="Groq", default_model="openai/gpt-oss-120b",
        models=("openai/gpt-oss-120b", "openai/gpt-oss-20b"),
        key_credential="GROQ_API_KEY", key_env="GROQ_API_KEY",
        factory=_compatible_factory("https://api.groq.com/openai/v1"),
    ),
    "ollama": ProviderSpec(
        id="ollama", label="Ollama (local)", default_model="qwen2.5:7b",
        models=("qwen2.5:7b", "qwen2.5:3b", "llama3.2", "llama3.1", "mistral"),
        key_credential="", key_env="",
        factory=_ollama_factory,
        requires_api_key=False,
    ),
    "deepseek": ProviderSpec(
        id="deepseek", label="DeepSeek", default_model="deepseek-chat",
        models=("deepseek-chat", "deepseek-reasoner"),
        key_credential="DEEPSEEK_API_KEY", key_env="DEEPSEEK_API_KEY",
        factory=_compatible_factory("https://api.deepseek.com/v1"),
    ),
    "openrouter": ProviderSpec(
        id="openrouter", label="OpenRouter",
        default_model="openai/gpt-4o-mini",
        models=("openai/gpt-4o-mini", "anthropic/claude-3.5-sonnet",
                "google/gemini-2.5-flash"),
        key_credential="OPENROUTER_API_KEY", key_env="OPENROUTER_API_KEY",
        factory=_compatible_factory("https://openrouter.ai/api/v1"),
    ),
}


def available_providers() -> list[ProviderSpec]:
    return list(PROVIDER_REGISTRY.values())


class AIService:
    """Owns provider configuration, key resolution, testing and chat routing."""

    def __init__(self, settings: Any, secret_store: SecretStore,
                 security_manager: Any | None = None,
                 connectivity: Any | None = None) -> None:
        self.settings = settings
        self.secret_store = secret_store
        self._security = security_manager
        self.connectivity = connectivity if connectivity is not None else ConnectivityManager()
        self._lock = threading.Lock()
        self._provider: AIProvider | None = None
        self._provider_fingerprint: str | None = None
        self._verified = False
        self._last_result: ConnectionResult | None = None
        # Cached local-Ollama reachability probe: (monotonic_ts, reachable).
        self._ollama_cache: tuple[float, bool] | None = None
        self._ollama_ttl = 10.0
        self._router: Any | None = None

    # ---------------------------------------------------------- config api --
    @property
    def provider_id(self) -> str:
        pid = str(self.settings.get("ai.provider", "gemini") or "gemini").strip().lower()
        return pid if pid in PROVIDER_REGISTRY else "gemini"

    @property
    def spec(self) -> ProviderSpec:
        return PROVIDER_REGISTRY[self.provider_id]

    @property
    def model(self) -> str:
        model = str(self.settings.get("ai.model", "") or "").strip()
        return model or self.spec.default_model

    # ------------------------------------------------------- routing (mode) --
    @property
    def mode(self) -> str:
        """Top-level provider mode: local | cloud | auto (defaults to auto)."""
        value = str(self.settings.get("ai.mode", MODE_AUTO) or MODE_AUTO).strip().lower()
        return value if value in AI_MODES else MODE_AUTO

    @property
    def mode_label(self) -> str:
        return MODE_LABELS.get(self.mode, self.mode)

    @property
    def ollama_model(self) -> str:
        """The local model used by Ollama (independent of the cloud model)."""
        model = str(self.settings.get("ai.ollama_model", "") or "").strip()
        return model or PROVIDER_REGISTRY["ollama"].default_model

    @property
    def cloud_provider_id(self) -> str:
        """The cloud provider used by Cloud and Automatic fallback."""
        pid = self.provider_id
        if pid != "ollama" and PROVIDER_REGISTRY[pid].requires_api_key:
            return pid
        return DEFAULT_CLOUD_PROVIDER

    def ollama_reachable(self, *, timeout: float = 2.0, force: bool = False) -> bool:
        """Best-effort, cached probe of the local Ollama server.

        Used by Automatic mode to decide local vs. cloud. Never raises; a probe
        failure simply means "local not available right now".
        """
        import time
        now = time.monotonic()
        with self._lock:
            cached = self._ollama_cache
        if not force and cached is not None and (now - cached[0]) < self._ollama_ttl:
            return cached[1]
        reachable = False
        try:
            resp = httpx.get(f"{OLLAMA_BASE_URL}/api/version", timeout=timeout)
            reachable = resp.status_code == 200
        except (httpx.HTTPError, OSError, TypeError, ValueError):
            reachable = False
        with self._lock:
            self._ollama_cache = (now, reachable)
        return reachable

    def list_ollama_models(self, *, timeout: float = 5.0) -> list[str]:
        """Return installed Ollama model names (empty when unreachable).

        Never raises and never triggers a download. Used by the settings UI
        to offer only models that are actually installed, and by offline
        checks to explain what must be installed.
        """
        try:
            resp = httpx.get(f"{OLLAMA_BASE_URL}/api/tags", timeout=timeout)
            if resp.status_code != 200:
                return []
            data = resp.json() or {}
            models = data.get("models") or []
            names = [str(m.get("name", "")).strip() for m in models
                     if isinstance(m, dict)]
            return [n for n in names if n]
        except (AttributeError, httpx.HTTPError, OSError, TypeError, ValueError):
            return []

    @property
    def effective_provider_id(self) -> str:
        """Resolve which provider actually serves requests for the current mode.

        - local : always Ollama (offline, never touches the cloud)
        - cloud : always the configured cloud provider (Groq by default)
        - auto  : configured cloud provider online, Ollama offline
        """
        mode = self.mode
        if mode == MODE_LOCAL:
            return "ollama"
        if mode == MODE_CLOUD:
            return self.cloud_provider_id
        if self.connectivity.has_internet() and self._cloud_provider_has_key():
            return self.cloud_provider_id
        return "ollama" if self.ollama_reachable() else self.cloud_provider_id

    def _cloud_provider_has_key(self) -> bool:
        spec = PROVIDER_REGISTRY[self.cloud_provider_id]
        if not spec.requires_api_key:
            return True
        return self.secret_store.exists(
            spec.key_credential, env_fallback=spec.key_env
        )

    @property
    def effective_spec(self) -> ProviderSpec:
        return PROVIDER_REGISTRY[self.effective_provider_id]

    @property
    def effective_model(self) -> str:
        if self.effective_provider_id == "ollama":
            return self.ollama_model
        return self.model

    def effective_api_key(self) -> str | None:
        """Resolve the API key for the effective provider (None for Ollama)."""
        spec = self.effective_spec
        if not spec.requires_api_key:
            return None
        return self.secret_store.retrieve(spec.key_credential,
                                          env_fallback=spec.key_env)

    @property
    def fallback_provider_id(self) -> str:
        """Configured fallback cloud provider (validated, never Ollama-loop)."""
        raw = str(self.settings.get("ai.fallback_provider", "groq") or "groq")
        pid = raw.strip().lower()
        if pid not in PROVIDER_REGISTRY:
            return DEFAULT_CLOUD_PROVIDER
        if pid == "ollama":
            return DEFAULT_CLOUD_PROVIDER
        return pid

    def _request_timeout(self) -> float:
        try:
            value = float(self.settings.get("ai.timeout_s", 30.0) or 30.0)
        except (TypeError, ValueError):
            return 30.0
        return min(max(value, 5.0), 300.0)

    def _request_retries(self) -> int:
        try:
            value = int(self.settings.get("ai.retries", 1) or 1)
        except (TypeError, ValueError):
            return 1
        return min(max(value, 0), 3)

    def _retry_backoff(self) -> float:
        try:
            value = float(self.settings.get("ai.retry_backoff_s", 1.0) or 1.0)
        except (TypeError, ValueError):
            return 1.0
        return min(max(value, 0.0), 10.0)

    def set_mode(self, mode: str) -> None:
        """Persist the provider mode and reset cached runtime state."""
        value = str(mode).strip().lower()
        if value not in AI_MODES:
            raise ValueError(f"Unsupported AI mode: {mode}")
        self.settings.set("ai.mode", value)
        self._reset_runtime()
        self._log("ai_mode_set", f"AI provider mode set to {value}")

    def api_key(self) -> str | None:
        """Resolve the configured API key (Credential Manager -> env)."""
        if not self.spec.requires_api_key:
            return None
        return self.secret_store.retrieve(
            self.spec.key_credential, env_fallback=self.spec.key_env
        )

    def has_api_key(self) -> bool:
        if not self.spec.requires_api_key:
            return False
        return self.secret_store.exists(
            self.spec.key_credential, env_fallback=self.spec.key_env
        )

    def is_configured(self) -> bool:
        """Whether the provider that will actually serve requests is usable.

        Local mode needs no key (Ollama); Cloud mode needs the cloud key;
        Automatic is usable when local Ollama is reachable, or when internet
        and credentials are available for the selected cloud provider.
        """
        mode = self.mode
        if mode == MODE_LOCAL:
            return True
        if mode == MODE_CLOUD:
            return self.has_api_key()
        return (self.ollama_reachable()
            or (self.connectivity.has_internet()
                and self._cloud_provider_has_key()))

    def key_hint(self) -> str:
        """Masked representation of the key - never the key itself."""
        return mask_secret(self.api_key())

    def configure(self, *, api_key: str | None = None,
                  provider: str | None = None, model: str | None = None,
                  mode: str | None = None) -> None:
        """Validate and persist configuration; resets cached runtime state.

        Raises ValueError on invalid input and RuntimeError when no secure
        storage backend is available for the key.
        """
        if provider is not None:
            pid = provider.strip().lower()
            if pid not in PROVIDER_REGISTRY:
                raise ValueError(f"Unsupported AI provider: {provider}")
            self.settings.set("ai.provider", pid)
        if mode is not None:
            value = str(mode).strip().lower()
            if value not in AI_MODES:
                raise ValueError(f"Unsupported AI mode: {mode}")
            self.settings.set("ai.mode", value)
        if model is not None:
            # Keep the local (Ollama) model separate from the cloud model so
            # switching modes never leaves a mismatched model string behind.
            if self.provider_id == "ollama":
                self.settings.set("ai.ollama_model", model.strip())
            else:
                self.settings.set("ai.model", model.strip())
        if api_key is not None:
            if not self.spec.requires_api_key:
                raise ValueError(f"{self.spec.label} does not require an API key")
            key = api_key.strip()
            if not key:
                raise ValueError("API key is empty")
            if len(key) < 10:
                raise ValueError("API key looks too short to be valid")
            self.secret_store.store(self.spec.key_credential, key)
            # Keep the process environment consistent with the stored secret
            # so env-based consumers see the same configuration.
            os.environ[self.spec.key_env] = key
        self._reset_runtime()
        self._log("ai_provider_configured",
                  f"AI provider configured: {self.provider_id} / {self.model} "
                  f"(key storage: {self.secret_store.backend})")

    def clear_key(self) -> bool:
        """Remove the stored API key (Credential Manager + process env)."""
        if not self.spec.requires_api_key:
            return False
        removed = self.secret_store.delete(self.spec.key_credential)
        os.environ.pop(self.spec.key_env, None)
        self._reset_runtime()
        self._log("ai_provider_key_removed",
                  "AI provider API key removed from secure storage")
        return removed

    def _reset_runtime(self) -> None:
        with self._lock:
            self._provider = None
            self._provider_fingerprint = None
            self._verified = False
            self._last_result = None

    # ------------------------------------------------------------ runtime ---
    @staticmethod
    def _fingerprint(key: str) -> str:
        return hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]

    def build_provider(self) -> AIProvider:
        """Construct (or reuse) the provider that will actually serve requests.

        The provider is chosen by the active mode (Local/Cloud/Automatic), so
        Local mode always yields the offline Ollama provider. Automatic mode
        uses the cloud provider online and Ollama offline. If neither internet
        nor local Ollama is available, it raises a classified network error.
        """
        if (self.mode == MODE_AUTO
                and not self.connectivity.has_internet()
                and not self.ollama_reachable()):
            raise AIServiceError(
                NETWORK_ERROR,
                "No internet connection is available and local Ollama is not "
                "running. Start Ollama and install the selected local model "
                "to use AI offline.",
            )
        spec = self.effective_spec
        provider_id = self.effective_provider_id
        model = self.effective_model
        key = self.effective_api_key()
        if spec.requires_api_key and not key:
            raise AIServiceError(
                CONFIG_ERROR,
                "No API key configured. Open INTEGRATIONS > AI PROVIDER and "
                f"save a {spec.label} API key first.",
            )
        key = key or ""
        timeout = self._request_timeout()
        fingerprint = self._fingerprint(f"{provider_id}:{model}:{key}:{timeout}")
        with self._lock:
            if self._provider is not None and self._provider_fingerprint == fingerprint:
                return self._provider
        try:
            provider = spec.build(key, model, timeout=timeout)
        except AIServiceError:
            raise
        except Exception as exc:  # dependency missing / bad arguments
            raise AIServiceError(
                CONFIG_ERROR, redact(f"Provider initialization failed: {exc}", key)
            ) from None
        with self._lock:
            self._provider = provider
            self._provider_fingerprint = fingerprint
        return provider

    def provider_or_none(self) -> AIProvider | None:
        try:
            return self.build_provider()
        except AIServiceError:
            return None

    # ------------------------------------------------------------- status ---
    @property
    def verified(self) -> bool:
        return self._verified

    @property
    def last_result(self) -> ConnectionResult | None:
        return self._last_result

    def state(self) -> str:
        if not self.is_configured():
            return STATE_NOT_CONFIGURED
        if self._last_result is not None and not self._last_result.ok:
            return STATE_ERROR
        if self._verified:
            return STATE_ONLINE
        return STATE_UNVERIFIED

    def status(self) -> dict[str, Any]:
        """UI-safe status snapshot - contains no secret values."""
        state = self.state()
        eff_id = self.effective_provider_id
        return {
            "state": state,
            "label": STATE_LABELS[state],
            "provider": self.provider_id,
            "provider_label": self.spec.label,
            "model": self.model,
            "configured": self.is_configured(),
            "key_hint": self.key_hint(),
            "verified": self._verified,
            "key_storage": self.secret_store.backend,
            "last_result": self._last_result,
            # Routing (mode) information for the settings UI.
            "mode": self.mode,
            "mode_label": self.mode_label,
            "effective_provider": eff_id,
            "effective_provider_label": PROVIDER_REGISTRY[eff_id].label,
            "effective_model": self.effective_model,
            "ollama_reachable": self.ollama_reachable(),
        }

    # --------------------------------------------------------------- test ---
    def test_connection(self, timeout: float = 20.0,
                        api_key: str | None = None) -> ConnectionResult:
        """Perform a REAL minimal API request and classify the outcome.

        Never reports success without a genuine provider response.
        Safe to call from a worker thread. When ``api_key`` is provided it is
        tested instead of the stored key (the stored key is not modified and
        verification state is only updated for stored-key tests).
        """
        started = time.monotonic()
        # Test the provider that will ACTUALLY serve requests for the active
        # mode (Local -> Ollama, Cloud -> Groq, Automatic -> whichever is live).
        provider_id = self.effective_provider_id
        spec = self.effective_spec
        model = self.effective_model
        override = (api_key or "").strip()
        key = override or self.effective_api_key() or ""

        def finish(ok: bool, code: str, message: str,
                   detail: str = "") -> ConnectionResult:
            result = ConnectionResult(
                ok=ok, code=code, message=redact(message, key),
                detail=redact(detail, key),
                latency_ms=int((time.monotonic() - started) * 1000),
                provider=provider_id, model=model,
            )
            with self._lock:
                self._last_result = result
                if ok and not override:
                    # Only stored-key successes flip the global verified flag.
                    self._verified = True
                elif not ok and code == INVALID_KEY and not override:
                    self._verified = False
            self._log(
                "ai_connection_test",
                f"AI connection test: {result.label} ({provider_id}/{model}, "
                f"{result.latency_ms} ms) {result.message}"[:400],
            )
            return result

        if spec.requires_api_key and not key:
            return finish(False, CONFIG_ERROR,
                          f"No API key configured for {spec.label}.")
        try:
            if override:
                provider = spec.build(key, model)
            else:
                provider = self.build_provider()
        except AIServiceError as exc:
            return finish(False, exc.code, str(exc))
        except Exception as exc:
            return finish(False, CONFIG_ERROR,
                          f"Provider initialization failed: {redact(exc, key)}")

        box: dict[str, Any] = {}

        def work() -> None:
            try:
                box["text"] = asyncio.run(
                    provider.chat("Reply with the single word: OK")
                )
            except BaseException as exc:  # noqa: BLE001 - classified below
                box["error"] = exc

        # Local models can take a while to load on first use; give Ollama a
        # more generous window so a cold start is not reported as a timeout.
        effective_timeout = max(timeout, 120.0) if provider_id == "ollama" else timeout
        worker = threading.Thread(target=work, name="mamba-ai-test", daemon=True)
        worker.start()
        worker.join(effective_timeout)
        if worker.is_alive():
            if provider_id == "ollama":
                return finish(
                    False, NETWORK_ERROR,
                    f"Ollama did not answer within {effective_timeout:.0f}s. "
                    "The model may still be loading - try again.",
                )
            return finish(
                False, NETWORK_ERROR,
                f"The provider did not answer within {effective_timeout:.0f}s - "
                "check your internet connection.",
            )
        if "error" in box:
            exc = box["error"]
            # Surface Ollama's specific, actionable failures directly.
            if isinstance(exc, OllamaNotRunningError):
                return finish(False, NETWORK_ERROR, str(exc))
            if isinstance(exc, OllamaModelMissingError):
                return finish(False, PROVIDER_ERROR, str(exc))
            code = classify_error(exc)
            raw = redact(exc, key)
            if code == INVALID_KEY:
                msg = f"The API key was rejected by {spec.label}: {raw[:200]}"
            elif code == NETWORK_ERROR:
                msg = f"Network error while reaching {spec.label}: {raw[:200]}"
            else:
                model_hint = ""
                if (re.search(r"NOT_FOUND|not found", raw, re.IGNORECASE)
                        and re.search(r"model", raw, re.IGNORECASE)):
                    model_hint = (f" The model '{model}' was not accepted - "
                                  "try another model in the selector.")
                msg = f"{spec.label} returned an error: {raw[:200]}{model_hint}"
            return finish(False, code, msg)

        text = str(box.get("text") or "").strip()
        if not text:
            return finish(False, PROVIDER_ERROR,
                          f"{spec.label} responded without any usable text.")
        excerpt = text if len(text) <= 60 else text[:57] + "..."
        return finish(True, CONNECTED,
                      f"Connected to {spec.label}",
                      detail=f"Provider reply: {excerpt}")

    def _record_success(self, provider_id: str, model: str) -> None:
        with self._lock:
            self._verified = True
            self._last_result = ConnectionResult(
                ok=True, code=CONNECTED, message="Connected",
                provider=provider_id, model=model,
            )

    def _record_failure(self, code: str, safe: str, provider_id: str,
                        model: str) -> None:
        with self._lock:
            self._last_result = ConnectionResult(
                ok=False, code=code, message=safe,
                provider=provider_id, model=model,
            )
            if code == INVALID_KEY:
                self._verified = False
        self._log("ai_request_failed",
                  f"AI request failed ({code}): {safe}"[:400])

    async def _single_attempt(self, prompt: str, *,
                              system_prompt: str | None,
                              messages: list[dict[str, Any]] | None,
                              provider: AIProvider, key: str | None,
                              provider_id: str, model: str,
                              timeout: float) -> str:
        try:
            coro = (provider.chat(prompt, system_prompt=system_prompt,
                                  messages=messages)
                    if messages and isinstance(provider, OllamaProvider)
                    else provider.chat(prompt, system_prompt=system_prompt))
            return await asyncio.wait_for(asyncio.ensure_future(coro),
                                          timeout=timeout)
        except OllamaNotRunningError as exc:
            safe = str(exc)
            self._record_failure(NETWORK_ERROR, safe, provider_id, model)
            raise AIServiceError(NETWORK_ERROR, safe) from None
        except OllamaModelMissingError as exc:
            safe = str(exc)
            self._record_failure(PROVIDER_ERROR, safe, provider_id, model)
            raise AIServiceError(PROVIDER_ERROR, safe) from None
        except asyncio.TimeoutError as exc:
            safe = (f"The provider did not answer within {timeout:.0f}s - "
                    "check your connection or raise ai.timeout_s.")
            self._record_failure(NETWORK_ERROR, safe, provider_id, model)
            raise AIServiceError(NETWORK_ERROR, safe) from exc
        except Exception as exc:
            code = classify_error(exc)
            safe = redact(exc, key)
            self._record_failure(code, safe, provider_id, model)
            raise AIServiceError(code, safe) from None

    def _fallback_local_provider(self, failed_id: str) -> AIProvider | None:
        """Build Ollama as an offline fallback in Automatic mode only."""
        if self.mode != MODE_AUTO or failed_id == "ollama":
            return None
        if not self.ollama_reachable(force=True):
            return None
        return PROVIDER_REGISTRY["ollama"].build("", self.ollama_model)

    def _fallback_provider_for(self, failed_id: str) -> AIProvider | None:
        """Build the fallback cloud provider (None when not applicable)."""
        if self.mode == MODE_LOCAL:
            return None  # manual local mode never leaves the device
        if failed_id == "ollama":
            return None  # callers handle ollama->cloud via effective routing
        cand = self.fallback_provider_id
        if cand == failed_id:
            return None
        spec = PROVIDER_REGISTRY[cand]
        key = self.secret_store.retrieve(spec.key_credential,
                                         env_fallback=spec.key_env)
        if spec.requires_api_key and not key:
            return None
        return spec.build(key or "", self.model or spec.default_model)
    # --------------------------------------------------------------- chat ---
    async def chat(self, prompt: str, *, system_prompt: str | None = None,
                   messages: list[dict[str, Any]] | None = None) -> str:
        """Send a prompt with timeout, retry, and configured fallback.

        Retry applies to transient network/provider errors only (never to
        invalid keys or config errors), with backoff between attempts. When
        the primary cloud provider keeps failing, one fallback-provider
        attempt is made if a usable fallback is configured. Every failure is
        classified and redacted; success marks the provider verified.
        """
        provider = self.build_provider()
        key = self.effective_api_key()
        provider_id = self.effective_provider_id
        model = self.effective_model
        timeout = self._request_timeout()
        retries = self._request_retries()
        backoff = self._retry_backoff()
        last_err: AIServiceError | None = None
        for attempt in range(retries + 1):
            try:
                text = await self._single_attempt(
                    prompt, system_prompt=system_prompt, messages=messages,
                    provider=provider, key=key, provider_id=provider_id,
                    model=model, timeout=timeout)
                self._record_success(provider_id, model)
                return text
            except AIServiceError as exc:
                last_err = exc
                # Never retry auth/config problems; never delay after final try.
                if exc.code in (INVALID_KEY, CONFIG_ERROR):
                    raise
                if attempt < retries:
                    await asyncio.sleep(backoff * (attempt + 1))
                    continue
                if exc.code == NETWORK_ERROR:
                    local = self._fallback_local_provider(provider_id)
                    if local is not None:
                        local_model = self.ollama_model
                        try:
                            text = await self._single_attempt(
                                prompt, system_prompt=system_prompt,
                                messages=messages, provider=local, key=None,
                                provider_id="ollama", model=local_model,
                                timeout=max(timeout, 120.0))
                            self._record_success("ollama", local_model)
                            self._log(
                                "ai_fallback_used",
                                f"Local Ollama served request after {provider_id} "
                                "failed (network_error)",
                            )
                            return text
                        except AIServiceError as local_error:
                            raise local_error from None
                # Primary exhausted: one fallback attempt for transient faults.
                if exc.code in (NETWORK_ERROR, PROVIDER_ERROR, RATE_LIMITED):
                    fallback = self._fallback_provider_for(provider_id)
                    if fallback is not None:
                        try:
                            text = await self._single_attempt(
                                prompt, system_prompt=system_prompt,
                                messages=None, provider=fallback, key=None,
                                provider_id=self.fallback_provider_id,
                                model=self.model, timeout=timeout)
                            self._record_success(self.fallback_provider_id,
                                                 self.model)
                            self._log("ai_fallback_used",
                                      f"Fallback {self.fallback_provider_id} "
                                      f"served request after {provider_id} "
                                      f"failed ({exc.code})")
                            return text
                        except AIServiceError as fexc:
                            raise fexc from None
                raise
        assert last_err is not None
        raise last_err

    async def chat_stream(self, prompt: str, *,
                          system_prompt: str | None = None):
        """Yield streamed chunks from the effective provider.

        Streams with an overall timeout; any streaming failure degrades
        honestly to one non-streamed reply (which carries the classified
        router error) so the UI never goes silent.
        """
        provider = self.build_provider()
        provider_id = self.effective_provider_id
        model = self.effective_model
        timeout = self._request_timeout() + 60.0
        try:
            async def _collect():
                out: list[str] = []
                async for chunk in provider.chat_stream(
                        prompt, system_prompt=system_prompt):
                    out.append(chunk)
                return out
            chunks = await asyncio.wait_for(_collect(), timeout=timeout)
            for chunk in chunks:
                yield chunk
            self._record_success(provider_id, model)
        except Exception as exc:
            code = classify_error(exc)
            self._record_failure(code, redact(exc, self.effective_api_key()),
                                 provider_id, model)
            yield await self.chat(prompt, system_prompt=system_prompt)

    # -------------------------------------------------------------- util ---
    def _log(self, event: str, detail: str) -> None:
        """Audit-log an AI lifecycle event. Never pass secrets into detail."""
        if self._security is None:
            return
        try:
            self._security.log_event(event=event, detail=detail)
        except Exception:
            pass


# ------------------------------------------------------------- redaction ---
_KEY_RE = re.compile(r"AIza[0-9A-Za-z_\-]{20,}")

_INVALID_KEY_PATTERNS = (
    re.compile(r"API_KEY_INVALID", re.IGNORECASE),
    re.compile(r"API key not valid", re.IGNORECASE),
    re.compile(r"API key[^.\n]{0,40}invalid", re.IGNORECASE),
    re.compile(r"PERMISSION_DENIED", re.IGNORECASE),
    re.compile(r"UNAUTHENTICATED", re.IGNORECASE),
    re.compile(r"invalid authentication credentials", re.IGNORECASE),
    re.compile(r"unauthenticated", re.IGNORECASE),
    re.compile(r"permission denied", re.IGNORECASE),
)

_NETWORK_PATTERNS = (
    re.compile(r"timed? ?out", re.IGNORECASE),
    re.compile(r"connection (refused|reset|aborted|error)", re.IGNORECASE),
    re.compile(r"connect(timeout|error)", re.IGNORECASE),
    re.compile(r"read(timeout|error)", re.IGNORECASE),
    re.compile(r"temporary failure in name resolution", re.IGNORECASE),
    re.compile(r"(getaddrinfo|name or service not known)", re.IGNORECASE),
    re.compile(r"network is unreachable", re.IGNORECASE),
    re.compile(r"nodename nor servname", re.IGNORECASE),
    re.compile(r"proxyerror", re.IGNORECASE),
    re.compile(r"ssl\b.*(error|failed|handshake)", re.IGNORECASE),
    re.compile(r"all connection attempts failed", re.IGNORECASE),
    re.compile(r"failed to establish a new connection", re.IGNORECASE),
    re.compile(r"max retries exceeded", re.IGNORECASE),
    re.compile(r"socket\.gaierror", re.IGNORECASE),
    re.compile(r"certificate verify failed", re.IGNORECASE),
)

_RATE_LIMIT_PATTERNS = (
    re.compile(r"rate.?limit", re.IGNORECASE),
    re.compile(r"\b429\b"),
    re.compile(r"too many requests", re.IGNORECASE),
    re.compile(r"quota exceeded", re.IGNORECASE),
)


def redact(text: Any, *secrets: str | None) -> str:
    """Strip secret values and Gemini-key-shaped tokens from any message."""
    result = str(text)
    for secret in secrets:
        if secret:
            result = result.replace(secret, "***")
    return _KEY_RE.sub("***", result)


def _walk_cause_chain(exc: BaseException) -> list[BaseException]:
    chain: list[BaseException] = []
    seen: set[int] = set()
    node: BaseException | None = exc
    while node is not None and id(node) not in seen:
        chain.append(node)
        seen.add(id(node))
        node = node.__cause__ or node.__context__
    return chain


def _status_code_of(exc: BaseException) -> int | None:
    """Find an HTTP status code anywhere in the cause chain."""
    for node in _walk_cause_chain(exc):
        code = getattr(node, "code", None)
        if isinstance(code, int):
            return code
        response = getattr(node, "response", None)
        status = getattr(response, "status_code", None)
        if isinstance(status, int):
            return status
    return None


def classify_error(exc: BaseException) -> str:
    """Map a real provider/network exception to a stable result code."""
    status = _status_code_of(exc)
    if status in (401, 403):
        return INVALID_KEY
    if status == 429:
        return RATE_LIMITED
    blob = redact(" ".join(str(n) for n in _walk_cause_chain(exc)))
    if any(p.search(blob) for p in _INVALID_KEY_PATTERNS):
        return INVALID_KEY
    if any(p.search(blob) for p in _RATE_LIMIT_PATTERNS):
        return RATE_LIMITED
    if isinstance(exc, ValueError) and "API key" in str(exc):
        return CONFIG_ERROR
    if any(p.search(blob) for p in _NETWORK_PATTERNS):
        return NETWORK_ERROR
    # 404/400 usually mean bad model name or malformed request - the request
    # reached the API, so report it as a provider-side error.
    return PROVIDER_ERROR


@dataclass
class ConnectionResult:
    """Outcome of one real connection test (safe to display/log)."""

    ok: bool
    code: str
    message: str
    detail: str = ""
    latency_ms: int = 0
    provider: str = ""
    model: str = ""

    @property
    def label(self) -> str:
        return RESULT_LABELS.get(self.code, self.code)
