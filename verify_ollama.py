"""Live verification of the Ollama integration in MAMBA AI.

Run with the project venv:  .venv\\Scripts\\python.exe verify_ollama.py

Checks, in order:
  1. Is Ollama reachable at http://localhost:11434 ?
  2. Can the local qwen2.5:7b model answer a message (native /api/chat)?
  3. Does Local mode build an Ollama provider without any API key?
    4. Does Automatic mode select the configured cloud provider online?
    5. Does Automatic mode select Ollama offline?
Each check prints PASS/FAIL and never raises.
"""
from __future__ import annotations

import asyncio
import sys

import httpx

from core.ai_provider import (
    OllamaModelMissingError,
    OllamaNotRunningError,
    OllamaProvider,
)
from core.ai_service import MODE_AUTO, MODE_LOCAL, AIService

BASE = "http://localhost:11434"
MODEL = "qwen2.5:7b"


class _Settings:
    def __init__(self):
        self.values = {
            "ai.provider": "groq",
            "ai.model": "openai/gpt-oss-120b",
            "ai.mode": MODE_LOCAL,
            "ai.ollama_model": MODEL,
        }

    def get(self, key, default=None):
        return self.values.get(key, default)

    def set(self, key, value):
        self.values[key] = value


class _Secrets:
    backend = "test"

    def __init__(self, cloud_key: bool = False):
        self.cloud_key = cloud_key

    def retrieve(self, name, *, env_fallback=None):
        return "test-cloud-key" if self.cloud_key and name == "GROQ_API_KEY" else None

    def exists(self, name, *, env_fallback=None):
        return self.cloud_key and name == "GROQ_API_KEY"

    def store(self, name, value):
        raise AssertionError("no key needed")

    def delete(self, name):
        return False


class _Connectivity:
    def __init__(self, internet: bool):
        self.internet = internet

    def has_internet(self, *, force=False):
        return self.internet


def check(name, ok, detail=""):
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f" - {detail}" if detail else ""))
    return ok


def main() -> int:
    results = []

    # 1. Reachability
    try:
        r = httpx.get(f"{BASE}/api/version", timeout=3)
        reachable = r.status_code == 200
        version = r.text.strip()
    except Exception as exc:  # noqa: BLE001
        reachable, version = False, f"not reachable ({type(exc).__name__})"
    results.append(check("Ollama server reachable at " + BASE, reachable, version))

    # 2. qwen answers a message via the native /api/chat endpoint
    provider = OllamaProvider(MODEL, base_url=BASE)
    try:
        reply = asyncio.run(provider.chat(
            "Reply with exactly: PONG", system_prompt=" obey exactly."))
        answered = "PONG" in reply.upper()
        results.append(check("qwen2.5:7b answered a message", answered,
                             reply.strip()[:80]))
    except OllamaModelMissingError as exc:
        results.append(check("qwen2.5:7b answered a message", False, str(exc)))
    except OllamaNotRunningError as exc:
        results.append(check("qwen2.5:7b answered a message", False, str(exc)))
    except Exception as exc:  # noqa: BLE001
        results.append(check("qwen2.5:7b answered a message", False,
                             f"{type(exc).__name__}: {exc}"))

    # 3. Local mode builds an Ollama provider with no API key
    svc = AIService(_Settings(), _Secrets())
    prov = svc.build_provider()
    results.append(check(
        "Local mode -> Ollama provider (no key)",
        isinstance(prov, OllamaProvider) and not svc.has_api_key(),
        f"effective={svc.effective_provider_id}"))

    # 4. AIService.test_connection against local Ollama
    res = svc.test_connection(timeout=120)
    results.append(check("AIService.test_connection (local)",
                         res.ok, f"{res.label}: {res.message}"))

    # 5. Automatic routing prefers the configured cloud provider online.
    auto_settings = _Settings()
    auto_settings.values["ai.mode"] = MODE_AUTO
    auto_settings.values["ai.provider"] = "groq"
    svc2 = AIService(auto_settings, _Secrets(cloud_key=True),
                     connectivity=_Connectivity(internet=True))
    results.append(check(
        "Automatic selects cloud when online and configured",
        svc2.effective_provider_id == "groq",
        f"effective={svc2.effective_provider_id}"))

    # 6. Automatic routing returns to Ollama when internet is unavailable.
    svc3 = AIService(auto_settings, _Secrets(cloud_key=True),
                     connectivity=_Connectivity(internet=False))
    results.append(check(
        "Automatic selects Ollama when offline",
        svc3.effective_provider_id == "ollama",
        f"effective={svc3.effective_provider_id}"))

    print("\nSUMMARY:", "ALL PASS" if all(results) else "SOME FAILED",
          f"({sum(results)}/{len(results)})")
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
