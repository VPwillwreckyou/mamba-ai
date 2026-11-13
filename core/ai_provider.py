from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class AIProvider(ABC):
    """Abstract interface for AI providers.

    The application core must not depend on a specific provider implementation.
    Each provider must return responses as text, with structured metadata when
    relevant, and must never be trusted to validate or authorize actions.
    """

    @abstractmethod
    async def chat(self, prompt: str, *, system_prompt: str | None = None) -> str:
        """Send a conversational prompt and return the text response."""

    @abstractmethod
    async def raw_response(self, prompt: str, *, system_prompt: str | None = None) -> dict[str, Any]:
        """Return a provider response as a structured dictionary for inspection."""

    async def chat_stream(self, prompt: str, *, system_prompt: str | None = None):
        """Yield text chunks; default falls back to one full reply."""
        yield await self.chat(prompt, system_prompt=system_prompt)


class GeminiProvider(AIProvider):
    """Google Gemini provider for MVP.

    If the API key is missing or the provider cannot be initialized, this module
    must fail closed and raise clearly, not silently fake responses.
    """

    def __init__(self, api_key: str, *, model: str | None = None,
                 timeout: float = 30.0) -> None:
        """
        Initialize the Gemini provider.

        Raises:
            ValueError: if the API key is empty or invalid.
        """
        if not api_key:
            raise ValueError("Gemini API key is required")
        self.api_key = api_key
        self.model = model or "gemini-1.5-flash"
        self.timeout = timeout
        self._client = None

    @property
    def client(self):
        """Lazily initialize and return the provider client.

        This property is intentionally implementation-private. The public API does
        not expose the client directly.
        """
        if self._client is None:
            try:
                import google.genai as _genai
            except ImportError as exc:
                raise RuntimeError(
                    "google-genai is required for the Gemini provider"
                ) from exc
            self._client = _genai.Client(api_key=self.api_key)
            import os
            os.environ.setdefault("MAMBA_SKIP_GENAI_CHECK", "1")
        return self._client

    async def chat(self, prompt: str, *, system_prompt: str | None = None) -> str:
        """Send a conversational prompt and return the text response."""
        response = await self.raw_response(prompt, system_prompt=system_prompt)
        return self._extract_text(response)

    async def raw_response(self, prompt: str, *, system_prompt: str | None = None) -> dict[str, Any]:
        """Return the provider response as a structured dictionary."""
        import asyncio

        def _call():
            client = self.client
            config = None
            if system_prompt:
                config = {"system_instruction": system_prompt}
            return client.models.generate_content(
                model=self.model,
                contents=prompt,
                config=config or {},
            )

        try:
            # The google-genai SDK is blocking: run it off the event loop so
            # the UI thread never stalls on a network round-trip.
            response = await asyncio.to_thread(_call)
            return self._serialize(response)
        except Exception as exc:
            raise RuntimeError(f"Gemini request failed: {exc}") from exc

    def _extract_text(self, response: dict[str, Any]) -> str:
        text = response.get("text")
        if not text:
            raise RuntimeError("Gemini response did not contain usable text")
        return text

    def _serialize(self, response) -> dict[str, Any]:
        return {
            "text": get_text_content(response),
            "raw": response,
        }


class OpenAICompatibleProvider(AIProvider):
    """Chat-completions provider for OpenAI-compatible APIs."""

    def __init__(self, api_key: str, *, model: str, base_url: str,
                 timeout: float = 30.0) -> None:
        self.api_key = api_key
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    async def chat(self, prompt: str, *, system_prompt: str | None = None) -> str:
        response = await self.raw_response(prompt, system_prompt=system_prompt)
        text = response.get("text")
        if not text:
            raise RuntimeError("Provider response did not contain usable text")
        return text

    async def raw_response(self, prompt: str, *, system_prompt: str | None = None) -> dict[str, Any]:
        import asyncio

        import httpx

        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})
        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        try:
            response = await asyncio.to_thread(
                httpx.post,
                f"{self.base_url}/chat/completions",
                headers=headers,
                json={"model": self.model, "messages": messages},
                timeout=self.timeout,
            )
        except httpx.HTTPError as exc:
            raise RuntimeError(f"Network error reaching provider: {exc}") from exc
        response.raise_for_status()
        payload = response.json()
        try:
            text = payload["choices"][0]["message"]["content"]
        except Exception as exc:
            raise RuntimeError("Provider response missing choices/message") from exc
        return {"text": text, "raw": payload}

    async def chat_stream(self, prompt: str, *, system_prompt: str | None = None):
        """Stream via SSE when available, else single reply fallback."""
        import httpx

        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})
        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        try:
            with httpx.stream(
                "POST", f"{self.base_url}/chat/completions",
                headers={**headers, "Accept": "text/event-stream"},
                json={"model": self.model, "messages": messages, "stream": True},
                timeout=self.timeout,
            ) as resp:
                resp.raise_for_status()
                import json as _json

                for line in resp.iter_lines():
                    if not line or not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if data == "[DONE]":
                        break
                    try:
                        chunk = _json.loads(data)
                        delta = chunk["choices"][0].get("delta", {}).get("content", "")
                    except (KeyError, TypeError, ValueError):
                        delta = ""
                    if delta:
                        yield delta
                return
        except httpx.HTTPError:
            yield await self.chat(prompt, system_prompt=system_prompt)


class OllamaError(RuntimeError):
    """Base error for the local Ollama provider (never carries secrets)."""


class OllamaNotRunningError(OllamaError):
    """Raised when the local Ollama server cannot be reached at all."""

    def __init__(self, base_url: str) -> None:
        super().__init__(
            f"Could not connect to Ollama at {base_url}. Make sure Ollama is "
            f"running locally (start it with 'ollama serve') and that the "
            f"server is reachable."
        )
        self.base_url = base_url


class OllamaModelMissingError(OllamaError):
    """Raised when the requested model is not installed in Ollama."""

    def __init__(self, model: str) -> None:
        super().__init__(
            f"The model '{model}' is not available in Ollama. Install it with "
            f"'ollama pull {model}' and try again."
        )
        self.model = model


class OllamaProvider(AIProvider):
    """Local Ollama provider using Ollama's native ``/api/chat`` endpoint.

    This provider talks directly to a locally running Ollama server
    (default ``http://localhost:11434``). It requires no API key and never
    contacts any external service, so MAMBA's AI works fully offline.

    Conversation history is supported natively: callers may pass a list of
    ``{"role", "content"}`` messages. When only a plain prompt is given, a
    single user turn (plus an optional system prompt) is sent.
    """

    DEFAULT_BASE_URL = "http://localhost:11434"
    DEFAULT_MODEL = "qwen2.5:7b"

    def __init__(self, model: str = DEFAULT_MODEL, *,
                    base_url: str = DEFAULT_BASE_URL, timeout: float = 120.0) -> None:
        self.model = model or self.DEFAULT_MODEL
        self.base_url = base_url.rstrip("/")
        # Local generation can be slow on first load; default to a generous
        # timeout so a cold model start is not mistaken for a failure.
        self.timeout = timeout

    async def chat(self, prompt: str, *, system_prompt: str | None = None,
                    messages: list[dict[str, Any]] | None = None) -> str:
        response = await self.raw_response(prompt, system_prompt=system_prompt,
                                            messages=messages)
        text = response.get("text")
        if not text:
            raise OllamaError(
                "Ollama returned an empty response. Check that the model is "
                "loaded correctly and try again."
            )
        return text

    async def chat_stream(self, prompt: str, *, system_prompt: str | None = None,
                            messages: list[dict[str, Any]] | None = None):
        """Stream NDJSON chunks from /api/chat, fallback to single reply."""
        import json as _json

        import httpx

        payload_messages = self._build_messages(prompt, system_prompt, messages)
        try:
            with httpx.stream(
                "POST", f"{self.base_url}/api/chat",
                json={"model": self.model, "messages": payload_messages,
                        "stream": True},
                timeout=self.timeout,
            ) as resp:
                if resp.status_code == 404:
                    raise OllamaModelMissingError(self.model)
                resp.raise_for_status()
                for line in resp.iter_lines():
                    if not line:
                        continue
                    try:
                        chunk = _json.loads(line)
                    except (TypeError, ValueError):
                        chunk = {}
                    delta = (chunk.get("message") or {}).get("content", "")
                    if delta:
                        yield delta
                    if chunk.get("done"):
                        break
                return
        except OllamaError:
            raise
        except httpx.HTTPError:
            yield await self.chat(prompt, system_prompt=system_prompt,
                                  messages=messages)

    async def raw_response(self, prompt: str, *, system_prompt: str | None = None,
                            messages: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        import asyncio

        import httpx

        payload_messages = self._build_messages(prompt, system_prompt, messages)
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": payload_messages,
            "stream": False,
        }
        try:
            response = await asyncio.to_thread(
                httpx.post, f"{self.base_url}/api/chat", json=payload,
                timeout=self.timeout)
        except httpx.ConnectError as exc:
            raise OllamaNotRunningError(self.base_url) from exc
        except httpx.TimeoutException as exc:
            raise OllamaError(
                f"Ollama did not respond within {self.timeout:.0f}s. The model "
                f"may still be loading - try again."
            ) from exc

        if response.status_code == 404:
            # Ollama returns 404 when the requested model is not pulled.
            raise OllamaModelMissingError(self.model)
        response.raise_for_status()
        data = response.json()
        message = data.get("message") or {}
        text = message.get("content") or ""
        return {"text": text, "raw": data}

    @staticmethod
    def _build_messages(prompt: str, system_prompt: str | None,
                        messages: list[dict[str, Any]] | None) -> list[dict[str, str]]:
        """Build a clean Ollama message list from prompt or explicit history."""
        if messages:
            cleaned = [
                {"role": str(m.get("role", "user")),
                "content": str(m.get("content", ""))}
                for m in messages
            ]
            if system_prompt and not any(m["role"] == "system" for m in cleaned):
                cleaned.insert(0, {"role": "system", "content": system_prompt})
            return cleaned
        built: list[dict[str, str]] = []
        if system_prompt:
            built.append({"role": "system", "content": system_prompt})
        built.append({"role": "user", "content": prompt})
        return built


class AnthropicProvider(AIProvider):
    """Anthropic Messages API provider."""

    def __init__(self, api_key: str, *, model: str, timeout: float = 30.0) -> None:
        if not api_key:
            raise ValueError("API key is required")
        self.api_key = api_key
        self.model = model
        self.timeout = timeout

    async def chat(self, prompt: str, *, system_prompt: str | None = None) -> str:
        response = await self.raw_response(prompt, system_prompt=system_prompt)
        text = response.get("text")
        if not text:
            raise RuntimeError("Provider response did not contain usable text")
        return text

    async def raw_response(self, prompt: str, *, system_prompt: str | None = None) -> dict[str, Any]:
        import asyncio

        import httpx

        payload: dict[str, Any] = {
            "model": self.model,
            "max_tokens": 512,
            "messages": [{"role": "user", "content": prompt}],
        }
        if system_prompt:
            payload["system"] = system_prompt
        response = await asyncio.to_thread(
            httpx.post,
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": self.api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json=payload,
            timeout=self.timeout,
        )
        response.raise_for_status()
        result = response.json()
        text = "".join(
            block.get("text", "") for block in result.get("content", [])
            if block.get("type") == "text"
        )
        return {"text": text, "raw": result}


def get_text_content(response) -> str:
    """Extract text content from a Gemini response object.

    This helper keeps text extraction separate from provider construction so the
    provider implementation can evolve without changing the public API.
    """
    try:
        parts = getattr(response, "candidates", None)
        if parts:
            for candidate in parts:
                content = getattr(candidate, "content", None)
                if content is not None:
                    for part in getattr(content, "parts", []):
                        text = getattr(part, "text", None)
                        if text:
                            return text
        fallback = getattr(response, "text", None)
        if fallback:
            return fallback
    except (AttributeError, TypeError, ValueError):
        return ""
    return ""
