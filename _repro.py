"""Reproduce MAMBA's Ollama malformed-response bug against the real server.

This mirrors app.py::_assistant_reply's message construction exactly:
  - user messages are the ONLY thing stored in memory (kind="conversation")
  - assistant replies are NEVER stored
  - history is built as recent[-6:-1] + current, ALL with role "user"

Then it sends those messages through the real OllamaProvider and prints
exactly what MAMBA would send and receive.
"""
from __future__ import annotations

import asyncio

from core.ai_provider import OllamaProvider

BASE = "http://localhost:11434"
MODEL = "qwen2.5:7b"

# Simulate 3 turns of a real conversation.
user_turns = [
    "My name is Ada and I love gardening.",
    "What is a good fertilizer for tomatoes?",
    "What is the capital of France?",
]

# --- EXACT reproduction of app.py::_assistant_reply message building ---
# Only user messages exist in memory (assistant replies are never stored).
memory = list(user_turns)  # after storing each user message

current = user_turns[-1]
recent = memory  # search(kind="conversation") -> only user messages, in order

history: list[dict] = []
for e in recent[-6:-1]:
    content = str(e).strip()
    if content:
        history.append({"role": "user", "content": content})
history.append({"role": "user", "content": current})

system_prompt = (
    "You are MAMBA, a concise, helpful personal AI assistant "
    "running locally. Answer clearly and briefly."
)

print("=== MESSAGES MAMBA SENDS TO OLLAMA (current code) ===")
for m in history:
    print(f"  [{m['role']:9}] {m['content'][:70]}")
print("system:", system_prompt[:60], "...")
print()

provider = OllamaProvider(MODEL, base_url=BASE)
reply = asyncio.run(provider.chat(
    current, system_prompt=system_prompt, messages=history))

print("=== OLLAMA REPLY MAMBA DISPLAYS ===")
print(reply)
