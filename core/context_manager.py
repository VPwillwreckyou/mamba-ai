from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ContextEntry:
    """A single entry in the short-term conversation/task context."""

    role: str
    content: str
    metadata: dict[str, Any] = field(default_factory=dict)


class ContextManager:
    """Short-term context for the current conversation/task session.

    The context manager preserves recent exchanges and current task state so the
    AI can stay coherent within a session. It is intentionally separate from
    long-term memory and must not be used to store security policy.
    """

    def __init__(self, *, max_entries: int = 200) -> None:
        self._entries: deque[ContextEntry] = deque(maxlen=max_entries)
        self.current_task: str | None = None
        self.current_action: str | None = None
        self.metadata: dict[str, Any] = {}

    def add_entry(self, role: str, content: str, *, metadata: dict[str, Any] | None = None) -> ContextEntry:
        entry = ContextEntry(role=role, content=content, metadata=metadata or {})
        self._entries.append(entry)
        return entry

    def add_user_message(self, content: str, *, metadata: dict[str, Any] | None = None) -> ContextEntry:
        return self.add_entry("user", content, metadata=metadata)

    def add_assistant_message(self, content: str, *, metadata: dict[str, Any] | None = None) -> ContextEntry:
        return self.add_entry("assistant", content, metadata=metadata)

    def add_system_message(self, content: str, *, metadata: dict[str, Any] | None = None) -> ContextEntry:
        return self.add_entry("system", content, metadata=metadata)

    def clear(self) -> None:
        """Clear the current conversation context."""
        self._entries.clear()
        self.current_task = None
        self.current_action = None
        self.metadata.clear()

    def get_entries(self) -> list[ContextEntry]:
        return list(self._entries)

    def to_messages(self) -> list[dict[str, Any]]:
        """Convert the current context into a message list suitable for an AI provider."""
        return [
            {
                "role": entry.role,
                "content": entry.content,
                "metadata": entry.metadata,
            }
            for entry in self._entries
        ]

    def summarize(self, max_length: int = 200) -> str:
        """Return a compact textual summary of recent context."""
        lines = []
        for entry in list(self._entries)[-10:]:
            lines.append(f"[{entry.role}] {entry.content[:max_length]}")
        return "\n".join(lines)
