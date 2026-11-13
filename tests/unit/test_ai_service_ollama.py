from __future__ import annotations

import asyncio
import time

import pytest

from core.ai_provider import (
    OllamaModelMissingError,
    OllamaNotRunningError,
    OllamaProvider,
    OpenAICompatibleProvider,
)
from core.ai_service import (
    CONNECTED,
    MODE_AUTO,
    MODE_CLOUD,
    MODE_LOCAL,
    NETWORK_ERROR,
    PROVIDER_ERROR,
    AIService,
)


class FakeSettings:
    """Minimal settings stub mirroring SettingsManager's dotted get/set."""

    def __init__(self, provider: str = "ollama", model: str = "qwen2.5:7b",
                 mode: str = MODE_LOCAL, ollama_model: str = "qwen2.5:7b") -> None:
        self.values = {
            "ai.provider": provider,
            "ai.model": model,
            "ai.mode": mode,
            "ai.ollama_model": ollama_model,
        }

    def get(self, key: str, default=None):
        return self.values.get(key, default)

    def set(self, key: str, value: str) -> None:
        self.values[key] = value


class FakeSecretStore:
    backend = "test"

    def retrieve(self, name: str, *, env_fallback: str | None = None) -> str | None:
        return None

    def exists(self, name: str, *, env_fallback: str | None = None) -> bool:
        return False

    def store(self, name: str, value: str) -> None:
        raise AssertionError("Ollama should not store an API key")

    def delete(self, name: str) -> bool:
        return False


class FakeGroqSecretStore(FakeSecretStore):
    def retrieve(self, name: str, *, env_fallback: str | None = None) -> str | None:
        return "test-groq-api-key" if name == "GROQ_API_KEY" else None

    def exists(self, name: str, *, env_fallback: str | None = None) -> bool:
        return name == "GROQ_API_KEY"


class FakeConnectivity:
    def __init__(self, internet: bool) -> None:
        self.internet = internet

    def has_internet(self, *, force: bool = False) -> bool:
        return self.internet


# ---------------------------------------------------------------------------
# Local (Ollama) configuration
# ---------------------------------------------------------------------------
def test_ollama_is_configured_without_an_api_key() -> None:
    service = AIService(FakeSettings(mode=MODE_LOCAL), FakeSecretStore())

    assert service.is_configured()
    assert not service.has_api_key()
    provider = service.build_provider()
    assert isinstance(provider, OllamaProvider)
    # Native Ollama endpoint (NOT the OpenAI-compatible /v1 shim).
    assert provider.base_url == "http://localhost:11434"
    assert provider.model == "qwen2.5:7b"


def test_local_mode_resolves_to_ollama_even_with_a_groq_key() -> None:
    # Local mode must never touch the cloud, even when a Groq key exists.
    service = AIService(FakeSettings(provider="groq", mode=MODE_LOCAL),
                        FakeGroqSecretStore())

    assert service.effective_provider_id == "ollama"
    provider = service.build_provider()
    assert isinstance(provider, OllamaProvider)


def test_ollama_native_chat_payload_and_no_auth(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class FakeResponse:
        status_code = 200

        def raise_for_status(self) -> None:
            pass

        def json(self) -> dict[str, object]:
            return {"message": {"role": "assistant", "content": "OK"}}

    def fake_post(url, *, json, timeout):
        captured.update(url=url, json=json, timeout=timeout)
        return FakeResponse()

    monkeypatch.setattr("httpx.post", fake_post)
    provider = OllamaProvider("qwen2.5:7b")

    text = asyncio.run(provider.chat("Hello"))

    assert text == "OK"
    assert captured["url"] == "http://localhost:11434/api/chat"
    payload = captured["json"]
    assert payload["model"] == "qwen2.5:7b"
    assert payload["stream"] is False
    assert payload["messages"] == [{"role": "user", "content": "Hello"}]


@pytest.mark.parametrize("provider_kind", ["ollama", "openai-compatible"])
def test_chat_keeps_event_loop_responsive(monkeypatch, provider_kind: str) -> None:
    loop_responsive = asyncio.Event()
    request_observed_responsive_loop = False

    class FakeResponse:
        status_code = 200

        def raise_for_status(self) -> None:
            pass

        def json(self) -> dict[str, object]:
            if provider_kind == "ollama":
                return {"message": {"content": "OK"}}
            return {"choices": [{"message": {"content": "OK"}}]}

    def fake_post(url, **kwargs):
        nonlocal request_observed_responsive_loop
        time.sleep(0.05)
        request_observed_responsive_loop = loop_responsive.is_set()
        return FakeResponse()

    monkeypatch.setattr("httpx.post", fake_post)
    if provider_kind == "ollama":
        provider = OllamaProvider("qwen2.5:7b")
    else:
        provider = OpenAICompatibleProvider(
            "test-key", model="test-model", base_url="https://example.test/v1")

    async def exercise() -> None:
        async def mark_loop_responsive() -> None:
            await asyncio.sleep(0.01)
            loop_responsive.set()

        heartbeat = asyncio.create_task(mark_loop_responsive())
        assert await provider.chat("Hello") == "OK"
        await heartbeat

    asyncio.run(exercise())

    assert request_observed_responsive_loop


def test_ollama_supports_conversation_history(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class FakeResponse:
        status_code = 200

        def raise_for_status(self) -> None:
            pass

        def json(self) -> dict[str, object]:
            return {"message": {"role": "assistant", "content": "Hi again"}}

    def fake_post(url, *, json, timeout):
        captured.update(json=json)
        return FakeResponse()

    monkeypatch.setattr("httpx.post", fake_post)
    provider = OllamaProvider("qwen2.5:7b")

    history = [
        {"role": "user", "content": "My name is Ada."},
        {"role": "assistant", "content": "Nice to meet you, Ada."},
        {"role": "user", "content": "What is my name?"},
    ]
    asyncio.run(provider.chat("What is my name?", system_prompt="Be brief.",
                              messages=history))

    messages = captured["json"]["messages"]
    # A system turn is prepended and the full history is preserved.
    assert messages[0] == {"role": "system", "content": "Be brief."}
    assert messages[1:] == history


def test_ollama_connection_test_uses_native_endpoint(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class FakeResponse:
        status_code = 200

        def raise_for_status(self) -> None:
            pass

        def json(self) -> dict[str, object]:
            return {"message": {"content": "OK"}}

    def fake_post(url, *, json, timeout):
        captured.update(url=url, json=json)
        return FakeResponse()

    monkeypatch.setattr(AIService, "ollama_reachable", lambda self, **k: True)
    monkeypatch.setattr("httpx.post", fake_post)
    service = AIService(FakeSettings(mode=MODE_LOCAL), FakeSecretStore())

    result = service.test_connection(timeout=2)

    assert result.ok
    assert result.code == CONNECTED
    assert captured["url"] == "http://localhost:11434/api/chat"
    assert captured["json"]["model"] == "qwen2.5:7b"
    assert service.status()["configured"] is True


def test_ollama_not_running_surfaces_clear_error(monkeypatch) -> None:
    import httpx

    def boom(url, **kwargs):
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr("httpx.post", boom)
    service = AIService(FakeSettings(mode=MODE_LOCAL), FakeSecretStore())

    result = service.test_connection(timeout=2)

    assert not result.ok
    assert result.code == NETWORK_ERROR
    assert "Ollama" in result.message
    assert "ollama serve" in result.message


def test_ollama_model_missing_surfaces_clear_error(monkeypatch) -> None:
    class FakeResponse:
        status_code = 404

        def raise_for_status(self) -> None:
            pass

        def json(self) -> dict[str, object]:
            return {"error": "model 'qwen2.5:7b' not found"}

    monkeypatch.setattr("httpx.post", lambda url, **kwargs: FakeResponse())
    service = AIService(FakeSettings(mode=MODE_LOCAL), FakeSecretStore())

    result = service.test_connection(timeout=2)

    assert not result.ok
    assert result.code == PROVIDER_ERROR
    assert "ollama pull" in result.message


# ---------------------------------------------------------------------------
# Cloud (Groq) configuration - preserved
# ---------------------------------------------------------------------------
def test_groq_provider_uses_hosted_api() -> None:
    service = AIService(
        FakeSettings("groq", "openai/gpt-oss-120b", mode=MODE_CLOUD),
        FakeGroqSecretStore(),
    )

    provider = service.build_provider()

    assert isinstance(provider, OpenAICompatibleProvider)
    assert provider.base_url == "https://api.groq.com/openai/v1"
    assert provider.model == "openai/gpt-oss-120b"


# ---------------------------------------------------------------------------
# Automatic routing
# ---------------------------------------------------------------------------
def test_auto_prefers_cloud_when_online_even_if_ollama_is_reachable(monkeypatch) -> None:
    monkeypatch.setattr(AIService, "ollama_reachable", lambda self, **k: True)
    service = AIService(
        FakeSettings("groq", "openai/gpt-oss-120b", mode=MODE_AUTO),
        FakeGroqSecretStore(),
        connectivity=FakeConnectivity(internet=True),
    )

    assert service.effective_provider_id == "groq"
    assert isinstance(service.build_provider(), OpenAICompatibleProvider)


def test_auto_prefers_ollama_when_offline(monkeypatch) -> None:
    monkeypatch.setattr(AIService, "ollama_reachable", lambda self, **k: True)
    service = AIService(
        FakeSettings("groq", "openai/gpt-oss-120b", mode=MODE_AUTO),
        FakeGroqSecretStore(),
        connectivity=FakeConnectivity(internet=False),
    )

    assert service.effective_provider_id == "ollama"
    assert isinstance(service.build_provider(), OllamaProvider)


def test_auto_restores_cloud_selection_when_connectivity_returns(monkeypatch) -> None:
    monkeypatch.setattr(AIService, "ollama_reachable", lambda self, **k: True)
    connectivity = FakeConnectivity(internet=False)
    service = AIService(
        FakeSettings("groq", "openai/gpt-oss-120b", mode=MODE_AUTO),
        FakeGroqSecretStore(),
        connectivity=connectivity,
    )

    assert service.effective_provider_id == "ollama"
    connectivity.internet = True
    assert service.effective_provider_id == "groq"


def test_auto_falls_back_to_cloud_when_ollama_down(monkeypatch) -> None:
    monkeypatch.setattr(AIService, "ollama_reachable", lambda self, **k: False)
    service = AIService(
        FakeSettings("groq", "openai/gpt-oss-120b", mode=MODE_AUTO),
        FakeGroqSecretStore(),
        connectivity=FakeConnectivity(internet=True),
    )

    assert service.effective_provider_id == "groq"
    provider = service.build_provider()
    assert isinstance(provider, OpenAICompatibleProvider)
    assert provider.base_url == "https://api.groq.com/openai/v1"


def test_auto_without_ollama_and_without_key_is_not_configured(monkeypatch) -> None:
    monkeypatch.setattr(AIService, "ollama_reachable", lambda self, **k: False)
    service = AIService(
        FakeSettings("groq", "openai/gpt-oss-120b", mode=MODE_AUTO),
        FakeSecretStore(),
        connectivity=FakeConnectivity(internet=False),
    )

    assert service.effective_provider_id == "groq"
    assert not service.is_configured()
    from core.ai_service import AIServiceError
    with pytest.raises(AIServiceError) as error:
        service.build_provider()
    assert error.value.code == NETWORK_ERROR


def test_auto_falls_back_to_ollama_after_cloud_network_failure(monkeypatch) -> None:
    import httpx

    settings = FakeSettings("groq", "openai/gpt-oss-120b", mode=MODE_AUTO)
    settings.values["ai.retries"] = 0
    settings.values["ai.timeout_s"] = 5
    service = AIService(settings, FakeGroqSecretStore(),
                        connectivity=FakeConnectivity(internet=True))
    monkeypatch.setattr(
        AIService, "ollama_reachable",
        lambda self, *, force=False, **kwargs: force,
    )
    requests: list[tuple[str, dict[str, object]]] = []

    class FakeResponse:
        status_code = 200

        def raise_for_status(self) -> None:
            pass

        def json(self) -> dict[str, object]:
            return {"message": {"role": "assistant", "content": "Local reply"}}

    def fake_post(url, **kwargs):
        if url.startswith("http://localhost:11434"):
            requests.append((url, kwargs["json"]))
            return FakeResponse()
        raise httpx.ConnectError("network is unreachable")

    monkeypatch.setattr("httpx.post", fake_post)
    history = [
        {"role": "user", "content": "Remember this detail."},
        {"role": "assistant", "content": "I will."},
    ]

    reply = asyncio.run(service.chat("Continue", messages=history))

    assert reply == "Local reply"
    assert len(requests) == 1
    assert requests[0][0] == "http://localhost:11434/api/chat"
    assert requests[0][1]["messages"] == history
    assert service.last_result.provider == "ollama"


def test_cloud_mode_does_not_fall_back_to_ollama_on_network_failure(monkeypatch) -> None:
    import httpx

    from core.ai_service import AIServiceError

    settings = FakeSettings("groq", "openai/gpt-oss-120b", mode=MODE_CLOUD)
    settings.values["ai.retries"] = 0
    service = AIService(settings, FakeGroqSecretStore(),
                        connectivity=FakeConnectivity(internet=True))
    monkeypatch.setattr(AIService, "ollama_reachable", lambda self, **kwargs: True)
    local_requests: list[str] = []

    def fake_post(url, **kwargs):
        if url.startswith("http://localhost:11434"):
            local_requests.append(url)
        raise httpx.ConnectError("network is unreachable")

    monkeypatch.setattr("httpx.post", fake_post)

    with pytest.raises(AIServiceError):
        asyncio.run(service.chat("Hello"))

    assert not local_requests


def test_auto_does_not_fall_back_to_ollama_on_authentication_failure(monkeypatch) -> None:
    import httpx

    from core.ai_service import INVALID_KEY, AIServiceError

    settings = FakeSettings("groq", "openai/gpt-oss-120b", mode=MODE_AUTO)
    settings.values["ai.retries"] = 0
    service = AIService(settings, FakeGroqSecretStore(),
                        connectivity=FakeConnectivity(internet=True))
    monkeypatch.setattr(
        AIService, "ollama_reachable",
        lambda self, *, force=False, **kwargs: force,
    )
    local_requests: list[str] = []

    def fake_post(url, **kwargs):
        if url.startswith("http://localhost:11434"):
            local_requests.append(url)
        request = httpx.Request("POST", url)
        return httpx.Response(401, request=request)

    monkeypatch.setattr("httpx.post", fake_post)

    with pytest.raises(AIServiceError) as error:
        asyncio.run(service.chat("Hello"))

    assert error.value.code == INVALID_KEY
    assert not local_requests


def test_cloud_mode_requires_a_key(monkeypatch) -> None:
    monkeypatch.setattr(AIService, "ollama_reachable", lambda self, **k: True)
    service = AIService(
        FakeSettings("groq", "openai/gpt-oss-120b", mode=MODE_CLOUD),
        FakeSecretStore(),
    )

    # Even though Ollama is up, Cloud mode must not use it and needs a key.
    assert service.effective_provider_id == "groq"
    assert not service.is_configured()


# ---------------------------------------------------------------------------
# Mode persistence
# ---------------------------------------------------------------------------
def test_set_mode_persists_and_validates() -> None:
    service = AIService(FakeSettings(mode=MODE_AUTO), FakeSecretStore())

    service.set_mode(MODE_LOCAL)
    assert service.mode == MODE_LOCAL
    assert service.settings.get("ai.mode") == MODE_LOCAL

    try:
        service.set_mode("bogus")
    except ValueError:
        pass
    else:  # pragma: no cover - explicit failure path
        raise AssertionError("set_mode should reject unknown modes")


def test_local_and_cloud_models_are_stored_separately() -> None:
    settings = FakeSettings(provider="groq", mode=MODE_CLOUD)
    service = AIService(settings, FakeGroqSecretStore())

    # Cloud model goes to ai.model.
    service.configure(provider="groq", model="openai/gpt-oss-120b", mode=MODE_CLOUD)
    assert settings.get("ai.model") == "openai/gpt-oss-120b"

    # Local model goes to ai.ollama_model, leaving the cloud model intact.
    service.configure(provider="ollama", model="qwen2.5:3b", mode=MODE_LOCAL)
    assert settings.get("ai.ollama_model") == "qwen2.5:3b"
    assert settings.get("ai.model") == "openai/gpt-oss-120b"
    assert service.ollama_model == "qwen2.5:3b"


def test_provider_error_classes_expose_actionable_text() -> None:
    assert "ollama serve" in str(OllamaNotRunningError("http://localhost:11434"))
    assert "ollama pull" in str(OllamaModelMissingError("qwen2.5:7b"))


