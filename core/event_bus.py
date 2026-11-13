from __future__ import annotations

import asyncio
from collections.abc import Callable, Coroutine
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class EventType(str, Enum):
    """Application-level event types."""

    WAKE_WORD_DETECTED = "wake_word_detected"
    VOICE_INPUT_RECEIVED = "voice_input_received"
    COMMAND_PARSED = "command_parsed"
    TASK_STARTED = "task_started"
    TOOL_STARTED = "tool_started"
    TOOL_COMPLETED = "tool_completed"
    TOOL_FAILED = "tool_failed"
    CONFIRMATION_REQUIRED = "confirmation_required"
    TASK_COMPLETED = "task_completed"
    EMERGENCY_STOP = "emergency_stop"
    ACCESS_REVOKED = "access_revoked"
    AUTOMATION_TRIGGERED = "automation_triggered"


@dataclass
class Event:
    """A named application event with optional payload."""

    type: EventType
    payload: Any = None
    source: str | None = None
    timestamp: float = field(default_factory=lambda: asyncio.get_event_loop().time() if hasattr(asyncio, "get_event_loop") else 0.0)


class EventBus:
    """Simple in-process event bus for publishing and subscribing to events.

    This bus is synchronous by default, but subscribers may be async. Async
    subscribers are scheduled on the running event loop when possible.
    """

    def __init__(self) -> None:
        self._handlers: dict[EventType, list[Callable[[Event], None | Coroutine[Any, Any, None]]]] = {}
        self._any_handlers: list[Callable[[Event], None | Coroutine[Any, Any, None]]] = []

    def subscribe(
        self,
        event_type: EventType,
        handler: Callable[[Event], None | Coroutine[Any, Any, None]],
    ) -> None:
        """Register a handler for a specific event type."""
        handlers = self._handlers.setdefault(event_type, [])
        if handler not in handlers:
            handlers.append(handler)

    def subscribe_any(self, handler: Callable[[Event], None | Coroutine[Any, Any, None]]) -> None:
        """Register a handler for all events."""
        if handler not in self._any_handlers:
            self._any_handlers.append(handler)

    def unsubscribe(self, event_type: EventType, handler: Callable[[Event], None | Coroutine[Any, Any, None]]) -> None:
        """Remove a previously registered handler."""
        handlers = self._handlers.get(event_type)
        if handlers:
            if handler in handlers:
                handlers.remove(handler)
        if handler in self._any_handlers:
            self._any_handlers.remove(handler)

    def publish(self, event: Event) -> None:
        """Publish an event to matching subscribers synchronously."""
        for handler in self._any_handlers:
            try:
                result = handler(event)
            except Exception:
                continue
            if asyncio.iscoroutine(result):
                try:
                    asyncio.ensure_future(result)
                except Exception:
                    pass
        for handler in self._handlers.get(event.type, []):
            try:
                result = handler(event)
            except Exception:
                continue
            if asyncio.iscoroutine(result):
                try:
                    asyncio.ensure_future(result)
                except Exception:
                    pass
